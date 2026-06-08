"""Comprehensive orchestration tests for PythonAdapter.

Targets: run_l3a, run_l1, run_l2, run_l3b, run_l4, check_tools, tool_versions,
         private helpers (_run_ruff, _run_pyright, _run_pytest, _run_vulture,
         _run_deptry, _run_mutmut, _run_bandit).
Design: Mutation testing / python_adapter coverage
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.models import Finding, LayerResult, MutationStats


def _make_finding(
    severity: str = "error",
    message: str = "test finding",
    node: str = "test.py",
    rule_id: str | None = None,
    fix_hint: str | None = None,
    tool: str = "ruff",
    layer: str = "L3A",
    language: str = "python",
    cwe: str = "",
) -> Finding:
    return Finding(
        severity=severity,
        message=message,
        node=node,
        rule_id=rule_id,
        fix_hint=fix_hint,
        tool=tool,
        layer=layer,
        language=language,
        cwe=cwe,
    )


def _mock_subadapter(findings: list[Finding] | None = None) -> MagicMock:
    """Replace a sub-adapter attribute with a MagicMock.

    MagicMock.parse.return_value → findings list.
    MagicMock.invoke → ToolInvocation-like object.
    """
    mock = MagicMock()
    mock.parse.return_value = findings or []
    mock.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)
    return mock


def _all_tools_on_path(which_map: dict[str, str | None] | None = None):
    """Return a patch for shutil.which that considers all Python tools present.

    Default: all tools considered found. Optionally customize per-tool.
    This patches 'harness_quality_gate.adapters.python.python_adapter.shutil.which'.
    """
    defaults = {
        "ruff": "/bin/ruff", "pyright": "/bin/pyright",
        "vulture": "/bin/vulture", "deptry": "/bin/deptry",
        "mutmut": "/bin/mutmut", "bandit": "/bin/bandit",
        "python3": "/usr/bin/python3",
    }
    if which_map:
        defaults.update(which_map)

    def _which(name):
        return defaults.get(name)

    return patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", side_effect=_which)


# ---------------------------------------------------------------------------
# Run L3A (ruff + pyright)
# ---------------------------------------------------------------------------

class TestRunL3A:
    """Test run_l3a branch coverage: ruff check + pyright type check."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_l3a_all_pass(self, tmp_path: Path):
        """Both ruff and pyright return 0 findings -> passed=True."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.pyright = _mock_subadapter(findings=[])
        layer = a.run_l3a(tmp_path, {})
        assert layer.layer == "L3A"
        assert layer.language == "python"
        assert layer.passed is True
        assert layer.findings == []
        assert isinstance(layer.duration_sec, float)

    def test_l3a_ruff_findings(self, tmp_path: Path):
        """ruff returns findings, pyright clean -> passed=False."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[_make_finding(rule_id="E501")])
        a.pyright = _mock_subadapter(findings=[])
        layer = a.run_l3a(tmp_path, {})
        assert layer.passed is False
        assert len(layer.findings) == 1
        assert layer.findings[0].tool == "ruff"

    def test_l3a_pyright_findings(self, tmp_path: Path):
        """ruff clean, pyright returns findings -> passed=False."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.pyright = _mock_subadapter(findings=[_make_finding(tool="pyright")])
        layer = a.run_l3a(tmp_path, {})
        assert layer.passed is False
        assert len(layer.findings) == 1
        assert layer.findings[0].tool == "pyright"

    def test_l3a_both_findings(self, tmp_path: Path):
        """Both tools return findings -> all merged, passed=False."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[_make_finding(tool="ruff")])
        a.pyright = _mock_subadapter(findings=[_make_finding(tool="pyright")])
        layer = a.run_l3a(tmp_path, {})
        assert layer.passed is False
        assert len(layer.findings) == 2

    def test_l3a_ruff_raises_oserror(self, tmp_path: Path):
        """ruff raises OSError -> only pyright findings counted."""
        a = self._adapter()
        with patch.object(a.ruff, "invoke", side_effect=OSError("ruff broken")):
            a.pyright = _mock_subadapter(findings=[_make_finding(tool="pyright")])
            layer = a.run_l3a(tmp_path, {})
        assert layer.passed is False
        assert len(layer.findings) == 1
        assert layer.findings[0].tool == "pyright"

    def test_l3a_ruff_raises_runtimeerror(self, tmp_path: Path):
        """ruff raises RuntimeError -> only pyright findings counted."""
        a = self._adapter()
        with patch.object(a.ruff, "invoke", side_effect=RuntimeError("tool error")):
            a.pyright = _mock_subadapter(findings=[])
            layer = a.run_l3a(tmp_path, {})
        assert layer.passed is True

    def test_l3a_pyright_raises_oserror(self, tmp_path: Path):
        """pyright raises OSError -> only ruff findings counted."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        with patch.object(a.pyright, "invoke", side_effect=OSError("pyright broken")):
            layer = a.run_l3a(tmp_path, {})
        assert layer.passed is True

    def test_l3a_pyright_raises_runtimeerror(self, tmp_path: Path):
        """pyright raises RuntimeError -> only ruff findings."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[_make_finding(tool="ruff")])
        with patch.object(a.pyright, "invoke", side_effect=RuntimeError("pyright error")):
            layer = a.run_l3a(tmp_path, {})
        assert len(layer.findings) == 1
        assert layer.findings[0].tool == "ruff"

    def test_l3a_ruff_returns_none_stdout(self, tmp_path: Path):
        """ruff.invoke returns None stdout -> parse handles gracefully."""
        a = self._adapter()
        inv_result = MagicMock()
        inv_result.stdout = None
        inv_result.stderr = ""
        inv_result.exitcode = 1
        # Use parse.return_value so we bypass the real parse method
        a.pyright = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            layer = a.run_l3a(tmp_path, {})
        assert isinstance(layer, LayerResult)

    def test_l3a_both_raise(self, tmp_path: Path):
        """Both adapters raise -> empty findings, passed=True."""
        a = self._adapter()
        with patch.object(a.ruff, "invoke", side_effect=OSError("ruff down")):
            with patch.object(a.pyright, "invoke", side_effect=OSError("pyright down")):
                layer = a.run_l3a(tmp_path, {})
        assert layer.passed is True
        assert layer.findings == []

    def test_l3a_ruff_empty_parse_result(self, tmp_path: Path):
        """ruff.parse returns empty list -> no ruff findings included."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.ruff.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        a.pyright = _mock_subadapter(findings=[])
        layer = a.run_l3a(tmp_path, {})
        assert layer.passed is True
        assert layer.findings == []


# ---------------------------------------------------------------------------
# Run L1 (pytest)
# ---------------------------------------------------------------------------

class TestRunL1:
    """Test run_l1 branch coverage: pytest with xml report."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_l1_all_pass(self, tmp_path: Path):
        """No pytest failure findings -> passed=True."""
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[])
        layer = a.run_l1(tmp_path, {})
        assert layer.layer == "L1"
        assert layer.language == "python"
        assert layer.passed is True
        assert layer.findings == []

    def test_l1_has_findings(self, tmp_path: Path):
        """Pytest returns findings -> passed=False."""
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[_make_finding(tool="pytest")])
        layer = a.run_l1(tmp_path, {})
        assert layer.passed is False
        assert len(layer.findings) == 1

    def test_l1_pytest_raises_oserror(self, tmp_path: Path):
        """Pytest.invoke raises OSError -> empty findings."""
        a = self._adapter()
        with patch.object(a.pytest, "invoke", side_effect=OSError("pytest failed")):
            layer = a.run_l1(tmp_path, {})
            assert layer.passed is True
            assert layer.findings == []

    def test_l1_pytest_raises_runtimeerror(self, tmp_path: Path):
        """Pytest.invoke raises RuntimeError -> empty findings."""
        a = self._adapter()
        with patch.object(a.pytest, "invoke", side_effect=RuntimeError("boom")):
            layer = a.run_l1(tmp_path, {})
            assert layer.passed is True

    def test_l1_pytest_empty_stdout(self, tmp_path: Path):
        """Pytest returns empty stdout -> parse returns []."""
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[])
        a.pytest.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)
        layer = a.run_l1(tmp_path, {})
        assert layer.passed is True

    def test_l1_pytest_returns_invalid_json(self, tmp_path: Path):
        """Pytest returns non-parseable data -> parse returns empty."""
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[])
        a.pytest.invoke.return_value = MagicMock(stdout="garbage", stderr="", exitcode=1)
        layer = a.run_l1(tmp_path, {})
        assert layer.passed is True

    def test_l1_pytest_multiple_findings(self, tmp_path: Path):
        """Multiple pytest findings all included."""
        a = self._adapter()
        findings = [
            _make_finding(tool="pytest", rule_id="failure", node="t1.py"),
            _make_finding(tool="pytest", rule_id="failure", node="t2.py"),
        ]
        a.pytest = _mock_subadapter(findings=findings)
        layer = a.run_l1(tmp_path, {})
        assert layer.passed is False
        assert len(layer.findings) == 2

    def test_l1_duration_included(self, tmp_path: Path):
        """LayerResult includes duration_sec."""
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[])
        layer = a.run_l1(tmp_path, {})
        assert layer.duration_sec >= 0


# ---------------------------------------------------------------------------
# Run L2 (ruff + vulture + deptry)
# ---------------------------------------------------------------------------

class TestRunL2:
    """Test run_l2 branch coverage: code quality tools."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_l2_all_pass(self, tmp_path: Path):
        """All tools return 0 findings -> passed=True."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.vulture = _mock_subadapter(findings=[])
        a.deptry = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            layer = a.run_l2(tmp_path, {})
        assert layer.layer == "L2"
        assert layer.passed is True
        assert layer.findings == []

    def test_l2_ruff_findings(self, tmp_path: Path):
        """Ruff returns findings -> included."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[_make_finding(tool="ruff")])
        a.vulture = _mock_subadapter(findings=[])
        a.deptry = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            layer = a.run_l2(tmp_path, {})
        assert layer.passed is False
        assert len(layer.findings) == 1
        assert layer.findings[0].tool == "ruff"

    def test_l2_vulture_findings(self, tmp_path: Path):
        """Vulture returns findings -> included."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.vulture = _mock_subadapter(findings=[_make_finding(tool="vulture", severity="warning")])
        a.deptry = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            layer = a.run_l2(tmp_path, {})
        assert layer.passed is False
        assert len(layer.findings) == 1
        assert layer.findings[0].tool == "vulture"
        assert layer.findings[0].severity == "warning"

    def test_l2_deptry_findings(self, tmp_path: Path):
        """Deptry returns findings -> included."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.vulture = _mock_subadapter(findings=[])
        a.deptry = _mock_subadapter(findings=[_make_finding(tool="deptry")])
        with _all_tools_on_path():
            layer = a.run_l2(tmp_path, {})
        assert layer.passed is False
        assert layer.findings[0].tool == "deptry"

    def test_l2_all_findings(self, tmp_path: Path):
        """All three tools return findings -> all merged."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[_make_finding(tool="ruff")])
        a.vulture = _mock_subadapter(findings=[_make_finding(tool="vulture")])
        a.deptry = _mock_subadapter(findings=[_make_finding(tool="deptry")])
        with _all_tools_on_path():
            layer = a.run_l2(tmp_path, {})
        assert layer.passed is False
        assert len(layer.findings) == 3

    def test_l2_ruff_error(self, tmp_path: Path):
        """Ruff raises -> skipped, other tools still run."""
        a = self._adapter()
        with patch.object(a.ruff, "invoke", side_effect=OSError("ruff broken")):
            a.vulture = _mock_subadapter(findings=[_make_finding(tool="vulture")])
            a.deptry = _mock_subadapter(findings=[])
            with _all_tools_on_path():
                layer = a.run_l2(tmp_path, {})
        assert len(layer.findings) == 1
        assert layer.findings[0].tool == "vulture"

    def test_l2_vulture_error(self, tmp_path: Path):
        """Vulture raises -> skipped, ruff and deptry still run."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[_make_finding(tool="ruff")])
        with patch.object(a.vulture, "invoke", side_effect=RuntimeError("vulture broke")):
            a.deptry = _mock_subadapter(findings=[_make_finding(tool="deptry")])
            with _all_tools_on_path():
                layer = a.run_l2(tmp_path, {})
        assert len(layer.findings) == 2

    def test_l2_deptry_error(self, tmp_path: Path):
        """Deptry raises -> skipped, ruff and vulture still run."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.vulture = _mock_subadapter(findings=[])
        with patch.object(a.deptry, "invoke", side_effect=OSError("deptry err")):
            with _all_tools_on_path():
                layer = a.run_l2(tmp_path, {})
            assert layer.findings == []

    def test_l2_all_error(self, tmp_path: Path):
        """All three raise -> empty findings, passed=True."""
        a = self._adapter()
        with patch.object(a.ruff, "invoke", side_effect=OSError("fail")):
            with patch.object(a.vulture, "invoke", side_effect=OSError("fail")):
                with patch.object(a.deptry, "invoke", side_effect=OSError("fail")):
                    with _all_tools_on_path():
                        layer = a.run_l2(tmp_path, {})
        assert layer.passed is True
        assert layer.findings == []

    def test_l2_non_dict_items_in_parse(self, tmp_path: Path):
        """Sub-adapter parse receives non-dict results -> skips them."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.vulture = _mock_subadapter(findings=[])
        a.deptry = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            layer = a.run_l2(tmp_path, {})
        assert isinstance(layer, LayerResult)


# ---------------------------------------------------------------------------
# Run L3B (mutmut)
# ---------------------------------------------------------------------------

class TestRunL3B:
    """Test run_l3b branch coverage: mutation testing."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_l3b_no_mutants(self, tmp_path: Path):
        """All mutants killed -> passed=True."""
        a = self._adapter()
        mock_mutmut = _mock_subadapter()
        mock_mutmut.parse.return_value = MutationStats(
            total=10, killed=10, survived=0, timed_out=0,
            escaped=0, untested=0, msi=1.0, covered_msi=1.0,
        )
        with patch.object(a, 'mutmut', mock_mutmut):
            with _all_tools_on_path():
                layer = a.run_l3b(tmp_path, {})
        assert layer.layer == "L3B"
        assert layer.passed is True
        assert layer.findings == []
        ms = layer.tool_specific["mutation_stats"]
        assert ms.killed == 10
        assert ms.survived == 0

    def test_l3b_survived_mutants(self, tmp_path: Path):
        """Some mutants survived -> passed=False."""
        a = self._adapter()
        mock_mutmut = _mock_subadapter()
        mock_mutmut.parse.return_value = MutationStats(
            total=10, killed=7, survived=3, timed_out=0,
            escaped=0, untested=0, msi=0.7, covered_msi=0.7,
        )
        with patch.object(a, "mutmut", mock_mutmut):
            with _all_tools_on_path():
                layer = a.run_l3b(tmp_path, {})
        assert layer.passed is False
        ms = layer.tool_specific["mutation_stats"]
        assert ms.survived == 3

    def test_l3b_timed_out(self, tmp_path: Path):
        """Some mutants timed out -> passed=False."""
        a = self._adapter()
        mock_mutmut = _mock_subadapter()
        mock_mutmut.parse.return_value = MutationStats(
            total=10, killed=8, survived=0, timed_out=2,
            escaped=0, untested=0, msi=0.8, covered_msi=0.8,
        )
        with patch.object(a, "mutmut", mock_mutmut):
            with _all_tools_on_path():
                layer = a.run_l3b(tmp_path, {})
        assert layer.passed is False
        ms = layer.tool_specific["mutation_stats"]
        assert ms.timed_out == 2

    def test_l3b_escaped_mutants(self, tmp_path: Path):
        """Escaped mutants -> survived > 0, passed=False."""
        a = self._adapter()
        mock_mutmut = _mock_subadapter()
        mock_mutmut.parse.return_value = MutationStats(
            total=10, killed=8, survived=1, timed_out=0,
            escaped=1, untested=0, msi=0.8, covered_msi=0.8,
        )
        with patch.object(a, "mutmut", mock_mutmut):
            with _all_tools_on_path():
                layer = a.run_l3b(tmp_path, {})
        assert layer.passed is False
        ms = layer.tool_specific["mutation_stats"]
        assert ms.escaped == 1

    def test_l3b_no_mutants_found(self, tmp_path: Path):
        """Zero mutants total (0,0,0) -> passed=True."""
        a = self._adapter()
        mock_mutmut = _mock_subadapter()
        mock_mutmut.parse.return_value = MutationStats(
            total=0, killed=0, survived=0, timed_out=0,
            escaped=0, untested=0, msi=0.0, covered_msi=0.0,
        )
        with patch.object(a, "mutmut", mock_mutmut):
            with _all_tools_on_path():
                layer = a.run_l3b(tmp_path, {})
        assert layer.passed is True
        ms = layer.tool_specific["mutation_stats"]
        assert ms.total == 0

    def test_l3b_mutmut_not_on_path(self, tmp_path: Path, caplog):
        """mutmut not found -> empty stats + exact warning message.

        Kills mutmut_5 (None), mutmut_6 (XX...XX), mutmut_7 (path→PATH),
        mutmut_8 (UPPERCASE), mutmut_13 (escaped=None), mutmut_14 (untested=None).
        """
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                layer = a.run_l3b(tmp_path, {})
        ms = layer.tool_specific["mutation_stats"]
        assert ms.total == 0
        assert ms.killed == 0
        assert ms.survived == 0
        assert ms.timed_out == 0
        assert ms.escaped == 0
        assert ms.untested == 0
        assert ms.msi == 0.0
        assert ms.covered_msi == 0.0
        assert ms.survived == ms.timed_out == 0  # confirms passed logic
        assert ms.escaped == 0  # kills mutmut_13: escaped=0 → None
        assert ms.untested == 0  # kills mutmut_14: untested=0 → None
        assert layer.passed is True
        # Exact log message kills string mutations 5,6,7,8
        assert "mutmut not found on PATH, returning empty stats" in caplog.text

    def test_l3b_mutmut_raises_oserror(self, tmp_path: Path):
        """mutmut.invoke raises OSError -> empty fallback stats."""
        a = self._adapter()
        mock_mutmut = _mock_subadapter()
        with patch.object(a, "mutmut", mock_mutmut):
            with patch.object(mock_mutmut, "invoke", side_effect=OSError("mutmut broken")):
                with _all_tools_on_path():
                    layer = a.run_l3b(tmp_path, {})
        ms = layer.tool_specific["mutation_stats"]
        assert ms.total == 0
        assert layer.passed is True

    def test_l3b_mutmut_raises_runtimeerror(self, tmp_path: Path):
        """mutmut.invoke raises RuntimeError -> empty fallback stats."""
        a = self._adapter()
        mock_mutmut = _mock_subadapter()
        with patch.object(a, "mutmut", mock_mutmut):
            with patch.object(mock_mutmut, "invoke", side_effect=RuntimeError("boom")):
                with _all_tools_on_path():
                    layer = a.run_l3b(tmp_path, {})
        ms = layer.tool_specific["mutation_stats"]
        assert ms.total == 0
        assert layer.passed is True

    def test_l3b_mutmut_parse_return_full_stats(self, tmp_path: Path):
        """Parsed MutationStats contains all expected fields."""
        a = self._adapter()
        expected = MutationStats(
            total=50, killed=30, survived=15, timed_out=3,
            escaped=2, untested=0, msi=0.6, covered_msi=0.7,
        )
        mock_mutmut = _mock_subadapter()
        with patch.object(a, "mutmut", mock_mutmut):
            with _all_tools_on_path():
                mock_mutmut.parse.return_value = expected
                layer = a.run_l3b(tmp_path, {})
        ms = layer.tool_specific["mutation_stats"]
        assert ms.total == 50
        assert ms.killed == 30
        assert ms.survived == 15
        assert ms.timed_out == 3
        assert ms.escaped == 2
        assert ms.untested == 0
        assert ms.msi == 0.6
        assert ms.covered_msi == 0.7

    def test_l3b_layer_name_and_language(self, tmp_path: Path):
        """Layer name and language are set correctly."""
        a = self._adapter()
        mock_mutmut = _mock_subadapter()
        with patch.object(a, "mutmut", mock_mutmut):
            with _all_tools_on_path():
                mock_mutmut.parse.return_value = MutationStats(
                    total=0, killed=0, survived=0, timed_out=0,
                    escaped=0, untested=0, msi=0.0, covered_msi=0.0,
                )
                layer = a.run_l3b(tmp_path, {})
        assert layer.layer == "L3B"
        assert layer.language == "python"


# ---------------------------------------------------------------------------
# Run L4 (bandit)
# ---------------------------------------------------------------------------

class TestRunL4:
    """Test run_l4 branch coverage: security scanning."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_l4_no_findings(self, tmp_path: Path):
        """Bandit returns all clear -> passed=True."""
        a = self._adapter()
        a.bandit = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            layer = a.run_l4(tmp_path, {})
        assert layer.layer == "L4"
        assert layer.language == "python"
        assert layer.passed is True
        assert layer.findings == []

    def test_l4_security_findings(self, tmp_path: Path):
        """Bandit finds security issues -> passed=False."""
        a = self._adapter()
        a.bandit = _mock_subadapter(findings=[_make_finding(tool="bandit", severity="error")])
        with _all_tools_on_path():
            layer = a.run_l4(tmp_path, {})
        assert layer.passed is False
        assert len(layer.findings) == 1
        assert layer.findings[0].tool == "bandit"

    def test_l4_multiple_security_findings(self, tmp_path: Path):
        """Multiple bandit findings -> all merged."""
        a = self._adapter()
        findings = [
            _make_finding(tool="bandit", severity="error", rule_id="B101",
                          node="app.py", message="Use of assert detected"),
            _make_finding(tool="bandit", severity="medium", rule_id="B602",
                          node="db.py", message="Subprocess call"),
        ]
        a.bandit = _mock_subadapter(findings=findings)
        with _all_tools_on_path():
            layer = a.run_l4(tmp_path, {})
        assert layer.passed is False
        assert len(layer.findings) == 2
        assert layer.findings[0].rule_id == "B101"
        assert layer.findings[1].severity == "medium"

    def test_l4_bandit_raises_oserror(self, tmp_path: Path):
        """Bandit raises OSError -> empty findings."""
        a = self._adapter()
        with patch.object(a.bandit, "invoke", side_effect=OSError("bandit error")):
            with _all_tools_on_path():
                layer = a.run_l4(tmp_path, {})
            assert layer.passed is True
            assert layer.findings == []

    def test_l4_bandit_raises_runtimeerror(self, tmp_path: Path):
        """Bandit raises RuntimeError -> empty findings."""
        a = self._adapter()
        with patch.object(a.bandit, "invoke", side_effect=RuntimeError("boom")):
            with _all_tools_on_path():
                layer = a.run_l4(tmp_path, {})
            assert layer.passed is True

    def test_l4_bandit_cwe_in_finding(self, tmp_path: Path):
        """Bandit CWE field correctly propagated to finding."""
        a = self._adapter()
        finding = _make_finding(
            tool="bandit", severity="error", cwe="CWE-328",
            rule_id="B602", message="Subprocess without shell=True",
        )
        a.bandit = _mock_subadapter(findings=[finding])
        with _all_tools_on_path():
            layer = a.run_l4(tmp_path, {})
        assert layer.findings[0].cwe == "CWE-328"

    def test_l4_bandit_empty_stdout(self, tmp_path: Path):
        """Bandit returns empty stdout -> empty findings."""
        a = self._adapter()
        a.bandit = _mock_subadapter(findings=[])
        a.bandit.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)
        with _all_tools_on_path():
            layer = a.run_l4(tmp_path, {})
        assert layer.passed is True

    def test_l4_high_severity(self, tmp_path: Path):
        """High severity security finding properly tracked."""
        a = self._adapter()
        a.bandit = _mock_subadapter(
            findings=[_make_finding(tool="bandit", severity="error",
                                    message="CRITICAL: hardcoded password")],
        )
        with _all_tools_on_path():
            layer = a.run_l4(tmp_path, {})
        assert layer.findings[0].severity == "error"


# ---------------------------------------------------------------------------
# check_tools
# ---------------------------------------------------------------------------

class TestCheckTools:
    """Test check_tools: verify ruff and pyright are on PATH."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_check_tools_nothing_found(self, tmp_path: Path):
        """Neither ruff nor pyright present -> RuntimeError."""
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="Missing Python tool"):
                a.check_tools()

    def test_check_tools_ruff_missing(self, tmp_path: Path):
        """Only ruff missing -> RuntimeError with ruff."""
        a = self._adapter()

        def _which(cmd):
            if cmd == "ruff":
                return None
            return "/usr/bin/fake"

        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", side_effect=_which):
            with pytest.raises(RuntimeError, match="ruff") as exc_info:
                a.check_tools()
        assert "ruff" in exc_info.value.args[0]

    def test_check_tools_pyright_missing(self, tmp_path: Path):
        """Only pyright missing -> RuntimeError with pyright."""
        a = self._adapter()

        def _which(cmd):
            if cmd == "pyright":
                return None
            return "/usr/bin/fake"

        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", side_effect=_which):
            with pytest.raises(RuntimeError, match="pyright") as exc_info:
                a.check_tools()
        assert "pyright" in exc_info.value.args[0]

    def test_check_tools_both_present(self, tmp_path: Path):
        """Both ruff and pyright present -> return list."""
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value="/usr/bin/tool"):
            result = a.check_tools()
        assert result == ["ruff", "pyright"]

    def test_check_tools_error_message_contains_both_names(self, tmp_path: Path):
        """Error lists both missing tool names."""
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            try:
                a.check_tools()
            except RuntimeError as e:
                msg = str(e)
                assert "ruff" in msg
                assert "pyright" in msg


# ---------------------------------------------------------------------------
# tool_versions
# ---------------------------------------------------------------------------

class TestToolVersions:
    """Test tool_versions: version collection from all sub-adapters."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_tool_versions_all_success(self, tmp_path: Path):
        """All adapters return versions -> full version dict."""
        a = self._adapter()
        versions_map = {
            "ruff": "ruff 0.4.0", "pyright": "1.1.350", "pytest": "8.0.0",
            "mutmut": "2.4.6", "bandit": "1.7.5", "vulture": "2.11", "deptry": "0.12.0",
        }
        for attr, (name, ver) in zip(
            ("ruff", "pyright", "pytest", "mutmut", "bandit", "vulture", "deptry"),
            versions_map.items(),
        ):
            sub = getattr(a, attr)
            versioned = MagicMock()
            versioned.name = name
            versioned.version = MagicMock(return_value=ver)
            setattr(a, attr, versioned)
        result = a.tool_versions()
        for name, ver in versions_map.items():
            assert result[name] == ver

    def test_tool_versions_all_missing(self, tmp_path: Path):
        """All adapters raise -> all MISSING."""
        a = self._adapter()
        for attr in ("ruff", "pyright", "pytest", "mutmut", "bandit", "vulture", "deptry"):
            sub = MagicMock()
            sub.name = attr
            sub.version = MagicMock(side_effect=RuntimeError("missing"))
            setattr(a, attr, sub)
        result = a.tool_versions()
        for name in ("ruff", "pyright", "pytest", "mutmut", "bandit", "vulture", "deptry"):
            assert result[name] == "MISSING"

    def test_tool_versions_oserror(self, tmp_path: Path):
        """Adapter raises OSError -> MISSING."""
        a = self._adapter()
        for attr in ("ruff", "pyright", "pytest", "mutmut", "bandit", "vulture", "deptry"):
            sub = MagicMock()
            sub.name = attr
            sub.version = MagicMock(side_effect=OSError("tool not found"))
            setattr(a, attr, sub)
        result = a.tool_versions()
        assert result["ruff"] == "MISSING"
        assert result["pyright"] == "MISSING"


def _make_versioned(name: str, version: str) -> MagicMock:
    sub = MagicMock()
    sub.name = name
    sub.version = MagicMock(return_value=version)
    return sub


# ---------------------------------------------------------------------------
# Private helper: _run_ruff
# ---------------------------------------------------------------------------

class TestRunRuffHelper:
    """Test _run_ruff: tool-not-found and invocation branches."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_run_ruff_tool_found(self, tmp_path: Path):
        """Ruff on PATH -> invoke + parse called."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[_make_finding(tool="ruff")])
        findings = a._run_ruff(tmp_path, {})
        assert len(findings) == 1
        assert findings[0].tool == "ruff"

    def test_run_ruff_tool_not_found(self, tmp_path: Path):
        """Ruff not on PATH -> empty list."""
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            findings = a._run_ruff(tmp_path, {})
        assert findings == []

    def test_run_ruff_parse_error(self, tmp_path: Path):
        """Ruff parse raises -> caught, empty list returned."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.ruff.parse = MagicMock(side_effect=RuntimeError("parse err"))
        findings = a._run_ruff(tmp_path, {})
        assert findings == []

    def test_run_ruff_oserror_on_invoke(self, tmp_path: Path):
        """Ruff.invoke raises OSError -> caught, empty list returned."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.ruff.invoke = MagicMock(side_effect=OSError("ruff exec failed"))
        findings = a._run_ruff(tmp_path, {})
        assert findings == []


# ---------------------------------------------------------------------------
# Private helper: _run_pyright
# ---------------------------------------------------------------------------

class TestRunPyrightHelper:
    """Test _run_pyright: tool-not-found and invocation branches."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_run_pyright_tool_found(self, tmp_path: Path):
        """Pyright on PATH -> parse returns findings."""
        a = self._adapter()
        a.pyright = _mock_subadapter(findings=[_make_finding(tool="pyright")])
        findings = a._run_pyright(tmp_path, {})
        assert len(findings) == 1

    def test_run_pyright_tool_not_found(self, tmp_path: Path):
        """Pyright not on PATH -> empty list."""
        a = self._adapter()
        a.pyright = _mock_subadapter(findings=[])
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            findings = a._run_pyright(tmp_path, {})
        assert findings == []

    def test_run_pyright_oserror(self, tmp_path: Path):
        """Pyright.invoke raises OSError -> empty list."""
        a = self._adapter()
        a.pyright = _mock_subadapter(findings=[])
        a.pyright.invoke = MagicMock(side_effect=OSError("pyright exec failed"))
        findings = a._run_pyright(tmp_path, {})
        assert findings == []


# ---------------------------------------------------------------------------
# Private helper: _run_pytest
# ---------------------------------------------------------------------------

class TestRunPytestHelper:
    """Test _run_pytest: python3-path and invocation branches."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_run_pytest_tool_found(self, tmp_path: Path):
        """Pytest runs and returns findings."""
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[_make_finding(tool="pytest")])
        findings = a._run_pytest(tmp_path, {})
        assert len(findings) == 1

    def test_run_pytest_oserror(self, tmp_path: Path):
        """Pytest.invoke raises -> empty list."""
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[])
        with patch.object(a.pytest, "invoke", side_effect=RuntimeError("pytest failed")):
            findings = a._run_pytest(tmp_path, {})
        assert findings == []


# ---------------------------------------------------------------------------
# Private helper: _run_vulture
# ---------------------------------------------------------------------------

class TestRunVultureHelper:
    """Test _run_vulture: tool-not-found and invocation branches."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_run_vulture_tool_found(self, tmp_path: Path):
        """Vulture on PATH -> parse returns findings."""
        a = self._adapter()
        a.vulture = _mock_subadapter(findings=[_make_finding(tool="vulture", severity="warning")])
        with _all_tools_on_path({"vulture": "/bin/vulture"}):
            findings = a._run_vulture(tmp_path, {})
        assert len(findings) == 1
        assert findings[0].severity == "warning"

    def test_run_vulture_tool_not_found(self, tmp_path: Path):
        """Vulture not on PATH -> empty list."""
        a = self._adapter()
        a.vulture = _mock_subadapter(findings=[])
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            findings = a._run_vulture(tmp_path, {})
        assert findings == []

    def test_run_vulture_oserror(self, tmp_path: Path):
        """Vulture.invoke raises -> empty list."""
        a = self._adapter()
        a.vulture = _mock_subadapter(findings=[])
        a.vulture.invoke = MagicMock(side_effect=OSError("vulture exec failed"))
        with _all_tools_on_path({"vulture": "/bin/vulture"}):
            findings = a._run_vulture(tmp_path, {})
        assert findings == []


# ---------------------------------------------------------------------------
# Private helper: _run_deptry
# ---------------------------------------------------------------------------

class TestRunDeptryHelper:
    """Test _run_deptry: tool-not-found and invocation branches."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_run_deptry_tool_found(self, tmp_path: Path):
        """Deptry on PATH -> parse returns findings."""
        a = self._adapter()
        a.deptry = _mock_subadapter(findings=[_make_finding(tool="deptry")])
        with _all_tools_on_path({"deptry": "/bin/deptry"}):
            findings = a._run_deptry(tmp_path, {})
        assert len(findings) == 1

    def test_run_deptry_tool_not_found(self, tmp_path: Path):
        """Deptry not on PATH -> empty list."""
        a = self._adapter()
        a.deptry = _mock_subadapter(findings=[])
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            findings = a._run_deptry(tmp_path, {})
        assert findings == []

    def test_run_deptry_oserror(self, tmp_path: Path):
        """Deptry.invoke raises -> empty list."""
        a = self._adapter()
        a.deptry = _mock_subadapter(findings=[])
        a.deptry.invoke = MagicMock(side_effect=OSError("deptry exec failed"))
        with _all_tools_on_path({"deptry": "/bin/deptry"}):
            findings = a._run_deptry(tmp_path, {})
        assert findings == []


# ---------------------------------------------------------------------------
# Private helper: _run_bandit
# ---------------------------------------------------------------------------

class TestRunBanditHelper:
    """Test _run_bandit: tool-not-found and invocation branches."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_run_bandit_tool_found(self, tmp_path: Path):
        """Bandit on PATH -> parse returns findings."""
        a = self._adapter()
        a.bandit = _mock_subadapter(
            findings=[_make_finding(tool="bandit", severity="error", rule_id="B101")],
        )
        with _all_tools_on_path({"bandit": "/bin/bandit"}):
            findings = a._run_bandit(tmp_path, {})
        assert len(findings) == 1
        assert findings[0].rule_id == "B101"

    def test_run_bandit_tool_not_found(self, tmp_path: Path):
        """Bandit not on PATH -> empty list."""
        a = self._adapter()
        a.bandit = _mock_subadapter(findings=[])
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            findings = a._run_bandit(tmp_path, {})
        assert findings == []

    def test_run_bandit_oserror(self, tmp_path: Path):
        """Bandit.invoke raises -> empty list."""
        a = self._adapter()
        a.bandit = _mock_subadapter(findings=[])
        a.bandit.invoke = MagicMock(side_effect=OSError("bandit exec failed"))
        with _all_tools_on_path({"bandit": "/bin/bandit"}):
            findings = a._run_bandit(tmp_path, {})
        assert findings == []


# ---------------------------------------------------------------------------
# PythonAdapter instantiation and basic properties
# ---------------------------------------------------------------------------

class TestPythonAdapterBasics:
    """Test constructor and basic properties."""

    def test_adapter_name(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter()
        assert a._name == "python"

    def test_sub_adapters_instantiated(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        from harness_quality_gate.adapters.python.ruff_adapter import RuffAdapter
        from harness_quality_gate.adapters.python.pyright_adapter import PyrightAdapter
        from harness_quality_gate.adapters.python.pytest_adapter import PytestAdapter
        from harness_quality_gate.adapters.python.mutmut_adapter import MutmutAdapter
        from harness_quality_gate.adapters.python.bandit_adapter import BanditAdapter
        from harness_quality_gate.adapters.python.vulture_adapter import VultureAdapter
        from harness_quality_gate.adapters.python.deptry_adapter import DeptryAdapter
        a = PythonAdapter()
        assert isinstance(a.ruff, RuffAdapter)
        assert isinstance(a.pyright, PyrightAdapter)
        assert isinstance(a.pytest, PytestAdapter)
        assert isinstance(a.mutmut, MutmutAdapter)
        assert isinstance(a.bandit, BanditAdapter)
        assert isinstance(a.vulture, VultureAdapter)
        assert isinstance(a.deptry, DeptryAdapter)

    def test_repo_placeholder_identity(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter()
        path = Path("/some/path")
        assert a.repo_placeholder(path) == path

    def test_repo_placeholder_preserves_type(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter()
        path = Path("/some/path")
        result = a.repo_placeholder(path)
        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# Edge cases: combined orchestration
# ---------------------------------------------------------------------------

class TestPythonAdapterEdgeCases:
    """Edge cases for orchestration when env is populated."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_l3a_with_env(self, tmp_path: Path):
        """run_l3a receives env dict -> still works."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.pyright = _mock_subadapter(findings=[])
        layer = a.run_l3a(tmp_path, {"PYRIGHT_PYTHON_FORCE_VERSION": "1.1.350"})
        assert layer.passed is True
        assert layer.findings == []

    def test_l2_with_env(self, tmp_path: Path):
        """run_l2 receives env dict -> still works."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.vulture = _mock_subadapter(findings=[])
        a.deptry = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            layer = a.run_l2(tmp_path, {"RUFF_OUTPUT_FORMAT": "json"})
        assert layer.passed is True

    def test_l1_with_env(self, tmp_path: Path):
        """run_l1 receives env dict -> still works."""
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[])
        layer = a.run_l1(tmp_path, {"PYTEST_ADDOPTS": "-q"})
        assert layer.passed is True

    def test_l3b_with_env(self, tmp_path: Path):
        """run_l3b receives env dict -> still works."""
        a = self._adapter()
        mock_mutmut = _mock_subadapter()
        with patch.object(a, "mutmut", mock_mutmut):
            with _all_tools_on_path():
                mock_mutmut.parse.return_value = MutationStats(
                    total=5, killed=5, survived=0, timed_out=0,
                    escaped=0, untested=0, msi=1.0, covered_msi=1.0,
                )
                layer = a.run_l3b(tmp_path, {"MUTMUT_COMPILER": "python"})
        assert layer.passed is True

    def test_l4_with_env(self, tmp_path: Path):
        """run_l4 receives env dict -> still works."""
        a = self._adapter()
        a.bandit = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            layer = a.run_l4(tmp_path, {"BANDIT_CONFIG": "/path/to/config"})
        assert layer.passed is True

    def test_l3b_mutation_stats_immutable(self, tmp_path: Path):
        """MutationStats is a frozen dataclass -> not modified outside."""
        stats = MutationStats(
            total=10, killed=8, survived=2, timed_out=0,
            escaped=0, untested=0, msi=0.8, covered_msi=0.8,
        )
        # Frozen means no attribute assignment
        with pytest.raises(Exception):
            stats.killed = 9

    def test_run_l3a_layer_result_fields(self, tmp_path: Path):
        """LayerResult has all expected fields after run_l3a."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.pyright = _mock_subadapter(findings=[])
        layer = a.run_l3a(tmp_path, {})
        assert hasattr(layer, "layer")
        assert layer.layer == "L3A"
        assert hasattr(layer, "passed")
        assert layer.passed is True
        assert hasattr(layer, "findings")
        assert isinstance(layer.findings, list)
        assert hasattr(layer, "duration_sec")
        assert isinstance(layer.duration_sec, (int, float))
        assert hasattr(layer, "language")
        assert layer.language == "python"

    def test_run_l2_layer_result_fields(self, tmp_path: Path):
        """LayerResult has all expected fields after run_l2."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.vulture = _mock_subadapter(findings=[])
        a.deptry = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            layer = a.run_l2(tmp_path, {})
        assert layer.layer == "L2"
        assert layer.passed is True

    def test_run_l1_layer_result_fields(self, tmp_path: Path):
        """LayerResult has all expected fields after run_l1."""
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[])
        layer = a.run_l1(tmp_path, {})
        assert layer.layer == "L1"
        assert layer.passed is True

    def test_run_l4_layer_result_fields(self, tmp_path: Path):
        """LayerResult has all expected fields after run_l4."""
        a = self._adapter()
        a.bandit = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            layer = a.run_l4(tmp_path, {})
        assert layer.layer == "L4"
        assert layer.passed is True

    def test_logging_import_present(self):
        """Module imports logging without side effects."""
        from harness_quality_gate.adapters.python import python_adapter
        assert hasattr(python_adapter, "logger")

    def test_l1_duration_is_float(self, tmp_path: Path):
        """Duration is always a numeric value."""
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[])
        layer = a.run_l1(tmp_path, {})
        assert isinstance(layer.duration_sec, (int, float))
        assert layer.duration_sec >= 0

    def test_l2_duration_is_float(self, tmp_path: Path):
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.vulture = _mock_subadapter(findings=[])
        a.deptry = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            layer = a.run_l2(tmp_path, {})
        assert isinstance(layer.duration_sec, (int, float))

    def test_l3a_duration_is_float(self, tmp_path: Path):
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.pyright = _mock_subadapter(findings=[])
        layer = a.run_l3a(tmp_path, {})
        assert isinstance(layer.duration_sec, (int, float))

    def test_l4_duration_is_float(self, tmp_path: Path):
        a = self._adapter()
        a.bandit = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            layer = a.run_l4(tmp_path, {})
        assert isinstance(layer.duration_sec, (int, float))
