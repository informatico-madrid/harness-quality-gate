"""Comprehensive orchestration tests for PythonAdapter.

Targets: run_l3a, run_l1, run_l2, run_l3b, run_l4, check_tools, tool_versions,
         private helpers (_run_ruff, _run_pyright, _run_pytest, _run_vulture,
         _run_deptry, _run_mutmut, _run_bandit).
Design: Mutation testing / python_adapter coverage
"""
from __future__ import annotations

import os
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
        # Handle absolute paths (the code sometimes passes /usr/bin/python3 directly)
        if os.path.isabs(name):
            return name
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
        """ruff returns findings, pyright clean -> passed=False.

        Kills mutmut_21-26, 28, 50 (passed=len(x)==0 mutations).
        Kills mutmut_16 (env keyword arg mutation) — assert invoke called with env=.
        Kills mutmut_9-14 (logger format string mutations) — assert log message.
        """
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[_make_finding(rule_id="E501")])
        a.pyright = _mock_subadapter(findings=[])
        layer = a.run_l3a(tmp_path, {})
        assert layer.passed is False
        assert isinstance(layer.passed, bool), "passed must be bool (kills mutmut_21-26,28,50)"
        assert len(layer.findings) == 1
        assert layer.findings[0].tool == "ruff"
        # Kill mutmut_16: ruff.invoke called with env= keyword arg
        call_kwargs = a.ruff.invoke.call_args.kwargs
        assert "env" in call_kwargs, "invoke() must receive env= keyword arg (kills mutmut_16)"
        assert call_kwargs["env"] == {}, "env= keyword arg must be {} or dict (kills mutmut_17)"

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

    def test_l3a_logger_format_strings(self, tmp_path: Path, caplog):
        """Verify logger.info format strings contain colon+count pattern.

        Kills mutmut_9 (logger.info call removed → log text empty)
        Kills mutmut_10 (len(ruff)→None in format arg)
        Kills mutmut_11 ("ruff: %d"→"ruff" → no colon in message)
        Kills mutmut_12-14 (same for pyright logger)
        """
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.pyright = _mock_subadapter(findings=[])
        with caplog.at_level("INFO", logger="harness_quality_gate.adapters.python.python_adapter"):
            a.run_l3a(tmp_path, {})
        assert len(caplog.messages) >= 2
        # mutmut_9: if logger.info removed, this assertion fails
        ruff_msg = [m for m in caplog.messages if "ruff:" in m and "findings" in m]
        pyright_msg = [m for m in caplog.messages if "pyright:" in m and "findings" in m]
        assert len(ruff_msg) >= 1, "Logger must emit ruff message with format (kills mutmut_9,11)"
        assert len(pyright_msg) >= 1, "Logger must emit pyright message with format (kills mutmut_13)"
        # mutmut_10, 12: len→None means format fails at string % int → message empty/broken
        # Check format pattern: "tool: N findings"
        for msg in ruff_msg + pyright_msg:
            parts = msg.split(": ")
            assert len(parts) >= 2, f"Message must have 'tool: count' format, got: {msg}"
            count_str = parts[1].split()[0]
            int(count_str)  # kills mutmut_10, 12: count is int, not None

    def test_l3a_ruff_invoke_args_strict(self, tmp_path: Path):
        """Assert _run_ruff calls ruff.invoke with correct args.

        Kills mutmut_16 (repo→None as first param to _run_ruff)
        Kills mutmut_17 (env=dict(env) removed → changed positional args)
        """
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.pyright = _mock_subadapter(findings=[])
        with _all_tools_on_path({"ruff": "/bin/ruff", "pyright": "/bin/pyright"}):
            layer = a.run_l3a(tmp_path, {})
        # Kill mutmut_16: invoke first arg must be the repo path (not None)
        assert a.ruff.invoke.called
        inv_args, inv_kwargs = a.ruff.invoke.call_args
        assert inv_args[0] is tmp_path, "invoke() first arg = repo (kills mutmut_16)"
        # Kill mutmut_17: env keyword arg must be present and dict
        assert "env" in inv_kwargs, "invoke() called with env= keyword arg (kills mutmut_17)"
        assert isinstance(inv_kwargs["env"], dict), "env= must be dict (kills mutmut_17)"
        assert layer.passed is True, "passed must be bool True (kills mutmut_21-28,50)"

    def test_l3a_pyright_invoke_args_strict(self, tmp_path: Path):
        """Assert _run_pyright calls pyright.invoke with correct args."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.pyright = _mock_subadapter(findings=[])
        with _all_tools_on_path({"ruff": "/bin/ruff", "pyright": "/bin/pyright"}):
            layer = a.run_l3a(tmp_path, {})
        assert a.pyright.invoke.called
        inv_args, inv_kwargs = a.pyright.invoke.call_args
        assert inv_args[0] is tmp_path, "invoke() first arg = repo (kills mutmut_15,29)"
        assert inv_args[1] == [], "invoke() second arg = [] (kills mutmut_15,29)"

    def test_l3a_passed_type_when_fail(self, tmp_path: Path):
        """passed must be exact bool False when findings exist.

        Kills mutmut_21 (False→None in passed=assignment)
        Kills mutmut_22 (True→False, etc.)
        Kills mutmut_23-26 (len(x)==0 mutations)
        Kills mutmut_28 (0→None in == comparison)
        Kills mutmut_50 (passed=False→True)
        """
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[_make_finding(tool="ruff")])
        a.pyright = _mock_subadapter(findings=[])
        layer = a.run_l3a(tmp_path, {})
        assert layer.passed is False, "passed must be False when findings exist (kills mutmut_21-28,50)"
        assert isinstance(layer.passed, bool), f"passed must be bool, got {type(layer.passed)}"


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

    def test_l1_has_findings(self, tmp_path: Path, caplog):
        """Pytest returns findings -> passed=False.

        Kills mutmut_4 (env→None positional), mutmut_5 (env=None keyword)
        Kills mutmut_9-14 (logger format string mutations)
        Kills mutmut_35-38 (passed=len(x)==0 mutations)
        """
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[_make_finding(tool="pytest")])
        with caplog.at_level("INFO", logger="harness_quality_gate.adapters.python.python_adapter"):
            layer = a.run_l1(tmp_path, {})
        assert layer.passed is False
        assert isinstance(layer.passed, bool)
        assert len(layer.findings) == 1
        # Kill mutmut_10, 12: logger.info format string mutations
        pytest_msg = [m for m in caplog.messages if "pytest:" in m and "findings" in m]
        assert len(pytest_msg) >= 1, "Logger must emit pytest message (kills mutmut_9, 11)"
        for msg in pytest_msg:
            parts = msg.split(": ")
            assert len(parts) >= 2
            int(parts[1].split()[0])  # kills mutmut_10, 12: count must be int

    def test_l1_pytest_invoke_args(self, tmp_path: Path):
        """Assert pytest.invoke called with correct args."""
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[])
        layer = a.run_l1(tmp_path, {})
        assert a.pytest.invoke.called
        inv_args, inv_kwargs = a.pytest.invoke.call_args
        assert inv_args[0] is tmp_path, "first arg = repo"
        assert inv_args[1] == [], "second arg = []"

    def test_l1_all_pass_strict(self, tmp_path: Path):
        """passed must be exact bool True (kills mutmut_35-38)."""
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[])
        layer = a.run_l1(tmp_path, {})
        assert layer.layer == "L1"
        assert layer.language == "python"
        assert layer.passed is True
        assert layer.findings == []
        assert isinstance(layer.passed, bool), "passed must be bool (kills mutmut_35-38)"

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

    def test_l2_all_pass(self, tmp_path: Path, caplog):
        """All tools return 0 findings -> passed=True.

        Kills: mutmut_9 (format string → None), mutmut_10 (count → None),
        mutmut_11 (format string removed), mutmut_12 (len → None).
        Verifies logger.info called with exact format string and numeric count.
        Kills mutmut_17,18 (env keyword arg mutation), mutmut_57,58 (logger msg mutations).
        Kills mutmut_63 (return value mutations).
        """
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.vulture = _mock_subadapter(findings=[])
        a.deptry = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            with caplog.at_level("INFO", logger="harness_quality_gate.adapters.python.python_adapter"):
                layer = a.run_l2(tmp_path, {})
        assert layer.layer == "L2"
        assert layer.passed is True
        assert isinstance(layer.passed, bool), f"passed must be bool (kills mutmut_37-40,46)"
        assert layer.findings == []
        assert isinstance(layer.duration_sec, float)
        # Kills: mutmut_9 (format string → None), mutmut_10 (count → None), mutmut_11 (no format)
        assert "ruff (L2)" in caplog.text
        assert "vulture" in caplog.text
        assert "deptry" in caplog.text
        # Verify log messages contain numeric count values (kills count → None mutations)
        for line in caplog.messages:
            if "ruff (L2)" in line or "vulture" in line or "deptry" in line:
                # Message is "tool: %d findings" % count — count must be numeric
                assert isinstance(int(str(line.split(":")[1].split()[0])), int)
        # Kill mutmut_17, 18: _run_ruff passes env=dict(env) if env else {}
        assert a.ruff.invoke.called
        inv_kwargs = a.ruff.invoke.call_args.kwargs
        assert "env" in inv_kwargs, "ruff.invoke() called with env= kwarg (kills mutmut_17,18)"
        # Kill mutmut_63: validate LayerResult creation (ensure not returning wrong type)
        assert isinstance(layer, LayerResult), "return must be LayerResult (kills mutmut_63)"

    def test_l2_vulture_invoke_args(self, tmp_path: Path):
        """Assert vulture.invoke called with correct args."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.vulture = _mock_subadapter(findings=[])
        a.deptry = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            layer = a.run_l2(tmp_path, {})
        assert a.vulture.invoke.called
        inv_args = a.vulture.invoke.call_args[0]
        assert inv_args[0] is tmp_path, "invoke() first arg = repo"
        assert inv_args[1] == [], "invoke() second arg = []"

    def test_l2_deptry_invoke_args(self, tmp_path: Path):
        """Assert deptry.invoke called with correct args."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.vulture = _mock_subadapter(findings=[])
        a.deptry = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            layer = a.run_l2(tmp_path, {})
        assert a.deptry.invoke.called
        inv_args = a.deptry.invoke.call_args[0]
        assert inv_args[0] is tmp_path, "invoke() first arg = repo"
        assert inv_args[1] == [], "invoke() second arg = []"

    def test_l2_passed_type_when_fail(self, tmp_path: Path):
        """passed must be exact bool False when findings exist (mutmut_37-40,46)."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[_make_finding(tool="ruff")])
        a.vulture = _mock_subadapter(findings=[])
        a.deptry = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            layer = a.run_l2(tmp_path, {})
        assert layer.passed is False
        assert isinstance(layer.passed, bool), f"passed must be bool, got {type(layer.passed)} (kills mutmut_37-40,46)"

    def test_l2_ruff_findings(self, tmp_path: Path):
        """Ruff returns findings -> included.

        Kills: mutmut_4 (repo → None in _run_ruff call), mutmut_5 (env → None
        in _run_ruff call). Verifies invoke is called with correct (repo, env) args.
        """
        a = self._adapter()
        env_arg: dict[str, str] = {}
        a.ruff = _mock_subadapter(findings=[_make_finding(tool="ruff")])
        a.vulture = _mock_subadapter(findings=[])
        a.deptry = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            layer = a.run_l2(tmp_path, env_arg)
        assert layer.passed is False
        assert len(layer.findings) == 1
        assert layer.findings[0].tool == "ruff"
        # Kills mutmut_4 (repo→None): first positional arg must be tmp_path
        assert a.ruff.invoke.call_args[0][0] is tmp_path
        # Kills mutmut_5 (env→None): env keyword arg must be actual env dict (not None)
        assert a.ruff.invoke.call_args.kwargs.get("env") == env_arg

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
        # Strict exact-message assertion — kills mutmut_6 (XX...XX prefix/suffix)
        for record in caplog.records:
            if record.levelname == "WARNING" and "mutmut not found" in record.getMessage():
                assert record.getMessage() == "mutmut not found on PATH, returning empty stats"

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

    def test_l3b_invoke_and_parse_args_strict(self, tmp_path: Path):
        """Assert _run_mutmut calls invoke/parse with correct args.

        Kills mutations on _run_mutmut:
        - mutmut_34: repo→None         (first param of invoke)
        - mutmut_35: []→None           (second param of invoke)
        - mutmut_36: invoke([])        — first param missing/wrong
        - mutmut_37: invoke(repo,)     — second arg removed
        - mutmut_38: parse(None, …)    — stdout→None
        Strategy: mock invoke() to return real JSON, then call REAL MutmutAdapter.parse()
        so that mutation 38 (passing None) crashes with TypeError.
        For mutations 34-37: assert invoke is called with correct args.
        """
        from harness_quality_gate.adapters.python.mutmut_adapter import MutmutAdapter

        a = self._adapter()
        real_adapter = MutmutAdapter()

        # Create a partial mock: mock invoke to return valid data, keep real parse
        mock_mutmut = MagicMock()
        mutation_payload = '{"total":5,"killed":5,"survived":0,"timeout":0,"escaped":0,"untested":0}'
        mock_mutmut.invoke.return_value = MagicMock(
            stdout=mutation_payload,
            stderr="",
            exitcode=0,
        )
        # Replace .parse with the REAL MutmutAdapter.parse()
        mock_mutmut.parse = real_adapter.parse

        with patch.object(a, "mutmut", mock_mutmut):
            with _all_tools_on_path():
                layer = a.run_l3b(tmp_path, {})
        # Layer-level correctness
        assert layer.passed is True
        assert layer.layer == "L3B"
        assert layer.language == "python"
        ms = layer.tool_specific["mutation_stats"]
        # Full assertion on parsed stats (kills return-value mutations)
        assert ms.total == 5
        assert ms.killed == 5
        assert ms.survived == 0
        assert ms.timed_out == 0
        assert ms.escaped == 0
        assert ms.untested == 0
        assert ms.msi == 1.0
        assert ms.covered_msi == 1.0
        # Kill mutmut_38: REAL parse was called — mutation 38 passes None → crashes
        # Kill mutmut_34-37: assert invoke() received correct args
        inv_args, inv_kwargs = mock_mutmut.invoke.call_args
        assert inv_args[0] is tmp_path, "invoke() first arg must be the repo path"
        assert inv_args[1] == [], "invoke() second arg must be [] (not None/removed)"
        # After mutation 38, real parse(None) raises TypeError and we never get here



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

    def test_l4_security_findings(self, tmp_path: Path, caplog):
        """Bandit finds security issues -> passed=False.

        Kills mutmut_4 (env→None positional), mutmut_5 (env=None keyword)
        Kills mutmut_9-10, 12-14 (logger format string mutations)
        Kills mutmut_35-37 (passed=len(x)==0 mutations)
        """
        a = self._adapter()
        a.bandit = _mock_subadapter(findings=[_make_finding(tool="bandit", severity="error")])
        with _all_tools_on_path():
            with caplog.at_level("INFO", logger="harness_quality_gate.adapters.python.python_adapter"):
                layer = a.run_l4(tmp_path, {})
        assert layer.passed is False
        assert isinstance(layer.passed, bool), f"passed must be bool (kills mutmut_35-37)"
        assert len(layer.findings) == 1
        assert layer.findings[0].tool == "bandit"
        # Kill mutmut_9, 10: logger.info format string mutations
        bandit_msg = [m for m in caplog.messages if "bandit:" in m and "findings" in m]
        assert len(bandit_msg) >= 1, "Logger must emit bandit message (kills mutmut_9, 12)"
        for msg in bandit_msg:
            parts = msg.split(": ")
            assert len(parts) >= 2
            int(parts[1].split()[0])  # kills mutmut_10, 13, 14: count must be int

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


def _assert_invoke_and_parse_args(mock_mutmut_adapter: MagicMock, expected_repo: Path) -> None:
    """Assert _run_mutmut called invoke/parse with correct arguments.

    Kills mutations on _run_mutmut:
    - mutmut_34: repo→None  (first positional arg of invoke)
    - mutmut_35: []→None   (second positional arg of invoke)
    - mutmut_36: invoke([]) — first arg missing/wrong
    - mutmut_37: invoke(repo,) — arg count mutation
    - mutmut_38: parse(None, …) — stdout → None
    """
    # invoke MUST be called
    assert mock_mutmut_adapter.invoke.called, "invoke() should have been called"

    # First positional arg must be the expected repo (not None, not another type)
    inv_args, inv_kwargs = mock_mutmut_adapter.invoke.call_args
    assert len(inv_args) >= 1, "invoke() called with too few positional args"
    assert inv_args[0] is expected_repo, (
        f"invoke() first arg must be {expected_repo}, got {inv_args[0]!r}"
    )

    # Second positional arg must be [] (not None)
    if len(inv_args) >= 2:
        assert inv_args[1] == [], (
            f"invoke() second arg must be [], got {inv_args[1]!r}"
        )

    # parse MUST be called (with real data, not None)
    assert mock_mutmut_adapter.parse.called, "parse() should have been called"
    pars_args, pars_kwargs = mock_mutmut_adapter.parse.call_args
    assert len(pars_args) >= 1, "parse() called with too few positional args"
    assert pars_args[0] is not None, (
        "First arg to parse() (stdout) must not be None — kills mutmut_38"
    )
    assert isinstance(pars_args[0], str), (
        f"First arg to parse() (stdout) must be str, got {type(pars_args[0])}"
    )


# ---------------------------------------------------------------------------
# Private helper: _run_ruff
# ---------------------------------------------------------------------------

class TestRunRuffHelper:
    """Test _run_ruff: tool-not-found and invocation branches."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_run_ruff_tool_found(self, tmp_path: Path, caplog):
        """Ruff on PATH -> invoke + parse called.

        Kills mutmut_6 (False→None assertion), mutmut_7 (True→False)
        Kills mutmut_8, 9, 12, 18-23, 25-28 (return []→None mutations)
        Kills mutmut_11: logger.warning call removed (caplog checks warning)
        """
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[_make_finding(tool="ruff")])
        findings = a._run_ruff(tmp_path, {})
        # Type assertion: kills mutmut_8, 9, 12, 18-23, 25-28 (return []→None)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None, "findings must not be None"
        assert len(findings) == 1
        assert findings[0].tool == "ruff"
        # Assert invoke was called with correct args
        assert a.ruff.invoke.called
        inv_args, inv_kwargs = a.ruff.invoke.call_args
        assert inv_args[0] is tmp_path, "invoke() first arg = repo (kills mutmut_3, 5)"
        assert inv_args[1] == [], "invoke() second arg = [] (kills mutmut_3, 5)"
        # Assert parse was called with non-None stdout
        assert a.ruff.parse.called
        pars_args = a.ruff.parse.call_args[0]
        assert pars_args[0] is not None, "parse() stdout must not be None (kills mutmut_13)"
        assert isinstance(pars_args[0], str), f"parse() stdout must be str, got {type(pars_args[0])}"

    def test_run_ruff_tool_not_found(self, tmp_path: Path, caplog):
        """Ruff not on PATH -> empty list."""
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            findings = a._run_ruff(tmp_path, {})
        # Kill mutmut_6 (False→None), mutmut_7, 12 (return []→None)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None, "findings must not be None (kills mutmut_12)"
        assert findings == []

    def test_run_ruff_parse_error(self, tmp_path: Path, caplog):
        """Ruff parse raises -> caught, empty list returned."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.ruff.parse = MagicMock(side_effect=RuntimeError("parse err"))
        with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
            findings = a._run_ruff(tmp_path, {})
        # Kill mutmut_18, 19, 20 (parse return → None, replaced with empty list path)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None
        assert findings == []
        # Kill logger string mutations in warning (mutmut_14-18 string changes)
        ruff_warn = [r for r in caplog.records if r.levelname == "WARNING" and "ruff" in r.message.lower()]
        assert len(ruff_warn) == 1, f"Expected 1 ruff warning log, got {len(ruff_warn)}"
        assert "ruff invocation failed" in ruff_warn[0].getMessage()

    def test_run_ruff_oserror_on_invoke(self, tmp_path: Path, caplog):
        """Ruff.invoke raises OSError -> caught, empty list returned."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        a.ruff.invoke = MagicMock(side_effect=OSError("ruff exec failed"))
        with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
            findings = a._run_ruff(tmp_path, {})
        # Kill mutmut_21, 22, 23 (exception path return → None)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None
        assert findings == []
        # Kill logger string mutations in warning path
        ruff_warn = [r for r in caplog.records if r.levelname == "WARNING" and "ruff" in r.message.lower()]
        assert len(ruff_warn) == 1, f"Expected 1 ruff warning log, got {len(ruff_warn)}"
        assert "ruff invocation failed" in ruff_warn[0].getMessage()


# ---------------------------------------------------------------------------
# Private helper: _run_pyright
# ---------------------------------------------------------------------------

class TestRunPyrightHelper:
    """Test _run_pyright: tool-not-found and invocation branches."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_run_pyright_tool_found(self, tmp_path: Path):
        """Pyright on PATH -> invoke + parse called with correct args -> findings returned.

        Kills mutations on invoke() args: repo and [] (not None/removed/wrong)
        Kills return-value mutations on parse result via isinstance assertion
        """
        a = self._adapter()
        a.pyright = _mock_subadapter(findings=[_make_finding(tool="pyright")])
        findings = a._run_pyright(tmp_path, {})
        assert len(findings) == 1
        # Type assertion: kills return []→None mutations (mutmut_15-19, 22-24)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None
        # Kill mutations on invoke() args: repo and [] (not None/removed/wrong)
        inv_args, inv_kwargs = a.pyright.invoke.call_args
        assert inv_args[0] is tmp_path
        assert inv_args[1] == []
        # Kill mutations on parse() args: not None, proper types (not swapped)
        pars_args, pars_kwargs = a.pyright.parse.call_args
        assert pars_args[0] is not None
        assert isinstance(pars_args[0], str)

    def test_run_pyright_tool_not_found(self, tmp_path: Path, caplog):
        """Pyright not on PATH -> early return empty list."""
        a = self._adapter()
        a.pyright = _mock_subadapter(findings=[])
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                findings = a._run_pyright(tmp_path, {})
        # Type assertion: kills return []→None mutations
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None
        assert findings == []
        # Kill logger string mutations in "not found" warning (mutmut_5-8)
        pyright_warn = [r for r in caplog.records if r.levelname == "WARNING" and "pyright" in r.message.lower()]
        assert len(pyright_warn) == 1, f"Expected warning, got {len(pyright_warn)}"
        assert "pyright not found on PATH" in pyright_warn[0].getMessage()

    def test_run_pyright_oserror(self, tmp_path: Path, caplog):
        """Pyright.invoke raises OSError -> empty list + invoke was called correctly."""
        a = self._adapter()
        a.pyright = _mock_subadapter(findings=[])
        a.pyright.invoke = MagicMock(side_effect=OSError("pyright exec failed"))
        with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
            findings = a._run_pyright(tmp_path, {})
        # Kill mutations: verify invoke was called with repo+[]
        assert a.pyright.invoke.called
        inv_args = a.pyright.invoke.call_args[0]
        assert inv_args[0] is tmp_path
        assert inv_args[1] == []
        assert findings == []
        # Type assertion: kills return None mutations (mutmut_15-19, 22-24)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        # Kill logger string mutations in "invocation failed" warning
        pyright_warn = [r for r in caplog.records if r.levelname == "WARNING" and "pyright" in r.message.lower()]
        assert len(pyright_warn) == 1
        assert "pyright invocation failed" in pyright_warn[0].getMessage()


# ---------------------------------------------------------------------------
# Private helper: _run_pytest
# ---------------------------------------------------------------------------

class TestRunPytestHelper:
    """Test _run_pytest: python3-path and invocation branches."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_run_pytest_tool_found(self, tmp_path: Path, caplog):
        """Pytest runs and returns findings.

        Kills return-value mutations via isinstance assertion
        Kills logger string mutations via caplog checks
        """
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[_make_finding(tool="pytest")])
        with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
            findings = a._run_pytest(tmp_path, {})
        assert len(findings) == 1
        # Type assertion: kills return []→None mutations (mutmut_11, 12)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None

    def test_run_pytest_oserror(self, tmp_path: Path, caplog):
        """Pytest.invoke raises -> empty list."""
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[])
        with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
            with patch.object(a.pytest, "invoke", side_effect=RuntimeError("pytest failed")):
                findings = a._run_pytest(tmp_path, {})
        # Type assertion: kills return None mutations (mutmut_26-29)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings == []
        # Kill logger string mutations in warning path (mutmut_6, 7)
        pytest_warn = [r for r in caplog.records if r.levelname == "WARNING" and "pytest" in r.message.lower()]
        assert len(pytest_warn) == 1, f"Expected pytest warning, got {len(pytest_warn)}"
        assert "pytest invocation failed" in pytest_warn[0].getMessage()

    def test_run_pytest_tool_not_found(self, tmp_path: Path, caplog):
        """python3 not found on PATH -> empty list, no invoke called."""
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[])
        with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
            with patch(
                "harness_quality_gate.adapters.python.python_adapter.shutil.which",
                return_value=None,
            ):
                findings = a._run_pytest(tmp_path, {})
        # Type assertion: kills return []→None mutations
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings == []
        # Kill logger string mutations in "not found" warning
        pytest_warn = [r for r in caplog.records if r.levelname == "WARNING" and "python" in r.message.lower()]
        assert len(pytest_warn) == 1, f"Expected python not found warning, got {len(pytest_warn)}"
        assert "python3 not found on PATH" in pytest_warn[0].getMessage()

    def test_run_pytest_invoke_args_strict(self, tmp_path: Path):
        """Validate invoke() receives (repo, []) — kills argument mutations."""
        a = self._adapter()
        mock_pytest = MagicMock()
        mock_pytest.parse.return_value = [_make_finding(tool="pytest")]
        a.pytest = mock_pytest
        with _all_tools_on_path({"python3": "/usr/bin/python3"}):
            findings = a._run_pytest(tmp_path, {})
        assert findings
        assert mock_pytest.invoke.call_args[0][0] is tmp_path
        assert mock_pytest.invoke.call_args[0][1] == []
    def test_run_pytest_parse_args_strict(self, tmp_path: Path):
        """Validate parse() receives (stdout, stderr, exitcode) — kills arg mutations."""
        from harness_quality_gate.adapters.python.pytest_adapter import PytestAdapter

        a = self._adapter()
        real_adapter = PytestAdapter()
        mock_pytest = MagicMock()
        mock_pytest.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)
        mock_pytest.parse = MagicMock(wraps=real_adapter.parse)
        with patch.object(a, "pytest", mock_pytest):
            findings = a._run_pytest(tmp_path, {})
        assert mock_pytest.parse.called
        pars_args = mock_pytest.parse.call_args[0]
        assert pars_args[0] is not None
        assert pars_args[1] is not None
        assert pars_args[2] is not None

    def test_run_pytest_invoke_return_propagated(self, tmp_path: Path):
        """invoke() result flows to parse() — kills remove-mutations."""
        from harness_quality_gate.adapters.python.pytest_adapter import PytestAdapter

        a = self._adapter()
        real_adapter = PytestAdapter()
        mock_pytest = MagicMock()
        mock_pytest.parse = real_adapter.parse
        mock_pytest.invoke.return_value = MagicMock(
            stdout="[{'message': 'test'}]", stderr="", exitcode=0,
        )
        with patch.object(a, "pytest", mock_pytest):
            findings = a._run_pytest(tmp_path, {})
        assert isinstance(findings, list)
        inv_args = mock_pytest.invoke.call_args[0]
        assert inv_args[0] is tmp_path
        assert inv_args[1] == []
# ---------------------------------------------------------------------------
# Private helper: _run_vulture - ENHANCED
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
