"""Unit tests for harness_quality_gate/cli.py.

Covers the two live subcommands (all, audit-ignores), the output helpers,
and the main() dispatcher.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from harness_quality_gate.cli import (
    _asdict,
    _cmd_all,
    _cmd_audit_ignores,
    _detect_language,
    _exit_with,
    main,
)
from harness_quality_gate.exit_codes import FAIL, INTERNAL_ERROR, PASS, UNSUPPORTED
from harness_quality_gate.models import LayerResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_args(**kwargs):
    """Build a minimal argparse.Namespace with sane defaults."""
    import argparse
    defaults = {"repo": ".", "json": False, "quiet": False}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _make_layer(*, passed: bool = True, layer: str = "L3A", language: str = "python") -> LayerResult:
    return LayerResult(layer=layer, language=language, passed=passed, findings=[], duration_sec=0.0)


# ---------------------------------------------------------------------------
# _detect_language
# ---------------------------------------------------------------------------

class TestDetectLanguage:
    def test_php_when_composer_json_present(self, tmp_path):
        (tmp_path / "composer.json").write_text("{}", encoding="utf-8")
        assert _detect_language(tmp_path) == "php"

    def test_python_when_no_composer_json(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
        assert _detect_language(tmp_path) == "python"

    def test_php_takes_priority_over_pyproject(self, tmp_path):
        (tmp_path / "composer.json").write_text("{}", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
        assert _detect_language(tmp_path) == "php"

    def test_empty_dir_defaults_to_python(self, tmp_path):
        assert _detect_language(tmp_path) == "python"


# ---------------------------------------------------------------------------
# _asdict
# ---------------------------------------------------------------------------

class TestAsdict:
    def test_plain_dict(self):
        assert _asdict({"a": 1, "b": {"c": 2}}) == {"a": 1, "b": {"c": 2}}

    def test_list(self):
        assert _asdict([1, "x", None]) == [1, "x", None]

    def test_scalar_types(self):
        for val in ("hello", 42, 3.14, True, None):
            assert _asdict(val) == val

    def test_unknown_object_coerced_to_str(self):
        class Foo:
            def __str__(self) -> str:
                return "foo-str"
        assert _asdict(Foo()) == "foo-str"

    def test_dataclass_instance_converted_to_dict(self):
        """Kill is_dataclass(obj) → is_dataclass(None) mutation (mutant_2)
        and is_dataclass(obj) && isinstance(obj, type) mutation (mutant_3):
        the dataclass class itself must NOT be converted, only instances."""
        from dataclasses import dataclass

        @dataclass
        class Point:
            x: int
            y: int

        # Instance → dict (the real path)
        result = _asdict(Point(x=1, y=2))
        assert result == {"x": 1, "y": 2}

        # Class object (a type) → str, NOT asdict (kills mutant_3)
        result_type = _asdict(Point)
        assert isinstance(result_type, str)

    def test_none_is_not_treated_as_dataclass(self):
        """Kill is_dataclass(None) mutation — None must pass through unchanged."""
        assert _asdict(None) is None


# ---------------------------------------------------------------------------
# _exit_with
# ---------------------------------------------------------------------------

class TestExitWith:
    def test_json_mode_dict(self, capsys):
        _exit_with(PASS, {"key": "val"}, json_mode=True)
        assert json.loads(capsys.readouterr().out) == {"key": "val"}

    def test_json_output_uses_indent_2(self, capsys):
        """Kill indent=2→None mutation: output must be pretty-printed (has newlines)."""
        _exit_with(PASS, {"key": "val"}, json_mode=True)
        out = capsys.readouterr().out
        assert "\n" in out  # indent=None produces a single line; indent=2 adds newlines

    def test_non_json_dict_prints_json(self, capsys):
        _exit_with(PASS, {"x": 1}, json_mode=False)
        assert '"x": 1' in capsys.readouterr().out

    def test_non_json_str_prints_string_not_none(self, capsys):
        """Kill print(payload)→print(None) mutation: str payload printed as-is."""
        _exit_with(PASS, "hello-world", json_mode=False)
        out = capsys.readouterr().out
        assert "hello-world" in out
        assert "None" not in out

    def test_default_quiet_is_false_output_produced(self, capsys):
        """Kill quiet default False→True mutation: output must appear by default."""
        _exit_with(PASS, {"k": "v"})
        assert capsys.readouterr().out != ""

    def test_quiet_suppresses_output(self, capsys):
        _exit_with(PASS, {"key": "val"}, json_mode=True, quiet=True)
        assert capsys.readouterr().out == ""

    def test_returns_code(self):
        assert _exit_with(FAIL, "") == FAIL
        assert _exit_with(INTERNAL_ERROR, "") == INTERNAL_ERROR


# ---------------------------------------------------------------------------
# _cmd_all
# ---------------------------------------------------------------------------

class TestCmdAll:
    """Tests for the 'all' subcommand with the new inline-adapter architecture."""

    def _make_mock_adapter(self, *, passed: bool = True) -> MagicMock:
        adapter = MagicMock()
        lr = _make_layer(passed=passed)
        for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
            getattr(adapter, method).return_value = lr
        return adapter

    def test_nonexistent_repo_returns_unsupported(self, tmp_path):
        code = _cmd_all(_make_args(repo=str(tmp_path / "nowhere")))
        assert code == UNSUPPORTED

    def test_python_repo_all_pass(self, tmp_path):
        adapter = self._make_mock_adapter(passed=True)
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path)))
        assert code == PASS

    def test_php_repo_all_pass(self, tmp_path):
        (tmp_path / "composer.json").write_text("{}", encoding="utf-8")
        adapter = self._make_mock_adapter(passed=True)
        with (
            patch("harness_quality_gate.cli.PhpAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path)))
        assert code == PASS

    def test_any_layer_fails_returns_fail(self, tmp_path):
        adapter = MagicMock()
        adapter.run_l3a.return_value = _make_layer(passed=False)
        for method in ("run_l1", "run_l2", "run_l3b", "run_l4"):
            getattr(adapter, method).return_value = _make_layer(passed=True)
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path)))
        assert code == FAIL

    def test_adapter_import_failure_returns_internal_error(self, tmp_path):
        with patch("harness_quality_gate.cli.PythonAdapter", side_effect=ImportError("missing")):
            code = _cmd_all(_make_args(repo=str(tmp_path)))
        assert code == INTERNAL_ERROR

    def test_layer_run_exception_returns_internal_error(self, tmp_path):
        adapter = MagicMock()
        adapter.run_l3a.side_effect = RuntimeError("tool crashed")
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path)))
        assert code == INTERNAL_ERROR

    def test_json_output_contains_layers(self, tmp_path, capsys):
        adapter = self._make_mock_adapter(passed=True)
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path), json=True))
        assert code == PASS
        out = json.loads(capsys.readouterr().out)
        assert "layers" in out
        assert out["language"] == "python"

    def test_nonexistent_repo_json_error_has_error_key(self, tmp_path, capsys):
        """Kill error-dict key mutations: JSON must contain 'error' and 'exit_code'."""
        code = _cmd_all(_make_args(repo=str(tmp_path / "nowhere"), json=True))
        assert code == UNSUPPORTED
        out = json.loads(capsys.readouterr().out)
        assert "error" in out
        assert out["exit_code"] == UNSUPPORTED

    def test_adapter_exception_json_error_keys(self, tmp_path, capsys):
        """Kill error-dict key mutations on adapter load failure path."""
        with patch("harness_quality_gate.cli.PythonAdapter", side_effect=ImportError("missing")):
            code = _cmd_all(_make_args(repo=str(tmp_path), json=True))
        assert code == INTERNAL_ERROR
        out = json.loads(capsys.readouterr().out)
        assert "error" in out
        assert out["exit_code"] == INTERNAL_ERROR

    def test_php_language_uses_php_adapter_not_python(self, tmp_path):
        """Kill language=='php'→'XXphpXX' mutation: composer.json must trigger PhpAdapter."""
        (tmp_path / "composer.json").write_text("{}", encoding="utf-8")
        php_adapter = MagicMock()
        py_adapter = MagicMock()
        lr = _make_layer(passed=True)
        for m in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
            getattr(php_adapter, m).return_value = lr
            getattr(py_adapter, m).return_value = lr
        with (
            patch("harness_quality_gate.cli.PhpAdapter", return_value=php_adapter),
            patch("harness_quality_gate.cli.PythonAdapter", return_value=py_adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            _cmd_all(_make_args(repo=str(tmp_path)))
        # PhpAdapter must have been called, NOT PythonAdapter
        assert php_adapter.run_l3a.called
        assert not py_adapter.run_l3a.called

    def test_checkpoint_written_to_quality_gate_path(self, tmp_path):
        """Kill work_dir path mutations: checkpoint written under _quality-gate/work."""
        adapter = MagicMock()
        lr = _make_layer(passed=True)
        for m in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
            getattr(adapter, m).return_value = lr
        written_paths: list[str] = []

        def capture_write(path, data):
            written_paths.append(str(path))

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint", side_effect=capture_write),
        ):
            _cmd_all(_make_args(repo=str(tmp_path)))
        assert written_paths, "write_checkpoint should have been called"
        assert "_quality-gate" in written_paths[0]
        assert "work" in written_paths[0]

    def test_latest_checkpoint_write_failure_is_swallowed(self, tmp_path):
        adapter = self._make_mock_adapter(passed=True)
        write_fail_count = {"n": 0}
        original = Path.write_text

        def patched(self, *args, **kwargs):
            write_fail_count["n"] += 1
            if write_fail_count["n"] == 1:
                raise OSError("disk full")
            return original(self, *args, **kwargs)

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
            patch.object(Path, "write_text", patched),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path)))
        assert code == PASS


# ---------------------------------------------------------------------------
# _cmd_audit_ignores
# ---------------------------------------------------------------------------

class TestCmdAuditIgnores:
    def _make_audit_report(self, exit_code: int = 0):
        from harness_quality_gate.allow_list_auditor import AuditReport
        return AuditReport(findings=[], summary="clean", exit_code=exit_code, ignored_count=0)

    def test_python_pragma_unjustified_fails(self, tmp_path):
        (tmp_path / "m.py").write_text("x = 1  # pragma: no mutate\n", encoding="utf-8")
        assert _cmd_audit_ignores(_make_args(repo=str(tmp_path))) == FAIL

    def test_python_pragma_justified_passes(self, tmp_path):
        (tmp_path / "m.py").write_text(
            "# reason: provably-equivalent mutant\n"
            "# audited: 2026-06-03\n"
            "x = 1  # pragma: no mutate\n",
            encoding="utf-8",
        )
        assert _cmd_audit_ignores(_make_args(repo=str(tmp_path))) == PASS

    def test_clean_repo_passes(self, tmp_path):
        (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")
        assert _cmd_audit_ignores(_make_args(repo=str(tmp_path))) == PASS

    def test_php_unjustified_fails(self, tmp_path):
        (tmp_path / "x.php").write_text(
            "<?php\n// @infection-ignore-all\nfunction f() {}\n", encoding="utf-8"
        )
        assert _cmd_audit_ignores(_make_args(repo=str(tmp_path))) == FAIL

    def test_audit_exception_returns_internal_error(self, tmp_path):
        with patch.object(
            __import__("harness_quality_gate.allow_list_auditor", fromlist=["AllowListAuditor"])
            .AllowListAuditor,
            "audit",
            side_effect=RuntimeError("scan failed"),
        ):
            code = _cmd_audit_ignores(_make_args(repo=str(tmp_path)))
        assert code == INTERNAL_ERROR

    def test_exception_emits_error_json(self, tmp_path, capsys):
        with patch.object(
            __import__("harness_quality_gate.allow_list_auditor", fromlist=["AllowListAuditor"])
            .AllowListAuditor,
            "audit",
            side_effect=RuntimeError("scan failed"),
        ):
            code = _cmd_audit_ignores(_make_args(repo=str(tmp_path), json=True))
        assert code == INTERNAL_ERROR
        out = json.loads(capsys.readouterr().out)
        assert out["error"] == "scan failed"
        assert out["exit_code"] == INTERNAL_ERROR

    def test_json_output_merges_languages(self, tmp_path, capsys):
        (tmp_path / "m.py").write_text(
            "# reason: provably-equivalent\n# audited: 2026-06-03\n"
            "x = 1  # pragma: no mutate\n",
            encoding="utf-8",
        )
        code = _cmd_audit_ignores(_make_args(repo=str(tmp_path), json=True))
        assert code == PASS
        out = json.loads(capsys.readouterr().out)
        assert out["exit_code"] == PASS
        assert out["ignored_count"] == 1
        assert " | " in out["summary"]

    def test_diff_from_passed_to_both_auditors(self, tmp_path):
        report = self._make_audit_report(exit_code=0)
        args = _make_args(repo=str(tmp_path))
        args.diff_from = "origin/main"
        with patch.object(
            __import__("harness_quality_gate.allow_list_auditor", fromlist=["AllowListAuditor"])
            .AllowListAuditor,
            "audit",
            return_value=report,
        ) as mock_audit:
            _cmd_audit_ignores(args)
        assert mock_audit.call_count == 2
        for call in mock_audit.call_args_list:
            assert call.args == (tmp_path.resolve(), "origin/main")


# ---------------------------------------------------------------------------
# main() dispatcher
# ---------------------------------------------------------------------------

class TestMain:
    def test_no_subcommand_returns_unsupported(self):
        code = main([])
        assert code == UNSUPPORTED

    def test_all_subcommand_dispatches(self, tmp_path):
        adapter = MagicMock()
        lr = _make_layer(passed=True)
        for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
            getattr(adapter, method).return_value = lr
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = main(["all", str(tmp_path)])
        assert code == PASS

    def test_audit_ignores_subcommand_dispatches(self, tmp_path):
        (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")
        code = main(["audit-ignores", str(tmp_path)])
        assert code == PASS

    def test_unknown_subcommand_returns_unsupported(self):
        code = main(["nonexistent"])
        assert code == UNSUPPORTED
