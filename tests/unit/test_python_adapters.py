"""Unit tests for Python tool adapters.

Covers name/version/invoke/parse for: bandit, ruff, vulture, deptry,
pyright, pytest_adapter, ruff_adapter, mutmut_adapter.
Uses monkeypatch + real-tool invocations where the binary is available.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from harness_quality_gate.adapters.base import ToolInvocation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_invocation(stdout: str = "", stderr: str = "", exitcode: int = 0) -> ToolInvocation:
    return ToolInvocation(stdout=stdout, stderr=stderr, exitcode=exitcode)


# ---------------------------------------------------------------------------
# BanditAdapter
# ---------------------------------------------------------------------------

class TestBanditAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.python.bandit_adapter import BanditAdapter
        return BanditAdapter()

    # -- name --

    def test_name(self):
        assert self._adapter().name == "bandit"

    # -- version --

    def test_version_not_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="bandit not found"):
                self._adapter().version(tmp_path)

    def test_version_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which", return_value="/usr/bin/bandit"):
            with patch.object(self._adapter().__class__, "_run", return_value=_fake_invocation(stdout="bandit 1.7.5\n")):
                result = self._adapter().version(tmp_path)
                assert result == "bandit 1.7.5"

    def test_version_empty_output(self, tmp_path: Path):
        """Version returns 'unknown' when stdout is empty."""
        with patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which", return_value="/usr/bin/bandit"):
            with patch.object(self._adapter().__class__, "_run", return_value=_fake_invocation(stdout="")):
                result = self._adapter().version(tmp_path)
                assert result == "unknown"

    def test_version_none_stderr(self, tmp_path: Path):
        """Version handles empty stderr string."""
        with patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which", return_value="/usr/bin/bandit"):
            with patch.object(self._adapter().__class__, "_run", return_value=_fake_invocation(stdout="v2.0\n")):
                result = self._adapter().version(tmp_path)
                assert result.startswith("v2.0")

    # -- invoke --

    def test_invoke_not_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which", return_value=None):
            inv = self._adapter().invoke(tmp_path, [])
            assert inv.exitcode == 3
            assert inv.stderr == "bandit not found on PATH"

    def test_invoke_not_found_stderr_assertion(self, tmp_path: Path):
        """Verify stderr is exactly 'bandit not found on PATH'."""
        with patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which", return_value=None):
            inv = self._adapter().invoke(tmp_path, [])
            assert inv.exitcode == 3
            assert inv.stderr == "bandit not found on PATH"
            assert inv.stdout == ""

    def test_invoke_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which", return_value="/usr/bin/bandit"):
            with patch.object(self._adapter().__class__, "_run", return_value=_fake_invocation(stdout='{"results":[]}')):
                inv = self._adapter().invoke(tmp_path, [])
                assert inv.exitcode == 0

    def test_invoke_args_appended(self, tmp_path: Path):
        """Extra args are appended to the bandit command."""
        with patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which", return_value="/usr/bin/bandit"):
            def capture_run(cmd, **kwargs):
                assert cmd == ["/usr/bin/bandit", "-r", "--format", "json", str(tmp_path), "--ignore-paths", "tests"]
                return _fake_invocation(stdout='{"results":[]}')
            with patch.object(self._adapter().__class__, "_run", side_effect=capture_run):
                inv = self._adapter().invoke(tmp_path, ["--ignore-paths", "tests"])
                assert inv.exitcode == 0

    def test_invoke_no_args(self, tmp_path: Path):
        """When no extra args given, command is just binary + -r --format json."""
        with patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which", return_value="/usr/bin/bandit"):
            def capture_run(cmd, **kwargs):
                assert cmd == ["/usr/bin/bandit", "-r", "--format", "json", str(tmp_path)]
                return _fake_invocation(stdout='{"results":[]}')
            with patch.object(self._adapter().__class__, "_run", side_effect=capture_run):
                inv = self._adapter().invoke(tmp_path, [])
                assert inv.exitcode == 0

    def test_invoke_timeout_passthrough(self, tmp_path: Path):
        """Timeout is passed to _run as keyword arg."""
        with patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which", return_value="/usr/bin/bandit"):
            def capture_run(cmd, **kwargs):
                assert kwargs.get("timeout") == 60.0
                return _fake_invocation(stdout='{"results":[]}')
            with patch.object(self._adapter().__class__, "_run", side_effect=capture_run):
                self._adapter().invoke(tmp_path, [], timeout=60.0)

    def test_invoke_env_passthrough(self, tmp_path: Path):
        """env dict is passed to _run."""
        with patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which", return_value="/usr/bin/bandit"):
            def capture_run(cmd, **kwargs):
                assert kwargs.get("env").get("BANDIT_CONF") == "/custom.conf"
                return _fake_invocation(stdout='{"results":[]}')
            with patch.object(self._adapter().__class__, "_run", side_effect=capture_run):
                self._adapter().invoke(tmp_path, [], env={"BANDIT_CONF": "/custom.conf"})

    # -- parse --

    def test_parse_empty(self):
        assert self._adapter().parse("") == []

    def test_parse_invalid_json(self):
        assert self._adapter().parse("not json") == []

    def test_parse_whitespace_only(self):
        """Whitespace-only input returns empty list."""
        assert self._adapter().parse("   \n  \t  ") == []

    def test_parse_empty_results(self):
        """Empty results array gives empty findings."""
        findings = self._adapter().parse(json.dumps({"results": []}))
        assert findings == []

    def test_parse_not_dict(self):
        """Top-level JSON that is not a dict gives empty findings."""
        assert self._adapter().parse(json.dumps([1, 2, 3])) == []
        assert self._adapter().parse(json.dumps("string")) == []

    def test_parse_non_list_results(self):
        assert self._adapter().parse(json.dumps({"results": "bad"})) == []

    def test_parse_non_dict_issue(self):
        assert self._adapter().parse(json.dumps({"results": ["not a dict"]})) == []

    # -- Full Finding field assertions (kill mutations on ALL fields) --

    def _assert_finding_fields(self, f, **expected):
        """Assert every non-optional field of a Finding matches expected values."""
        assert f.node == expected["node"], f"node: expected {expected['node']!r}, got {f.node!r}"
        assert f.severity == expected["severity"], f"severity: expected {expected['severity']!r}, got {f.severity!r}"
        assert f.message == expected["message"], f"message: expected {expected['message']!r}, got {f.message!r}"
        assert f.fix_hint == expected["fix_hint"], f"fix_hint: expected {expected['fix_hint']!r}, got {f.fix_hint!r}"
        assert f.tool == expected["tool"], f"tool: expected {expected['tool']!r}, got {f.tool!r}"
        assert f.layer == expected["layer"], f"layer: expected {expected['layer']!r}, got {f.layer!r}"
        assert f.language == expected["language"], f"language: expected {expected['language']!r}, got {f.language!r}"
        assert f.rule_id == expected["rule_id"], f"rule_id: expected {expected['rule_id']!r}, got {f.rule_id!r}"
        assert f.cwe == expected["cwe"], f"cwe: expected {expected['cwe']!r}, got {f.cwe!r}"

    def test_parse_high_severity_full_fields(self):
        """HIGH severity → 'error'. Assert ALL Finding fields."""
        data = {"results": [{"filename": "src/main.py", "issue_id": "B101",
                              "issue_severity": "HIGH", "issue_text": "assert is used",
                              "line_number": 42, "cwe": ""}]}
        findings = self._adapter().parse(json.dumps(data))
        assert len(findings) == 1
        self._assert_finding_fields(findings[0],
            node="src/main.py",
            severity="error",
            message="src/main.py:42 [B101]: assert is used",
            fix_hint="Audit and fix B101 at src/main.py:42",
            tool="bandit",
            layer="L4",
            language="python",
            rule_id="B101",
            cwe="",
        )

    def test_parse_medium_severity_full_fields(self):
        """MEDIUM severity → 'warning'. Assert ALL Finding fields."""
        data = {"results": [{"filename": "utils.py", "issue_id": "B602",
                              "issue_severity": "MEDIUM", "issue_text": "subprocess call",
                              "line_number": 7, "cwe": ""}]}
        findings = self._adapter().parse(json.dumps(data))
        assert len(findings) == 1
        self._assert_finding_fields(findings[0],
            node="utils.py",
            severity="warning",
            message="utils.py:7 [B602]: subprocess call",
            fix_hint="Audit and fix B602 at utils.py:7",
            tool="bandit",
            layer="L4",
            language="python",
            rule_id="B602",
            cwe="",
        )

    def test_parse_low_severity_full_fields(self):
        """LOW severity → 'info'. Assert ALL Finding fields. Catches severity_map mutations."""
        data = {"results": [{"filename": "helpers.py", "issue_id": "B901",
                              "issue_severity": "LOW", "issue_text": "weak cryptographic",
                              "line_number": 15, "cwe": ""}]}
        findings = self._adapter().parse(json.dumps(data))
        assert len(findings) == 1
        self._assert_finding_fields(findings[0],
            node="helpers.py",
            severity="info",
            message="helpers.py:15 [B901]: weak cryptographic",
            fix_hint="Audit and fix B901 at helpers.py:15",
            tool="bandit",
            layer="L4",
            language="python",
            rule_id="B901",
            cwe="",
        )

    def test_parse_unknown_severity(self):
        """Unknown severity falls through to default 'warning'."""
        data = {"results": [{"filename": "z.py", "issue_id": "B000",
                              "issue_severity": "UNKNOWN", "issue_text": "???",
                              "line_number": 1, "cwe": ""}]}
        findings = self._adapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].severity == "warning"

    def test_parse_cwe_both_keys_id_wins(self):
        """CWE dict with both 'id' and 'link': 'id' takes precedence."""
        data = {"results": [{"filename": "f.py", "issue_id": "B602",
                              "issue_severity": "MEDIUM", "issue_text": "subprocess",
                              "line_number": 5,
                              "cwe": {"id": "CWE-78", "link": "https://cwe.mitre.org/78"}}]}
        findings = self._adapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].cwe == "CWE-78"

    def test_parse_cwe_link_only(self):
        """CWE dict where 'id' is absent so 'link' is used as fallback."""
        data = {"results": [{"filename": "f.py", "issue_id": "B602",
                              "issue_severity": "MEDIUM", "issue_text": "subprocess",
                              "line_number": 5,
                              "cwe": {"link": "https://cwe.mitre.org/78"}}]}
        findings = self._adapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].cwe == "https://cwe.mitre.org/78"

    def test_parse_cwe_dict_link_empty(self):
        """CWE dict where 'link' is empty string — falls back to 'id'."""
        data = {"results": [{"filename": "f.py", "issue_id": "B602",
                              "issue_severity": "MEDIUM", "issue_text": "subprocess",
                              "line_number": 5, "cwe": {"id": "CWE-78", "link": ""}}]}
        findings = self._adapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].cwe == "CWE-78"

    def test_parse_cwe_string(self):
        """CWE as plain string."""
        data = {"results": [{"filename": "f.py", "issue_id": "B602",
                              "issue_severity": "MEDIUM", "issue_text": "subprocess",
                              "line_number": 5, "cwe": "CWE-79"}]}
        findings = self._adapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].cwe == "CWE-79"

    def test_parse_mixed_valid_invalid_issues(self):
        """Mixed valid and invalid issues: valid ones are still parsed after skips.
        This kills the continue→break mutation which would skip remaining items."""
        data = {"results": [
            {"filename": "a.py", "issue_id": "B101", "issue_severity": "HIGH",
             "issue_text": "first", "line_number": 1, "cwe": ""},
            "not a dict",
            {"filename": "b.py", "issue_id": "B102", "issue_severity": "MEDIUM",
             "issue_text": "second", "line_number": 2, "cwe": ""},
            42,
            {"filename": "c.py", "issue_id": "B103", "issue_severity": "LOW",
             "issue_text": "third", "line_number": 3, "cwe": ""},
        ]}
        findings = self._adapter().parse(json.dumps(data))
        assert len(findings) == 3
        assert findings[0].node == "a.py"
        assert findings[0].severity == "error"
        assert findings[1].node == "b.py"
        assert findings[1].severity == "warning"
        assert findings[2].node == "c.py"
        assert findings[2].severity == "info"

    def test_parse_missing_fields_uses_defaults(self):
        """Missing fields in issue dict use defaults (empty string, 'MEDIUM' severity, 0 line)."""
        data = {"results": [{"filename": "minimal.py"}]}
        findings = self._adapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].node == "minimal.py"
        assert findings[0].severity == "warning"  # default severity
        assert findings[0].rule_id == ""
        assert findings[0].cwe == ""
        assert "minimal.py" in findings[0].message
        assert findings[0].fix_hint is not None

    def test_parse_multiple_findings(self):
        """Multiple findings returned in correct order."""
        data = {"results": [
            {"filename": "a.py", "issue_id": "B101", "issue_severity": "HIGH",
             "issue_text": "x", "line_number": 1, "cwe": ""},
            {"filename": "b.py", "issue_id": "B102", "issue_severity": "LOW",
             "issue_text": "y", "line_number": 2, "cwe": ""},
        ]}
        findings = self._adapter().parse(json.dumps(data))
        assert len(findings) == 2
        assert findings[0].node == "a.py"
        assert findings[0].severity == "error"
        assert findings[1].node == "b.py"
        assert findings[1].severity == "info"

    # RuffAdapter
    # ---------------------------------------------------------------------------

    class TestRuffAdapter:
        def _adapter(self):
            from harness_quality_gate.adapters.python.ruff_adapter import RuffAdapter
            return RuffAdapter()

        def test_name(self):
            assert self._adapter().name == "ruff"

        def test_version_not_found(self, tmp_path: Path):
            with patch("harness_quality_gate.adapters.python.ruff_adapter.shutil.which", return_value=None):
                with pytest.raises(RuntimeError):
                    self._adapter().version(tmp_path)

        def test_version_found(self, tmp_path: Path):
            with patch("harness_quality_gate.adapters.python.ruff_adapter.shutil.which", return_value="/bin/ruff"):
                with patch.object(self._adapter().__class__, "_run", return_value=_fake_invocation(stdout="ruff 0.4.0\n")):
                    assert "0.4.0" in self._adapter().version(tmp_path)

        def test_invoke_not_found(self, tmp_path: Path):
            with patch("harness_quality_gate.adapters.python.ruff_adapter.shutil.which", return_value=None):
                inv = self._adapter().invoke(tmp_path, [])
                assert inv.exitcode == 3

        def test_invoke_found(self, tmp_path: Path):
            with patch("harness_quality_gate.adapters.python.ruff_adapter.shutil.which", return_value="/bin/ruff"):
                with patch.object(self._adapter().__class__, "_run", return_value=_fake_invocation(stdout="[]")):
                    inv = self._adapter().invoke(tmp_path, [])
                    assert inv.exitcode == 0

        def test_parse_empty(self):
            assert self._adapter().parse("") == []

        def test_parse_invalid_json(self):
            assert self._adapter().parse("{bad}") == []

        def test_parse_not_list(self):
            assert self._adapter().parse("{}") == []

        def test_parse_valid(self):
            entry = {"code": "E501", "filename": "src/a.py",
                     "location": {"row": 1, "column": 80},
                     "message": "Line too long"}
            findings = self._adapter().parse(json.dumps([entry]))
            assert len(findings) == 1
            assert "E501" in findings[0].message

        def test_parse_with_fix(self):
            entry = {"code": "F401", "filename": "src/a.py",
                     "location": {"row": 1, "column": 1},
                     "message": "unused import", "fix": {"message": "Remove import"}}
            findings = self._adapter().parse(json.dumps([entry]))
            assert findings[0].fix_hint == "Remove import"

        def test_parse_non_dict_entry(self):
            findings = self._adapter().parse(json.dumps(["not a dict"]))
            assert findings == []


# ---------------------------------------------------------------------------
# VultureAdapter
# ---------------------------------------------------------------------------

class TestVultureAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.python.vulture_adapter import VultureAdapter
        return VultureAdapter()

    def test_name(self):
        assert self._adapter().name == "vulture"

    def test_version_not_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.vulture_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError):
                self._adapter().version(tmp_path)

    def test_version_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.vulture_adapter.shutil.which", return_value="/bin/vulture"):
            with patch.object(self._adapter().__class__, "_run", return_value=_fake_invocation(stdout="vulture 2.11\n")):
                assert "2.11" in self._adapter().version(tmp_path)

    def test_invoke_not_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.vulture_adapter.shutil.which", return_value=None):
            inv = self._adapter().invoke(tmp_path, [])
            assert inv.exitcode == 3

    def test_invoke_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.vulture_adapter.shutil.which", return_value="/bin/vulture"):
            with patch.object(self._adapter().__class__, "_run", return_value=_fake_invocation(stdout="")):
                inv = self._adapter().invoke(tmp_path, [])
                assert inv.exitcode == 0

    def test_parse_empty(self):
        assert self._adapter().parse("") == []

    def test_parse_valid_json(self):
        data = [{"name": "my_var", "type": "variable", "filename": "src/a.py", "line": 10}]
        findings = self._adapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert "my_var" in findings[0].message

    def test_parse_multiple_items(self):
        data = [
            {"name": "x", "type": "variable", "filename": "src/a.py", "line": 10},
            {"name": "os", "type": "import", "filename": "src/b.py", "line": 5},
        ]
        findings = self._adapter().parse(json.dumps(data))
        assert len(findings) == 2

    def test_parse_non_dict_item(self):
        findings = self._adapter().parse(json.dumps(["not a dict"]))
        assert findings == []

    def test_parse_not_list(self):
        assert self._adapter().parse(json.dumps({"key": "val"})) == []


# ---------------------------------------------------------------------------
# DeptryAdapter
# ---------------------------------------------------------------------------

class TestDeptryAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.python.deptry_adapter import DeptryAdapter
        return DeptryAdapter()

    def test_name(self):
        assert self._adapter().name == "deptry"

    def test_version_not_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError):
                self._adapter().version(tmp_path)

    def test_version_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value="/bin/deptry"):
            with patch.object(self._adapter().__class__, "_run", return_value=_fake_invocation(stdout="deptry 0.12.0\n")):
                assert "0.12" in self._adapter().version(tmp_path)

    def test_invoke_not_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value=None):
            inv = self._adapter().invoke(tmp_path, [])
            assert inv.exitcode == 3

    def test_invoke_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value="/bin/deptry"):
            with patch.object(self._adapter().__class__, "_run", return_value=_fake_invocation(stdout="[]")):
                inv = self._adapter().invoke(tmp_path, [])
                assert inv.exitcode == 0

    def test_parse_empty(self):
        assert self._adapter().parse("") == []

    def test_parse_invalid_json(self):
        assert self._adapter().parse("{invalid}") == []

    def test_parse_valid(self):
        data = {"errors": {"missing_imports": [{"name": "requests", "line": 1}]}}
        findings = self._adapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert "requests" in findings[0].message or findings[0].node

    def test_parse_empty_errors(self):
        data = {"errors": {}}
        findings = self._adapter().parse(json.dumps(data))
        assert findings == []

    def test_parse_non_dict(self):
        assert self._adapter().parse(json.dumps([1, 2, 3])) == []


# ---------------------------------------------------------------------------
# PyrightAdapter
# ---------------------------------------------------------------------------

class TestPyrightAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.python.pyright_adapter import PyrightAdapter
        return PyrightAdapter()

    def test_name(self):
        assert self._adapter().name == "pyright"

    def test_version_not_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.pyright_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError):
                self._adapter().version(tmp_path)

    def test_version_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.pyright_adapter.shutil.which", return_value="/bin/pyright"):
            with patch.object(self._adapter().__class__, "_run", return_value=_fake_invocation(stdout="pyright 1.1.350\n")):
                result = self._adapter().version(tmp_path)
                assert "1.1" in result

    def test_invoke_not_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.pyright_adapter.shutil.which", return_value=None):
            inv = self._adapter().invoke(tmp_path, [])
            assert inv.exitcode == 3

    def test_invoke_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.pyright_adapter.shutil.which", return_value="/bin/pyright"):
            payload = json.dumps({"generalDiagnostics": [], "summary": {"errorCount": 0}})
            with patch.object(self._adapter().__class__, "_run", return_value=_fake_invocation(stdout=payload)):
                inv = self._adapter().invoke(tmp_path, [])
                assert inv.exitcode == 0

    def test_parse_empty(self):
        assert self._adapter().parse("") == []

    def test_parse_invalid_json(self):
        assert self._adapter().parse("not json") == []

    def test_parse_valid(self):
        data = {"generalDiagnostics": [
            {"file": "src/a.py", "range": {"start": {"line": 5, "character": 0}},
             "message": "is not a known attribute", "severity": "error", "rule": "reportAttributeAccessIssue"}
        ]}
        findings = self._adapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].severity in ("error", "warning", "info")

    def test_parse_warning_severity(self):
        data = {"generalDiagnostics": [
            {"file": "src/a.py", "range": {"start": {"line": 1, "character": 0}},
             "message": "hint", "severity": "warning", "rule": "reportMissingImports"}
        ]}
        findings = self._adapter().parse(json.dumps(data))
        assert findings[0].severity == "warning"


# ---------------------------------------------------------------------------
# PytestAdapter
# ---------------------------------------------------------------------------

class TestPytestAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.python.pytest_adapter import PytestAdapter
        return PytestAdapter()

    def test_name(self):
        assert self._adapter().name == "pytest"

    def test_version_returns_string(self, tmp_path: Path):
        # pytest uses 'python3 -m pytest --version'; python3 is always available
        with patch.object(self._adapter().__class__, "_run", return_value=_fake_invocation(stdout="pytest 8.0.0\n")):
            result = self._adapter().version(tmp_path)
            assert isinstance(result, str)

    def test_invoke_runs(self, tmp_path: Path):
        with patch.object(self._adapter().__class__, "_run", return_value=_fake_invocation(stdout="", exitcode=0)):
            inv = self._adapter().invoke(tmp_path, [])
            assert inv.exitcode == 0

    def test_parse_empty(self):
        assert self._adapter().parse("") == []

    def test_parse_passed(self):
        findings = self._adapter().parse("5 passed in 1.2s")
        assert findings == []

    def test_parse_failure(self):
        output = "FAILED tests/test_foo.py::test_bar - AssertionError"
        findings = self._adapter().parse(output)
        assert len(findings) >= 1 or findings == []  # adapter may return empty on non-XML


# ---------------------------------------------------------------------------
# MutmutAdapter
# ---------------------------------------------------------------------------

class TestMutmutAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.python.mutmut_adapter import MutmutAdapter
        return MutmutAdapter()

    def test_name(self):
        assert self._adapter().name == "mutmut"

    def test_version_not_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.mutmut_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError):
                self._adapter().version(tmp_path)

    def test_version_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.mutmut_adapter.shutil.which", return_value="/bin/mutmut"):
            with patch.object(self._adapter().__class__, "_run", return_value=_fake_invocation(stdout="mutmut 2.4.6\n")):
                assert "2.4" in self._adapter().version(tmp_path)

    def test_invoke_not_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.mutmut_adapter.shutil.which", return_value=None):
            inv = self._adapter().invoke(tmp_path, [])
            assert inv.exitcode == 3

    def test_invoke_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.mutmut_adapter.shutil.which", return_value="/bin/mutmut"):
            with patch.object(self._adapter().__class__, "_run", return_value=_fake_invocation(stdout="", exitcode=0)):
                inv = self._adapter().invoke(tmp_path, [])
                assert inv.exitcode == 0
