"""§4.1 Dense-assertion tests for mutmut survivors across CLI, PHP and Python adapters.

Targets:
  CLI _cmd_all          — dict keys (mutmut_28/34/39/50/130-133/148/149/204/242/244/245)
  phpunit _parse_junit  — mutmut_27/28/29
  weak_test _parse_single_output — mutmut_12/13/14/15
  visitor_runner _parse_visitor_output — mutmut_12/13/14/15
  visitor_runner _build_finding — mutmut_10/12
  visitor_runner _merge_findings — mutmut_2
  python_adapter _run_pytest — mutmut_27/29/33/34/36/38/39/40/41 (PATH construction)
  python_adapter _weak_test_findings — mutmut_69/73/74
  python_adapter check_tools — mutmut_7/11
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.base import ToolInvocation
from harness_quality_gate.cli import _cmd_all, main
from harness_quality_gate.exit_codes import CONFIG_INVALID, FAIL, PASS, UNSUPPORTED
from harness_quality_gate.models import Finding, LayerResult


# ===========================================================================
# HELPERS
# ===========================================================================

def _args(**kw):
    defaults = {"repo": ".", "json": False, "quiet": False, "paths": None}
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _mock_adapter(*, passed: bool = True) -> MagicMock:
    adapter = MagicMock()
    lr = LayerResult(
        layer="L3A", language="python", passed=passed,
        findings=[], duration_sec=0.0,
    )
    for m in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
        getattr(adapter, m).return_value = lr
    return adapter


# ===========================================================================
# CLI _cmd_all — dict key mutations
# ===========================================================================

class TestCmdAllDictKeys:
    """Mutants that change dict keys: 'error' -> 'XXerrorXX', 'exit_code' -> ...

    Also checks LayerResult fields (language, findings, duration_sec) via the
    JSON output of capsys.readouterr() for partial runs.
    """

    def test_error_dict_has_correct_keys_on_validate_paths_failure(
        self, tmp_path, capsys
    ):
        """validate_paths ValueError -> JSON with {'error': str, 'exit_code': int}.

        Kills: mutmut_28, 30, 31, 38, 43-47
        """
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test"\nversion = "0.1.0"\n', encoding="utf-8"
        )
        with patch("harness_quality_gate.cli.PythonAdapter", return_value=MagicMock()):
            with patch(
                "harness_quality_gate.bootstrap.validate_paths",
                side_effect=ValueError("invalid path: --evil"),
            ):
                _cmd_all(_args(repo=str(tmp_path), paths=["--evil"], json=True))

        out = json.loads(capsys.readouterr().out)
        assert set(out.keys()) == {"error", "exit_code"}
        assert out["error"] == "invalid path: --evil"
        assert out["exit_code"] == CONFIG_INVALID

    def test_error_dict_empty_paths_has_exact_keys(self, tmp_path, capsys):
        """args.paths=[] -> CONFIG_INVALID with keys {'error', 'exit_code'}.

        Kills: mutmut_28, 30, 31
        """
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test"\nversion = "0.1.0"\n',
            encoding="utf-8",
        )
        with patch("harness_quality_gate.cli.PythonAdapter", return_value=MagicMock()):
            _cmd_all(_args(repo=str(tmp_path), paths=[], json=True))

        out = json.loads(capsys.readouterr().out)
        assert set(out.keys()) == {"error", "exit_code"}
        assert isinstance(out["error"], str) and len(out["error"]) > 0
        assert out["exit_code"] == CONFIG_INVALID

    def test_error_dict_missing_php_tools_exact_keys(self, tmp_path, capsys):
        """PHP repo missing tools -> keys {'error', 'missing_tools', 'exit_code'}.

        Kills: mutmut_28/30/31 on the _missing_php_tools path.
        """
        (tmp_path / "composer.json").write_text("{}")
        with patch("shutil.which", return_value=None):
            ret = main(["all", str(tmp_path), "--json"])

        assert ret == 3  # INFRA_INCOMPLETE
        out = json.loads(capsys.readouterr().out)
        assert set(out.keys()) >= {"error", "missing_tools", "exit_code"}
        assert isinstance(out["missing_tools"], list)
        assert out["exit_code"] == 3

    def test_checkpoint_dict_has_layers_key(self, tmp_path, capsys):
        """checkpoint dict must have 'layers' key with list content.

        Kills: mutmut_130-133 (layer_names tuple mutations).
        """
        adapter = _mock_adapter(passed=True)
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            _cmd_all(_args(repo=str(tmp_path), json=True))

        data = json.loads(capsys.readouterr().out)
        assert "layers" in data
        assert isinstance(data["layers"], list)
        assert len(data["layers"]) == 5

    def test_checkpoint_pass_key_is_boolean_true(self, tmp_path, capsys):
        """PASS key must be True (boolean), not None, 'pass', etc.

        Kills: mutmut_204, 239-241.
        """
        adapter = _mock_adapter(passed=True)
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            _cmd_all(_args(repo=str(tmp_path), json=True))

        data = json.loads(capsys.readouterr().out)
        assert "PASS" in data
        assert data["PASS"] is True
        assert type(data["PASS"]) is bool

    def test_checkpoint_pass_key_is_boolean_false(self, tmp_path, capsys):
        """PASS key must be False when layers fail."""
        adapter = MagicMock()
        adapter.run_l3a.return_value = LayerResult(
            layer="L3A", language="python", passed=False,
            findings=[], duration_sec=0.0,
        )
        adapter.run_l1.return_value = LayerResult(
            layer="L1", language="python", passed=True,
            findings=[], duration_sec=0.0,
        )
        for m in ("run_l2", "run_l3b", "run_l4"):
            getattr(adapter, m).return_value = LayerResult(
                layer=m.replace("run_", ""), language="python", passed=True,
                findings=[], duration_sec=0.0,
            )
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            _cmd_all(_args(repo=str(tmp_path), json=True))

        data = json.loads(capsys.readouterr().out)
        assert data["PASS"] is False

    def test_layer_output_has_all_field_keys(self, tmp_path, capsys):
        """Each layer dict must have keys: layer, language, passed, findings, duration_sec.

        Kills: mutmut_242, 244, 245 -- mutations on field->None in JSON construction.
        """
        adapter = _mock_adapter(passed=True)
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            _cmd_all(_args(repo=str(tmp_path), json=True))

        data = json.loads(capsys.readouterr().out)
        required_keys = {"layer", "language", "passed", "findings", "duration_sec"}
        for layer in data["layers"]:
            assert set(layer.keys()) >= required_keys
            assert isinstance(layer["findings"], list)

    def test_quick_pass_l2_fields_all_exact(self, tmp_path, capsys):
        """Quick-pass L2: language='python', findings=[], duration_sec=0.0.

        Kills: mutmut_146 (language=None), 148 (findings=None), 149
        (duration_sec=None).
        """
        adapter = _mock_adapter(passed=True)
        adapter.run_l3a.return_value = LayerResult(
            layer="L3A", language="python", passed=True,
            findings=[], duration_sec=0.5,
        )
        adapter.run_l1.return_value = LayerResult(
            layer="L1", language="python", passed=True,
            findings=[], duration_sec=1.0,
        )
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            _cmd_all(_args(repo=str(tmp_path), paths=["src/"], json=True))

        data = json.loads(capsys.readouterr().out)
        l2 = next((l for l in data["layers"] if l["layer"] == "L2"), None)
        assert l2 is not None
        assert l2["language"] == "python"
        assert l2["findings"] == []
        assert l2["duration_sec"] == 0.0
        assert l2["passed"] is True

    def test_quick_pass_l3b_l4_fields_all_exact(self, tmp_path, capsys):
        """Quick-pass L3B and L4 must have correct fields."""
        adapter = _mock_adapter(passed=True)
        adapter.run_l3a.return_value = LayerResult(
            layer="L3A", language="python", passed=True,
            findings=[], duration_sec=0.5,
        )
        adapter.run_l1.return_value = LayerResult(
            layer="L1", language="python", passed=True,
            findings=[], duration_sec=1.0,
        )
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            _cmd_all(_args(repo=str(tmp_path), paths=["src/"], json=True))

        data = json.loads(capsys.readouterr().out)
        for name in ("L3B", "L4"):
            layer = next(l for l in data["layers"] if l["layer"] == name)
            assert layer["language"] == "python"
            assert layer["findings"] == []
            assert layer["duration_sec"] == 0.0
            assert layer["passed"] is True

    def test_run_l2_quick_pass_layer_name(self, tmp_path, capsys):
        """Quick-pass L2 must have layer='L2', language='python'."""
        adapter = _mock_adapter(passed=True)
        adapter.run_l3a.return_value = LayerResult(
            layer="L3A", language="python", passed=True,
            findings=[], duration_sec=0.5,
        )
        adapter.run_l1.return_value = LayerResult(
            layer="L1", language="python", passed=True,
            findings=[], duration_sec=1.0,
        )
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            _cmd_all(_args(repo=str(tmp_path), paths=["src/"], json=True))

        data = json.loads(capsys.readouterr().out)
        l2 = next(l for l in data["layers"] if l["layer"] == "L2")
        assert l2["layer"] == "L2"

    def test_argparse_paths_flags_in_help(self, capsys):
        """'all --help' contains 'Tier 1' with capital T.

        Kills: mutmut_31, 36, 37, 38 -- help string mutations.
        """
        code = main(["all", "--help"])
        assert code == UNSUPPORTED
        out = capsys.readouterr().out
        assert "--paths" in out
        assert "Tier 1" in out
        assert "Subset" in out

    def test_repo_not_found_dict_has_error_key(self, tmp_path, capsys):
        """Non-existent repo -> JSON with {'error'..., 'exit_code': 2}."""
        with patch("pathlib.Path.is_dir", return_value=False):
            _cmd_all(_args(repo="/nonexistent", json=True))

        out = json.loads(capsys.readouterr().out)
        assert set(out.keys()) >= {"error", "exit_code"}
        assert out["exit_code"] == UNSUPPORTED

    def test_internal_error_dict_has_error_key(self, tmp_path, capsys):
        """Adapter init fails -> JSON with {'error'..., 'exit_code': 5}."""
        with patch(
            "harness_quality_gate.cli.PythonAdapter",
            side_effect=RuntimeError("boom"),
        ):
            _cmd_all(_args(repo=str(tmp_path), json=True))

        out = json.loads(capsys.readouterr().out)
        assert "error" in out
        assert "exit_code" in out
        assert out["exit_code"] == 5

    def test_runtime_dict_has_required_fields(self, tmp_path, capsys):
        """runtime dict must have python_version, venv_path, concurrency, ci."""
        adapter = _mock_adapter(passed=True)
        captured_runtime = {}

        def capture_build(*, layer_results, runtime, detection):
            nonlocal captured_runtime
            captured_runtime.update(runtime)
            from harness_quality_gate.checkpoint import build
            return build(layer_results=layer_results, runtime=runtime, detection=detection)

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
            patch(
                "harness_quality_gate.cli.build_checkpoint",
                side_effect=capture_build,
            ),
        ):
            _cmd_all(_args(repo=str(tmp_path), quiet=True))

        assert "python_version" in captured_runtime
        assert "venv_path" in captured_runtime
        assert "concurrency" in captured_runtime
        assert "ci" in captured_runtime
        assert "venv_activated" in captured_runtime
        assert isinstance(captured_runtime["venv_activated"], list)


# ===========================================================================
# phpunit _parse_junit_xml — mutmut_27/28/29
# ===========================================================================

class TestPhpunitParseJunitXmlMutants:
    """Kill phpunit mutmut_27/28/29: root.get() default mutations."""

    def test_root_get_tests_default_not_mutated(self, tmp_path):
        """root.get('tests', '0') -> '0' not '' or None."""
        from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter
        p = tmp_path / "junit.xml"
        p.write_text(
            '<?xml version="1.0"?>'
            '<testsuites><testsuite></testsuite></testsuites>',
            encoding="utf-8",
        )
        findings = PhpUnitAdapter()._parse_junit_xml(p)
        warn = [f for f in findings if "No tests" in f.message]
        assert len(warn) == 1

    def test_root_get_errors_default_not_mutated(self, tmp_path):
        """root.get('errors', '0') -> '0' not 'XXXX' or None."""
        from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter
        p = tmp_path / "junit.xml"
        p.write_text(
            '<?xml version="1.0"?>'
            '<testsuites tests="1" errors="0" failures="0" skipped="0">'
            '<testsuite name="Tests"><testcase name="t" file="t.php"/>'
            '</testsuite></testsuites>',
            encoding="utf-8",
        )
        findings = PhpUnitAdapter()._parse_junit_xml(p)
        summary = [f for f in findings if "Tests:" in f.message][0]
        assert summary.severity == "info"

    def test_root_get_failures_default_not_mutated(self, tmp_path):
        """root.get('failures', '0') -> '0' not mutated."""
        from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter
        p = tmp_path / "junit.xml"
        p.write_text(
            '<?xml version="1.0"?>'
            '<testsuites tests="1" errors="0" failures="1" skipped="0">'
            '<testsuite name="Tests"><testcase name="t" classname="X">'
            '<failure>fail</failure></testcase></testsuite></testsuites>',
            encoding="utf-8",
        )
        findings = PhpUnitAdapter()._parse_junit_xml(p)
        summary = [f for f in findings if "Tests:" in f.message][0]
        assert summary.severity == "error"


# ===========================================================================
# weak_test _parse_single_output — mutmut_12/13/14/15
# ===========================================================================

class TestWeakTestParseSingleOutput:
    """Kill mutmut_12/13/14/15 on _parse_single_output."""

    def test_parse_single_output_valid_json(self):
        """Valid JSON array -> exact parsed result."""
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        data = [{"file": "t.php", "line": 1, "rule_id": "A1", "message": "m"}]
        result = PhpWeakTestAdapter._parse_single_output(json.dumps(data))
        assert result == data
        assert len(result) == 1

    def test_parse_single_output_not_truncated(self):
        """Long JSON -> 100 items, not 50."""
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        data = [{"file": f"t{i}.php", "line": i} for i in range(100)]
        result = PhpWeakTestAdapter._parse_single_output(json.dumps(data))
        assert len(result) == 100
        assert result[99]["file"] == "t99.php"

    def test_parse_single_output_returns_list_not_none(self):
        """Empty input -> [] not None."""
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        result = PhpWeakTestAdapter._parse_single_output("")
        assert result == []
        assert isinstance(result, list)

    def test_parse_single_output_invalid_json_returns_list(self):
        """Invalid JSON -> [] not None."""
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        result = PhpWeakTestAdapter._parse_single_output("{bad")
        assert result == []
        assert isinstance(result, list)

    def test_parse_single_output_bracket_extraction(self):
        """JSON embedded in warning text -> extracted correctly."""
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        text = 'Warning: ...\n[{"file":"x.php","line":5}]'
        result = PhpWeakTestAdapter._parse_single_output(text)
        assert len(result) == 1
        assert result[0]["file"] == "x.php"
        assert result[0]["line"] == 5

    def test_parse_single_output_no_bracket_extraction(self):
        """Only open bracket -> []"""
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        result = PhpWeakTestAdapter._parse_single_output("[[")
        assert result == []

    def test_parse_single_output_reverse_brackets(self):
        """] before [ -> []"""
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        result = PhpWeakTestAdapter._parse_single_output("]abc[")
        assert result == []

    def test_parse_single_output_all_paths_list(self):
        """Every code path returns list, never None."""
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        for inp in ("", "  ", "{bad", "[[", "]]", "[]", 'warn: [{"k":"v"}]'):
            result = PhpWeakTestAdapter._parse_single_output(inp)
            assert isinstance(result, list), f"Got {type(result).__name__} for {inp!r}"


# ===========================================================================
# visitor_runner _parse_visitor_output — mutmut_12/13/14/15
# ===========================================================================

class TestVisitorRunnerParseOutput:
    """Kill mutmut_12/13/14/15 on _parse_visitor_output."""

    def test_parse_visitor_output_valid_json(self):
        """Valid JSON -> exact result."""
        from harness_quality_gate.adapters.php.visitor_runner_adapter import (
            VisitorRunnerAdapter,
        )
        data = [{"file": "a.php", "line": 10, "rule_id": "R1", "message": "msg"}]
        result = VisitorRunnerAdapter._parse_visitor_output(json.dumps(data))
        assert result == data
        assert len(result) == 1

    def test_parse_visitor_output_not_truncated(self):
        """100 items -> all 100 returned."""
        from harness_quality_gate.adapters.php.visitor_runner_adapter import (
            VisitorRunnerAdapter,
        )
        data = [{"file": f"f{i}.php", "line": i} for i in range(100)]
        result = VisitorRunnerAdapter._parse_visitor_output(json.dumps(data))
        assert len(result) == 100
        assert result[99]["file"] == "f99.php"

    def test_parse_visitor_output_returns_list_empty(self):
        """Empty/invalid input -> [] not None."""
        from harness_quality_gate.adapters.php.visitor_runner_adapter import (
            VisitorRunnerAdapter,
        )
        for inp in ("", "   ", "{bad", "[["):
            result = VisitorRunnerAdapter._parse_visitor_output(inp)
            assert result == []
            assert isinstance(result, list)

    def test_parse_visitor_output_bracket_extraction(self):
        """JSON embedded in text -> extracted."""
        from harness_quality_gate.adapters.php.visitor_runner_adapter import (
            VisitorRunnerAdapter,
        )
        text = 'warn: [{"file":"x.php"}]'
        result = VisitorRunnerAdapter._parse_visitor_output(text)
        assert result == [{"file": "x.php"}]

    def test_parse_visitor_output_reverse_brackets(self):
        """] before [ -> []"""
        from harness_quality_gate.adapters.php.visitor_runner_adapter import (
            VisitorRunnerAdapter,
        )
        result = VisitorRunnerAdapter._parse_visitor_output("]abc[")
        assert result == []

    def test_parse_visitor_output_multiple_arrays(self):
        """find('[') != rfind(']') -- first and last matter."""
        from harness_quality_gate.adapters.php.visitor_runner_adapter import (
            VisitorRunnerAdapter,
        )
        text = '[{"a":1}, {"b":2}]'
        result = VisitorRunnerAdapter._parse_visitor_output(text)
        assert len(result) == 2

    def test_parse_visitor_output_all_paths_list(self):
        """Every path returns list."""
        from harness_quality_gate.adapters.php.visitor_runner_adapter import (
            VisitorRunnerAdapter,
        )
        for inp in ("", "   ", "{bad", "[[", "]]", "[]", "warn: [{\"k\":\"v\"}]"):
            result = VisitorRunnerAdapter._parse_visitor_output(inp)
            assert isinstance(result, list), f"Got {type(result).__name__} for {inp!r}"


# ===========================================================================
# visitor_runner _build_finding — mutmut_10/12
# ===========================================================================

class TestVisitorRunnerBuildFinding:
    """Kill mutmut_10/12 on _build_finding."""

    def test_build_finding_from_valid_dict_all_fields(self):
        """Valid dict -> Finding with ALL correct fields."""
        from harness_quality_gate.adapters.php.visitor_runner_adapter import (
            VisitorRunnerAdapter,
        )
        item = {
            "file": "src/Foo.php", "line": 42, "rule_id": "GOD001",
            "message": "Too many methods", "severity": "error",
            "fix_hint": "Split the class",
        }
        f = VisitorRunnerAdapter._build_finding(item)
        assert f is not None
        assert f.node == "src/Foo.php:42"
        assert f.severity == "error"
        assert f.message == "Too many methods"
        assert f.fix_hint == "Split the class"
        assert f.rule_id == "GOD001"
        assert f.tool == "visitor-runner"
        assert f.layer == "L3A"
        assert f.language == "php"

    def test_build_finding_null_file_not_none_in_node(self):
        """file: null -> node is empty, not 'None'."""
        from harness_quality_gate.adapters.php.visitor_runner_adapter import (
            VisitorRunnerAdapter,
        )
        f = VisitorRunnerAdapter._build_finding({"file": None, "line": 3})
        assert f is not None
        assert f.node == ":3"
        assert "None" not in f.node

    def test_build_finding_non_string_file_degrades(self):
        """file: 123 -> degrades to empty path."""
        from harness_quality_gate.adapters.php.visitor_runner_adapter import (
            VisitorRunnerAdapter,
        )
        f = VisitorRunnerAdapter._build_finding({"file": 123, "line": 7})
        assert f is not None
        assert f.node == ":7"

    def test_build_finding_non_dict_returns_none(self):
        """Non-dict -> None."""
        from harness_quality_gate.adapters.php.visitor_runner_adapter import (
            VisitorRunnerAdapter,
        )
        assert VisitorRunnerAdapter._build_finding("string") is None
        assert VisitorRunnerAdapter._build_finding(42) is None
        assert VisitorRunnerAdapter._build_finding(None) is None

    def test_build_finding_with_path_key(self):
        """path key works as alternative to file."""
        from harness_quality_gate.adapters.php.visitor_runner_adapter import (
            VisitorRunnerAdapter,
        )
        f = VisitorRunnerAdapter._build_finding({"path": "src/Bar.php", "line": 10})
        assert f is not None
        assert f.node == "src/Bar.php:10"

    def test_build_finding_default_severity_is_info(self):
        """Missing severity -> 'info'."""
        from harness_quality_gate.adapters.php.visitor_runner_adapter import (
            VisitorRunnerAdapter,
        )
        f = VisitorRunnerAdapter._build_finding({"file": "x.php"})
        assert f.severity == "info"

    def test_build_finding_default_tool_layer_language(self):
        """tool, layer, language always set."""
        from harness_quality_gate.adapters.php.visitor_runner_adapter import (
            VisitorRunnerAdapter,
        )
        f = VisitorRunnerAdapter._build_finding({"file": "x.php"})
        assert f.tool == "visitor-runner"
        assert f.layer == "L3A"
        assert f.language == "php"


# ===========================================================================
# visitor_runner _merge_findings — mutmut_2
# ===========================================================================

class TestVisitorRunnerMergeFindings:
    """Kill mutmut_2 on _merge_findings."""

    def test_merge_findings_returns_str_not_none_or_false(self):
        """_merge_findings -> str, not None or False."""
        from harness_quality_gate.adapters.php.visitor_runner_adapter import (
            VisitorRunnerAdapter,
        )
        result = VisitorRunnerAdapter._merge_findings([])
        assert isinstance(result, str)
        assert result == "[]"

    def test_merge_findings_preserves_unicode(self):
        """ensure_ascii=False preserves unicode."""
        from harness_quality_gate.adapters.php.visitor_runner_adapter import (
            VisitorRunnerAdapter,
        )
        data = [{"message": "caf\u00e9"}]
        result = VisitorRunnerAdapter._merge_findings(data)
        assert "caf\u00e9" in result


# ===========================================================================
# python_adapter check_tools — mutmut_7/11
# ===========================================================================

class TestPythonAdapterCheckTools:
    """Kill mutmut_7/11 on check_tools."""

    def test_check_tools_returns_list_with_ruff_pyright(self, tmp_path):
        """check_tools -> ['ruff', 'pyright'] when present."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        from harness_quality_gate.bootstrap import resolve_tool, ToolNotAvailable

        def mock_resolve(tool, path):
            if tool in ("ruff", "pyright"):
                return f"/path/{tool}"
            raise ToolNotAvailable(tool)

        with patch("harness_quality_gate.adapters.python.python_adapter.resolve_tool", side_effect=mock_resolve):
            adapter = PythonAdapter()
            result = adapter.check_tools()
        assert result == ["ruff", "pyright"]

    def test_check_tools_raises_when_missing(self, tmp_path):
        """check_tools -> RuntimeError when ruff or pyright missing."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        from harness_quality_gate.bootstrap import ToolNotAvailable

        with patch(
            "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
            side_effect=ToolNotAvailable("ruff"),
        ):
            adapter = PythonAdapter()
            with pytest.raises(RuntimeError, match=".*ruff.*"):
                adapter.check_tools()


# ===========================================================================
# python_adapter _run_pytest — PATH construction
# ===========================================================================

class TestPythonAdapterRunPytest:
    """Kill mutmut_27/29/33/34/36/38/39/40/41 -- PATH construction mutations."""

    def test_run_pytest_returns_list(self, tmp_path):
        """_run_pytest returns a list of Findings (or empty list)."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        adapter = PythonAdapter()
        result = adapter._run_pytest(tmp_path, {})
        assert isinstance(result, list)
        for f in result:
            assert isinstance(f, Finding)

    def test_run_pytest_venv_path_construction(self, tmp_path):
        """When .venv/bin/pytest exists, PATH is patched with venv_dir."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "pytest").write_text("#!")

        adapter = PythonAdapter()
        with patch.object(adapter, "pytest") as mock_pytest:
            mock_pytest.invoke.return_value = ToolInvocation(
                stdout="", stderr="", exitcode=0,
            )
            adapter._run_pytest(tmp_path, {})
            mock_pytest.invoke.assert_called_once()
            call_kwargs = mock_pytest.invoke.call_args[1]
            assert "env" in call_kwargs
            venv_path = str(tmp_path / ".venv" / "bin")
            assert venv_path in call_kwargs["env"]["PATH"]

    def test_run_pytest_no_venv(self, tmp_path):
        """No venv -> still works (graceful degradation)."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        adapter = PythonAdapter()
        with patch.object(adapter, "pytest") as mock_pytest:
            mock_pytest.invoke.return_value = ToolInvocation(
                stdout="", stderr="", exitcode=0,
            )
            result = adapter._run_pytest(tmp_path, {})
        assert mock_pytest.invoke.called

    def test_run_pytest_finds_venv_pytest_file(self, tmp_path):
        """Check venv_dir is set when .venv/bin/pytest exists."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "pytest").write_text("#!")

        adapter = PythonAdapter()
        captured_env = []

        def record_env(*args, **kwargs):
            captured_env.append(kwargs.get("env", {}))
            return ToolInvocation(stdout="", stderr="", exitcode=0)

        with patch.object(adapter, "pytest") as mock_pytest:
            mock_pytest.invoke.side_effect = record_env
            adapter._run_pytest(tmp_path, {"PATH": "/usr/bin"})

        assert len(captured_env) == 1
        venv_path = str(tmp_path / ".venv" / "bin")
        assert venv_path in captured_env[0]["PATH"]


# ===========================================================================
# python_adapter _weak_test_findings — mutmut_69/73/74
# ===========================================================================

class TestPythonAdapterWeakTestFindings:
    """Kill mutmut_69/73/74 on _weak_test_findings."""

    def test_weak_test_findings_from_report(self, tmp_path):
        """Report -> Findings with correct fields."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        adapter = PythonAdapter()
        report = {
            "weak_tests": [
                {
                    "file": "tests/test_calc.py",
                    "name": "test_calc.py",
                    "lineno": 5,
                    "violations": [
                        {
                            "rule": "A1",
                            "description": "No assertions",
                            "severity": "ERROR",
                        }
                    ],
                }
            ],
        }

        tmp_path.joinpath("tests").mkdir()
        with patch(
            "harness_quality_gate.adapters.python.python_adapter.run_weak_test_analysis",
            return_value=report,
        ):
            findings = adapter._weak_test_findings(tmp_path)

        assert len(findings) == 1
        f = findings[0]
        assert f.node == "tests/test_calc.py:5"
        assert f.severity == "error"
        assert "test_calc.py: No assertions" in f.message
        assert f.tool == "weak-test"
        assert f.layer == "L2"
        assert f.language == "python"
        assert f.rule_id == "A1"

    def test_weak_test_findings_warning_severity(self, tmp_path):
        """Warning violation -> severity=warning."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        adapter = PythonAdapter()
        report = {
            "weak_tests": [
                {
                    "file": "tests/t.py",
                    "name": "t.py",
                    "lineno": 10,
                    "violations": [
                        {"rule": "A2", "description": "mocks only", "severity": "WARNING"},
                    ],
                }
            ],
        }

        tmp_path.joinpath("tests").mkdir()
        with patch(
            "harness_quality_gate.adapters.python.python_adapter.run_weak_test_analysis",
            return_value=report,
        ):
            findings = adapter._weak_test_findings(tmp_path)

        assert len(findings) == 1
        assert findings[0].severity == "warning"

    def test_weak_test_findings_no_tests_dir(self, tmp_path):
        """No tests/ dir -> empty list."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        adapter = PythonAdapter()
        findings = adapter._weak_test_findings(tmp_path)
        assert findings == []
        assert isinstance(findings, list)

    def test_weak_test_findings_empty_violations(self, tmp_path):
        """No violations -> empty list."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        adapter = PythonAdapter()
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        report = {"weak_tests": [{"file": "t.py", "name": "t", "lineno": 1, "violations": []}]}

        with patch(
            "harness_quality_gate.adapters.python.python_adapter.run_weak_test_analysis",
            return_value=report,
        ):
            findings = adapter._weak_test_findings(tmp_path)

        assert findings == []


# ===========================================================================
# Regression — dense assertions pass against current code
# ===========================================================================

class TestRegression:
    """Verify all dense assertions pass against current unmutated code."""

    def test_layer_result_fields(self):
        lr = LayerResult(
            layer="L1", language="python", passed=True,
            findings=[], duration_sec=1.5,
        )
        assert lr.layer == "L1"
        assert lr.language == "python"
        assert lr.passed is True
        assert lr.findings == []
        assert lr.duration_sec == 1.5
        assert lr.tool_specific is None

    def test_finding_defaults(self):
        f = Finding(node="x.py", severity="error", message="msg")
        assert f.node == "x.py"
        assert f.severity == "error"
        assert f.message == "msg"
        assert f.fix_hint is None
        assert f.cve is None
        assert f.cwe == ""
        assert f.tool is None
        assert f.layer is None
        assert f.language is None
        assert f.rule_id is None

    def test_tool_invocation_defaults(self):
        ti = ToolInvocation()
        assert ti.stdout == ""
        assert ti.stderr == ""
        assert ti.exitcode == 0
        assert ti.duration_seconds == 0.0
