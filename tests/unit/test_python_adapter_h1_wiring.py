"""Kill H1 WIRING/PASSTHROUGH survivors on python_adapter.py.

Mutants targeted (all Type H1 — passthrough de argumentos a colaboradores
mockeados o defaults muertos):

  run_l4__mutmut_5:   _run_bandit(repo, env) → _run_bandit(None, env)
  run_l4__mutmut_6:   _run_vulture(repo, env) → _run_vulture(None, env)
  run_l4__mutmut_17:  run_l4() calls resolve_tool with mutated args (env=None)
  run_l4__mutmut_33:  if not bandit_findings: → if bandit_findings: (guard
  run_l4__mutmut_35:  LayerResult(findings=None) instead of findings=[]
  run_l4__mutmut_67:  LayerResult(duration_sec=None) instead of 0.0
  run_l4__mutmut_68:  LayerResult passed=mutation (keyword arg changes)
  run_l4__mutmut_70:  resolve_tool("bandit", None) instead of resolve_tool("bandit", repo)
  run_l4__mutmut_71:  resolve_tool(tool_name, None) instead of resolve_tool(tool_name, repo)
  run_l4__mutmut_73:  resolve_tool("bandit", None) instead of resolve_tool("bandit", repo)
  _run_bandit__mutmut_3:  resolve_tool("bandit", repo) → resolve_tool("bandit", None)
  _run_mutmut__mutmut_28: resolve_tool("mutmut", repo) → resolve_tool("mutmut", None)

Strategy per the MUTANT_KILLING_GUIDE §H1:
  - Wiring tests with `autospec=True` spies on _run_* to assert call_args identity
  - resolve_tool spy to verify repo is passed (not mutated to None)
  - LayerResult field-type assertions to catch []→None and 0.0→None
  - Guard condition test to catch if not X: → if X: inversion
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _resolve_with_defaults(name: str, repo: Path | None = None) -> Path:
    """resolve_tool default implementation: return /usr/bin/<name> for known tools."""
    known = ("bandit", "vulture", "deptry", "ruff", "pyright", "mutmut", "python3")
    if name in known:
        return Path(f"/usr/bin/{name}")
    # When called as resolve_tool("bandit", tmp_path) — repo is the second param
    if isinstance(repo, Path):
        return repo
    return Path(f"/usr/bin/{name}")


# ---------------------------------------------------------------------------
# run_l4 wiring and passthrough mutations
# ---------------------------------------------------------------------------


class TestRunL4Wiring:
    """Kill mutmut_5, 6: _run_bandit / _run_vulture receive None repo (H1)."""

    def _mock_all_subadapters(self):
        """Return three patched MagicMock objects for _run_bandit, _run_vulture, _run_deptry."""
        bandit_mock = MagicMock(return_value=[])
        vulture_mock = MagicMock(return_value=[])
        deptry_mock = MagicMock(return_value=[])
        return bandit_mock, vulture_mock, deptry_mock

    def test_run_l4_bandit_received_exact_repo(self, tmp_path: Path) -> None:
        """KILL: run_l4__mutmut_5 (H1).

        Spy on _run_bandit with autospec=True to verify the first argument
        maintains identity with the passed `repo`, not mutated to None.
        """
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        a = PythonAdapter()
        bandit_mock = MagicMock(return_value=[], autospec=True)
        vulture_mock = MagicMock(return_value=[], autospec=True)
        deptry_mock = MagicMock(return_value=[], autospec=True)

        with patch.object(a, "_run_bandit", bandit_mock):
            with patch.object(a, "_run_vulture", vulture_mock):
                with patch.object(a, "_run_deptry", deptry_mock):
                    with patch(
                        "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
                        side_effect=lambda n, r=None: _resolve_with_defaults(n, r)
                        if n in ("bandit", "vulture", "deptry")
                        else None,
                    ):
                        layer = a.run_l4(tmp_path, {})

        # autospec=True + assert_called_once_with kills H1 passthrough
        bandit_mock.assert_called_once_with(tmp_path, {})
        # Identity assertion kills mutmut_5: if repo was mutated to None,
        # `is tmp_path` fails (None is not tmp_path)
        assert bandit_mock.call_args.args[0] is tmp_path, (
            f"KILLS run_l4__mutmut_5: repo mutated to {bandit_mock.call_args.args[0]!r}"
        )
        assert layer.passed is True
        assert layer.findings == []

    def test_run_l4_vulture_received_exact_repo(self, tmp_path: Path) -> None:
        """KILL: run_l4__mutmut_6 (H1).

        Same wiring pattern for _run_vulture.
        """
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        a = PythonAdapter()
        bandit_mock = MagicMock(return_value=[], autospec=True)
        vulture_mock = MagicMock(return_value=[], autospec=True)
        deptry_mock = MagicMock(return_value=[], autospec=True)

        with patch.object(a, "_run_bandit", bandit_mock):
            with patch.object(a, "_run_vulture", vulture_mock):
                with patch.object(a, "_run_deptry", deptry_mock):
                    with patch(
                        "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
                        side_effect=lambda n, r=None: _resolve_with_defaults(n, r)
                        if n in ("bandit", "vulture", "deptry")
                        else None,
                    ):
                        layer = a.run_l4(tmp_path, {})

        vulture_mock.assert_called_once_with(tmp_path, {})
        assert vulture_mock.call_args.args[0] is tmp_path, (
            f"KILLS run_l4__mutmut_6: repo mutated to {vulture_mock.call_args.args[0]!r}"
        )
        assert layer.passed is True


class TestRunL4Guard:
    """KILL: run_l4__mutmut_33 (guard on bandit_findings inverted).

    Original: if not bandit_findings: → resolve_tool("bandit", repo)
    Mutated:  if bandit_findings: → resolve_tool("bandit", repo)

    With bandit_findings=[] (empty list):
      - `not []` is True → enters branch → calls resolve_tool
      - `[]` (mutated guard) is False → skips branch → does NOT call resolve_tool
    """

    def test_empty_bandit_findings_triggers_resolve_tool(self, tmp_path: Path) -> None:
        """KILL: run_l4__mutmut_33.

        When bandit_findings is empty, the original code calls
        resolve_tool("bandit", repo) to verify the tool is available.
        If the guard is inverted (mutmut_33), this call never happens.
        """
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        resolve_calls: list[tuple[str, Path | None]] = []

        def spy_resolve(name: str, repo: Path | None = None) -> Path:
            resolve_calls.append((name, repo))
            if name in ("bandit", "vulture", "deptry"):
                return Path(f"/usr/bin/{name}")
            return Path(".")

        a = PythonAdapter()
        # Use MagicMock (NOT autospec) so the return value goes to all_findings.extend()
        # and we verify the result is correct.
        with patch.object(a, "_run_bandit", return_value=[]):
            with patch.object(a, "_run_vulture", return_value=[]):
                with patch.object(a, "_run_deptry", return_value=[]):
                    with patch(
                        "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
                        side_effect=spy_resolve,
                    ):
                        layer = a.run_l4(tmp_path, {})

        # The original code MUST call resolve_tool("bandit", repo) when findings are empty
        bandit_resolves = [(n, r) for n, r in resolve_calls if n == "bandit"]
        assert len(bandit_resolves) >= 1, (
            f"KILLS run_l4__mutmut_33: resolve_tool('bandit', repo) was NOT called. "
            f"Guard may be inverted: {resolve_calls}"
        )
        # repo must be the exact Path passed to run_l4, not None
        for _, repo_arg in bandit_resolves:
            assert repo_arg is tmp_path, (
                f"KILLS mutmut_33 + mutmut_70/71: resolve_tool repo is {repo_arg!r}, "
                f"not {tmp_path!r}"
            )
        # With empty findings, passed MUST be True
        assert layer.passed is True


class TestRunL4ResultFields:
    """KILL: mutmut_35 (findings=None), mutmut_67 (duration_sec None)."""

    def test_l4_findings_is_list_not_none(self, tmp_path: Path) -> None:
        """KILL: run_l4__mutmut_35 (H1: findings=[] → findings=None).

        The LayerResult findings field must be a list, not None.
        Mutations that replace [] with None cause isinstance/findings to fail.
        """
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        a = PythonAdapter()
        # Use autospec mocks so return value is the specified value
        bandit_mock = MagicMock(return_value=[], autospec=True)
        vulture_mock = MagicMock(return_value=[], autospec=True)
        deptry_mock = MagicMock(return_value=[], autospec=True)

        with patch.object(a, "_run_bandit", bandit_mock):
            with patch.object(a, "_run_vulture", vulture_mock):
                with patch.object(a, "_run_deptry", deptry_mock):
                    with patch(
                        "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
                        side_effect=lambda n, r=None: _resolve_with_defaults(n, r)
                        if n in ("bandit", "vulture", "deptry")
                        else None,
                    ):
                        layer = a.run_l4(tmp_path, {})

        # findings MUST be a list (not None, not mutated value)
        assert isinstance(
            layer.findings, list
        ), f"KILLS run_l4__mutmut_35: findings is {type(layer.findings).__name__}"
        assert layer.findings == []

    def test_l4_duration_sec_is_float_not_none(self, tmp_path: Path) -> None:
        """KILL: run_l4__mutmut_67 (H1: duration_sec=0.0 → duration_sec=None).

        The LayerResult duration_sec must be a float, not None.
        """
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        a = PythonAdapter()
        bandit_mock = MagicMock(return_value=[], autospec=True)
        vulture_mock = MagicMock(return_value=[], autospec=True)
        deptry_mock = MagicMock(return_value=[], autospec=True)

        with patch.object(a, "_run_bandit", bandit_mock):
            with patch.object(a, "_run_vulture", vulture_mock):
                with patch.object(a, "_run_deptry", deptry_mock):
                    with patch(
                        "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
                        side_effect=lambda n, r=None: _resolve_with_defaults(n, r)
                        if n in ("bandit", "vulture", "deptry")
                        else None,
                    ):
                        layer = a.run_l4(tmp_path, {})

        assert layer.duration_sec is not None, (
            "KILLS run_l4__mutmut_67: duration_sec is None"
        )
        assert isinstance(layer.duration_sec, (int, float)), (
            f"KILLS run_l4__mutmut_67: duration_sec is {type(layer.duration_sec).__name__}"
        )


class TestRunL4ResolveToolRepo:
    """KILL: mutmut_70, 71, 73 — resolve_tool called with repo=None instead of repo.

    A spy on resolve_tool across the full run_l4 verifies ALL calls receive
    the correct repo argument (not mutated to None).
    """

    def test_l4_resolve_tool_called_with_repo_not_none(self, tmp_path: Path) -> None:
        """KILL: run_l4__mutmut_70, mutmut_71, mutmut_73 (H1).

        Spy on resolve_tool and verify ALL calls receive the exact repo
        Path passed to run_l4, never None.
        """
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        calls: list[tuple[str, Path | None]] = []

        def spy_resolve(name: str, repo: Path | None = None) -> Path:
            calls.append((name, repo))
            if name in ("bandit", "vulture", "deptry"):
                return Path(f"/usr/bin/{name}")
            return Path(".")

        a = PythonAdapter()
        bandit_mock = MagicMock(return_value=[], autospec=True)
        vulture_mock = MagicMock(return_value=[], autospec=True)
        deptry_mock = MagicMock(return_value=[], autospec=True)

        with patch.object(a, "_run_bandit", bandit_mock):
            with patch.object(a, "_run_vulture", vulture_mock):
                with patch.object(a, "_run_deptry", deptry_mock):
                    with patch(
                        "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
                        side_effect=spy_resolve,
                    ):
                        a.run_l4(tmp_path, {})

        for tool_name, repo_arg in calls:
            assert repo_arg is not None, (
                f"KILLS mutmut_70/71/73: resolve_tool({tool_name!r}, {repo_arg!r}) — "
                f"repo mutated to None"
            )
            assert repo_arg == tmp_path, (
                f"KILLS mutmut_70/71/73: resolve_tool({tool_name!r}, {repo_arg!r}) — "
                f"repo must be {tmp_path!r}"
            )


class TestRunL4LayerResultKeywordArgs:
    """KILL: mutmut_17, 68 — LayerResult keyword argument mutations."""

    def test_l4_result_passed_is_true_not_mutated(self, tmp_path: Path) -> None:
        """KILL: run_l4__mutmut_17, mutmut_68.

        With zero error findings, passed MUST be True (boolean).
        """
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        a = PythonAdapter()
        bandit_mock = MagicMock(return_value=[], autospec=True)
        vulture_mock = MagicMock(return_value=[], autospec=True)
        deptry_mock = MagicMock(return_value=[], autospec=True)

        with patch.object(a, "_run_bandit", bandit_mock):
            with patch.object(a, "_run_vulture", vulture_mock):
                with patch.object(a, "_run_deptry", deptry_mock):
                    with patch(
                        "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
                        side_effect=lambda n, r=None: _resolve_with_defaults(n, r)
                        if n in ("bandit", "vulture", "deptry")
                        else None,
                    ):
                        layer = a.run_l4(tmp_path, {})

        assert layer.passed is True, (
            f"KILLS run_l4__mutmut_17/mutmut_68: passed={layer.passed!r}"
        )
        assert isinstance(layer.passed, bool), (
            f"KILLS mutmut_68: passed is {type(layer.passed).__name__}"
        )


class TestRunL4ResolveToolRequiredTools:
    """KILL mutmut_35, 5, 6 in required_tools path of run_l4.

    Lines 401, 403: the code iterates required_tools and calls resolve_tool.
    Mutations change resolve_tool("bandit", repo) → resolve_tool("bandit", None).
    """

    def test_l4_required_tools_resolve_tool_with_repo(self, tmp_path: Path) -> None:
        """KILL mutmut_5/6/35 in the required-tools path of run_l4.

        When the code checks required_tools for language="python",
        it calls resolve_tool("bandit", repo) to verify the tool.
        Mutations that pass repo=None are caught here.
        """
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        resolve_calls: list[tuple[str, Path | None]] = []

        def spy_resolve(name: str, repo: Path | None = None) -> Path:
            resolve_calls.append((name, repo))
            return Path(f"/usr/bin/{name}")

        a = PythonAdapter()
        bandit_mock = MagicMock(return_value=[], autospec=True)
        vulture_mock = MagicMock(return_value=[], autospec=True)
        deptry_mock = MagicMock(return_value=[], autospec=True)

        with patch.object(a, "_run_bandit", bandit_mock):
            with patch.object(a, "_run_vulture", vulture_mock):
                with patch.object(a, "_run_deptry", deptry_mock):
                    with patch(
                        "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
                        side_effect=spy_resolve,
                    ):
                        a.run_l4(tmp_path, {})

        # required_tools = self._REQUIRED_L4_TOOLS.get(self._name, ())
        # For python: ("bandit",). For each: resolve_tool(tool_name, repo)
        required_calls = [(n, r) for n, r in resolve_calls if n == "bandit"]
        assert len(required_calls) >= 1, (
            f"KILLS required-tools mutmut_5/6: bandit resolve_tool not called. "
            f"calls={resolve_calls}"
        )
        for _, repo_arg in required_calls:
            assert repo_arg is not None, (
                f"KILLS mutmut_5/6: resolve_tool('bandit', {repo_arg!r}) — "
                f"repo is None instead of {tmp_path!r}"
            )


# ---------------------------------------------------------------------------
# _run_bandit passthrough mutations
# ---------------------------------------------------------------------------


class TestRunBanditWiring:
    """KILL: _run_bandit__mutmut_3 (H1 passthrough).

    The _run_bandit method calls resolve_tool("bandit("bandit", repo).
    Mutant 3: resolve_tool("bandit", repo) → resolve_tool("bandit", None)
    """

    def test_run_bandit_resolve_tool_received_exact_repo(self, tmp_path: Path) -> None:
        """KILL: _run_bandit__mutmut_3 (H1).

        Spy on resolve_tool from within _run_bandit to verify the repo
        argument is passed (not mutated to None)."
        """
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        calls: list[tuple[str, Path | None]] = []

        def spy_resolve(name: str, repo: Path | None = None) -> Path:
            calls.append((name, repo))
            return Path(f"/usr/bin/{name}")

        a = PythonAdapter()
        mock_bandit = MagicMock()
        mock_bandit.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        mock_bandit.parse.return_value = []
        a.bandit = mock_bandit

        with patch(
            "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
            side_effect=spy_resolve,
        ):
            findings = a._run_bandit(tmp_path, {})

        assert findings == [], (
            f"Expected empty findings, got {findings!r}"
        )

        bandit_calls = [c for c in calls if c[0] == "bandit"]
        assert len(bandit_calls) >= 1, (
            f"_run_bandit: resolve_tool not called. calls={calls}"
        )
        for _, repo_arg in bandit_calls:
            assert repo_arg is not None, (
                f"KILLS _run_bandit__mutmut_3: resolve_tool('bandit', {repo_arg!r})"
            )
            assert repo_arg == tmp_path, (
                f"KILLS mutmut_3: repo={repo_arg!r} must be {tmp_path!r}"
            )

    def test_run_bandit_invoke_with_correct_args(self, tmp_path: Path) -> None:
        """Verify invoke on mock bandit receives correct repo.

        Kills H1 passthrough: invoke(repo, args) → invoke(None, args).
        """
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        mock_bandit = MagicMock()
        mock_bandit.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)

        a = PythonAdapter()
        mock_bandit.parse.return_value = []
        a.bandit = mock_bandit

        with patch(
            "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
            return_value=Path("/usr/bin/bandit"),
        ):
            a._run_bandit(tmp_path, {})

        mock_bandit.invoke.assert_called_once()
        call_args = mock_bandit.invoke.call_args
        assert call_args.args[0] is tmp_path, (
            f"KILLS H1: invoke first arg is {call_args.args[0]!r}"
        )


# ---------------------------------------------------------------------------
# _run_mutmut passthrough mutations
# ---------------------------------------------------------------------------


class TestRunMutmutWiring:
    """KILL: _run_mutmut__mutmut_28 (H1 passthrough).

    The _run_mutmut method calls resolve_tool("mutmut", repo).
    Mutant 28: resolve_tool("mutmut", repo) -> resolve_tool("mutmut", None)
    """

    def test_run_mutmut_resolve_tool_received_exact_repo(self, tmp_path: Path) -> None:
        """KILL: _run_mutmut__mutmut_28 (H1).

        Spy on resolve_tool from within _run_mutmut to verify the repo
        argument is passed (not mutated to None).
        """
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        from harness_quality_gate.models import MutationStats
        from harness_quality_gate.adapters.base import ToolInvocation

        calls: list[tuple[str, Path | None]] = []

        def spy_resolve(name: str, repo: Path | None = None) -> Path:
            calls.append((name, repo))
            return Path(f"/usr/bin/{name}")

        a = PythonAdapter()
        mock_mutmut = MagicMock()
        mock_mutmut.run.return_value = ToolInvocation(stdout="", stderr="", exitcode=0)
        mock_mutmut.invoke.return_value = ToolInvocation(stdout="{}", stderr="", exitcode=0)
        mock_mutmut.parse.return_value = MutationStats(
            total=0, killed=0, survived=0, timed_out=0,
            escaped=0, untested=0, msi=0.0, covered_msi=0.0,
        )
        a.mutmut = mock_mutmut

        with patch(
            "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
            side_effect=spy_resolve,
        ):
            stats, run_ok = a._run_mutmut(tmp_path, {})

        assert run_ok is True
        mutmut_calls = [c for c in calls if c[0] == "mutmut"]
        assert len(mutmut_calls) >= 1, (
            f"_run_mutmut: resolve_tool not called. calls={calls}"
        )
        for _, repo_arg in mutmut_calls:
            assert repo_arg is not None, (
                f"KILLS _run_mutmut__mutmut_28: resolve_tool('mutmut', {repo_arg!r})"
            )
            assert repo_arg == tmp_path, (
                f"KILLS mutmut_28: repo={repo_arg!r} must be {tmp_path!r}"
            )

    def test_run_mutmut_invoke_with_correct_repo(self, tmp_path: Path) -> None:
        """KILL H1 passthrough: _run_mutmut.invoke() -> invoke(None, args).

        Verify the mutmut adapter's invoke() receives correct repo.
        """
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        from harness_quality_gate.models import MutationStats
        from harness_quality_gate.adapters.base import ToolInvocation

        mock_mutmut = MagicMock()
        mock_mutmut.run.return_value = ToolInvocation(stdout="", stderr="", exitcode=0)
        mock_mutmut.invoke.return_value = ToolInvocation(stdout="{}", stderr="", exitcode=0)
        mock_mutmut.parse.return_value = MutationStats(
            total=0, killed=0, survived=0, timed_out=0,
            escaped=0, untested=0, msi=0.0, covered_msi=0.0,
        )

        a = PythonAdapter()
        a.mutmut = mock_mutmut

        with patch(
            "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
            return_value=Path("/usr/bin/mutmut"),
        ):
            a._run_mutmut(tmp_path, {})

        mock_mutmut.invoke.assert_called_once()
        call_args = mock_mutmut.invoke.call_args
        assert call_args.args[0] is tmp_path, (
            f"KILLS H1: mutate invoke first arg is {call_args.args[0]!r}"
)
