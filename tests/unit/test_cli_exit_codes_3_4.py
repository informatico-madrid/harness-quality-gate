"""Unit tests for the Fase-2 wiring: CONFIG_INVALID (4) and INFRA_INCOMPLETE (3).

Both checks run inside ``_cmd_all()`` — there is deliberately no separate
``doctor`` subcommand or module (decision 69b05df).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from harness_quality_gate.cli import _cmd_all, _missing_php_tools
from harness_quality_gate.exit_codes import CONFIG_INVALID, INFRA_INCOMPLETE, PASS
from harness_quality_gate.models import LayerResult


def _make_args(**kwargs):
    import argparse
    defaults = {"repo": ".", "json": False, "quiet": False}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _mock_adapter() -> MagicMock:
    adapter = MagicMock()
    lr = LayerResult(layer="L3A", language="python", passed=True,
                     findings=[], duration_sec=0.0)
    for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
        getattr(adapter, method).return_value = lr
    return adapter


# ---------------------------------------------------------------------------
# Config v1 rejection (exit 4)
# ---------------------------------------------------------------------------

class TestConfigV1Rejection:
    _V1_YAML = "layers:\n  l1:\n    enabled: true\n"

    def test_v1_config_returns_exit_4_with_payload(self, tmp_path, capsys):
        (tmp_path / "quality-gate.yaml").write_text(self._V1_YAML, encoding="utf-8")
        code = _cmd_all(_make_args(repo=str(tmp_path)))
        assert code == CONFIG_INVALID
        assert code == 4
        out = json.loads(capsys.readouterr().out)
        assert out["exit_code"] == 4
        assert "v1" in out["error"]

    def test_v1_config_checked_before_layers_run(self, tmp_path):
        """The adapter must never be constructed when config is invalid."""
        (tmp_path / ".quality-gate.yaml").write_text(self._V1_YAML, encoding="utf-8")
        with patch("harness_quality_gate.cli.PythonAdapter") as py_cls:
            code = _cmd_all(_make_args(repo=str(tmp_path), quiet=True))
        assert code == CONFIG_INVALID
        py_cls.assert_not_called()

    def test_missing_config_uses_defaults_and_passes(self, tmp_path):
        """FileNotFoundError from config_load must not abort the gate."""
        adapter = _mock_adapter()
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path), quiet=True))
        assert code == PASS

    def test_valid_v2_config_proceeds(self, tmp_path):
        (tmp_path / "quality-gate.yaml").write_text(
            "schema_version: 2\n", encoding="utf-8",
        )
        adapter = _mock_adapter()
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path), quiet=True))
        assert code == PASS

    def test_v1_config_quiet_suppresses_output(self, tmp_path, capsys):
        (tmp_path / "quality-gate.yaml").write_text(self._V1_YAML, encoding="utf-8")
        code = _cmd_all(_make_args(repo=str(tmp_path), quiet=True))
        assert code == CONFIG_INVALID
        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# Infra-check PHP (exit 3)
# ---------------------------------------------------------------------------

class TestPhpInfraCheck:
    def test_php_repo_missing_tools_exits_3_with_payload(self, tmp_path, capsys):
        (tmp_path / "composer.json").write_text("{}", encoding="utf-8")
        with patch(
            "harness_quality_gate.cli._missing_php_tools",
            return_value=["phpunit", "infection"],
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path)))
        assert code == INFRA_INCOMPLETE
        assert code == 3
        out = json.loads(capsys.readouterr().out)
        assert out["exit_code"] == 3
        assert out["missing_tools"] == ["phpunit", "infection"]
        assert out["error"] == (
            "Infraestructura PHP incompleta — herramientas críticas faltantes: "
            "phpunit, infection. Instálelas (composer install / gestor de "
            "paquetes) y reintente."
        )

    def test_php_infra_checked_before_adapter(self, tmp_path):
        (tmp_path / "composer.json").write_text("{}", encoding="utf-8")
        with (
            patch("harness_quality_gate.cli._missing_php_tools", return_value=["php"]),
            patch("harness_quality_gate.cli.PhpAdapter") as php_cls,
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path), quiet=True))
        assert code == INFRA_INCOMPLETE
        php_cls.assert_not_called()

    def test_python_repo_never_runs_infra_check(self, tmp_path):
        """Python keeps graceful degradation — no infra gate."""
        adapter = _mock_adapter()
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli._missing_php_tools") as infra,
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path), quiet=True))
        assert code == PASS
        infra.assert_not_called()

    def test_php_repo_with_complete_infra_runs_layers(self, tmp_path):
        (tmp_path / "composer.json").write_text("{}", encoding="utf-8")
        adapter = _mock_adapter()
        with (
            patch("harness_quality_gate.cli._missing_php_tools", return_value=[]) as infra,
            patch("harness_quality_gate.cli.PhpAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path), quiet=True))
        assert code == PASS
        # The infra-check must receive the resolved repo path, not None.
        infra.assert_called_once_with(Path(str(tmp_path)).resolve())
        adapter.run_l3a.assert_called_once()
        adapter.run_l4.assert_called_once()

    def test_infra_failure_quiet_suppresses_output(self, tmp_path, capsys):
        """quiet=args.quiet on the exit-3 path — quiet must silence stdout."""
        (tmp_path / "composer.json").write_text("{}", encoding="utf-8")
        with patch("harness_quality_gate.cli._missing_php_tools", return_value=["php"]):
            code = _cmd_all(_make_args(repo=str(tmp_path), quiet=True))
        assert code == INFRA_INCOMPLETE
        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# _missing_php_tools resolution logic
# ---------------------------------------------------------------------------

class TestMissingPhpTools:
    def test_everything_missing(self, tmp_path):
        with patch("harness_quality_gate.cli.shutil.which", return_value=None):
            missing = _missing_php_tools(tmp_path)
        assert missing == ["php", "phpunit", "phpstan", "infection"]

    def test_everything_on_path(self, tmp_path):
        """which() must receive the real tool name — a name-checking fake
        (not a blanket return_value) kills the which(None) arg mutant."""
        known = {"php", "phpunit", "phpstan", "infection"}

        def _which(name):
            return f"/usr/bin/{name}" if name in known else None

        with patch("harness_quality_gate.cli.shutil.which", side_effect=_which):
            assert _missing_php_tools(tmp_path) == []

    def test_vendor_bin_satisfies_tool(self, tmp_path):
        """A tool absent from PATH but present in vendor/bin is not missing."""
        vendor_bin = tmp_path / "vendor" / "bin"
        vendor_bin.mkdir(parents=True)
        for tool in ("phpunit", "phpstan", "infection"):
            (vendor_bin / tool).write_text("#!/bin/sh\n", encoding="utf-8")

        def _which(name):
            return "/usr/bin/php" if name == "php" else None

        with patch("harness_quality_gate.cli.shutil.which", side_effect=_which):
            assert _missing_php_tools(tmp_path) == []

    def test_partial_vendor_bin(self, tmp_path):
        vendor_bin = tmp_path / "vendor" / "bin"
        vendor_bin.mkdir(parents=True)
        (vendor_bin / "phpunit").write_text("#!/bin/sh\n", encoding="utf-8")

        def _which(name):
            return "/usr/bin/php" if name == "php" else None

        with patch("harness_quality_gate.cli.shutil.which", side_effect=_which):
            assert _missing_php_tools(tmp_path) == ["phpstan", "infection"]

    def test_composer_bin_dir_variant_satisfies_tool(self, tmp_path):
        """Projects with composer config.bin-dir=bin resolve from bin/."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for tool in ("phpunit", "phpstan", "infection"):
            (bin_dir / tool).write_text("#!/bin/sh\n", encoding="utf-8")

        def _which(name):
            return "/usr/bin/php" if name == "php" else None

        with patch("harness_quality_gate.cli.shutil.which", side_effect=_which):
            assert _missing_php_tools(tmp_path) == []

    def test_php_runtime_missing_but_vendor_complete(self, tmp_path):
        vendor_bin = tmp_path / "vendor" / "bin"
        vendor_bin.mkdir(parents=True)
        for tool in ("phpunit", "phpstan", "infection"):
            (vendor_bin / tool).write_text("#!/bin/sh\n", encoding="utf-8")
        with patch("harness_quality_gate.cli.shutil.which", return_value=None):
            assert _missing_php_tools(tmp_path) == ["php"]
