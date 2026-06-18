"""Unit tests for harness_quality_gate/cli.py.

Covers the two live subcommands (all, audit-ignores), the output helpers,
and the main() dispatcher.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from harness_quality_gate.cli import (
    _asdict,
    _check_venv,
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
    defaults = {"repo": ".", "json": False, "quiet": False, "paths": None}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _make_layer(*, passed: bool = True, layer: str = "L3A", language: str = "python", tool_specific: dict | None = None) -> LayerResult:
    return LayerResult(
        layer=layer, language=language, passed=passed, findings=[],
        duration_sec=0.0, tool_specific=tool_specific,
    )


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
    def test_dict_payload_prints_exact_json(self, capsys):
        """Pin the exact serialised output: kills indent=2 and quiet-inversion mutations."""
        _exit_with(PASS, {"key": "val"}, quiet=False)
        assert capsys.readouterr().out == '{\n  "key": "val"\n}\n'

    def test_dataclass_payload_serialised_as_dict(self, capsys):
        from harness_quality_gate.allow_list_auditor import AuditReport
        report = AuditReport(findings=[], summary="s", exit_code=0, ignored_count=3)
        _exit_with(PASS, report, quiet=False)
        assert json.loads(capsys.readouterr().out) == {
            "findings": [], "summary": "s", "exit_code": 0, "ignored_count": 3,
        }

    def test_quiet_suppresses_output(self, capsys):
        _exit_with(PASS, {"key": "val"}, quiet=True)
        assert capsys.readouterr().out == ""

    def test_returns_code(self):
        assert _exit_with(FAIL, {}, quiet=True) == FAIL
        assert _exit_with(INTERNAL_ERROR, {}, quiet=True) == INTERNAL_ERROR


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
            patch("harness_quality_gate.cli._missing_php_tools", return_value=[]),
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

    def test_layer_with_tool_specific_included_in_checkpoint(self, tmp_path, capsys):
        """Kill tool_specific branch (cli.py:146-147): a non-None tool_specific
        is included in the layer dict sent to write_checkpoint."""
        tool_specific = {"phpunit_version": "10.5.0", "infection_msi": 100.0}
        adapter = MagicMock()
        for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
            getattr(adapter, method).return_value = _make_layer(
                layer=method.replace("run_", "").upper(),
                language="php",
                passed=True,
                tool_specific=tool_specific,
            )
        with (
            patch("harness_quality_gate.cli.PhpAdapter", return_value=adapter),
            patch("harness_quality_gate.cli._missing_php_tools", return_value=[]),
            patch("harness_quality_gate.cli.write_checkpoint") as mock_write,
        ):
            (tmp_path / "composer.json").write_text("{}", encoding="utf-8")
            code = _cmd_all(_make_args(repo=str(tmp_path)))
        assert code == PASS
        # Verify write_checkpoint was called with a checkpoint dict containing tool_specific
        call_args = mock_write.call_args
        checkpoint_dict = call_args.args[1]
        l3a = next(ly for ly in checkpoint_dict["layers"] if ly.get("layer") == "L3A")
        assert l3a.get("tool_specific") == tool_specific

    def test_nonexistent_repo_quiet_suppresses_output(self, tmp_path, capsys):
        """Kill quiet=args.quiet→None on the nonexistent-repo error path."""
        code = _cmd_all(_make_args(repo=str(tmp_path / "nowhere"), quiet=True))
        assert code == UNSUPPORTED
        assert capsys.readouterr().out == ""

    def test_adapter_error_quiet_suppresses(self, tmp_path, capsys):
        """Kill quiet=args.quiet→None on the adapter-load-error path."""
        with patch("harness_quality_gate.cli.PythonAdapter", side_effect=ImportError("boom")):
            code = _cmd_all(_make_args(repo=str(tmp_path), quiet=True))
        assert code == INTERNAL_ERROR
        assert capsys.readouterr().out == ""

    def test_layer_error_quiet_suppresses(self, tmp_path, capsys):
        """Kill quiet=args.quiet→None on the layer-execution-error path."""
        adapter = MagicMock()
        adapter.run_l3a.side_effect = RuntimeError("boom")
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path), quiet=True))
        assert code == INTERNAL_ERROR
        assert capsys.readouterr().out == ""

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
            patch("harness_quality_gate.cli._missing_php_tools", return_value=[]),
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
        from pathlib import PurePath
        p = PurePath(written_paths[0])
        # Must be under _quality-gate/work/ directory (not just in the filename)
        assert "_quality-gate" in p.parts, f"Expected _quality-gate dir in {p}"
        assert "work" in p.parts, f"Expected work dir in {p}"

    def test_layer_receives_repo_path_not_none(self, tmp_path):
        """Kill run_layer(repo, env) → run_layer(None, env) mutation.
        The adapter must receive the actual repo Path, not None."""
        adapter = MagicMock()
        lr = _make_layer(passed=True)
        received_repos: list = []

        def capture_call(repo_arg, env_arg):
            received_repos.append(repo_arg)
            return lr

        for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
            getattr(adapter, method).side_effect = capture_call

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            _cmd_all(_make_args(repo=str(tmp_path)))

        assert all(r == tmp_path.resolve() for r in received_repos), (
            f"Expected all calls with repo={tmp_path.resolve()!r}, got {received_repos}"
        )

    def test_json_output_layer_keys(self, tmp_path, capsys):
        """Kill 'layer'→'XXlayerXX', 'findings'→'XXfindingsXX', 'duration_sec' mutations
        in layer_dicts. The checkpoint JSON must use exact key names with correct values."""
        from harness_quality_gate.models import Finding
        adapter = MagicMock()
        finding = Finding(node="src/A.php", severity="error", message="SRP violation")
        lr = LayerResult(layer="L3A", language="python", passed=True, findings=[finding], duration_sec=1.25)
        for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
            getattr(adapter, method).return_value = lr
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path), json=True))
        assert code == PASS
        out = json.loads(capsys.readouterr().out)
        layer = out["layers"][0]
        assert layer["layer"] == "L3A"
        assert layer["language"] == "python"
        assert layer["passed"] is True
        assert layer["duration_sec"] == 1.25
        # findings must come from the "findings" key, not empty default
        assert len(layer["findings"]) == 1
        assert layer["findings"][0]["node"] == "src/A.php"

    def test_json_output_detection_keys(self, tmp_path, capsys):
        """Kill 'repo_path'→'XXrepo_pathXX', 'language'→'XXlanguageXX' in detection_info."""
        adapter = self._make_mock_adapter(passed=True)
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            _cmd_all(_make_args(repo=str(tmp_path), json=True))
        out = json.loads(capsys.readouterr().out)
        assert out["language"] == "python"
        assert out["repository"] == str(tmp_path.resolve())

    def test_exit_with_non_serialisable_coerced_by_asdict(self, capsys):
        """Non-JSON-serialisable values are stringified by _asdict before dumping."""
        from pathlib import Path
        _exit_with(PASS, {"path": Path("/some/path")}, quiet=False)
        out = json.loads(capsys.readouterr().out)
        assert out["path"] == "/some/path"

    def test_env_has_work_dir_key(self, tmp_path):
        """Kill env={**os.environ,'work_dir':str(work_dir)}→str(None) mutation.
        The adapter must receive env with 'work_dir' equal to the actual work path."""
        adapter = MagicMock()
        lr = _make_layer(passed=True)
        received_envs: list = []

        def capture_call(repo_arg, env_arg):
            received_envs.append(dict(env_arg) if env_arg else None)
            return lr

        for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
            getattr(adapter, method).side_effect = capture_call

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            _cmd_all(_make_args(repo=str(tmp_path)))

        assert received_envs, "adapter must be called"
        assert all(e is not None for e in received_envs)
        assert all("work_dir" in e for e in received_envs)
        # str(None) = "None" — value must be the actual work_dir path, not "None"
        expected_work_dir = str(tmp_path.resolve() / "_quality-gate" / "work")
        assert all(e["work_dir"] == expected_work_dir for e in received_envs), (
            f"Expected work_dir={expected_work_dir!r}, got {received_envs[0].get('work_dir')!r}"
        )

    def test_json_output_has_runtime_keys(self, tmp_path, capsys):
        """Kill 'python_version'→'XXpython_versionXX' and 'ci' key mutations."""
        adapter = self._make_mock_adapter(passed=True)
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            _cmd_all(_make_args(repo=str(tmp_path), json=True))
        out = json.loads(capsys.readouterr().out)
        # Checkpoint builder embeds runtime; language should appear
        assert "language" in out
        assert "layers" in out

    def test_json_output_languages_detected(self, tmp_path, capsys):
        """Kill 'languages_detected'→'XXlanguages_detectedXX' mutation in detection_info."""
        adapter = self._make_mock_adapter(passed=True)
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            _cmd_all(_make_args(repo=str(tmp_path), json=True))
        # The checkpoint builder reads detection_info; even if schema omits it,
        # the language field (from detection_info["language"]) must be "python"
        out = json.loads(capsys.readouterr().out)
        assert out.get("language") == "python"

    def test_adapter_error_json_keys_exact(self, tmp_path, capsys):
        """Kill {'error':...,'exit_code':...}→None on adapter load error path."""
        with patch("harness_quality_gate.cli.PythonAdapter", side_effect=RuntimeError("boom")):
            code = _cmd_all(_make_args(repo=str(tmp_path), json=True))
        assert code == INTERNAL_ERROR
        out = json.loads(capsys.readouterr().out)
        assert "error" in out
        assert out["exit_code"] == INTERNAL_ERROR

    def test_layer_error_json_keys_exact(self, tmp_path, capsys):
        """Kill {'error':str(exc),'exit_code':INTERNAL_ERROR} key mutations on layer error."""
        adapter = MagicMock()
        adapter.run_l3a.side_effect = RuntimeError("layer crashed")
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path), json=True))
        assert code == INTERNAL_ERROR
        out = json.loads(capsys.readouterr().out)
        assert "error" in out
        assert "layer crashed" in out["error"]
        # Kill "exit_code"→"XXexit_codeXX" / "EXIT_CODE" key mutations
        assert out["exit_code"] == INTERNAL_ERROR

    def test_cmd_all_output_is_always_json(self, tmp_path, capsys):
        """Checkpoint payloads are dicts → output must always be valid JSON."""
        adapter = self._make_mock_adapter(passed=True)
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            _cmd_all(_make_args(repo=str(tmp_path), json=True))
        out_str = capsys.readouterr().out.strip()
        assert out_str.startswith("{") or out_str.startswith("[")

    def test_nonexistent_repo_exact_error_payload(self, tmp_path, capsys):
        """Pin exact payload of the repo-not-found branch (keys, message, exit code)."""
        missing = tmp_path / "nowhere"
        code = _cmd_all(_make_args(repo=str(missing)))
        assert code == UNSUPPORTED
        out = json.loads(capsys.readouterr().out)
        assert out == {
            "error": f"repository not found: {missing.resolve()}",
            "exit_code": UNSUPPORTED,
        }

    def test_runtime_and_detection_exact_dicts(self, tmp_path, monkeypatch):
        """Pin the EXACT runtime and detection dicts passed to build_checkpoint.
        Kills key/value mutations: python_version→None, 'sequential', ci, repo_path,
        framework, confidence=1.0, languages_detected, file_counts."""
        import platform
        monkeypatch.delenv("CI", raising=False)
        adapter = self._make_mock_adapter(passed=True)
        captured: dict = {}

        def fake_build(*, layer_results, runtime, detection):
            captured["runtime"] = runtime
            captured["detection"] = detection
            from harness_quality_gate.checkpoint import build
            return build(layer_results=layer_results, runtime=runtime, detection=detection)

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
            patch("harness_quality_gate.cli.build_checkpoint", side_effect=fake_build),
        ):
            _cmd_all(_make_args(repo=str(tmp_path), quiet=True))

        assert captured["runtime"] == {
            "python_version": platform.python_version(),
            "venv_path": os.path.realpath(sys.executable),
            "venv_activated": [],
            "concurrency": "sequential",
            "ci": False,
        }
        assert captured["detection"] == {
            "repo_path": str(tmp_path.resolve()),
            "language": "python",
            "framework": None,
            "confidence": 1.0,
            "languages_detected": ["python"],
            "file_counts": {},
        }

    def test_layer_dict_exact_with_and_without_tool_specific(self, tmp_path, capsys):
        """Pin the exact layer dict shape, including the tool_specific branch."""
        adapter = MagicMock()
        lr_plain = LayerResult(
            layer="L3A", language="python", passed=True, findings=[], duration_sec=0.5,
        )
        lr_tool = LayerResult(
            layer="L1", language="python", passed=True, findings=[],
            duration_sec=1.25, tool_specific={"k": 1},
        )
        adapter.run_l3a.return_value = lr_plain
        adapter.run_l1.return_value = lr_tool
        for method in ("run_l2", "run_l3b", "run_l4"):
            getattr(adapter, method).return_value = lr_plain
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path), json=True))
        assert code == PASS
        out = json.loads(capsys.readouterr().out)
        assert out["layers"][0] == {
            "layer": "L3A", "language": "python", "passed": True,
            "findings": [], "duration_sec": 0.5,
        }
        assert out["layers"][1] == {
            "layer": "L1", "language": "python", "passed": True,
            "findings": [], "duration_sec": 1.25, "tool_specific": {"k": 1},
        }

    def test_cmd_all_quiet_mode_suppresses_output(self, tmp_path, capsys):
        """Kill quiet=args.quiet→quiet=None: quiet flag must suppress output."""
        adapter = self._make_mock_adapter(passed=True)
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            _cmd_all(_make_args(repo=str(tmp_path), quiet=True))
        assert capsys.readouterr().out == ""

    def test_ci_env_detected_in_runtime(self, tmp_path, capsys, monkeypatch):
        """Kill 'ci': bool(os.environ.get('CI')) mutation: CI flag must be True when set."""
        monkeypatch.setenv("CI", "true")
        adapter = self._make_mock_adapter(passed=True)
        checkpoint_calls: list = []

        def capture_build(*args, **kwargs):
            checkpoint_calls.append(kwargs)
            from harness_quality_gate.checkpoint import build
            return build(*args, **kwargs)

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
            patch("harness_quality_gate.cli.build_checkpoint", side_effect=capture_build),
        ):
            _cmd_all(_make_args(repo=str(tmp_path)))

        assert checkpoint_calls, "build_checkpoint must be called"
        runtime = checkpoint_calls[0].get("runtime", {})
        assert runtime.get("ci") is True

    def test_build_checkpoint_called_with_runtime_and_detection(self, tmp_path):
        """Kill runtime=runtime→runtime=None and detection=detection_info→detection=None mutations."""
        adapter = self._make_mock_adapter(passed=True)
        build_calls: list = []

        def capture_build(layer_results, runtime, detection):
            build_calls.append({"runtime": runtime, "detection": detection})
            from harness_quality_gate.checkpoint import build
            return build(layer_results=layer_results, runtime=runtime, detection=detection)

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
            patch("harness_quality_gate.cli.build_checkpoint", side_effect=capture_build),
        ):
            _cmd_all(_make_args(repo=str(tmp_path)))

        assert build_calls, "build_checkpoint must be called"
        # Both runtime and detection must be non-None dicts
        assert isinstance(build_calls[0]["runtime"], dict)
        assert isinstance(build_calls[0]["detection"], dict)
        assert "python_version" in build_calls[0]["runtime"]
        assert "language" in build_calls[0]["detection"]

    def test_write_checkpoint_receives_non_none_data(self, tmp_path):
        """Kill write_checkpoint(output_path, checkpoint_dict)→write_checkpoint(..., None).
        The data arg must be the actual checkpoint dict (not None) with 'layers' key."""
        adapter = self._make_mock_adapter(passed=True)
        written_data: list = []

        def capture_write(path, data):
            written_data.append(data)

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint", side_effect=capture_write),
        ):
            _cmd_all(_make_args(repo=str(tmp_path)))

        assert written_data, "write_checkpoint must be called"
        assert written_data[0] is not None
        assert isinstance(written_data[0], dict)
        assert "layers" in written_data[0]

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

    def test_timestamped_checkpoint_write_failure_is_swallowed(self, tmp_path):
        """Kill the 'except Exception ... logger.warning' mutation path (cli.py lines 187-189).

        When write_checkpoint raises for the timestamped file, the warning must be
        logged but execution continues so the latest checkpoint is still written.
        """
        adapter = self._make_mock_adapter(passed=True)
        call_count = {"n": 0}

        def failing_write(path, data):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First call: timestamped checkpoint — raise
                raise OSError("disk full for timestamped")
            # Second call: latest checkpoint — succeeds

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint", side_effect=failing_write),
            patch.object(Path, "write_text", Path.write_text),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path)))

        # The command should still pass — exception is swallowed
        assert code == PASS
        # The latest checkpoint must still have been written
        latest = tmp_path / "_quality-gate" / "quality-gate-latest.json"
        assert latest.exists()


# ---------------------------------------------------------------------------
# _cmd_audit_ignores
# ---------------------------------------------------------------------------

class TestCmdAuditIgnores:
    def _make_audit_report(self, exit_code: int = 0):
        from harness_quality_gate.allow_list_auditor import AuditReport
        return AuditReport(findings=[], summary="clean", exit_code=exit_code, ignored_count=0)

    def test_python_pragma_unjustified_fails(self, tmp_path):
        (tmp_path / "m.py").write_text("x = 1  # pragma: " "no mutate\n", encoding="utf-8")
        assert _cmd_audit_ignores(_make_args(repo=str(tmp_path))) == FAIL

    def test_python_pragma_justified_passes(self, tmp_path):
        (tmp_path / "m.py").write_text(
            "# reason: provably-equivalent mutant\n"
            "# audited: 2026-06-03\n"
            "x = 1  # pragma: " "no mutate\n",
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
            "x = 1  # pragma: " "no mutate\n",
            encoding="utf-8",
        )
        code = _cmd_audit_ignores(_make_args(repo=str(tmp_path), json=True))
        assert code == PASS
        out = json.loads(capsys.readouterr().out)
        assert out["exit_code"] == PASS
        assert out["ignored_count"] == 1
        assert " | " in out["summary"]

    def test_audit_exception_quiet_suppresses_output(self, tmp_path, capsys):
        """Kill quiet=args.quiet→None in exception path: quiet=True must suppress output."""
        with patch.object(
            __import__("harness_quality_gate.allow_list_auditor", fromlist=["AllowListAuditor"])
            .AllowListAuditor,
            "audit",
            side_effect=RuntimeError("scan failed"),
        ):
            code = _cmd_audit_ignores(_make_args(repo=str(tmp_path), quiet=True))
        assert code == INTERNAL_ERROR
        assert capsys.readouterr().out == ""

    def test_audit_findings_are_merged_from_both_languages(self, tmp_path, capsys):
        """Kill findings=[flatmap]→findings=None: merged report JSON must list all findings."""
        from harness_quality_gate.allow_list_auditor import AuditReport
        from harness_quality_gate.models import Finding

        php_finding = Finding(node="x.php", severity="error", message="PHP suppress")
        py_finding = Finding(node="m.py", severity="error", message="Py suppress")
        php_report = AuditReport(findings=[php_finding], summary="php:1", exit_code=FAIL, ignored_count=1)
        py_report = AuditReport(findings=[py_finding], summary="py:1", exit_code=FAIL, ignored_count=1)

        with patch.object(
            __import__("harness_quality_gate.allow_list_auditor", fromlist=["AllowListAuditor"])
            .AllowListAuditor,
            "audit",
            side_effect=[php_report, py_report],
        ):
            code = _cmd_audit_ignores(_make_args(repo=str(tmp_path), json=True))
        assert code == FAIL
        out = json.loads(capsys.readouterr().out)
        # findings=None would produce null; flatmap must produce a list of 2 entries
        assert isinstance(out["findings"], list)
        assert len(out["findings"]) == 2
        nodes = {f["node"] for f in out["findings"]}
        assert "x.php" in nodes and "m.py" in nodes

    def test_unjustified_pragma_json_exit_code_is_fail(self, tmp_path, capsys):
        """Kill exit_code=FAIL if has_unjustified else PASS removal from AuditReport.
        When unjustified pragma exists, merged JSON must have exit_code=FAIL (not default 0)."""
        (tmp_path / "m.py").write_text("x = 1  # pragma: " "no mutate\n", encoding="utf-8")
        code = _cmd_audit_ignores(_make_args(repo=str(tmp_path), json=True))
        assert code == FAIL
        out = json.loads(capsys.readouterr().out)
        # exit_code in merged AuditReport must be FAIL (1), not the default 0
        assert out["exit_code"] == FAIL

    def test_merged_summary_exact_join(self, tmp_path, capsys):
        """Pin the exact ' | ' separator: kills ' | '→'XX | XX' (substring asserts miss it)."""
        from harness_quality_gate.allow_list_auditor import AuditReport
        php_r = AuditReport(findings=[], summary="php-part", exit_code=0, ignored_count=2)
        py_r = AuditReport(findings=[], summary="py-part", exit_code=0, ignored_count=3)

        def fake_auditor(language):
            report = php_r if language == "php" else py_r
            return MagicMock(audit=MagicMock(return_value=report))

        with patch("harness_quality_gate.cli.AllowListAuditor", side_effect=fake_auditor):
            code = _cmd_audit_ignores(_make_args(repo=str(tmp_path), json=True))
        assert code == PASS
        out = json.loads(capsys.readouterr().out)
        assert out["summary"] == "php-part | py-part"
        assert out["ignored_count"] == 5
        assert out["exit_code"] == PASS
        assert out["findings"] == []

    def test_happy_path_quiet_suppresses_output(self, tmp_path, capsys):
        """Kill quiet=args.quiet→None on the final (non-exception) return."""
        (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")
        code = _cmd_audit_ignores(_make_args(repo=str(tmp_path), quiet=True))
        assert code == PASS
        assert capsys.readouterr().out == ""

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

    def test_main_with_none_argv_uses_sys_argv(self, monkeypatch):
        """Kill argv is None → argv is not None: when None, must read sys.argv[1:]."""
        monkeypatch.setattr("sys.argv", ["prog"])  # sys.argv[1:] = []
        code = main(None)
        # With empty argv, command is None → UNSUPPORTED
        assert code == UNSUPPORTED

    def test_main_with_explicit_argv_ignores_sys_argv(self, monkeypatch):
        """Kill argv is None inversion: explicit argv must NOT fall back to sys.argv.

        _cmd_all is mocked so the parse_args(argv)->parse_args(None) mutant
        dies fast: unmocked, the mutant dispatched the FULL gate (mutation
        campaign included) and only died as an expensive timeout (self-eval).
        """
        monkeypatch.setattr("sys.argv", ["prog", "all"])
        with patch("harness_quality_gate.cli._cmd_all", return_value=PASS) as cmd_all:
            # Pass explicit empty list — should NOT dispatch 'all' from sys.argv
            code = main([])
        assert code == UNSUPPORTED
        cmd_all.assert_not_called()

    def test_main_none_argv_dispatches_from_sys_argv(self, tmp_path, monkeypatch, capsys):
        """Kill sys.argv[1:] index mutations: bare main() must parse real argv."""
        (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")
        monkeypatch.setattr(
            "sys.argv", ["prog", "audit-ignores", str(tmp_path), "--quiet"],
        )
        assert main(None) == PASS
        assert capsys.readouterr().out == ""

    def test_repo_arg_defaults_to_dot(self):
        """Kill default='.' mutation: omitted repo must reach the command as '.'.

        NOTE: do NOT use monkeypatch.chdir here — mutmut's stats collection
        resolves mutated source paths relative to the cwd and crashes.
        """
        with patch("harness_quality_gate.cli._cmd_audit_ignores", return_value=PASS) as cmd:
            assert main(["audit-ignores", "--quiet"]) == PASS
        args = cmd.call_args.args[0]
        assert args.repo == "."
        assert args.quiet is True
        assert args.json is False

    def test_top_level_help_exact_strings(self, capsys):
        """Kill prog/description/subcommand-help string mutations via --help output.

        Plain substring asserts cannot kill XXfooXX-style wrapping (the original
        is still contained), so each literal is anchored with a delimiter the
        wrap breaks: 'usage: ' on the left, '\\n' on the right.
        """
        code = main(["--help"])
        assert code == UNSUPPORTED
        out = capsys.readouterr().out
        assert "usage: harness_quality_gate " in out
        assert "\nPolyglot quality gate for Python and PHP repositories.\n" in out
        assert "Run all quality-gate layers\n" in out
        assert "Audit suppression annotations\n" in out

    def test_subcommand_help_exact_strings(self, capsys):
        """Kill _add_common_flags help-string mutations via 'all --help' output."""
        code = main(["all", "--help"])
        assert code == UNSUPPORTED
        out = capsys.readouterr().out
        assert "Path to repository root\n" in out
        assert "Emit JSON output\n" in out
        assert "Suppress output\n" in out

    def test_audit_ignores_help_exact_strings(self, capsys):
        """Kill --diff-from help-string mutation via 'audit-ignores --help' output."""
        code = main(["audit-ignores", "--help"])
        assert code == UNSUPPORTED
        out = capsys.readouterr().out
        assert "Git ref to diff against\n" in out

    def test_diff_from_flag_parsed_through_main(self):
        """Kill '--diff-from'→'--DIFF-FROM' flag-name mutation via real parsing."""
        with patch("harness_quality_gate.cli._cmd_audit_ignores", return_value=PASS) as cmd:
            code = main(["audit-ignores", ".", "--diff-from", "origin/main", "--quiet"])
        assert code == PASS
        args = cmd.call_args.args[0]
        assert args.diff_from == "origin/main"


class TestCheckVenv:
    """Tests for _check_venv(repo, language) — venv mismatch detection."""

    def test_returns_empty_list_for_php(self, tmp_path: Path) -> None:
        """PHP repos skip venv checks."""
        assert _check_venv(tmp_path, "php") == []

    def test_returns_empty_when_no_venv(self, tmp_path: Path) -> None:
        """No .venv dir → no warnings."""
        assert _check_venv(tmp_path, "python") == []

    def test_warns_when_outside_venv(self, tmp_path: Path) -> None:
        """Running outside .venv → warning."""
        venv_py = tmp_path / ".venv" / "bin" / "python"
        venv_py.parent.mkdir(parents=True, exist_ok=True)
        venv_py.touch()
        # Fake sys.executable to a different path
        with patch("harness_quality_gate.cli.sys.executable", "/usr/bin/python3"):
            warnings = _check_venv(tmp_path, "python")
        assert len(warnings) == 1
        assert "outside venv" in warnings[0]
        assert str(venv_py) in warnings[0]

    def test_no_warning_when_inside_venv(self, tmp_path: Path) -> None:
        """Running inside .venv → no warning."""
        venv_py = tmp_path / ".venv" / "bin" / "python"
        venv_py.parent.mkdir(parents=True, exist_ok=True)
        venv_py.touch()
        with patch("harness_quality_gate.cli.sys.executable", str(venv_py)):
            warnings = _check_venv(tmp_path, "python")
        assert warnings == []

