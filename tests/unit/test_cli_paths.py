"""Unit tests for --paths CLI argument and partial-run support.

Covers:
  - --paths arg is parsed correctly by argparse
  - When --paths is set, only L3A and L1 run (mock the adapter)
  - When --paths is not set, all 5 layers run
  - CLI dispatches PythonAdapter(paths=args.paths)
  - Quick-pass LayerResults are created for L2, L3B, L4
  - Empty --paths is CONFIG_INVALID (security fix #5)
  - Invalid --paths is CONFIG_INVALID (security fix #5)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.cli import (
    _cmd_all,
    main,
)
from harness_quality_gate.exit_codes import (
    CONFIG_INVALID,
    PASS,
    UNSUPPORTED,
    FAIL,
)
from harness_quality_gate.models import LayerResult


def _make_args(**kwargs):
    """Build a minimal argparse.Namespace with sane defaults."""
    import argparse
    defaults = {"repo": ".", "json": False, "quiet": False, "paths": None}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _make_layer(*, passed: bool = True, layer: str = "L3A", language: str = "python", tool_specific: dict | None = None) -> LayerResult:
    return LayerResult(
        layer=layer, language=language, passed=passed, findings=[],
        duration_sec=0.0, tool_specific=tool_specific,
    )


# ---------------------------------------------------------------------------
# main() --argparsing --paths
# ---------------------------------------------------------------------------

class TestPathsArgParsing:
    """Test that --paths is correctly parsed by argparse."""

    def test_paths_parsed_as_list(self):
        """--paths a.py b.py → paths=['a.py', 'b.py']."""
        with patch("harness_quality_gate.cli._cmd_all", return_value=PASS) as cmd:
            main(["all", ".", "--paths", "a.py", "b.py"])
        args = cmd.call_args.args[0]
        assert args.paths == ["a.py", "b.py"]

    def test_paths_empty_list_when_not_provided(self):
        """No --paths → paths=None (the default)."""
        with patch("harness_quality_gate.cli._cmd_all", return_value=PASS) as cmd:
            main(["all", "."])
        args = cmd.call_args.args[0]
        assert args.paths is None

    def test_paths_single_file(self):
        """--paths single.py → paths=['single.py']."""
        with patch("harness_quality_gate.cli._cmd_all", return_value=PASS) as cmd:
            main(["all", ".", "--paths", "single.py"])
        args = cmd.call_args.args[0]
        assert args.paths == ["single.py"]

    def test_paths_passed_as_nargs_star(self):
        """--paths with no values after it yields None (nargs='*')."""
        # Actually nargs='*' with no values: argparse returns []
        # But default=None: when no --paths flag at all, it's None
        with patch("harness_quality_gate.cli._cmd_all", return_value=PASS) as cmd:
            main(["all", ".", "--paths"])
        args = cmd.call_args.args[0]
        assert args.paths == []

    def test_paths_flag_in_help(self, capsys):
        """--paths appears in 'all --help' output."""
        code = main(["all", "--help"])
        assert code == UNSUPPORTED
        out = capsys.readouterr().out
        assert "paths" in out.lower()


# ---------------------------------------------------------------------------
# _cmd_all -- paths → PythonAdapter(paths=...)
# ---------------------------------------------------------------------------

class TestCmdAllPathsAdapter:
    """Test that _cmd_all passes paths to PythonAdapter."""

    def test_python_adapter_receives_paths(self, tmp_path):
        """PythonAdapter is called with paths=args.paths."""
        args = _make_args(repo=str(tmp_path), paths=["src/foo.py", "tests/"])
        received_paths = []

        def capture_adapter(paths=None, **kwargs):
            received_paths.append(paths)
            adapter = MagicMock()
            adapter.paths = paths  # match the paths arg so partial_run is correct
            lr = _make_layer(passed=True)
            for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
                getattr(adapter, method).return_value = lr
            return adapter

        with (
            patch("harness_quality_gate.cli.PythonAdapter", side_effect=capture_adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(args)
        assert code == PASS
        assert received_paths == [["src/foo.py", "tests/"]]

    def test_python_adapter_no_paths_when_none(self, tmp_path):
        """PythonAdapter is called with paths=None when --paths not provided."""
        args = _make_args(repo=str(tmp_path))
        received_paths = []

        def capture_adapter(paths=None, **kwargs):
            received_paths.append(paths)
            adapter = MagicMock()
            adapter.paths = paths  # match the paths arg so partial_run is correct
            lr = _make_layer(passed=True)
            for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
                getattr(adapter, method).return_value = lr
            return adapter

        with (
            patch("harness_quality_gate.cli.PythonAdapter", side_effect=capture_adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(args)
        assert code == PASS
        assert received_paths == [None]


# ---------------------------------------------------------------------------
# _cmd_all -- partial run behavior
# ---------------------------------------------------------------------------

class TestCmdAllPartialRun:
    """Test that partial runs skip L2, L3B, L4."""

    def _make_mock_adapter(self, *, passed: bool = True, paths: list[str] | None = None) -> MagicMock:
        adapter = MagicMock()
        # Default to a non-None paths list so partial_run triggers in CLI.
        # Tests that want full-run behavior override this explicitly.
        adapter.paths = paths if paths is not None else ["test_stub"]
        lr = _make_layer(passed=passed)
        for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
            getattr(adapter, method).return_value = lr
        return adapter

    def test_partial_run_only_calls_l3a_and_l1(self, tmp_path):
        """When --paths is set, only run_l3a and run_l1 are invoked.
        L2, L3B, L4 return quick-pass LayerResults."""
        adapter = MagicMock()
        adapter.paths = ["src/foo.py"]  # enable partial_run detection
        lr_l3a = _make_layer(layer="L3A")
        lr_l1 = _make_layer(layer="L1")
        adapter.run_l3a.return_value = lr_l3a
        adapter.run_l1.return_value = lr_l1
        args = _make_args(repo=str(tmp_path), paths=["src/foo.py"])

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(args)

        assert code == PASS
        # L3A and L1 should be called
        assert adapter.run_l3a.called
        assert adapter.run_l1.called
        # L2, L3B, L4 should NOT be called
        assert not adapter.run_l2.called
        assert not adapter.run_l3b.called
        assert not adapter.run_l4.called

    def test_partial_run_checkpoint_has_all_5_layers(self, tmp_path):
        """Checkpoint still contains all 5 layers even in partial run.

        Each run_* must return a LayerResult with the correct layer name.
        The mock originally returned layer="L3A" for all methods.
        """
        adapter = MagicMock()
        adapter.paths = ["src/foo.py"]  # enable partial_run detection
        # Each method returns a LayerResult with its actual layer name
        for idx, layer_name in enumerate(["L3A", "L1", "L2", "L3B", "L4"]):
            method = ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4")[idx]
            getattr(adapter, method).return_value = _make_layer(
                passed=True, layer=layer_name
            )
        args = _make_args(repo=str(tmp_path), paths=["src/foo.py"])
        written_data = []

        def capture_write(path, data):
            written_data.append(data)

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint", side_effect=capture_write),
        ):
            code = _cmd_all(args)

        assert code == PASS
        assert len(written_data) == 1
        layers = written_data[0]["layers"]
        layer_names = [l["layer"] for l in layers]
        assert layer_names == ["L3A", "L1", "L2", "L3B", "L4"]

    def test_partial_run_l2_l3b_l4_passed_is_true(self, tmp_path):
        """L2, L3B, L4 layers in partial run have passed=True."""
        adapter = self._make_mock_adapter(passed=True)
        args = _make_args(repo=str(tmp_path), paths=["src/foo.py"])
        layer_results = []

        def capture_build(*, layer_results, runtime, detection):
            layer_results_copy = []
            for lr in layer_results:
                layer_results_copy.append(lr)
            from harness_quality_gate.checkpoint import build
            return build(layer_results=layer_results, runtime=runtime, detection=detection)

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
            patch("harness_quality_gate.cli.build_checkpoint", side_effect=capture_build) as mock_build,
        ):
            code = _cmd_all(args)

        assert code == PASS
        # Capture actual LayerResults before checkpoint build
        # We need to inspect what was passed to build_checkpoint
        # The layer_dicts have already been built, so check the layers in output
        adapter.run_l3a.return_value = _make_layer(layer="L3A", passed=True)
        adapter.run_l1.return_value = _make_layer(layer="L1", passed=True)
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint") as mock_write,
        ):
            code = _cmd_all(args)
        # Get the written checkpoint
        call_args = mock_write.call_args
        checkpoint = call_args.args[1]
        layers = checkpoint["layers"]
        assert layers[0]["layer"] == "L3A"
        assert layers[0]["passed"] is True
        assert layers[1]["layer"] == "L1"
        assert layers[1]["passed"] is True
        assert layers[2]["layer"] == "L2"
        assert layers[2]["passed"] is True
        assert layers[3]["layer"] == "L3B"
        assert layers[3]["passed"] is True
        assert layers[4]["layer"] == "L4"
        assert layers[4]["passed"] is True

    def test_partial_run_l2_l3b_l4_duration_zero(self, tmp_path):
        """L2, L3B, L4 quick-pass results have duration_sec=0.0."""
        adapter = self._make_mock_adapter(passed=True)
        adapter.run_l3a.return_value = _make_layer(layer="L3A")
        adapter.run_l1.return_value = _make_layer(layer="L1")
        adapter.paths = ["src/foo.py"]
        args = _make_args(repo=str(tmp_path), paths=["src/foo.py"])

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint") as mock_write,
        ):
            code = _cmd_all(args)

        call_args = mock_write.call_args
        checkpoint = call_args.args[1]
        layers = checkpoint["layers"]
        # L2, L3B, L4 should have duration_sec=0.0
        assert layers[2]["duration_sec"] == 0.0
        assert layers[3]["duration_sec"] == 0.0
        assert layers[4]["duration_sec"] == 0.0


# ---------------------------------------------------------------------------
# _cmd_all -- full run (no --paths) behavior unchanged
# ---------------------------------------------------------------------------

class TestCmdAllFullRun:
    """Test that full runs (no --paths) still call all 5 layers."""

    def test_full_run_calls_all_layers(self, tmp_path):
        """When --paths is NOT set, all 5 layers are invoked."""
        adapter = MagicMock()
        adapter.supports_partial_run = False  # full run — no partial_run
        lr = _make_layer(passed=True)
        for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
            getattr(adapter, method).return_value = lr

        args = _make_args(repo=str(tmp_path))

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(args)

        assert code == PASS
        assert adapter.run_l3a.called
        assert adapter.run_l1.called
        assert adapter.run_l2.called
        assert adapter.run_l3b.called
        assert adapter.run_l4.called

    def test_full_run_l3a_passes_paths_none_to_adapter(self, tmp_path):
        """Full run passes paths=None to PythonAdapter."""
        received_paths = []

        def capture_adapter(paths=None, **kwargs):
            received_paths.append(paths)
            adapter = MagicMock()
            adapter.supports_partial_run = False  # full run
            lr = _make_layer(passed=True)
            for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
                getattr(adapter, method).return_value = lr
            return adapter

        args = _make_args(repo=str(tmp_path))

        with (
            patch("harness_quality_gate.cli.PythonAdapter", side_effect=capture_adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            _cmd_all(args)

        assert received_paths == [None]


# ---------------------------------------------------------------------------
# PHP repo with --paths (paths should be ignored)
# ---------------------------------------------------------------------------

class TestPathsPhpRepo:
    """Verify that --paths is only effective for Python repos."""

    def test_php_repo_ignores_paths(self, tmp_path):
        """PHP repos ignore --paths; all 5 layers still run via PhpAdapter."""
        (tmp_path / "composer.json").write_text("{}", encoding="utf-8")
        adapter = MagicMock()
        adapter.supports_partial_run = False  # Python would use paths for partial
        adapter.paths = None  # PHP ignores --paths; prevent partial_run detection
        lr_php = _make_layer(passed=True, language="php", layer="L3A")
        for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
            getattr(adapter, method).return_value = lr_php

        args = _make_args(repo=str(tmp_path), paths=["src/foo.php"])

        with (
            patch("harness_quality_gate.cli.PhpAdapter", return_value=adapter),
            patch("harness_quality_gate.cli._missing_php_tools", return_value=[]),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(args)

        assert code == PASS
        # PhpAdapter was used, not PythonAdapter
        assert adapter.run_l3a.called
        assert adapter.run_l1.called
        assert adapter.run_l2.called
        assert adapter.run_l3b.called
        assert adapter.run_l4.called


# ---------------------------------------------------------------------------
# Security fix #5: Empty --paths is CONFIG_INVALID
# ---------------------------------------------------------------------------

class TestEmptyPathsConfigInvalid:
    """Test that empty or invalid --paths returns CONFIG_INVALID exit code."""

    def test_empty_paths_returns_config_invalid(self, tmp_path):
        """args with paths=[] should return CONFIG_INVALID exit code.
        Catches security fix #5: empty --paths must not proceed to adapter creation."""
        # Setup a minimal Python project so _cmd_all doesn't fail early on language detection
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test"\nversion = "0.1.0"\n', encoding="utf-8"
        )
        adapter_mock = MagicMock()
        adapter_mock.supports_partial_run = False
        lr = _make_layer(passed=True)
        for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
            getattr(adapter_mock, method).return_value = lr

        args = _make_args(repo=str(tmp_path), paths=[])

        with patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter_mock):
            code = _cmd_all(args)

        assert code == CONFIG_INVALID

    def test_empty_paths_json_includes_error(self, tmp_path, capfd):
        """Empty paths should return JSON with error message containing
        'at least one path' - validated by inspecting _exit_with parameters."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test"\nversion = "0.1.0"\n', encoding="utf-8"
        )
        adapter_mock = MagicMock()
        adapter_mock.supports_partial_run = False
        lr = _make_layer(passed=True)
        for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
            getattr(adapter_mock, method).return_value = lr

        args = _make_args(repo=str(tmp_path), paths=[])

        exit_calls = []

        def capture_exit(code, data, *, quiet):
            exit_calls.append((code, data, quiet))
            print(json.dumps({"error": str(data.get("error", "")), "exit_code": code}, indent=2))
            return code

        with patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter_mock):
            with patch("harness_quality_gate.cli._exit_with", side_effect=capture_exit):
                _cmd_all(args)

        assert len(exit_calls) == 1
        code, data, quiet = exit_calls[0]
        assert code == CONFIG_INVALID
        err_msg = str(data.get("error", ""))
        assert "at least one path" in err_msg
        assert quiet is False

        # Verify JSON printed via print() includes the error message
        out, err = capfd.readouterr()
        assert "at least one path" in out

    def test_invalid_path_returns_config_invalid(self, tmp_path):
        """paths=['--evil'] should return CONFIG_INVALID (validate_paths rejects it)."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test"\nversion = "0.1.0"\n', encoding="utf-8"
        )
        adapter_mock = MagicMock()
        adapter_mock.supports_partial_run = False
        lr = _make_layer(passed=True)
        for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
            getattr(adapter_mock, method).return_value = lr

        args = _make_args(repo=str(tmp_path), paths=["--evil"])

        with patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter_mock):
            code = _cmd_all(args)

        assert code == CONFIG_INVALID

