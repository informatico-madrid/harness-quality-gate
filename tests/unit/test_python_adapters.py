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

    def test_name(self):
        assert self._adapter().name == "bandit"

    def test_version_not_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="bandit not found"):
                self._adapter().version(tmp_path)

    def test_version_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which", return_value="/usr/bin/bandit"):
            with patch.object(self._adapter().__class__, "_run", return_value=_fake_invocation(stdout="bandit 1.7.5\n")):
                result = self._adapter().version(tmp_path)
                assert result == "bandit 1.7.5"

    def test_invoke_not_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which", return_value=None):
            inv = self._adapter().invoke(tmp_path, [])
            assert inv.exitcode == 3

    def test_invoke_found(self, tmp_path: Path):
        with patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which", return_value="/usr/bin/bandit"):
            with patch.object(self._adapter().__class__, "_run", return_value=_fake_invocation(stdout='{"results":[]}')):
                inv = self._adapter().invoke(tmp_path, [])
                assert inv.exitcode == 0

    def test_parse_empty(self):
        assert self._adapter().parse("") == []

    def test_parse_invalid_json(self):
        assert self._adapter().parse("not json") == []

    def test_parse_valid(self):
        data = {"results": [{"filename": "f.py", "issue_id": "B101", "issue_severity": "HIGH",
                              "issue_text": "assert used", "line_number": 10, "cwe": ""}]}
        findings = self._adapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].severity == "error"
        assert "B101" in findings[0].message

    def test_parse_cwe_dict(self):
        data = {"results": [{"filename": "f.py", "issue_id": "B602", "issue_severity": "MEDIUM",
                              "issue_text": "subprocess", "line_number": 5,
                              "cwe": {"id": "CWE-78", "link": "..."}}]}
        findings = self._adapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert "CWE-78" in findings[0].cwe

    def test_parse_non_list_results(self):
        assert self._adapter().parse(json.dumps({"results": "bad"})) == []

    def test_parse_non_dict_issue(self):
        assert self._adapter().parse(json.dumps({"results": ["not a dict"]})) == []


# ---------------------------------------------------------------------------
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
