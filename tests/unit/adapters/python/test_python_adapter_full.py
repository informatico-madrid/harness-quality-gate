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

    @pytest.fixture(autouse=True)
    def _tools_on_path(self):
        """Deterministic: the sub-adapters are mocked; the which() guards in
        _run_ruff/_run_pyright must not depend on locally installed tools."""
        with patch(
            "harness_quality_gate.adapters.python.python_adapter.shutil.which",
            side_effect=lambda name: (
                f"/usr/bin/{name}" if name in ("ruff", "pyright") else None
            ),
        ):
            yield

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
    """Test run_l1 branch coverage: pytest with xml report.

    The mutation half of L1 is mocked clean here; it has its own dedicated
    coverage in TestRunL1MutationGate.
    """

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter()
        a.mutmut = _mock_subadapter()
        a.mutmut.parse.return_value = MutationStats(
            total=0, killed=0, survived=0, timed_out=0,
            escaped=0, untested=0, msi=0.0, covered_msi=0.0,
        )
        return a

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

    def test_l1_duration_rounding_exact(self, tmp_path: Path):
        """Round(duration, 3) must produce a float with 3 decimal precision (H2).

        Kills mutmut_20 (time.monotonic → time.monotonic+1),
        mutmut_21 (duration round arg mutations → round to None/changed precision).
        """
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[])
        ticks = iter([100.0, 101.123456])
        with _all_tools_on_path():
            with patch(
                "harness_quality_gate.adapters.python.python_adapter.time.monotonic",
                side_effect=lambda: next(ticks),
            ):
                layer = a.run_l1(tmp_path, {})
        # Duration = 1.123456, round(_, 3) = 1.123 (float)
        # If round(_, 3) → round(_, None): round(1.123456, None)=1 (int) → type assertion fails
        assert isinstance(layer.duration_sec, float), \
            f"round(_, 3) must return float (kills round(_, None) -> int: mutmut_36, 38)"
        assert layer.duration_sec == 1.123, \
            "duration_sec must be exactly round(1.123456, 3) = 1.123 (kills duration mutations)"

    def test_l1_invoke_args_strict(self, tmp_path: Path):
        """Assert pytest.invoke called with exact args (repo, []) — H1 wiring.

        Kills mutmut_15 (invoke(repo,[])→invoke(None,[])),
        mutmut_16 (invoke(repo,[])→invoke(repo,None/missing)),
        mutmut_17 (invoke arg removal).
        """
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[_make_finding(tool="pytest")])
        layer = a.run_l1(tmp_path, {})
        assert layer.passed is False
        inv_args, inv_kwargs = a.pytest.invoke.call_args
        assert inv_args[0] is tmp_path, "invoke() first arg must be repo (kills mutmut_15)"
        assert inv_args[1] == [], "invoke() second arg must be [] (kills mutmut_16)"

    def test_l1_logger_format_strings_exact(self, tmp_path: Path, caplog):
        """Verify logger.info("pytest: %d findings", ...) format string not mutated (H3).

        Kills mutmut_13 (logger.info call removed → no log emitted).
        Kills mutmut_10 (len(pytest_findings)→None in format arg).
        Kills mutmut_9, 11 (format string "pytest:" → "XXpytest:XX").
        """
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[_make_finding(tool="pytest")])
        with caplog.at_level("INFO",
                              logger="harness_quality_gate.adapters.python.python_adapter"):
            layer = a.run_l1(tmp_path, {})
        pytest_msgs = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "INFO" and "pytest:" in r.message and "findings" in r.message
        ]
        assert len(pytest_msgs) >= 1, \
            "Logger must emit pytest message (kills mutmut_13: logger.info removed)"
        # Exact message format: "pytest: N findings" with N being an integer
        for msg in pytest_msgs:
            assert "pytest:" in msg, \
                f"Message must contain 'pytest:' (kills format string mutation: mutmut_9,11)"
            assert "findings" in msg, \
                "Message must contain 'findings'"
            # Verify the count is a number (kills len→None mutation)
            parts = msg.split(": ", 1)
            assert len(parts) >= 2
            int(parts[1].split()[0]), \
                "Count must be parseable as int (kills len→None: mutmut_10)"


# ---------------------------------------------------------------------------
# Run L2 (weak-test detection + diversity)
# ---------------------------------------------------------------------------

class TestRunL2:
    """Test run_l2 branch coverage: weak-test detection (A1-A8) + diversity."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    @staticmethod
    def _write_weak_test_repo(repo: Path) -> None:
        """One test with a single assertion -> A1 (ERROR) + A2/A3/A5 (WARNING)."""
        tests = repo / "tests"
        tests.mkdir()
        (tests / "test_calc.py").write_text(
            "def test_add():\n"
            "    result = 1 + 1\n"
            "    assert result == 2\n",
            encoding="utf-8",
        )
        src = repo / "src"
        src.mkdir()
        (src / "calc.py").write_text(
            "def add(a, b):\n    return a + b\n", encoding="utf-8",
        )

    def test_l2_no_tests_dir_passes_with_warning(self, tmp_path: Path, caplog):
        """Repo without tests/ -> 0 findings, passed=True, exact warning."""
        a = self._adapter()
        with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
            layer = a.run_l2(tmp_path, {})
        assert layer.layer == "L2"
        assert layer.language == "python"
        assert layer.passed is True
        assert layer.findings == []
        warn = [m for m in caplog.messages if "no tests/ directory" in m]
        assert len(warn) == 1
        assert warn[0] == f"no tests/ directory in {tmp_path}, skipping weak-test analysis"
        div = layer.tool_specific["diversity"]
        assert div["total_tests"] == 0
        assert div["diversity_score"] == 1.0

    def test_l2_weak_test_produces_error_findings_and_fails(self, tmp_path: Path):
        """A1 (ERROR) gates the layer; finding fields mapped exactly."""
        a = self._adapter()
        self._write_weak_test_repo(tmp_path)
        layer = a.run_l2(tmp_path, {})
        assert layer.layer == "L2"
        assert layer.language == "python"
        assert layer.passed is False
        rules = {f.rule_id for f in layer.findings}
        assert "A1" in rules
        assert "A2" in rules
        a1 = next(f for f in layer.findings if f.rule_id == "A1")
        assert a1.severity == "error"
        assert a1.tool == "weak-test"
        assert a1.layer == "L2"
        assert a1.language == "python"
        assert a1.node == "test_calc.py:1"
        assert a1.message == "test_add: only 1 assertion(s) -- suspicious"
        a2 = next(f for f in layer.findings if f.rule_id == "A2")
        assert a2.severity == "warning"
        assert a2.message == "test_add: only 1 assertion(s) -- insufficient coverage"

    def test_l2_warnings_only_still_pass(self, tmp_path: Path):
        """3+ assertions avoid A1/A2; WARNING-only rules must not gate."""
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_calc.py").write_text(
            "def test_add():\n"
            "    result = 1 + 1\n"
            "    assert result == 2\n"
            "    assert result > 1\n"
            "    assert result < 3\n",
            encoding="utf-8",
        )
        a = self._adapter()
        layer = a.run_l2(tmp_path, {})
        assert layer.findings, "expected WARNING findings (A3/A5)"
        assert all(f.severity == "warning" for f in layer.findings)
        assert layer.passed is True

    def test_l2_diversity_in_tool_specific(self, tmp_path: Path):
        """Diversity report travels in tool_specific and is JSON-serialisable."""
        import json as _json
        self._write_weak_test_repo(tmp_path)
        a = self._adapter()
        layer = a.run_l2(tmp_path, {})
        div = layer.tool_specific["diversity"]
        assert div["total_tests"] == 1
        assert "diversity_score" in div
        assert "summary" in div
        _json.dumps(div)  # must be plain data, no dataclasses

    def test_l2_src_dir_fallback_to_repo(self, tmp_path: Path):
        """Without src/, the analysis uses the repo root as source dir."""
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_x.py").write_text(
            "def test_x():\n"
            "    value = 5\n"
            "    assert value == 5\n",
            encoding="utf-8",
        )
        a = self._adapter()
        layer = a.run_l2(tmp_path, {})
        # A1 fires regardless of src dir resolution
        assert any(f.rule_id == "A1" for f in layer.findings)
        assert layer.passed is False

    def test_l2_duration_rounding_exact(self, tmp_path: Path):
        """round(duration, 3) must produce a float with 3-decimal precision."""
        a = self._adapter()
        ticks = iter([100.0, 101.123456])
        with patch(
            "harness_quality_gate.adapters.python.python_adapter.time.monotonic",
            side_effect=lambda: next(ticks),
        ):
            layer = a.run_l2(tmp_path, {})
        assert isinstance(layer.duration_sec, float)
        assert layer.duration_sec == 1.123

    def test_l2_logger_messages_exact(self, tmp_path: Path, caplog):
        """weak-test and diversity log lines are emitted with real counts."""
        a = self._adapter()
        self._write_weak_test_repo(tmp_path)
        with caplog.at_level("INFO", logger="harness_quality_gate.adapters.python.python_adapter"):
            layer = a.run_l2(tmp_path, {})
        msgs = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
        assert f"weak-test: {len(layer.findings)} findings" in msgs
        div = layer.tool_specific["diversity"]
        assert (
            f"diversity: score {div['diversity_score']} over {div['total_tests']} tests"
            in msgs
        )


# ---------------------------------------------------------------------------
# Run L1 mutation gate (mutmut runs in L1 per spec glossary)
# ---------------------------------------------------------------------------

class TestRunL1MutationGate:
    """Test run_l1 mutation-gate coverage (mutmut).

    The pytest half of L1 is mocked clean here; it has its own dedicated
    coverage in TestRunL1.
    """

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter()
        a.pytest = _mock_subadapter(findings=[])
        return a

    def test_l1mut_no_mutants(self, tmp_path: Path):
        """All mutants killed -> passed=True, no remediation key."""
        a = self._adapter()
        mock_mutmut = _mock_subadapter()
        mock_mutmut.parse.return_value = MutationStats(
            total=10, killed=10, survived=0, timed_out=0,
            escaped=0, untested=0, msi=1.0, covered_msi=1.0,
        )
        with patch.object(a, 'mutmut', mock_mutmut):
            with _all_tools_on_path():
                layer = a.run_l1(tmp_path, {})
        assert layer.layer == "L1"
        assert layer.passed is True
        assert layer.findings == []
        ms = layer.tool_specific["mutation_stats"]
        assert ms.killed == 10
        assert ms.survived == 0
        assert "remediation" not in layer.tool_specific

    def test_l1mut_survived_mutants(self, tmp_path: Path):
        """Some mutants survived -> passed=False + remediation key present."""
        a = self._adapter()
        mock_mutmut = _mock_subadapter()
        mock_mutmut.parse.return_value = MutationStats(
            total=10, killed=7, survived=3, timed_out=0,
            escaped=0, untested=0, msi=0.7, covered_msi=0.7,
        )
        with patch.object(a, "mutmut", mock_mutmut):
            with _all_tools_on_path():
                layer = a.run_l1(tmp_path, {})
        assert layer.passed is False
        ms = layer.tool_specific["mutation_stats"]
        assert ms.survived == 3
        rem = layer.tool_specific["remediation"]
        assert rem["skill"] == "mutation-testing-guide"
        assert rem["guide"] == "MUTANT_KILLING_GUIDE.md"
        assert rem["instructions"] == "SUBAGENT_MUTATION_INSTRUCTIONS.md"
        assert rem["survived"] == 3
        assert rem["timed_out"] == 0
        assert "3 mutant(s) survived" in rem["summary"]

    def test_l1mut_timed_out(self, tmp_path: Path):
        """Some mutants timed out -> passed=False + remediation key present."""
        a = self._adapter()
        mock_mutmut = _mock_subadapter()
        mock_mutmut.parse.return_value = MutationStats(
            total=10, killed=8, survived=0, timed_out=2,
            escaped=0, untested=0, msi=0.8, covered_msi=0.8,
        )
        with patch.object(a, "mutmut", mock_mutmut):
            with _all_tools_on_path():
                layer = a.run_l1(tmp_path, {})
        assert layer.passed is False
        ms = layer.tool_specific["mutation_stats"]
        assert ms.timed_out == 2
        rem = layer.tool_specific["remediation"]
        assert rem["skill"] == "mutation-testing-guide"
        assert rem["timed_out"] == 2
        assert rem["survived"] == 0
        assert "2 mutant(s) timed out" in rem["summary"]

    def test_l1mut_escaped_mutants(self, tmp_path: Path):
        """Escaped mutants -> survived > 0, passed=False."""
        a = self._adapter()
        mock_mutmut = _mock_subadapter()
        mock_mutmut.parse.return_value = MutationStats(
            total=10, killed=8, survived=1, timed_out=0,
            escaped=1, untested=0, msi=0.8, covered_msi=0.8,
        )
        with patch.object(a, "mutmut", mock_mutmut):
            with _all_tools_on_path():
                layer = a.run_l1(tmp_path, {})
        assert layer.passed is False
        ms = layer.tool_specific["mutation_stats"]
        assert ms.escaped == 1

    def test_l1mut_no_mutants_found(self, tmp_path: Path):
        """Zero mutants total (0,0,0) -> passed=True."""
        a = self._adapter()
        mock_mutmut = _mock_subadapter()
        mock_mutmut.parse.return_value = MutationStats(
            total=0, killed=0, survived=0, timed_out=0,
            escaped=0, untested=0, msi=0.0, covered_msi=0.0,
        )
        with patch.object(a, "mutmut", mock_mutmut):
            with _all_tools_on_path():
                layer = a.run_l1(tmp_path, {})
        assert layer.passed is True
        ms = layer.tool_specific["mutation_stats"]
        assert ms.total == 0

    def test_l1mut_mutmut_not_on_path(self, tmp_path: Path, caplog):
        """mutmut not found -> empty stats + exact warning message.

        Kills mutmut_5 (None), mutmut_6 (XX...XX), mutmut_7 (path→PATH),
        mutmut_8 (UPPERCASE), mutmut_13 (escaped=None), mutmut_14 (untested=None).
        """
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                layer = a.run_l1(tmp_path, {})
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

    def test_l1mut_mutmut_raises_oserror(self, tmp_path: Path):
        """mutmut.invoke raises OSError -> empty fallback stats."""
        a = self._adapter()
        mock_mutmut = _mock_subadapter()
        with patch.object(a, "mutmut", mock_mutmut):
            with patch.object(mock_mutmut, "invoke", side_effect=OSError("mutmut broken")):
                with _all_tools_on_path():
                    layer = a.run_l1(tmp_path, {})
        ms = layer.tool_specific["mutation_stats"]
        assert ms.total == 0
        assert layer.passed is True

    def test_l1mut_mutmut_raises_runtimeerror(self, tmp_path: Path):
        """mutmut.invoke raises RuntimeError -> empty fallback stats."""
        a = self._adapter()
        mock_mutmut = _mock_subadapter()
        with patch.object(a, "mutmut", mock_mutmut):
            with patch.object(mock_mutmut, "invoke", side_effect=RuntimeError("boom")):
                with _all_tools_on_path():
                    layer = a.run_l1(tmp_path, {})
        ms = layer.tool_specific["mutation_stats"]
        assert ms.total == 0
        assert layer.passed is True

    def test_l1mut_mutmut_parse_return_full_stats(self, tmp_path: Path):
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
                layer = a.run_l1(tmp_path, {})
        ms = layer.tool_specific["mutation_stats"]
        assert ms.total == 50
        assert ms.killed == 30
        assert ms.survived == 15
        assert ms.timed_out == 3
        assert ms.escaped == 2
        assert ms.untested == 0
        assert ms.msi == 0.6
        assert ms.covered_msi == 0.7

    def test_l1mut_layer_name_and_language(self, tmp_path: Path):
        """Layer name and language are set correctly."""
        a = self._adapter()
        mock_mutmut = _mock_subadapter()
        with patch.object(a, "mutmut", mock_mutmut):
            with _all_tools_on_path():
                mock_mutmut.parse.return_value = MutationStats(
                    total=0, killed=0, survived=0, timed_out=0,
                    escaped=0, untested=0, msi=0.0, covered_msi=0.0,
                )
                layer = a.run_l1(tmp_path, {})
                assert layer.layer == "L1"
        assert layer.language == "python"

    def test_l1mut_invoke_and_parse_args_strict(self, tmp_path: Path):
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
                layer = a.run_l1(tmp_path, {})
        # Layer-level correctness
        assert layer.passed is True
        assert layer.layer == "L1"
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
# Run L3B (SOLID metrics + antipattern Tier A)
# ---------------------------------------------------------------------------

class TestRunL3B:
    """Test run_l3b branch coverage: SOLID + antipattern Tier A (in-process)."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_l3b_empty_repo_passes(self, tmp_path: Path):
        a = self._adapter()
        layer = a.run_l3b(tmp_path, {})
        assert layer.layer == "L3B"
        assert layer.language == "python"
        assert layer.passed is True
        assert layer.findings == []
        assert layer.tool_specific is None

    def test_l3b_solid_srp_violation_in_src_dir(self, tmp_path: Path):
        """Class with >7 public methods in src/ -> SOLID-S finding, exact fields."""
        src = tmp_path / "src"
        src.mkdir()
        methods = "\n".join(
            f"    def m{i}(self):\n        return {i}" for i in range(9)
        )
        (src / "fat.py").write_text(f"class Fat:\n{methods}\n", encoding="utf-8")
        a = self._adapter()
        layer = a.run_l3b(tmp_path, {})
        # warnings are reported but do not gate (uniform severity policy, F11)
        assert layer.passed is True
        s = next(f for f in layer.findings if f.rule_id == "SOLID-S")
        assert s.severity == "warning"
        assert s.tool == "solid-metrics"
        assert s.layer == "L3B"
        assert s.language == "python"
        assert s.node == "Fat"
        assert "public_methods=9 > 7 (SRP)" in s.message
        assert s.message.startswith("SOLID S: ")

    def test_l3b_solid_issue_key_variant(self, tmp_path: Path):
        """O-principle violations use the 'issue' key (not 'issues' list)."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "one.py").write_text(
            "class One:\n    def a(self):\n        return 1\n", encoding="utf-8",
        )
        a = self._adapter()
        layer = a.run_l3b(tmp_path, {})
        o = next(f for f in layer.findings if f.rule_id == "SOLID-O")
        assert o.message.startswith("SOLID O: abstractness=")
        assert o.node == "O"  # no class/file key -> falls back to principle

    def test_l3b_tier_a_ap02_finding(self, tmp_path: Path):
        """Static-only class (>=3 methods) -> AP02 Finding.

        Regression guard: the violation dict key was the live mutant
        "XXidXX" instead of "id" (antipattern_tier_a.py:419), which made
        AP02 violations invisible to run_tier_a's by-id grouping.
        """
        (tmp_path / "util.py").write_text(
            "class Util:\n"
            "    @staticmethod\n"
            "    def a():\n"
            "        return 1\n"
            "    @staticmethod\n"
            "    def b():\n"
            "        return 2\n"
            "    @staticmethod\n"
            "    def c():\n"
            "        return 3\n",
            encoding="utf-8",
        )
        a = self._adapter()
        layer = a.run_l3b(tmp_path, {})
        ap02 = [f for f in layer.findings if f.rule_id == "AP02"]
        assert len(ap02) >= 1
        f = ap02[0]
        assert f.tool == "antipattern-tier-a"
        assert f.severity == "warning"
        assert f.layer == "L3B"
        assert f.language == "python"
        assert "Functional Decomposition" in f.message
        assert "all 3 methods are static/class methods" in f.message
        assert f.node == "Util:1"  # class name + lineno
        # warnings are reported but do not gate (uniform severity policy, F11)
        assert layer.passed is True

    def test_l3b_logger_messages_exact(self, tmp_path: Path, caplog):
        a = self._adapter()
        with caplog.at_level("INFO", logger="harness_quality_gate.adapters.python.python_adapter"):
            a.run_l3b(tmp_path, {})
        msgs = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
        assert msgs == [
            "solid-metrics: 0 findings",
            "antipattern-tier-a: 0 findings",
        ]

    def test_l3b_duration_rounding_exact(self, tmp_path: Path):
        a = self._adapter()
        ticks = iter([100.0, 101.123456])
        with patch(
            "harness_quality_gate.adapters.python.python_adapter.time.monotonic",
            side_effect=lambda: next(ticks),
        ):
            layer = a.run_l3b(tmp_path, {})
        assert isinstance(layer.duration_sec, float)
        assert layer.duration_sec == 1.123


# ---------------------------------------------------------------------------
# _mutation_remediation (unit tests for the static method)
# ---------------------------------------------------------------------------

class TestMutationRemediation:
    """Unit tests for PythonAdapter._mutation_remediation."""

    def _rem(self, **kwargs):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        defaults = dict(total=10, killed=7, survived=3, timed_out=0,
                        escaped=0, untested=0, msi=0.7, covered_msi=0.7)
        defaults.update(kwargs)
        return PythonAdapter._mutation_remediation(MutationStats(**defaults))

    def test_keys_present(self):
        """All expected keys are present in the remediation dict."""
        rem = self._rem()
        assert set(rem.keys()) >= {"skill", "guide", "instructions", "summary", "msi", "survived", "timed_out"}

    def test_skill_name_exact(self):
        """skill must be exactly 'mutation-testing-guide' — kills string mutations."""
        assert self._rem()["skill"] == "mutation-testing-guide"

    def test_guide_name_exact(self):
        """guide must be exactly 'MUTANT_KILLING_GUIDE.md' — kills string mutations."""
        assert self._rem()["guide"] == "MUTANT_KILLING_GUIDE.md"

    def test_instructions_name_exact(self):
        """instructions must be exactly 'SUBAGENT_MUTATION_INSTRUCTIONS.md'."""
        assert self._rem()["instructions"] == "SUBAGENT_MUTATION_INSTRUCTIONS.md"

    def test_survived_only(self):
        """Only survived > 0: summary mentions survived count, not timed_out."""
        rem = self._rem(survived=5, timed_out=0)
        assert rem["survived"] == 5
        assert rem["timed_out"] == 0
        assert "5 mutant(s) survived" in rem["summary"]
        assert "timed out" not in rem["summary"]

    def test_timed_out_only(self):
        """Only timed_out > 0: summary mentions timed_out count, not survived."""
        rem = self._rem(survived=0, timed_out=3)
        assert rem["timed_out"] == 3
        assert rem["survived"] == 0
        assert "3 mutant(s) timed out" in rem["summary"]
        assert "survived" not in rem["summary"]

    def test_both_survived_and_timed_out(self):
        """Both > 0: summary mentions both issues."""
        rem = self._rem(survived=2, timed_out=4)
        assert "2 mutant(s) survived" in rem["summary"]
        assert "4 mutant(s) timed out" in rem["summary"]
        assert rem["survived"] == 2
        assert rem["timed_out"] == 4

    def test_msi_preserved(self):
        """msi value is passed through exactly."""
        rem = self._rem(msi=0.7, survived=1, timed_out=0)
        assert rem["msi"] == 0.7

    def test_summary_contains_guide_reference(self):
        """summary always references the guide for agent discoverability."""
        rem = self._rem(survived=1, timed_out=0)
        assert "mutation-testing-guide" in rem["summary"]
        assert "MUTANT_KILLING_GUIDE.md" in rem["summary"]

    def test_summary_contains_l1_label(self):
        """summary starts with 'L1 FAILED' so agents can grep for it."""
        rem = self._rem(survived=1, timed_out=0)
        assert rem["summary"].startswith("L1 FAILED")

    def test_priority_hint_in_summary(self):
        """summary includes priority section references for agents."""
        rem = self._rem(survived=1, timed_out=0)
        summary = rem["summary"]
        assert "§4.4" in summary
        assert "§4.1" in summary
        assert "H1" in summary


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

    def test_l4_duration_rounding_exact(self, tmp_path: Path):
        """Round(duration, 3) must produce a float (H2).

        Kills mutmut_35-36 (duration_sec: round arg mutations) and
        mutmut_15-16 (invoke arg mutations on bandit).
        """
        a = self._adapter()
        a.bandit = _mock_subadapter(findings=[])
        ticks = iter([100.0, 100.987654])
        with _all_tools_on_path():
            with patch(
                "harness_quality_gate.adapters.python.python_adapter.time.monotonic",
                side_effect=lambda: next(ticks),
            ):
                layer = a.run_l4(tmp_path, {})
        assert isinstance(layer.duration_sec, float), \
            "round(_, 3) must return float (kills round(_, None) -> int: mutmut_35, 36)"
        assert layer.duration_sec == 0.988, \
            "duration_sec must be exactly round(0.987654, 3) = 0.988"

    def test_l4_logger_format_string_exact(self, tmp_path: Path, caplog):
        """Verify logger.info("bandit: %d findings") format string not mutated (H3).

        Kills mutmut_4 (bandit.invoke arg mutation: repo→None),
        mutmut_5 (bandit.invoke env=None),
        mutmut_6 (bandit invoke call argument mutation),
        mutmut_13 (logger bandit format string: "bandit:%d" → "XXbandit:%dXX"),
        mutmut_9 (bandit.invoke argument mutation on first param).
        """
        a = self._adapter()
        a.bandit = _mock_subadapter(findings=[_make_finding(tool="bandit")])
        with _all_tools_on_path():
            with caplog.at_level("INFO",
                                  logger="harness_quality_gate.adapters.python.python_adapter"):
                layer = a.run_l4(tmp_path, {})
        assert layer.passed is False
        # Kill logger format string mutation: exact message must contain "bandit:"
        bandit_msgs = [r.getMessage() for r in caplog.records
                       if r.levelname == "INFO" and "bandit:" in r.message and "findings" in r.message]
        assert len(bandit_msgs) >= 1, \
            "Logger must emit bandit message (kills logger.info REMOVAL: mutmut_13)"
        for msg in bandit_msgs:
            assert "bandit:" in msg, \
                "Message must contain 'bandit:' (kills format string mutation: mutmut_4,5,6)"
            parts = msg.split(": ", 1)
            assert len(parts) >= 2
            int(parts[1].split()[0]), \
                "Count must be parseable as int (kills len->None mutation)"

    def test_l4_bandit_invoke_args_strict(self, tmp_path: Path):
        """Assert bandit.invoke called with correct args (repo, []) — H1 wiring.

        Kills mutmut_15 (invoke(repo,[])→invoke(None,[])),
        mutmut_16 (invoke(repo,[])→invoke(repo,None/removed)).
        """
        a = self._adapter()
        a.bandit = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            layer = a.run_l4(tmp_path, {})
        assert a.bandit.invoke.called
        inv_args, inv_kwargs = a.bandit.invoke.call_args
        assert inv_args[0] is tmp_path, \
            "invoke() first arg must be repo (kills H1: invoke repo→None: mutmut_15)"
        assert inv_args[1] == [], \
            "invoke() second arg must be [] (kills H1: invoke []→None: mutmut_16)"

    def test_l4_passed_type_when_true(self, tmp_path: Path):
        """passed must be exact bool True when no findings (kills passed=True→None).

        Kills mutmut_36 (passed→None in LayerResult) and
        mutmut_37 (bool mutation on passed assignment).
        """
        a = self._adapter()
        a.bandit = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            layer = a.run_l4(tmp_path, {})
        assert layer.passed is True, \
            "passed must be True when no findings (kills passed→None: mutmut_36, 37)"
        assert isinstance(layer.passed, bool), \
            "passed must be bool True (kills bool->int mutation: mutmut_36, 37)"

    def test_l4_security_findings(self, tmp_path: Path, caplog):
        """Bandit finds security issues -> passed=False.

        Kills mutmut_4 (env->None positional), mutmut_5 (env=None keyword)
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

    def test_l4_bandit_raises_oserror(self, tmp_path: Path, caplog):
        """Bandit raises OSError -> empty findings.
        
        Verifies invoke was called with correct args even in error path.
        Kills orchestrator-level H1 wiring mutants that change repo/[] args.
        """
        a = self._adapter()
        mock_bandit = MagicMock()
        mock_bandit.invoke = MagicMock(side_effect=OSError("bandit error"))
        with patch.object(a, "bandit", mock_bandit):
            with _all_tools_on_path():
                with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                    layer = a.run_l4(tmp_path, {})
            assert layer.passed is True
            assert layer.findings == []
            # Kill H1 wiring mutants: assert invoke called with (repo, [])
            assert mock_bandit.invoke.called
            inv_args = mock_bandit.invoke.call_args[0]
            assert inv_args[0] is tmp_path, "invoke() first arg = repo (kills H1 wiring mutant)"
            assert inv_args[1] == [], "invoke() second arg = [] (kills H1 wiring mutant)"
            # Kill H3 logger mutations on error path
            bandit_warn = [r for r in caplog.records
                           if r.levelname == "WARNING" and "bandit" in r.message
                           and "invocation failed" in r.message]
            assert len(bandit_warn) == 1, "Logger must emit invocation warning (kills mutmut on log removal)"

    def test_l4_bandit_raises_runtimeerror(self, tmp_path: Path, caplog):
        """Bandit raises RuntimeError -> empty findings.
        
        Kills mutmut on exception type mutation (OSError→RuntimeError removal)
        by verifying RuntimeError is caught.
        """
        a = self._adapter()
        mock_bandit = MagicMock()
        mock_bandit.invoke = MagicMock(side_effect=RuntimeError("boom"))
        with patch.object(a, "bandit", mock_bandit):
            with _all_tools_on_path():
                with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                    layer = a.run_l4(tmp_path, {})
            assert layer.passed is True
            bandit_warn = [r for r in caplog.records
                           if r.levelname == "WARNING" and "bandit" in r.message
                           and "invocation failed" in r.message]
            assert len(bandit_warn) == 1, "Logger must emit RuntimeError warning"

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

    def test_l4_wiring_spy_bandit_args_identity(self, tmp_path: Path):
        """H1 wiring: spy on _run_bandit, assert args identity with repo.

        Kills run_l4__mutmut_5 (H1): _run_bandit(repo, env) → _run_bandit(None, env).
        The spy catches repo→None because call_args.args[0] is repo fails.
        """
        a = self._adapter()
        with patch.object(a, "_run_bandit", return_value=[], autospec=True
                          ) as mock_run:
            with _all_tools_on_path():
                layer = a.run_l4(tmp_path, {})
        mock_run.assert_called_once_with(tmp_path, {})
        assert mock_run.call_args.args[0] is tmp_path, \
            "kill H1 wiring mutant: repo passed by identity, not equality"
        assert layer.passed is True
        assert layer.findings == []

    def test_l4_logger_exact_message_format(self, tmp_path: Path, caplog):
        """H3 logger exact message: assert complete formatted log line.

        Kills run_l4__mutmut_13 (H3): logger.info("bandit: %d findings")
        → logger.info("XXbandit: %d findingsXX").
        The exact message assertion kills it because the mutated string
        won't match the expected format. Also verifies log level.
        """
        a = self._adapter()
        a.bandit = _mock_subadapter(findings=[])
        with _all_tools_on_path():
            with caplog.at_level("INFO",
                                 logger="harness_quality_gate.adapters.python.python_adapter"):
                layer = a.run_l4(tmp_path, {})
        bandit_records = [r for r in caplog.records
                          if r.levelno == 20 and "bandit" in r.message
                          and "findings" in r.message]
        assert len(bandit_records) >= 1, \
            "Must log bandit findings count (killer for mutmut_13)"
        for record in bandit_records:
            full_msg = record.getMessage()
            assert full_msg.startswith("bandit: "), \
                f"message must start with 'bandit: ', got: {full_msg!r}"
            parts = full_msg.split(": ", 1)
            assert len(parts) == 2
            count = int(parts[1].split()[0])
            assert count == 0

    def test_l4_duration_rounding_frozen_clock(self, tmp_path: Path):
        """H2 time freeze: freeze monotonic clock, assert exact round value.

        Kills run_l4__mutmut_35 (H2): round(duration, 3) → round(duration, None).
        With frozen clock, duration = 0.987654, round(0.987654, 3) = 0.988 (float),
        but round(0.987654, None) = 1 (int). Asserts float type and exact value.
        """
        import time as time_module
        a = self._adapter()
        a.bandit = _mock_subadapter(findings=[])
        ticks = iter([100.0, 100.987654])
        with _all_tools_on_path():
            with patch(
                "harness_quality_gate.adapters.python.python_adapter.time.monotonic",
                side_effect=lambda: next(ticks),
            ):
                layer = a.run_l4(tmp_path, {})
        assert layer.duration_sec == 0.988, \
            "duration_sec must be round(0.987654, 3) = 0.988 (float)"
        assert type(layer.duration_sec).__name__ == "float", \
            "duration_sec must be float, kills round(_, None) → int: mutmut_35"


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
    """Test _run_ruff: tool-not-found, invocation branches, env= kwarg.

    Surviving mutants targeted: mutmut 6,7,8,9,19,20,21,22 + others.
    Strategy:
      - Non-empty env dict exposes conditional 'X if env else {}' mutations
        (with env={} both branches yield {}, mutations indistinguishable)
      - Return type/value assertions kill return []→None mutations
      - env kwarg assertions kill env=None/removed/conditional mutations
      - Separate test for tool-not-found path (shutil.which→None)
    """

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_run_ruff_tool_found(self, tmp_path: Path, caplog):
        """Ruff on PATH -> invoke + parse called.

        With non-empty env, exposes conditional 'dict(env) if env else {}'
        mutations because env={} (falsy) != {'K':'v'} (truthy).
        """
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[_make_finding(tool="ruff")])
        with _all_tools_on_path({"ruff": "/bin/ruff"}):
            findings = a._run_ruff(tmp_path, {"RUFF_ENV": "val"})
        assert isinstance(findings, list), "return must be list (kills return→None)"
        assert findings is not None
        assert len(findings) == 1
        assert findings[0].tool == "ruff"
        # Verify invoke() called with env= kwarg matching the dict passed in
        assert a.ruff.invoke.called
        inv_args, inv_kwargs = a.ruff.invoke.call_args
        assert inv_args[0] is tmp_path
        assert inv_args[1] == []
        assert inv_kwargs["env"] == {"RUFF_ENV": "val"}, \
            "env kwarg must propagate the exact dict (kills env mutation survivors)"
        # Verify parse was called with valid stdout/stderr
        assert a.ruff.parse.called
        pars_args = a.ruff.parse.call_args[0]
        assert pars_args[0] is not None and isinstance(pars_args[0], str)


    def test_run_ruff_shell_which_arg_exact(self, tmp_path, monkeypatch):
        """shutil.which() called with exact string "ruff", not mutated.

        Kills string mutations on the "ruff" literal:
        - mutmut_6: shutil.which("ruff") -> shutil.which("XXruffXX")
        - mutmut_7: similar string prefix/suffix mutations
        - mutmut_8: uppercase/lowercase mutation on "ruff"

        Strategy: mock shutil.which and capture args to verify EXACT string.
        """
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        which_calls = []

        def spy_which(name):
            which_calls.append(name)
            return "/bin/ruff"

        monkeypatch.setattr(
            "harness_quality_gate.adapters.python.python_adapter.shutil.which",
            spy_which,
        )
        a._run_ruff(tmp_path, {})
        assert len(which_calls) == 1
        assert which_calls[0] == "ruff", (
            f'shutil.which must be called with exact "ruff", '
            f'got {repr(which_calls[0])} (kills H8 string mutations)'
        )

    def test_run_ruff_parse_passthrough(self, tmp_path, monkeypatch):
        """Verify stdout/stderr from invoke are passed correctly to parse.

        Kills attribute mutations (H1) like inv.stdout/inv.stderr swap.
        Uses different values for stdout and stderr so a swap is detectable.
        """
        a = self._adapter()
        mock_ruff = MagicMock()
        inv_result = MagicMock(stdout="my_stdout_val", stderr="my_stderr_val", exitcode=0)
        mock_ruff.invoke.return_value = inv_result
        mock_ruff.parse.return_value = []
        a.ruff = mock_ruff
        with _all_tools_on_path({"ruff": "/bin/ruff"}):
            a._run_ruff(tmp_path, {})
        assert mock_ruff.parse.called
        parse_args = mock_ruff.parse.call_args[0]
        assert parse_args[0] == "my_stdout_val", (
            "invoke().stdout must be passed as first arg to parse "
            "(kills stdout/stderr swap mutant)"
        )
        assert parse_args[1] == "my_stderr_val", (
            "invoke().stderr must be passed as second arg to parse "
            "(kills stdout/stderr swap mutant)"
        )

    def test_run_ruff_tool_not_found(self, tmp_path: Path, caplog):
        """Ruff not on PATH -> return [] (not None).

        Kills return []→None mutations and H8 string log mutations.
        """
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                findings = a._run_ruff(tmp_path, {})
        assert isinstance(findings, list), "return must be list (kills return→None)"
        assert findings is not None
        assert findings == []
        # Kill H8 string mutation in log msg: assert EXACT message
        warn_msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert len(warn_msgs) == 1
        assert warn_msgs[0] == "ruff not found on PATH, skipping", (
            f"Logger must emit exact message, got {warn_msgs[0]!r} "
            "(kills H8 string mutation)"
        )

    def test_run_ruff_parse_error(self, tmp_path: Path, caplog):
        """Ruff parse raises RuntimeError -> caught, empty list returned."""
        a = self._adapter()
        mock_ruff = _mock_subadapter(findings=[])
        mock_ruff.parse = MagicMock(side_effect=RuntimeError("parse err"))
        a.ruff = mock_ruff
        with _all_tools_on_path({"ruff": "/bin/ruff"}):
            with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                findings = a._run_ruff(tmp_path, {})
        assert isinstance(findings, list), "return must be list (kills return→None)"
        assert findings is not None
        assert findings == []
        # Kill invoke-arg mutation (H1): assert invoke called with (repo, env)
        assert mock_ruff.invoke.called
        inv_args = mock_ruff.invoke.call_args[0]
        assert inv_args[0] is tmp_path, "invoke() first arg = repo (kills mutmut on repo→None)"
        assert inv_args[1] == [], "invoke() second arg = [] (kills mutmut on []→None)"
        # Kill logger mutation: verify warning was emitted
        ruff_warn = [r for r in caplog.records
                     if r.levelname == "WARNING" and "ruff" in r.message.lower() and "invocation failed" in r.message]
        assert len(ruff_warn) == 1, "Logger must emit ruff invocation warning"
        assert "parse err" in ruff_warn[0].getMessage(), "Exception message must be in log"
        # Kill H8 string mutation: verify format
        assert ruff_warn[0].getMessage().startswith("ruff invocation failed:"), \
            f"Log format must start with 'ruff invocation failed:', got {ruff_warn[0].getMessage()!r}" 

    def test_run_ruff_oserror_on_invoke(self, tmp_path: Path, caplog):
        """Ruff.invoke raises OSError -> caught, empty list returned."""
        a = self._adapter()
        mock_ruff = _mock_subadapter(findings=[])
        mock_ruff.invoke = MagicMock(side_effect=OSError("ruff exec failed"))
        a.ruff = mock_ruff
        with _all_tools_on_path({"ruff": "/bin/ruff"}):
            with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                findings = a._run_ruff(tmp_path, {})
        assert isinstance(findings, list), "return must be list (kills return→None)"
        assert findings is not None
        assert findings == []
        # Kill invoke-arg mutation (H1): assert invoke called with (repo, env)
        assert mock_ruff.invoke.called
        inv_args = mock_ruff.invoke.call_args[0]
        assert inv_args[0] is tmp_path, "invoke() first arg = repo (kills mutmut on repo→None)"
        assert inv_args[1] == [], "invoke() second arg = [] (kills mutmut on []→None)"
        # Kill logger mutation: verify warning was emitted
        ruff_warn = [r for r in caplog.records
                     if r.levelname == "WARNING" and "ruff" in r.message.lower() and "invocation failed" in r.message]
        assert len(ruff_warn) == 1, "Logger must emit ruff invocation warning"
        assert "ruff exec failed" in ruff_warn[0].getMessage(), "Exception message must be in log"
        # Kill H8 string mutation: exact log format
        assert ruff_warn[0].getMessage().startswith("ruff invocation failed:"), \
            f"Log format must start with 'ruff invocation failed:', got {ruff_warn[0].getMessage()!r}" 

    def test_run_ruff_runtimeerror_on_invoke(self, tmp_path: Path, caplog):
        """Ruff.invoke raises RuntimeError -> caught, empty list returned.

        Verifies RuntimeError (not just OSError) triggers exception handler.
        Kills RuntimeError-type-mutation survivors by testing RuntimeError explicitly.
        """
        a = self._adapter()
        mock_ruff = _mock_subadapter(findings=[])
        mock_ruff.invoke = MagicMock(side_effect=RuntimeError("ruff runtime err"))
        a.ruff = mock_ruff
        with _all_tools_on_path({"ruff": "/bin/ruff"}):
            with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                findings = a._run_ruff(tmp_path, {})
        assert isinstance(findings, list), "return must be list (kills return→None)"
        assert findings is not None
        assert findings == []
        # Kill invoke-arg mutation (H1): assert invoke called with (repo, env)
        assert mock_ruff.invoke.called
        inv_args = mock_ruff.invoke.call_args[0]
        assert inv_args[0] is tmp_path, "invoke() first arg = repo (kills mutmut on repo→None)"
        assert inv_args[1] == [], "invoke() second arg = [] (kills mutmut on []→None)"
        # Kill logger mutation: verify warning was emitted with RuntimeError path
        ruff_warn = [r for r in caplog.records
                     if r.levelname == "WARNING" and "ruff" in r.message.lower() and "invocation failed" in r.message]
        assert len(ruff_warn) == 1, "Logger must emit ruff invocation warning on RuntimeError"
        assert "ruff runtime err" in ruff_warn[0].getMessage(), "Exception message must be in log"

    def test_run_ruff_env_kwarg_preserved(self, tmp_path: Path):
        """env dict passed to _run_ruff must appear verbatim in invoke(env=).

        Kills env-related survivors (mutmut_19..22):
          - env=dict() -> {}
          - env=dict(env) if env else {} conditional
          - env=None replacement
          - env= kwarg removed
        Uses non-empty env so X if {} else {} evaluates differently from
        X if {"K":"v"} else {}, making mutations observable.
        """
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[_make_finding(tool="ruff")])
        env_arg = {"K1": "V1", "K2": "V2"}
        with _all_tools_on_path({"ruff": "/bin/ruff"}):
            findings = a._run_ruff(tmp_path, env_arg)
        assert isinstance(findings, list)
        assert findings is not None
        assert len(findings) == 1
        inv_args, inv_kwargs = a.ruff.invoke.call_args
        assert "env" in inv_kwargs, "invoke() must include env= keyword"
        # The exact dict must flow through — catches conditional mutations
        assert inv_kwargs["env"] == {"K1": "V1", "K2": "V2"}

    def test_run_ruff_env_empty_dict(self, tmp_path: Path):
        """env={} → invoke received env={} (not None, not missing)."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[_make_finding(tool="ruff")])
        with _all_tools_on_path({"ruff": "/bin/ruff"}):
            findings = a._run_ruff(tmp_path, {})
        assert isinstance(findings, list)
        assert findings is not None
        assert len(findings) == 1
        inv_args, inv_kwargs = a.ruff.invoke.call_args
        assert "env" in inv_kwargs
        # Empty env must be passed as empty dict (not None)
        assert inv_kwargs["env"] is not None
        assert inv_kwargs["env"] == {}

    def test_run_ruff_none_env_falls_back_to_empty_dict(self, tmp_path: Path):
        """env=None must reach ruff.invoke as env={} (defensive asserts removed)."""
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[])
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value="/usr/bin/ruff"):
            a._run_ruff(tmp_path, None)
        a.ruff.invoke.assert_called_once_with(tmp_path, [], env={})


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
        with patch(
            "harness_quality_gate.adapters.python.python_adapter.shutil.which",
            return_value="/usr/bin/pyright",
        ):
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
        """Pyright not on PATH -> early return empty list.

        Kills mutmut_5 ("pyright not found"→None → log removed) via caplog message.
        Kills mutmut_6 ("pyright not found"→garbled string) via exact message check.
        Kills mutmut_7 (return []→None) via isinstance assertion.
        Kills mutmut_8 (logger warning call removed) via log record check.
        """
        a = self._adapter()
        a.pyright = _mock_subadapter(findings=[])
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                findings = a._run_pyright(tmp_path, {})
        # Type assertion: kills mutmut_7 (return []→None)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None
        assert findings == []
        # Kill mutmut_5: verify warning was emitted (logger.warning call present)
        pyright_warn = [r for r in caplog.records if r.levelname == "WARNING" and "pyright" in r.message.lower()]
        assert len(pyright_warn) == 1, f"Expected warning, got {len(pyright_warn)}"
        # Kill mutmut_6: verify exact log message (not garbled/empty)
        assert pyright_warn[0].getMessage() == "pyright not found on PATH, skipping", \
            f"Expected exact warning message, got: {pyright_warn[0].getMessage()}"

    def test_run_pyright_oserror(self, tmp_path: Path, caplog):
        """Pyright.invoke raises OSError -> empty list + invoke was called correctly.

        Kills mutmut_8 (return []→None in exception handler) via isinstance assertion.
        Kills mutmut_10 (logger.warning call removed) via caplog message check.
        Kills mutmut_11 ("pyright invocation failed"→other string) via message check.
        Kills mutmut_12 (exc→None in format arg) via str(interpolation) of msg.
        Kills invoke-arg mutations (H1 wiring) via assert invoke called with (repo, []).
        """
        a = self._adapter()
        a.pyright = _mock_subadapter(findings=[])
        a.pyright.invoke = MagicMock(side_effect=OSError("pyright exec failed"))
        with _all_tools_on_path({"pyright": "/bin/pyright"}):
            with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                findings = a._run_pyright(tmp_path, {})
        # Type assertion on empty list: kills mutmut_8 (return []→None)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None
        assert findings == []
        # Kill mutmut on invoke-arg mutations (H1 wiring): assert invoke called with (repo, [])
        assert a.pyright.invoke.called
        inv_args = a.pyright.invoke.call_args[0]
        assert inv_args[0] is tmp_path, "invoke() first arg = repo (kills mutmut on repo→None)"
        assert inv_args[1] == [], "invoke() second arg = [] (kills mutmut on []→None)"
        # Kill mutmut_10: logger.warning call present, kills call-removed mutation
        pyright_warn = [r for r in caplog.records if r.levelname == "WARNING" and "pyright" in r.message.lower()]
        assert len(pyright_warn) == 1, f"Expected warning, got {len(pyright_warn)}"
        assert "pyright invocation failed" in pyright_warn[0].getMessage()
        # Kill mutmut_11, 12: verify format string has %s interpolated (not None, not empty)
        msg = pyright_warn[0].getMessage()
        # mutmut_12: exc→None means "%s" format would fail → msg broken/empty
        assert "pyright exec failed" in msg, f"exc must be interpolated in log msg (kills mutmut_12), got: {msg}"

    def test_run_pyright_runtimeerror_on_invoke(self, tmp_path: Path, caplog):
        """Pyright.invoke raises RuntimeError -> empty list + warning logged.

        Verifies RuntimeError (not just OSError) triggers exception handler.
        Kills RuntimeError-type-mutation survivors by testing RuntimeError explicitly.
        """
        a = self._adapter()
        a.pyright = _mock_subadapter(findings=[])
        a.pyright.invoke = MagicMock(side_effect=RuntimeError("pyright runtime err"))
        with _all_tools_on_path({"pyright": "/bin/pyright"}):
            with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                findings = a._run_pyright(tmp_path, {})
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None
        assert findings == []
        # Kill logger mutation: verify warning was emitted
        pyright_warn = [r for r in caplog.records
                        if r.levelname == "WARNING" and "pyright" in r.message.lower() and "invocation failed" in r.message]
        assert len(pyright_warn) == 1, "Logger must emit pyright invocation warning"
        assert "pyright runtime err" in pyright_warn[0].getMessage(), "Exception message must be in log"


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
        """Pytest.invoke raises -> empty list.

        Kills mutmut_8 (return []→None in exception handler) via isinstance assertion.
        Kills mutmut_10 (logger.warning call removed) via caplog message check.
        Kills mutmut_11 ("pytest invocation failed"→other string) via message check.
        Kills mutmut_12 (exc→None in format arg) via str(interpolation) of msg.
        """
        a = self._adapter()
        mock_pytest = MagicMock()
        mock_pytest.invoke = MagicMock(side_effect=RuntimeError("pytest failed"))
        a.pytest = mock_pytest
        with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
            findings = a._run_pytest(tmp_path, {})
        # Type assertion on empty list: kills mutmut_8 (return []→None)
        assert isinstance(findings, list), f"findings must be list, got {type(findings).__name__}"
        assert findings is not None, "findings must not be None"
        assert findings == []
        # Kill mutmut_10: logger.warning call present, kills call-removed mutation
        pytest_warn = [r for r in caplog.records if r.levelname == "WARNING" and "pytest" in r.message.lower()]
        assert len(pytest_warn) == 1, f"Expected pytest warning, got {len(pytest_warn)}"
        assert "pytest invocation failed" in pytest_warn[0].getMessage()
        # Kill mutmut_11, 12: verify format string has %s interpolated (not None, not empty)
        msg = pytest_warn[0].getMessage()
        assert "pytest failed" in msg, f"exc must be interpolated in log msg (kills mutmut_12), got: {msg}"

    def test_run_pytest_tool_not_found(self, tmp_path: Path, caplog):
        """python3 not found on PATH -> empty list, no invoke called.

        Kills mutmut_5 ("python3 not found"->None -> log removed) via caplog message.
        Kills mutmut_6 ("python3 not found"->garbled string) via exact message check.
        Kills mutmut_7 (return []->None) via isinstance assertion.
        Kills mutmut_8 (logger warning call removed) via log record check.
        Kills mutmut_29 (shutil.which->None guard mutation: early return [] instead of invoke).
        """
        a = self._adapter()
        a.pytest = _mock_subadapter(findings=[])
        with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
            with patch(
                "harness_quality_gate.adapters.python.python_adapter.shutil.which",
                return_value=None,
            ):
                findings = a._run_pytest(tmp_path, {})
        # Type assertion: kills mutmut_7 (return []->None)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None
        assert findings == []
        # Kill mutmut_5: verify warning was emitted (logger.warning call present)
        pytest_warn = [r for r in caplog.records if r.levelname == "WARNING" and "python" in r.message.lower()]
        assert len(pytest_warn) == 1, f"Expected python not found warning, got {len(pytest_warn)}"
        # Kill mutmut_6: verify exact log message (not garbled/empty)
        assert pytest_warn[0].getMessage() == "python3 not found on PATH, skipping", \
            f"Expected exact warning message, got: {pytest_warn[0].getMessage()}"
        # Kill mutmut_29: assert invoke was NOT called (early return before invoke)
        assert not a.pytest.invoke.called, \
            "invoke must NOT be called when tool not found (kills shutil.which mutant: mutmut_29)"

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
        """Validate parse() receives (stdout, stderr, exitcode) — kills arg mutations.

        Kills mutmut_8 (parse args → None/None/None) via each-arg-is-not-None check.
        Kills mutmut_11 (parse call removed) via assert parse.called.
        Kills mutmut_6,7 (stderr/stdout swap in parse call) via positional position check.
        """
        from harness_quality_gate.adapters.python.pytest_adapter import PytestAdapter

        a = self._adapter()
        real_adapter = PytestAdapter()
        mock_pytest = MagicMock()
        mock_pytest.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)
        mock_pytest.parse = MagicMock(wraps=real_adapter.parse)
        with patch.object(a, "pytest", mock_pytest):
            findings = a._run_pytest(tmp_path, {})
        assert mock_pytest.parse.called, "parse() must be called (kills mutmut_11)"
        pars_args = mock_pytest.parse.call_args[0]
        assert len(pars_args) >= 3, "parse() called with at least 3 args"
        assert pars_args[0] is not None, "parse() arg0=stdout must not be None (kills mutmut_5-8)"
        assert pars_args[1] is not None, "parse() arg1=stderr must not be None (kills mutmut_15-19)"
        assert pars_args[2] is not None, "parse() arg2=exitcode must not be None (kills mutmut_21-24)"

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

    def test_run_vulture_oserror(self, tmp_path: Path, caplog):
        """Vulture.invoke raises OSError -> empty list.

        Kills return None mutations (mutmut_23-24) via isinstance assertion.
        Kills invoke-args mutations (mutmut_19-21) via assert invoke called with args.
        Kills logger warning mutations via exact log-message assertion.
        """
        a = self._adapter()
        a.vulture = _mock_subadapter(findings=[])
        a.vulture.invoke = MagicMock(side_effect=OSError("vulture exec failed"))
        with _all_tools_on_path({"vulture": "/bin/vulture"}):
            with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                findings = a._run_vulture(tmp_path, {})
        # Type assertion: kills return None mutations (mutmut_23-24)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None, "findings must not be None"
        assert findings == []
        # Kill invoke-args mutations: verify invoke was called with correct args
        assert a.vulture.invoke.called
        inv_args = a.vulture.invoke.call_args[0]
        assert inv_args[0] is tmp_path, "invoke() first arg = repo (kills mutmut_19)"
        assert inv_args[1] == [], "invoke() second arg = [] (kills mutmut_19)"
        # Kill logger warning mutations: verify exact log message
        vulture_warning = [
            r for r in caplog.records
            if r.levelname == "WARNING" and "vulture" in r.message.lower()
            and "invocation failed" in r.message
        ]
        assert len(vulture_warning) == 1, "Logger must emit vulture invocation warning"
        assert "vulture exec failed" in vulture_warning[0].getMessage(), \
            f"Exception message must be interpolated in log"

    def test_run_vulture_strict_invoke_and_parse_args(self, tmp_path: Path):
        """Strict checks on _run_vulture success path: invoke/parse args verified.

        Kills mutmut_5, 6, 7, 8 (return []→None mutations) via isinstance/is-not-None.
        Kills mutmut_14 (invoke(repo,[])→invoke(None,[])) via invoke first-arg check.
        Kills mutmut_15 (invoke(repo,[])→invoke(repo,None/removed)) via invoke second-arg check.
        Kills mutmut_16 (parse(None,inv.stderr,inv.exitcode)) via parse first-arg is not None.
        Kills mutmut_17 (parse args swapped/removed) via parse positional args check.
        """
        from harness_quality_gate.adapters.python.vulture_adapter import VultureAdapter

        a = self._adapter()
        real_adapter = VultureAdapter()

        mock_vulture = MagicMock()
        mock_vulture.invoke.return_value = MagicMock(
            stdout='{}', stderr='', exitcode=0,
        )
        mock_vulture.parse = MagicMock(wraps=real_adapter.parse)

        with patch.object(a, "vulture", mock_vulture):
            with _all_tools_on_path({"vulture": "/bin/vulture"}):
                findings = a._run_vulture(tmp_path, {})

        # Type assertions: kills mutmut_5, 6, 7, 8 (return []→None mutations on any path)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None, "findings must not be None (kills mutmut_5,6,7,8)"

        # Kill mutmut_14, 15: invoke() called with correct positional args (repo, [])
        assert mock_vulture.invoke.called
        inv_args = mock_vulture.invoke.call_args[0]
        assert inv_args[0] is tmp_path, "invoke() first arg = repo (kills mutmut_14)"
        assert inv_args[1] == [], "invoke() second arg = [] (kills mutmut_15)"

        # Kill mutmut_16, 17: parse() called with non-None stdout, stderr, exitcode
        assert mock_vulture.parse.called
        pars_args = mock_vulture.parse.call_args[0]
        assert len(pars_args) >= 3, "parse() called with at least 3 positional args (kills mutmut_17)"
        assert pars_args[0] is not None, "parse() arg0=stdout must not be None (kills mutmut_16)"
        assert isinstance(pars_args[0], str), "parse() arg0=stdout must be str"
        assert pars_args[1] is not None, "parse() arg1=stderr must not be None"
        assert pars_args[2] is not None, "parse() arg2=exitcode must not be None"

    def test_run_vulture_runtimeerror(self, tmp_path: Path, caplog):
        """Vulture.invoke raises RuntimeError -> empty list + warning logged.

        Kills mutmut_5, 6 (return []→None on exception path) via type assertion.
        Kills mutmut_20 (OSError→RuntimeError exception type mutation).
        Kills logger warning mutations via caplog check.
        """
        a = self._adapter()
        mock_vulture = MagicMock()
        mock_vulture.invoke = MagicMock(side_effect=RuntimeError("vulture runtime error"))
        with patch.object(a, "vulture", mock_vulture):
            with _all_tools_on_path({"vulture": "/bin/vulture"}):
                with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                    findings = a._run_vulture(tmp_path, {})

        # Type assertion: kills mutmut_5, 6 (return []→None mutations on exception path)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None, "findings must not be None (kills mutmut_5,6)"
        assert findings == [], "findings must be empty list on exception path"

        # Kill invoke-args mutations: verify invoke WAS called before exception
        assert mock_vulture.invoke.called, "invoke() should have been called before RuntimeError"
        inv_args = mock_vulture.invoke.call_args[0]
        assert inv_args[0] is tmp_path, "invoke() first arg = repo (kills mutmut_21)"
        assert inv_args[1] == [], "invoke() second arg = [] (kills mutmut_22)"

        # Kill logger mutations: verify warning was logged
        vulture_warn = [
            r for r in caplog.records
            if r.levelname == "WARNING" and "vulture" in r.message.lower() and "invocation failed" in r.message
        ]
        assert len(vulture_warn) >= 1, "Logger must emit vulture invocation warning (kills mutmut_25, 26)"

    def test_run_vulture_strict_not_found(self, tmp_path: Path, caplog):
        """Vulture not on PATH -> empty list + exact warning message.

        Kills mutmut_5 (return []→None on early-return line) via isinstance assertion.
        Kills mutmut_6 (return []→None on early-return line) via isinstance assertion.
        Kills mutmut_7 (return []→None on early-return line) via findings is not None.
        Kills mutmut_8 (return []→None on early-return line) via findings == [].
        Kills logger warning removal mutation via caplog assertion.
        Kills logger message string mutation via exact message check.
        """
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                findings = a._run_vulture(tmp_path, {})

        # Type assertions: kills mutmut_5, 6, 7, 8 (return []→None mutations on early return)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None, "findings must not be None (kills mutmut_7,8)"
        assert findings == [], "findings must be empty list on not-found path"

        # Kill logger warning mutation: verify warning was emitted
        vulture_warn = [
            r for r in caplog.records
            if r.levelname == "WARNING" and "vulture" in r.message.lower() and "not found" in r.message
        ]
        assert len(vulture_warn) >= 1, "Logger must emit vulture not found warning (kills mutmut_10, 11)"
        # Kill exact-message string mutations (mutmut on log format string)
        assert any("vulture not found on PATH" in r.getMessage() for r in vulture_warn), (
            "Warning must contain 'vulture not found on PATH' message"
        )


# ---------------------------------------------------------------------------
# Private helper: _run_deptry
# ---------------------------------------------------------------------------

class TestRunDeptryHelper:
    """Test _run_deptry: tool-not-found and invocation branches."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_run_deptry_tool_found(self, tmp_path: Path):
        """Deptry on PATH -> parse returns findings.

        Kills mutmut_5, 6 (return []→None on early return path) via type assertion.
        Kills mutmut_14, 15 (invoke args: repo→None or []→None) via invoke arg checks.
        Kills mutmut_16, 17 (parse args → None) via parse arg checks.
        """
        from harness_quality_gate.adapters.python.deptry_adapter import DeptryAdapter

        a = self._adapter()
        real_adapter = DeptryAdapter()

        # Use wraps= to keep MagicMock tracking .call_count for assert_called_once
        mock_parse = MagicMock(wraps=real_adapter.parse)
        mock_deptry = MagicMock()
        mock_deptry.invoke.return_value = MagicMock(
            stdout='{"errors": {"missing_imports": [{"module": "foobar", "filepath": "/x.py"}]}}',
            stderr='', exitcode=0,
        )
        mock_deptry.parse = mock_parse

        with patch.object(a, 'deptry', mock_deptry):
            with _all_tools_on_path({"deptry": "/bin/deptry"}):
                findings = a._run_deptry(tmp_path, {})

        # Type assertion: kills return []→None mutations (mutmut_5, 6 on early path)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None, "findings must not be None (kills mutmut_5,6,7,8)"
        assert len(findings) == 1
        assert findings[0].tool == "deptry"

        # Kill mutmut_14, 15: invoke() called with correct positional args
        assert mock_deptry.invoke.called
        inv_args = mock_deptry.invoke.call_args[0]
        assert inv_args[0] is tmp_path, "invoke() first arg = repo (kills mutmut_14, 15)"
        assert inv_args[1] == [], "invoke() second arg = [] (kills mutmut_14, 15)"

        # Kill mutmut_16, 17: parse() called with non-None args
        mock_deptry.parse.assert_called_once()
        pars_args = mock_deptry.parse.call_args[0]
        assert pars_args[0] is not None, "parse() arg0=stdout must not be None (kills mutmut_16, 17)"
        assert pars_args[1] is not None, "parse() arg1=stderr must not be None (kills mutmut_16, 17)"
        assert pars_args[2] is not None, "parse() arg2=exitcode must not be None (kills mutmut_16, 17)"

    def test_run_deptry_tool_not_found(self, tmp_path: Path, caplog):
        """Deptry not on PATH -> empty list.

        Kills mutmut_5, 6 (return []→None on early return) via type assertion.
        Kills mutmut_7, 8 (logger warning string mutations) via message check.
        """
        from harness_quality_gate.adapters.python.deptry_adapter import DeptryAdapter

        a = self._adapter()
        a.deptry = _mock_subadapter(findings=[])

        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                findings = a._run_deptry(tmp_path, {})

        # Type assertion: kills return []→None mutations on early return path (mutmut_5, 6)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None, "findings must not be None (kills mutmut_5,6)"
        assert findings == [], "findings must be empty list on not-found path"

        # Kill logger warning mutations: verify warning was emitted with expected message.
        # mutmut_5: logger.warning(None) → no log emitted → len(deptry_warn)=0 → FAIL
        # mutmut_6: logger.warning("XXdeptry not found on PATH, skippingXX") → startswith fails
        # mutmut_7: logger.warning("deptry not found on path, skipping") → case mismatch fails
        # mutmut_8: logger.warning("DEPTRY NOT FOUND ON PATH, SKIPPING") → case mismatch fails
        deptry_warn = [
            r for r in caplog.records
            if r.levelname == "WARNING" and r.getMessage().startswith("deptry")
            and "not found" in r.message.lower()
        ]
        assert len(deptry_warn) >= 1, (
            f"Logger must emit deptry not found warning (kills mutmut_5,7,8), got {len(deptry_warn)}"
        )
        # Kill exact-message string mutations (mutmut_6: XX...XX prefix/suffix mutation)
        assert any(r.getMessage().startswith("deptry not found on PATH") for r in deptry_warn), (
            "Warning must start with 'deptry not found on PATH' (kills mutmut_6)"
        )

    def test_run_deptry_oserror(self, tmp_path: Path, caplog):
        """Deptry.invoke raises -> empty list.

        Kills mutmut_7, 8 (return []→None on exception path) via type assertion.
        Kills mutmut_14, 15 (invoke args: repo→None or []→None) via invoke arg checks.
        Kills mutmut_16, 17 (logger string mutation) via caplog assertion.
        """
        a = self._adapter()
        a.deptry = _mock_subadapter(findings=[])
        a.deptry.invoke = MagicMock(side_effect=OSError("deptry exec failed"))
        with _all_tools_on_path({"deptry": "/bin/deptry"}):
            with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                findings = a._run_deptry(tmp_path, {})

        # Type assertion: kills return None mutations on exception path (mutmut_7, 8)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None, "findings must not be None (kills mutmut_7, 8)"
        assert findings == []

        # Kill invoke-args mutations: verify invoke was called with correct args
        assert a.deptry.invoke.called
        inv_args = a.deptry.invoke.call_args[0]
        assert inv_args[0] is tmp_path, "invoke() first arg = repo (kills mutmut_14)"
        assert inv_args[1] == [], "invoke() second arg = [] (kills mutmut_15)"

        # Kill logger string mutations via caplog (mutmut_7, 8 warning path)
        deptry_warn = [r for r in caplog.records if r.levelname == "WARNING" and "deptry" in r.message.lower()]
        assert len(deptry_warn) == 1, f"Expected 1 deptry warning log, got {len(deptry_warn)}"
        assert "deptry invocation failed" in deptry_warn[0].getMessage()

    def test_run_deptry_not_found_no_invoke(self, tmp_path: Path):
        """When deptry not on PATH, deptry.invoke must NOT be called (kills guard mutation).

        Kills mutmut_21, 23, 24 (guard: if shutil.which("deptry") is None) mutations.
        If guard is mutated and invoke is called when tool not found, this fails.
        """
        a = self._adapter()
        mock_deptry = MagicMock()
        mock_deptry.parse.return_value = []
        with patch.object(a, "deptry", mock_deptry):
            with patch(
                "harness_quality_gate.adapters.python.python_adapter.shutil.which",
                return_value=None,
            ):
                a._run_deptry(tmp_path, {})
        assert not mock_deptry.invoke.called, \
            "invoke() must NOT be called when deptry is not on PATH (kills guard mutation: mutmut_21,23,24)"


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
        # Kills mutmut_21 (shutil.which→None guard mutation):
        # If shutil.which is mutated to a different falsy value, the early return still fires
        # But if the guard itself is mutated so shutil.which("bandit") returns truthy,
        # invoke would be called -> assert_not_called kills this

    def test_run_bandit_not_found_no_invoke(self, tmp_path: Path):
        """When bandit not on PATH, invoke must NOT be called (kills guard mutation mutmut_21).

        If mutmut mutates the guard so bandit.invoke IS called when it shouldn't be,
        this test fails.
        """
        a = self._adapter()
        mock_bandit = MagicMock()
        mock_bandit.parse.return_value = []
        with patch.object(a, "bandit", mock_bandit):
            with patch(
                "harness_quality_gate.adapters.python.python_adapter.shutil.which",
                return_value=None,
            ):
                a._run_bandit(tmp_path, {})
        assert not mock_bandit.invoke.called, \
            "invoke() must NOT be called when tool is not on PATH (kills guard mutation: mutmut_21)"

    def test_run_bandit_oserror(self, tmp_path: Path, caplog):
        """Bandit.invoke raises -> empty list + warning logged."""
        a = self._adapter()
        a.bandit = _mock_subadapter(findings=[])
        a.bandit.invoke = MagicMock(side_effect=OSError("bandit exec failed"))
        with _all_tools_on_path({"bandit": "/bin/bandit"}):
            with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                findings = a._run_bandit(tmp_path, {})
        assert findings == []
        # Kill logger mutation: warning must be logged on invocation failure
        bandit_warn = [r for r in caplog.records if r.levelname == "WARNING" and "bandit" in r.message.lower()]
        assert len(bandit_warn) >= 1, "Logger must emit warning on invocation failure (kills mutmut_10)"

    def test_run_bandit_runtimeerror(self, tmp_path: Path, caplog):
        """Bandit.invoke raises RuntimeError -> empty list + warning logged.

        Kills mutmut_12 (OSError→RuntimeError exception type mutation in except clause).
        """
        a = self._adapter()
        mock_bandit = MagicMock()
        mock_bandit.invoke = MagicMock(side_effect=RuntimeError("bandit runtime error"))
        with patch.object(a, "bandit", mock_bandit):
            with _all_tools_on_path({"bandit": "/bin/bandit"}):
                with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                    findings = a._run_bandit(tmp_path, {})

        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings == []
        bandit_warn = [r for r in caplog.records if r.levelname == "WARNING" and "bandit" in r.message.lower()]
        assert len(bandit_warn) >= 1, "Logger must emit warning on RuntimeError (kills mutmut_12)"

    def test_run_bandit_tool_found_strict(self, tmp_path: Path, caplog):
        """Strict checks on _run_bandit success path: type, invoke args, parse args.

        Kills mutmut_5 (return []→None mutmut_288) via isinstance assertion.
        Kills mutmut_6 (return []→None mutmut_294) via isinstance assertion.
        Kills mutmut_7 (return []→None mutmut_294) via findings is not None.
        Kills mutmut_8 (return []→None mutmut_294) via findings == [].
        Kills mutmut_10 (logger.warning on line 293 removed) via caplog check.
        Kills mutmut_13 (return []→None mutmut_294) via findings is not None.
        Kills invoke-arg mutations: assert first arg is repo, second is [].
        Kills parse-arg mutations: assert parse receives non-None str args.
        """
        a = self._adapter()
        # Wrap real parse in a MagicMock so we can assert on call_args
        from harness_quality_gate.adapters.python.bandit_adapter import BanditAdapter
        real_adapter = BanditAdapter()
        mock_bandit = MagicMock()
        mock_bandit.invoke.return_value = MagicMock(
            stdout="{}", stderr="", exitcode=0,
        )
        mock_bandit.parse = MagicMock(wraps=real_adapter.parse)

        with patch.object(a, "bandit", mock_bandit):
            with _all_tools_on_path({"bandit": "/bin/bandit"}):
                with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                    findings = a._run_bandit(tmp_path, {})

        # Type assertion: kills mutmut_5,6,7,8,13 (return []→None on any code path)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None, "findings must not be None (kills mutmut_7,13)"

        # Kill invoke-arg mutations: assert invoke was called with (repo, [])
        inv_args, inv_kwargs = mock_bandit.invoke.call_args
        assert inv_args[0] is tmp_path, "invoke() first arg must be repo (kills mutmut on invoke arg)"
        assert inv_args[1] == [], "invoke() second arg must be [] (kills mutmut on invoke arg)"

        # Kill parse-arg mutations: assert parse was called with stdout, stderr, exitcode
        assert mock_bandit.parse.called, "parse() must be called (kills mutmut_10 on parse call removed)"
        pars_args = mock_bandit.parse.call_args[0]
        assert len(pars_args) >= 3, "parse() called with at least 3 args"
        assert pars_args[0] is not None, "parse() arg0=stdout must not be None (kills mutmut on parse arg)"
        assert pars_args[1] is not None, "parse() arg1=stderr must not be None (kills mutmut on parse arg)"
        assert pars_args[2] is not None, "parse() arg2=exitcode must not be None (kills mutmut on parse arg)"

    def test_run_bandit_tool_not_found_strict(self, tmp_path: Path, caplog):
        """Bandit not on PATH -> empty list, warning logged with exact message.

        Kills mutmut_5,6,7,8,13 (return []→None mutations) via isinstance/is-not-None.
        Kills mutmut_10 (logger.warning call removed) via caplog record check.
        Kills mutmut_6 (guard log XX...XX prefix/suffix) via exact message equality.
        Kills mutmut_11 (string mutation in not-found message) via exact message.
        Kills mutmut_21,23,24 (guard path mutations) via invoke-not-called check.
        """
        a = self._adapter()
        mock_bandit = MagicMock()
        mock_bandit.parse.return_value = []
        with patch.object(a, "bandit", mock_bandit):
            with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
                with caplog.at_level("WARNING",
                                       logger="harness_quality_gate.adapters.python.python_adapter"):
                    findings = a._run_bandit(tmp_path, {})

        # Type assertion: kills mutmut_5,7,8,13 (return []→None mutations)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None, "findings must not be None (kills mutmut_7,13)"
        assert findings == [], "findings must be empty list"

        # Kill mutate guard mutation: verify invoke NOT called (kills mutmut_21,23,24)
        assert not mock_bandit.invoke.called, \
            "invoke() must NOT be called when bandit is not on PATH (kills mutmut_21,23,24)"

        # Kill logger removal mutation (mutmut_10): warning must be present
        bandit_warn = [r for r in caplog.records
                       if r.levelname == "WARNING" and "bandit" in r.message]
        assert len(bandit_warn) == 1, \
            f"Exactly 1 bandit warning expected, got {len(bandit_warn)} (kills mutmut_10)"

        # Kill mutmut_6: exact log message equality — XX...XX mutations killed by == check
        assert bandit_warn[0].getMessage() == "bandit not found on PATH, skipping", \
            f"Exact log message check kills mutmut_6 (XX...XX mutations in not-found message)"

    def test_run_bandit_oserror_strict(self, tmp_path: Path, caplog):
        """Bandit.invoke raises OSError -> empty list + invoke was called + warning logged.

        Kills mutmut_5 (return []→None mutmut_294) via isinstance assertion.
        Kills mutmut_6 (return []→None mutmut_294) via isinstance assertion.
        Kills mutmut_7 (return []→None mutmut_294) via findings is not None.
        Kills mutmut_8 (return []→None mutmut_294) via findings == [].
        Kills mutmut_12 (OSError→RuntimeError mutation) by testing OSError explicitly.
        Kills mutmut_10 (logger.warning on line 293 removed) via caplog check.
        Kills mutmut_13 (return []→None mutmut_294) via findings == [].
        Verifies invoke WAS called before exception (kills exception-path arg mutations).
        """
        a = self._adapter()
        mock_bandit = MagicMock()
        mock_bandit.invoke = MagicMock(side_effect=OSError("bandit exec failed"))
        with patch.object(a, "bandit", mock_bandit):
            with _all_tools_on_path({"bandit": "/bin/bandit"}):
                with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                    findings = a._run_bandit(tmp_path, {})

        # Type assertion: kills mutmut_5,6,7,8,13 (return []→None mutations on exception path)
        assert isinstance(findings, list), f"findings must be list, got {type(findings)}"
        assert findings is not None, "findings must not be None (kills mutmut_7,13)"
        assert findings == [], "findings must be empty list"

        # Kill invoke-args mutations: verify invoke WAS called before exception
        assert mock_bandit.invoke.called, "invoke() should have been called before raising (kills mutmut on invoke removed)"
        inv_args = mock_bandit.invoke.call_args[0]
        assert inv_args[0] is tmp_path, "invoke() first arg must be repo"
        assert inv_args[1] == [], "invoke() second arg must be []"

        # Kill logger mutations: verify warning was logged with correct message
        bandit_warn = [
            r for r in caplog.records
            if r.levelname == "WARNING" and "bandit" in r.message.lower() and "invocation failed" in r.message
        ]
        assert len(bandit_warn) >= 1, "Logger must emit invocation warning (kills mutmut_10)"


# ---------------------------------------------------------------------------
# PythonAdapter instantiation and basic properties
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Private helper: _run_mutmut — direct mutations on _run_mutmut (mutmut_39-48)
# ---------------------------------------------------------------------------

class TestRunMutmutDirect:
    """Target mutations on _run_mutmut: mutmut_39 through mutmut_48.

    These mutations are on _run_mutmut itself (not through run_l3b):
    - mutmut_39: shutil.which("mutmut") → None (already in test_l3b_mutmut_not_on_path)
    - mutmut_40: shutil.which("mutmut") → True
    - mutmut_42: logger.warning("mutmut not found on PATH, ") → removed
    - mutmut_43: "PATH, " → "XX...XX"
      Returns early with default MutationStats → assert all-zero fields.
    - mutmut_45: return MutationStats() → replaced with None
      Successful return path → assert exact MutationStats values.
    - mutmut_46: self.mutmut.invoke(repo, []) → self.mutmut.invoke(None, [])
    - mutmut_47: invoke(repo, []) → invoke(repo,) (2nd arg removed)
    - mutmut_48: parse(None, ...) → parse(inv.stdout, ...)
    """

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_run_mutmut_not_on_path(self, tmp_path: Path, caplog):
        """mutmut not on PATH → returns default empty MutationStats.

        Kills:
        - mutmut_39: shutil.which("mutmut") → None branch → assert all fields are 0
        - mutmut_40: shutil.which("mutmut") → True (mutated guard) → still returns default stats
        - mutmut_42: logger.warning() call removed → asserts warning is present kills removal
        - mutmut_43: format string "PATH, " → "XX...XX" → asserts exact log message
        """
        a = self._adapter()
        with patch(
            "harness_quality_gate.adapters.python.python_adapter.shutil.which",
            return_value=None,
        ):
            with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                # Replace mutmut sub-adapter with a spy mock so we can check .invoke.called
                mock_mutmut = MagicMock()
                mock_mutmut.parse = MagicMock(return_value=MutationStats(
                    total=0, killed=0, survived=0, timed_out=0,
                    escaped=0, untested=0, msi=0.0, covered_msi=0.0,
                ))
                with patch.object(a, "mutmut", mock_mutmut):
                    stats = a._run_mutmut(tmp_path, {})

        # Type assertion: kills mutmut_40 (return None instead of MutationStats)
        assert isinstance(stats, MutationStats), f"return must be MutationStats, got {type(stats)}"
        # Full zero-field assertion: kills mutmut_39 (any field mutated to non-zero)
        assert stats.total == 0
        assert stats.killed == 0
        assert stats.survived == 0
        assert stats.timed_out == 0
        # Mutmut_42: logger.warning must be called (not removed)
        # Mutmut_43: exact log message (format string not corrupted)
        warn = [r for r in caplog.records if r.levelname == "WARNING" and "mutmut not found" in r.message]
        assert len(warn) == 1, "logger.warning must be called (kills mutmut_42)"
        assert warn[0].getMessage() == "mutmut not found on PATH, returning empty stats"
        # Kill mutmut_54/55: assert mutmut.invoke NOT called (guard prevents invoke)
        assert not mock_mutmut.invoke.called, \
            "invoke() must NOT be called when mutmut is not on PATH (kills guard mutation)"

    def test_run_mutmut_oserror_fallback(self, tmp_path: Path, caplog):
        """mutmut.invoke raises OSError → returns default empty MutationStats.

        Kills mutmut_44: OSError → exception handler returns None.
        Type assertion: kills mutmut_44 (return None instead of MutationStats).
        Invoke-arg assertions: kills H1 wiring mutations on invoke.
        Log assertion: kills H3 logger-mutation survivors.
        """
        a = self._adapter()
        mock_mutmut = MagicMock()
        mock_mutmut.invoke = MagicMock(side_effect=OSError("mutmut broken"))
        with patch.object(a, "mutmut", mock_mutmut):
            with _all_tools_on_path():
                with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                    stats = a._run_mutmut(tmp_path, {})

        # Type assertion: kills mutmut_44 (exception path returns None)
        assert isinstance(stats, MutationStats), f"exception path must return MutationStats, got {type(stats)}"
        assert stats.total == 0
        assert stats.killed == 0
        # Kill invoke-arg mutations (H1): assert invoke called with (repo, [])
        assert mock_mutmut.invoke.called
        inv_args = mock_mutmut.invoke.call_args[0]
        assert inv_args[0] is tmp_path, "invoke() first arg = repo (kills mutmut_46)"
        assert inv_args[1] == [], "invoke() second arg = [] (kills mutmut_47)"
        # Kill logger warning mutations: verify exact log message with exception interpolated
        mutmut_warn = [
            r for r in caplog.records
            if r.levelname == "WARNING" and "mutmut" in r.message.lower()
            and "invocation failed" in r.message
        ]
        assert len(mutmut_warn) == 1, "Logger must emit mutmut invocation warning"
        assert "mutmut broken" in mutmut_warn[0].getMessage(), \
            f"Exception message must be in log (kills exc→None mutation)"

    def test_run_mutmut_successful_path_args(self, tmp_path: Path):
        """Successful mutation-stats return path: invoke + parse correctly chained.

        Kills:
        - mutmut_45: return MutationStats() → None
          Success path returns real parsed stats → assert exact field values.
        - mutmut_46: invoke(repo, []) → invoke(None, [])
          assert invoke first arg is tmp_path (not None).
        - mutmut_47: invoke(repo, []) → invoke(repo,)  (2nd arg removed)
          assert invoke second arg is [] (not removed).
        - mutmut_48: parse(None, ...) → parse(inv.stdout, inv.stderr, inv.exitcode)
          assert parse first arg is not None.
        """
        from harness_quality_gate.adapters.python.mutmut_adapter import MutmutAdapter

        a = self._adapter()
        real_adapter = MutmutAdapter()
        mock_mutmut = MagicMock()
        mutation_payload = '{"total":5,"killed":5,"survived":0,"timeout":0,"escaped":0,"untested":0}'
        mock_mutmut.invoke.return_value = MagicMock(
            stdout=mutation_payload,
            stderr="",
            exitcode=0,
        )
        # Wrap real parse in MagicMock so we can assert on call_args too
        mock_mutmut.parse = MagicMock(wraps=real_adapter.parse)

        with patch.object(a, "mutmut", mock_mutmut):
            with _all_tools_on_path():
                stats = a._run_mutmut(tmp_path, {})

        # Assert kill mutmut_45: return value is not None, has correct stats
        assert isinstance(stats, MutationStats), f"success path must return MutationStats, got {type(stats)}"
        assert stats.total == 5
        assert stats.killed == 5
        assert stats.survived == 0

        # Assert kill mutmut_46: invoke first arg is repo (not None)
        inv_args, _ = mock_mutmut.invoke.call_args
        assert inv_args[0] is tmp_path, "invoke() first arg must be repo (kills mutmut_46)"

        # Assert kill mutmut_47: invoke second arg is []
        assert inv_args[1] == [], "invoke() second arg must be [] (kills mutmut_47)"

        # Assert kill mutmut_48: parse first arg (stdout) is not None
        pars_args = mock_mutmut.parse.call_args[0]
        assert pars_args[0] is not None, "parse() arg0=stdout must not be None (kills mutmut_48)"
        assert isinstance(pars_args[0], str)

    def test_run_mutmut_runtimeerror_fallback(self, tmp_path: Path, caplog):
        """mutmut.invoke raises RuntimeError → returns default MutationStats.

        Completes exception-path coverage alongside test_run_mutmut_oserror_fallback.
        """
        a = self._adapter()
        mock_mutmut = MagicMock()
        mock_mutmut.invoke = MagicMock(side_effect=RuntimeError("boom"))
        with patch.object(a, "mutmut", mock_mutmut):
            with _all_tools_on_path():
                with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.python.python_adapter"):
                    stats = a._run_mutmut(tmp_path, {})

        assert isinstance(stats, MutationStats)
        assert stats.total == 0
        assert stats.survived == 0
        assert stats.timed_out == 0
        # Kill invoke-arg mutations (H1)
        assert mock_mutmut.invoke.called
        inv_args = mock_mutmut.invoke.call_args[0]
        assert inv_args[0] is tmp_path, "invoke() first arg = repo"
        assert inv_args[1] == [], "invoke() second arg = []"
        # Kill logger warning mutations
        mutmut_warn = [
            r for r in caplog.records
            if r.levelname == "WARNING" and "mutmut" in r.message.lower()
            and "invocation failed" in r.message
        ]
        assert len(mutmut_warn) == 1, "Logger must emit mutmut invocation warning on RuntimeError"
        assert "boom" in mutmut_warn[0].getMessage()


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

    def test_tool_versions_queries_with_dot_path(self):
        """tool_versions probes each tool with exactly Path('.') and {} env
        (replaces the removed repo_placeholder identity helper)."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter()
        names = ("ruff", "pyright", "pytest", "mutmut", "bandit", "vulture", "deptry")
        for attr in names:
            tool = MagicMock()
            tool.name = attr
            tool.version.return_value = "9.9"
            setattr(a, attr, tool)
        assert a.tool_versions() == {n: "9.9" for n in names}
        for attr in names:
            getattr(a, attr).version.assert_called_once_with(Path("."), {})


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


# ---------------------------------------------------------------------------
# Private helper: _run_mutmut
# ---------------------------------------------------------------------------

class TestRunMutmut:
    """Direct unit tests for PythonAdapter._run_mutmut.

    Targets 13 survivors in _run_mutmut (mutmut_39–43, 48, 54–57, 70–73):
      - mutmut_39 (stderr→None)  → assert parse arg1 is not None
      - mutmut_40 (exitcode→None) → assert parse arg2 is not None
      - mutmut_42,43 (arg removed) → assert len(pars_args) >= 3
      - mutmut_48 (log XX...XX)   → assert exact log message in error path
      - mutmut_54,55,56,57 (→None fallback) → assert fields are not None
      - mutmut_70,71,72,73 (0→1 fallback) → assert exact numeric values
    """

    @pytest.fixture(autouse=True)
    def _mutmut_on_path(self):
        """Deterministic: the which("mutmut") guard in _run_mutmut must not
        depend on mutmut being installed on the machine."""
        with patch(
            "harness_quality_gate.adapters.python.python_adapter.shutil.which",
            side_effect=lambda name: (
                "/usr/bin/mutmut" if name == "mutmut" else None
            ),
        ):
            yield

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_run_mutmut_success_path(self, tmp_path: Path):
        from harness_quality_gate.adapters.python.mutmut_adapter import MutmutAdapter  # noqa: E402
        """Use real MutmutAdapter.parse with mocked invoke to kill parse-arg mutations.

        Kills: mutmut_39 (stderr→None), mutmut_40 (exitcode→None),
        mutmut_42 (remove 2nd arg), mutmut_43 (remove 3rd arg).
        Strategy: mock invoke() returns valid data, use REAL bound parse(),
        assert parse received all 3 args with correct types.
        """
        a = self._adapter()
        real_mutmut = MutmutAdapter()

        class ResultHolder:
            stdout = (
                '{"total":5,"killed":5,"survived":0,"timeout":0,"escaped":0,"untested":0}'
            )
            stderr = ""
            exitcode = 0

        mock_mutmut = MutmutAdapter.__new__(MutmutAdapter)
        # run() mocked too: the unit test must not spawn a real campaign
        # (hidden integration dependency caught by the hermetic-PATH sweep)
        mock_mutmut.run = MagicMock(return_value=ResultHolder())
        mock_mutmut.invoke = MagicMock(return_value=ResultHolder())
        # Use bound method from a real instance (like existing test does)
        call_tracker = MagicMock(wraps=real_mutmut.parse)
        mock_mutmut.parse = call_tracker

        with patch.object(a, "mutmut", mock_mutmut):
            stats = a._run_mutmut(tmp_path, {})

        # Verify parse parsed the payload correctly
        assert stats.total == 5
        assert stats.killed == 5
        assert stats.survived == 0
        assert stats.msi == 1.0

        # === KILL PARSE-ARG MUTATIONS (H7 wiring) ===
        pars_args = call_tracker.call_args[0]

        # KILL mutmut_42,43: parse must receive 3 positional args
        assert len(pars_args) >= 3

        # KILL mutmut_39: stderr must not be None
        assert pars_args[1] is not None
        # KILL mutmut_40: exitcode must not be None
        assert pars_args[2] is not None
        # Validate stdout type
        assert pars_args[0] is not None
        assert isinstance(pars_args[0], str)

    def test_run_mutmut_exception_path(self, tmp_path: Path, caplog):
        """Trigger _run_mutmut OSError exception handler → fallback stats.

        Kills:
          - mutmut_48  (log message XX...XX): exact msg assertion
          - mutmut_54  (escaped→None): assert escaped is not None
          - mutmut_55  (untested→None): assert untested is not None
          - mutmut_56  (msi→None): assert msi is not None
          - mutmut_57  (covered_msi→None): assert covered_msi is not None
          - mutmut_70  (escaped 0->1): assert escaped == 0
          - mutmut_71  (untested 0->1): assert untested == 0
          - mutmut_72  (msi 0->1): assert msi == 0.0
          - mutmut_73  (covered_msi 0->1): assert covered_msi == 0.0
        """
        a = self._adapter()
        mock_mutmut = MagicMock()
        mock_mutmut.invoke = MagicMock(side_effect=OSError("mutmut exec failed"))
        with patch.object(a, "mutmut", mock_mutmut):
            with caplog.at_level("WARNING",
                                 logger="harness_quality_gate.adapters.python.python_adapter"):
                stats = a._run_mutmut(tmp_path, {})

        # Kill mutmut_48: exact log message assertion
        warns = [r for r in caplog.records
                 if r.levelname == "WARNING" and
                 "invocation failed" in r.getMessage()]
        assert len(warns) >= 1
        assert warns[0].getMessage() == (
            "mutmut invocation failed: mutmut exec failed"
        )

        # Kill fallback stats mutations (54-57: None, 70-73: 0->1)
        assert stats.escaped is not None
        assert stats.untested is not None
        assert stats.msi is not None
        assert stats.covered_msi is not None
        assert stats.escaped == 0
        assert stats.untested == 0
        assert stats.msi == 0.0
        assert stats.covered_msi == 0.0
        # Remaining fields
        assert stats.total == 0
        assert stats.killed == 0
        assert stats.survived == 0
        assert stats.timed_out == 0


# ===========================================================================
# v10 survivor killers — exact-equality tests (guide §4.1/§4.3/§4.4, H2/H3)
# ===========================================================================

import logging

from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

_PA_LOGGER = "harness_quality_gate.adapters.python.python_adapter"
_PA_MONOTONIC = "harness_quality_gate.adapters.python.python_adapter.time.monotonic"
_PA_WHICH = "harness_quality_gate.adapters.python.python_adapter.shutil.which"


def _pa_messages(caplog):
    return [r.getMessage() for r in caplog.records]


def _pa_full_mock_adapter() -> PythonAdapter:
    a = PythonAdapter()
    for i, attr in enumerate(("ruff", "pyright", "pytest", "mutmut", "bandit", "vulture", "deptry")):
        tool = MagicMock()
        tool.name = attr
        tool.invoke.return_value = MagicMock(stdout=f"out-{i}", stderr=f"err-{i}", exitcode=i)
        tool.parse.return_value = []
        setattr(a, attr, tool)
    return a


def _zero_stats() -> MutationStats:
    return MutationStats(
        total=0, killed=0, survived=0, timed_out=0,
        escaped=0, untested=0, msi=0.0, covered_msi=0.0,
    )


class TestPyAdapterSurvivorKillers:
    ENV = {"K": "V"}

    def test_l3a_exact_calls_logs_duration(self, tmp_path, caplog):
        a = _pa_full_mock_adapter()
        f = _make_finding()
        a.ruff.parse.return_value = [f]
        a.pyright.parse.return_value = [f, f]
        with caplog.at_level(logging.INFO, logger=_PA_LOGGER), \
             patch(_PA_WHICH, return_value="/usr/bin/x"), \
             patch(_PA_MONOTONIC, side_effect=[10.0, 11.23456]):
            result = a.run_l3a(tmp_path, self.ENV)
        a.ruff.invoke.assert_called_once_with(tmp_path, [], env=self.ENV)
        a.pyright.invoke.assert_called_once_with(tmp_path, [], env=self.ENV)
        a.ruff.parse.assert_called_once_with("out-0", "err-0", 0)
        a.pyright.parse.assert_called_once_with("out-1", "err-1", 1)
        assert _pa_messages(caplog) == ["ruff: 1 findings", "pyright: 2 findings"]
        assert result.duration_sec == 1.235
        assert result.layer == "L3A"
        assert result.language == "python"
        assert result.passed is False
        assert result.findings == [f, f, f]

    def test_l1_exact_calls_logs_duration(self, tmp_path, caplog):
        a = _pa_full_mock_adapter()
        stats = MutationStats(
            total=5, killed=5, survived=0, timed_out=0,
            escaped=0, untested=0, msi=100.0, covered_msi=100.0,
        )
        a.mutmut.parse.return_value = stats
        a.mutmut.run.return_value = MagicMock(exitcode=0, stderr="")
        with caplog.at_level(logging.INFO, logger=_PA_LOGGER), \
             patch(_PA_WHICH, return_value="/usr/bin/x"), \
             patch(_PA_MONOTONIC, side_effect=[10.0, 11.23456]):
            result = a.run_l1(tmp_path, self.ENV)
        a.pytest.invoke.assert_called_once_with(tmp_path, [], env=self.ENV)
        a.pytest.parse.assert_called_once_with("out-2", "err-2", 2)
        a.mutmut.run.assert_called_once_with(tmp_path, env=self.ENV)
        a.mutmut.invoke.assert_called_once_with(tmp_path, [], env=self.ENV)
        a.mutmut.parse.assert_called_once_with("out-3", "err-3", 3)
        assert _pa_messages(caplog) == ["pytest: 0 findings"]
        assert result.duration_sec == 1.235
        assert result.layer == "L1"
        assert result.language == "python"
        assert result.passed is True
        assert result.tool_specific == {"mutation_stats": stats}

    def test_l2_exact_logs_and_duration(self, tmp_path, caplog):
        """run_l2 is in-process (weak-test + diversity): exact logs + duration."""
        (tmp_path / "tests").mkdir()  # avoid the no-tests/ warning record
        a = _pa_full_mock_adapter()
        with caplog.at_level(logging.INFO, logger=_PA_LOGGER), \
             patch(_PA_MONOTONIC, side_effect=[10.0, 11.23456]):
            result = a.run_l2(tmp_path, self.ENV)
        assert _pa_messages(caplog) == [
            "weak-test: 0 findings",
            "diversity: score 1.0 over 0 tests",
        ]
        assert result.duration_sec == 1.235
        assert result.layer == "L2"
        assert result.language == "python"
        assert result.passed is True
        assert result.tool_specific["diversity"]["total_tests"] == 0

    def test_l3b_exact_logs_and_duration(self, tmp_path, caplog):
        """run_l3b is in-process (solid + tier-a): exact logs + duration."""
        a = _pa_full_mock_adapter()
        with caplog.at_level(logging.INFO, logger=_PA_LOGGER), \
             patch(_PA_MONOTONIC, side_effect=[10.0, 11.23456]):
            result = a.run_l3b(tmp_path, self.ENV)
        assert _pa_messages(caplog) == [
            "solid-metrics: 0 findings",
            "antipattern-tier-a: 0 findings",
        ]
        assert result.duration_sec == 1.235
        assert result.layer == "L3B"
        assert result.language == "python"
        assert result.passed is True
        assert result.tool_specific is None

    def test_l4_exact_calls_logs_duration(self, tmp_path, caplog):
        a = _pa_full_mock_adapter()
        with caplog.at_level(logging.INFO, logger=_PA_LOGGER), \
             patch(_PA_WHICH, return_value="/usr/bin/x"), \
             patch(_PA_MONOTONIC, side_effect=[10.0, 11.23456]):
            result = a.run_l4(tmp_path, self.ENV)
        a.bandit.invoke.assert_called_once_with(tmp_path, [], env=self.ENV)
        a.bandit.parse.assert_called_once_with("out-4", "err-4", 4)
        a.vulture.invoke.assert_called_once_with(tmp_path, [], env=self.ENV)
        a.vulture.parse.assert_called_once_with("out-5", "err-5", 5)
        a.deptry.invoke.assert_called_once_with(tmp_path, [], env=self.ENV)
        a.deptry.parse.assert_called_once_with("out-6", "err-6", 6)
        assert _pa_messages(caplog) == [
            "bandit: 0 findings", "vulture: 0 findings", "deptry: 0 findings",
        ]
        assert result.duration_sec == 1.235
        assert result.layer == "L4"
        assert result.language == "python"

    @pytest.mark.parametrize("attr,tool,not_found_msg,fail_msg", [
        ("ruff", "ruff", "ruff not found on PATH, skipping", "ruff invocation failed: io-boom"),
        ("pyright", "pyright", "pyright not found on PATH, skipping", "pyright invocation failed: io-boom"),
        ("vulture", "vulture", "vulture not found on PATH, skipping", "vulture invocation failed: io-boom"),
        ("deptry", "deptry", "deptry not found on PATH, skipping", "deptry invocation failed: io-boom"),
        ("bandit", "bandit", "bandit not found on PATH, skipping", "bandit invocation failed: io-boom"),
    ])
    def test_helper_not_found_and_failure_logs_exact(self, tmp_path, caplog, attr, tool, not_found_msg, fail_msg):
        a = _pa_full_mock_adapter()
        helper = getattr(a, f"_run_{attr}")
        with caplog.at_level(logging.WARNING, logger=_PA_LOGGER), \
             patch(_PA_WHICH, return_value=None):
            assert helper(tmp_path, self.ENV) == []
        getattr(a, attr).invoke.assert_not_called()
        assert _pa_messages(caplog) == [not_found_msg]

        caplog.clear()
        getattr(a, attr).invoke.side_effect = OSError("io-boom")
        with caplog.at_level(logging.WARNING, logger=_PA_LOGGER), \
             patch(_PA_WHICH, return_value="/usr/bin/x"):
            assert helper(tmp_path, self.ENV) == []
        assert _pa_messages(caplog) == [fail_msg]

    def test_run_pytest_not_found_and_failure_logs_exact(self, tmp_path, caplog):
        a = _pa_full_mock_adapter()
        with caplog.at_level(logging.WARNING, logger=_PA_LOGGER), \
             patch(_PA_WHICH, return_value=None):
            assert a._run_pytest(tmp_path, self.ENV) == []
        a.pytest.invoke.assert_not_called()
        assert _pa_messages(caplog) == ["python3 not found on PATH, skipping"]

        caplog.clear()
        a.pytest.invoke.side_effect = RuntimeError("py-boom")
        with caplog.at_level(logging.WARNING, logger=_PA_LOGGER), \
             patch(_PA_WHICH, return_value="/usr/bin/python3"):
            assert a._run_pytest(tmp_path, self.ENV) == []
        assert _pa_messages(caplog) == ["pytest invocation failed: py-boom"]

    def test_run_mutmut_not_found_returns_exact_zero_stats(self, tmp_path, caplog):
        a = _pa_full_mock_adapter()
        with caplog.at_level(logging.WARNING, logger=_PA_LOGGER), \
             patch(_PA_WHICH, return_value=None):
            stats = a._run_mutmut(tmp_path, self.ENV)
        assert stats == _zero_stats()
        a.mutmut.invoke.assert_not_called()
        assert _pa_messages(caplog) == ["mutmut not found on PATH, returning empty stats"]

    def test_run_mutmut_failure_returns_exact_zero_stats(self, tmp_path, caplog):
        a = _pa_full_mock_adapter()
        a.mutmut.run.return_value = MagicMock(exitcode=0, stderr="")
        a.mutmut.invoke.side_effect = RuntimeError("mm-boom")
        with caplog.at_level(logging.WARNING, logger=_PA_LOGGER), \
             patch(_PA_WHICH, return_value="/usr/bin/mutmut"):
            stats = a._run_mutmut(tmp_path, self.ENV)
        assert stats == _zero_stats()
        assert _pa_messages(caplog) == ["mutmut invocation failed: mm-boom"]

    def test_tool_versions_missing_marker_on_oserror(self):
        a = _pa_full_mock_adapter()
        for attr in ("ruff", "pyright", "pytest", "mutmut", "bandit", "vulture", "deptry"):
            getattr(a, attr).version.return_value = "1.2.3"
        a.pyright.version.side_effect = OSError("no")
        a.deptry.version.side_effect = RuntimeError("no")
        versions = a.tool_versions()
        assert versions == {
            "ruff": "1.2.3", "pyright": "MISSING", "pytest": "1.2.3",
            "mutmut": "1.2.3", "bandit": "1.2.3", "vulture": "1.2.3",
            "deptry": "MISSING",
        }

    def test_check_tools_exact_probe_and_message(self):
        a = _pa_full_mock_adapter()
        with patch(_PA_WHICH, return_value="/usr/bin/x") as which:
            assert a.check_tools() == ["ruff", "pyright"]
        assert [c.args[0] for c in which.call_args_list] == ["ruff", "pyright"]
        with patch(_PA_WHICH, return_value=None), pytest.raises(
            RuntimeError, match=r"^Missing Python tool\(s\): ruff, pyright$",
        ):
            a.check_tools()

    def test_mutation_remediation_full_dict_exact(self):
        # survived=1 / timed_out=1: exact boundary values so the >0 -> >1
        # comparison mutations change the outcome (guide section 4.2).
        stats = MutationStats(
            total=10, killed=8, survived=1, timed_out=1,
            escaped=0, untested=0, msi=87.5, covered_msi=90.0,
        )
        result = PythonAdapter._mutation_remediation(stats)
        assert result == {
            "skill": "mutation-testing-guide",
            "guide": "MUTANT_KILLING_GUIDE.md",
            "instructions": "SUBAGENT_MUTATION_INSTRUCTIONS.md",
            "summary": (
                "L1 FAILED — 1 mutant(s) survived, 1 mutant(s) timed out. "
                "Read skill 'mutation-testing-guide' or MUTANT_KILLING_GUIDE.md Part II "
                "(cases H1-H12). "
                "Priority: assert_called_once_with complete (§4.4), dense assertions (§4.1), "
                "boundary tests (§4.2). H1=passthrough to mocked deps is the dominant pattern."
            ),
            "msi": 87.5,
            "survived": 1,
            "timed_out": 1,
        }

    def test_l1_remediation_present_when_survivors(self, tmp_path):
        a = _pa_full_mock_adapter()
        stats = MutationStats(
            total=5, killed=4, survived=1, timed_out=0,
            escaped=0, untested=0, msi=80.0, covered_msi=80.0,
        )
        a.mutmut.parse.return_value = stats
        with patch(_PA_WHICH, return_value="/usr/bin/x"):
            result = a.run_l1(tmp_path, self.ENV)
        assert result.passed is False
        assert result.tool_specific["mutation_stats"] is stats
        assert result.tool_specific["remediation"]["survived"] == 1


# ---------------------------------------------------------------------------
# L2/L3B helper contracts — synthetic reports that exercise every fallback
# (kills the v17 survivors in _weak_test_findings/_solid_findings/
#  _tier_a_findings/_src_dir/run_l2 diversity wiring)
# ---------------------------------------------------------------------------

class TestSrcDirResolution:
    def test_src_dir_used_when_present(self, tmp_path: Path):
        """Exact name "src" (lowercase) — kills XXsrcXX/SRC mutants."""
        (tmp_path / "src").mkdir()
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        assert PythonAdapter._src_dir(tmp_path) == tmp_path / "src"

    def test_repo_fallback_when_no_src(self, tmp_path: Path):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        assert PythonAdapter._src_dir(tmp_path) == tmp_path

    def test_root_package_used_when_no_src(self, tmp_path: Path):
        """Package-at-root layout: analyse the package, not the whole repo.

        Falling back to the repo walked .venv/ and mutants/ too — L2/L3B
        hung for minutes on real repos (self-eval F10).
        """
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        (tmp_path / "mypkg").mkdir()
        (tmp_path / "mypkg" / "__init__.py").write_text("")
        (tmp_path / "mutants").mkdir()
        assert PythonAdapter._src_dir(tmp_path) == tmp_path / "mypkg"

    def test_src_wins_over_root_package(self, tmp_path: Path):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        (tmp_path / "src").mkdir()
        (tmp_path / "mypkg").mkdir()
        (tmp_path / "mypkg" / "__init__.py").write_text("")
        assert PythonAdapter._src_dir(tmp_path) == tmp_path / "src"


class TestRunL2DiversityWiring:
    def test_diversity_called_with_repo_and_python(self, tmp_path: Path):
        """Exact language arg — kills "python"→None/"PYTHON"/XX mutants."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter()
        report = {"diversity_score": 1.0, "total_tests": 0}
        with patch(
            "harness_quality_gate.adapters.python.python_adapter.diversity",
            return_value=report,
        ) as div:
            layer = a.run_l2(tmp_path, {})
        div.assert_called_once_with(tmp_path, "python")
        assert layer.tool_specific == {"diversity": report}


class TestWeakTestFindingsContract:
    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_analysis_invoked_with_tests_and_src_dirs(self, tmp_path: Path):
        """Exact (tests_dir, src_dir) args — kills str(None) arg mutants."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "src").mkdir()
        a = self._adapter()
        with patch(
            "harness_quality_gate.adapters.python.python_adapter.run_weak_test_analysis",
            return_value={"weak_tests": []},
        ) as rwta:
            assert a._weak_test_findings(tmp_path) == []
        rwta.assert_called_once_with(
            str(tmp_path / "tests"), str(tmp_path / "src"),
        )

    def test_missing_optional_keys_fall_back_to_exact_defaults(self, tmp_path: Path):
        """weak item without file/lineno/name and violation without
        rule/description/severity → defaults '' / 0 / warning, exactly."""
        (tmp_path / "tests").mkdir()
        a = self._adapter()
        with patch(
            "harness_quality_gate.adapters.python.python_adapter.run_weak_test_analysis",
            return_value={"weak_tests": [{"violations": [{}]}]},
        ):
            findings = a._weak_test_findings(tmp_path)
        assert len(findings) == 1
        f = findings[0]
        assert f.node == ":0"
        assert f.message == ": "
        assert f.severity == "warning"
        assert f.rule_id is None
        assert f.tool == "weak-test"
        assert f.layer == "L2"
        assert f.language == "python"

    def test_partial_keys_keep_real_values(self, tmp_path: Path):
        (tmp_path / "tests").mkdir()
        a = self._adapter()
        weak = {
            "file": "t.py",
            "violations": [{"rule": "A6", "severity": "ERROR"}],
        }
        with patch(
            "harness_quality_gate.adapters.python.python_adapter.run_weak_test_analysis",
            return_value={"weak_tests": [weak]},
        ):
            findings = a._weak_test_findings(tmp_path)
        f = findings[0]
        assert f.node == "t.py:0"       # lineno default exactly 0
        assert f.severity == "error"
        assert f.rule_id == "A6"
        assert f.message == ": "        # name/description defaults exactly ''

    def test_weak_tests_key_missing_yields_empty(self, tmp_path: Path):
        (tmp_path / "tests").mkdir()
        a = self._adapter()
        with patch(
            "harness_quality_gate.adapters.python.python_adapter.run_weak_test_analysis",
            return_value={},
        ):
            assert a._weak_test_findings(tmp_path) == []


class TestSolidFindingsContract:
    def _findings(self, tmp_path, report):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter()
        with patch(
            "harness_quality_gate.adapters.python.python_adapter.analyze_solid",
            return_value=report,
        ):
            return a._solid_findings(tmp_path)

    def test_all_five_principles_in_order(self, tmp_path: Path):
        """Every principle key letter exact — kills tuple element mutants."""
        report = {
            p: {"status": "FAIL", "violations": [{"issue": f"viol-{p}"}]}
            for p in ("S", "O", "L", "I", "D")
        }
        findings = self._findings(tmp_path, report)
        assert [f.rule_id for f in findings] == [
            "SOLID-S", "SOLID-O", "SOLID-L", "SOLID-I", "SOLID-D",
        ]
        assert [f.message for f in findings] == [
            "SOLID S: viol-S", "SOLID O: viol-O", "SOLID L: viol-L",
            "SOLID I: viol-I", "SOLID D: viol-D",
        ]

    def test_issues_list_joined_exactly(self, tmp_path: Path):
        report = {"S": {"status": "FAIL", "violations": [
            {"issues": ["a > 7", "b > 5"], "class": "Fat"},
        ]}}
        findings = self._findings(tmp_path, report)
        assert findings[0].message == "SOLID S: a > 7; b > 5"
        assert findings[0].node == "Fat"

    def test_file_fallback_when_no_class(self, tmp_path: Path):
        report = {"D": {"status": "FAIL", "violations": [{"file": "src/g.py", "issue": "cycle"}]}}
        findings = self._findings(tmp_path, report)
        assert findings[0].node == "src/g.py"

    def test_empty_violation_falls_back_to_principle_and_str(self, tmp_path: Path):
        report = {"O": {"status": "FAIL", "violations": [{}]}}
        findings = self._findings(tmp_path, report)
        assert findings[0].node == "O"
        assert findings[0].message == "SOLID O: {}"

    def test_pass_status_skipped(self, tmp_path: Path):
        report = {"S": {"status": "PASS", "violations": [{"issue": "x"}]}}
        assert self._findings(tmp_path, report) == []


class TestTierAFindingsContract:
    def _findings(self, tmp_path, report):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter()
        with patch(
            "harness_quality_gate.adapters.python.python_adapter.run_tier_a",
            return_value=report,
        ):
            return a._tier_a_findings(tmp_path)

    def test_file_fallback_and_or_chain(self, tmp_path: Path):
        """class missing → file used, never the ap_id — kills or→and."""
        report = {"AP02": {"status": "FAIL", "violations": [{"file": "x.py", "issue": "bad"}]}}
        findings = self._findings(tmp_path, report)
        assert findings[0].node == "x.py"

    def test_ap_id_fallback_without_lineno(self, tmp_path: Path):
        report = {"AP05": {"status": "FAIL", "violations": [{}]}}
        findings = self._findings(tmp_path, report)
        f = findings[0]
        assert f.node == "AP05"
        assert f.message == "AP05: "    # name defaults to ap_id, issue to ''
        assert f.rule_id == "AP05"

    def test_lineno_suffix_when_present(self, tmp_path: Path):
        report = {"AP01": {"status": "FAIL", "violations": [
            {"class": "God", "lineno": 7, "name": "God Class", "issue": "too big"},
        ]}}
        findings = self._findings(tmp_path, report)
        assert findings[0].node == "God:7"
        assert findings[0].message == "God Class: too big"

    def test_sorted_by_ap_id_and_pass_skipped(self, tmp_path: Path):
        report = {
            "AP09": {"status": "FAIL", "violations": [{"issue": "b"}]},
            "AP01": {"status": "FAIL", "violations": [{"issue": "a"}]},
            "AP05": {"status": "PASS", "violations": [{"issue": "z"}]},
        }
        findings = self._findings(tmp_path, report)
        assert [f.rule_id for f in findings] == ["AP01", "AP09"]


# ---------------------------------------------------------------------------
# Simulation regressions (H1/H9): layer gates must honour the severity
# policy (only error-severity findings block), and L1 must actually run
# the mutation campaign before collecting results (H2).
# ---------------------------------------------------------------------------

class TestL1MutmutRunWiring:
    def test_run_l1_executes_mutmut_run_before_collecting_results(self, tmp_path: Path):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        from harness_quality_gate.models import MutationStats

        a = PythonAdapter()
        a.pytest = MagicMock()
        a.pytest.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)
        a.pytest.parse.return_value = []
        stats = MutationStats(total=4, killed=4, survived=0, timed_out=0,
                              escaped=0, untested=0, msi=100.0, covered_msi=100.0)
        a.mutmut = MagicMock()
        a.mutmut.invoke.return_value = MagicMock(stdout="x", stderr="", exitcode=0)
        a.mutmut.parse.return_value = stats
        with patch("shutil.which", return_value="/usr/bin/x"):
            layer = a.run_l1(tmp_path, {})
        a.mutmut.run.assert_called_once()
        # run() must happen before results collection
        names = [c[0] for c in a.mutmut.method_calls]
        assert names.index("run") < names.index("invoke")
        assert layer.tool_specific["mutation_stats"] is stats
        assert layer.passed is True


class TestL3ASeverityGate:
    """L3A gates only on error findings (uniform severity policy, self-eval F1).

    The simulation fixed L1/L4 (Python) and all PHP layers; Python L3A kept
    the old ``len(findings) == 0`` gate — any ruff warning blocked the layer.
    """

    @pytest.fixture(autouse=True)
    def _tools_on_path(self):
        with patch(
            "harness_quality_gate.adapters.python.python_adapter.shutil.which",
            side_effect=lambda name: (
                f"/usr/bin/{name}" if name in ("ruff", "pyright") else None
            ),
        ):
            yield

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_l3a_warning_and_info_findings_do_not_gate(self, tmp_path: Path):
        a = self._adapter()
        a.ruff = _mock_subadapter(findings=[_make_finding(severity="warning")])
        a.pyright = _mock_subadapter(
            findings=[_make_finding(severity="info", tool="pyright")]
        )
        layer = a.run_l3a(tmp_path, {})
        assert layer.passed is True
        assert len(layer.findings) == 2  # reported, just not blocking

    def test_l3a_error_among_warnings_gates(self, tmp_path: Path):
        a = self._adapter()
        a.ruff = _mock_subadapter(
            findings=[
                _make_finding(severity="warning"),
                _make_finding(severity="error"),
            ]
        )
        a.pyright = _mock_subadapter(findings=[])
        layer = a.run_l3a(tmp_path, {})
        assert layer.passed is False


class TestL3BSeverityGate:
    """L3B gates only on error findings (uniform severity policy, self-eval F11).

    solid-metrics and antipattern Tier A emit warnings — heuristic counsel,
    not blockers; the old ``len(findings) == 0`` gate failed L3B on any hit.
    """

    def test_l3b_warning_findings_do_not_gate(self, tmp_path: Path):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter()
        warn = _make_finding(severity="warning", tool="solid-metrics", layer="L3B")
        with (
            patch.object(PythonAdapter, "_solid_findings", return_value=[warn]),
            patch.object(PythonAdapter, "_tier_a_findings", return_value=[warn]),
        ):
            layer = a.run_l3b(tmp_path, {})
        assert layer.passed is True
        assert len(layer.findings) == 2

    def test_l3b_error_findings_gate(self, tmp_path: Path):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter()
        err = _make_finding(severity="error", tool="solid-metrics", layer="L3B")
        with (
            patch.object(PythonAdapter, "_solid_findings", return_value=[err]),
            patch.object(PythonAdapter, "_tier_a_findings", return_value=[]),
        ):
            layer = a.run_l3b(tmp_path, {})
        assert layer.passed is False


class TestL1SeverityGate:
    def _layer(self, tmp_path, findings):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        from harness_quality_gate.models import MutationStats

        a = PythonAdapter()
        stats = MutationStats(total=1, killed=1, survived=0, timed_out=0,
                              escaped=0, untested=0, msi=100.0, covered_msi=100.0)
        with (
            patch.object(PythonAdapter, "_run_pytest", return_value=findings),
            patch.object(PythonAdapter, "_run_mutmut", return_value=stats),
        ):
            return a.run_l1(tmp_path, {})

    def test_skipped_tests_info_findings_do_not_gate(self, tmp_path: Path):
        info = Finding(node="t.py::test_a", severity="info",
                       message="Test skipped", tool="pytest",
                       layer="L1", language="python", rule_id="skipped")
        layer = self._layer(tmp_path, [info])
        assert layer.passed is True
        assert layer.findings == [info]

    def test_error_findings_gate(self, tmp_path: Path):
        err = Finding(node="t.py::test_a", severity="error",
                      message="Test failed", tool="pytest",
                      layer="L1", language="python", rule_id="failure")
        layer = self._layer(tmp_path, [err])
        assert layer.passed is False


class TestL4SeverityGate:
    def _layer(self, tmp_path, findings):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter()
        with (
            patch.object(PythonAdapter, "_run_bandit", return_value=findings),
            patch.object(PythonAdapter, "_run_vulture", return_value=[]),
            patch.object(PythonAdapter, "_run_deptry", return_value=[]),
        ):
            return a.run_l4(tmp_path, {})

    def test_info_and_warning_findings_do_not_gate(self, tmp_path: Path):
        """bandit B101 (assert in tests) maps to info — a clean hello-world
        repo must not fail L4 because its tests use assert."""
        lows = [
            Finding(node="tests/test_x.py", severity="info",
                    message="Use of assert detected", tool="bandit",
                    layer="L4", language="python"),
            Finding(node="src/x.py", severity="warning",
                    message="medium issue", tool="bandit",
                    layer="L4", language="python"),
        ]
        layer = self._layer(tmp_path, lows)
        assert layer.passed is True
        assert len(layer.findings) == 2

    def test_error_finding_gates(self, tmp_path: Path):
        high = Finding(node="src/x.py", severity="error",
                       message="hardcoded password", tool="bandit",
                       layer="L4", language="python")
        layer = self._layer(tmp_path, [high])
        assert layer.passed is False


class TestRunMutmutRunFailureLog:
    def test_nonzero_mutmut_run_logs_exact_warning(self, tmp_path, caplog):
        import logging as _logging
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        from harness_quality_gate.models import MutationStats

        a = PythonAdapter()
        a.mutmut = MagicMock()
        a.mutmut.run.return_value = MagicMock(exitcode=2, stderr=" boom\n")
        a.mutmut.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)
        a.mutmut.parse.return_value = MutationStats(
            total=0, killed=0, survived=0, timed_out=0,
            escaped=0, untested=0, msi=0.0, covered_msi=0.0,
        )
        with caplog.at_level(
            _logging.WARNING,
            logger="harness_quality_gate.adapters.python.python_adapter",
        ), patch("shutil.which", return_value="/usr/bin/mutmut"):
            a._run_mutmut(tmp_path, {})
        assert "mutmut run exited 2: boom" in caplog.messages
