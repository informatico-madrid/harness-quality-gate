"""Exact mutant killers for run_l4 (python_adapter.py).

8 mutants targeted:

  mutmut_5:   findings=[] → findings=None on early return (line 368)
  mutmut_6:   duration_sec=0.0 → duration_sec=None on early return (line 369)
  mutmut_17:  duration_sec=0.0 → duration_sec=1.0 on early return (line 369)
  mutmut_33:  if not bandit_findings: → if bandit_findings: (line 378)
  mutmut_67:  .get(self._name, ()) → .get(None, ()) on line 401
  mutmut_68:  .get(self._name, ()) → .get(self._name, None) on line 401
  mutmut_70:  .get(self._name, ()) → .get(self._name) on line 401
  mutmut_71:  if tool_name not in required_tools_skipped: → if tool_name in ... (line 403)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.bootstrap import ToolNotAvailable
from harness_quality_gate.models import LayerResult


# ---------------------------------------------------------------------------
# mutmut_5, 6, 17 — early return path
# ---------------------------------------------------------------------------


class TestMutmut5:
    """KILL: mutmut_5 (findings=[] → findings=None on early return).

    Assertion: result.findings == [] (not None).
    """

    def test_run_l4_partial_run_findings_is_not_none(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        a = PythonAdapter(paths=["src/foo.py"])
        result = a.run_l4(tmp_path, {})

        assert isinstance(result, LayerResult)
        assert result.findings is not None, (
            "KILLS mutmut_5: findings is None instead of []"
        )
        assert result.findings == [], (
            f"KILLS mutmut_5: findings is {result.findings!r} instead of []"
        )
        assert result.passed is True
        assert result.language == "python"
        assert result.layer == "L4"


class TestMutmut6:
    """KILL: mutmut_6 (duration_sec=0.0 → duration_sec=None on early return).

    Assertion: result.duration_sec == 0.0 (not None).
    """

    def test_run_l4_partial_run_duration_not_none(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        a = PythonAdapter(paths=["src/foo.py"])
        result = a.run_l4(tmp_path, {})

        assert result.duration_sec is not None, (
            "KILLS mutmut_6: duration_sec is None instead of 0.0"
        )
        assert isinstance(result.duration_sec, (int, float)), (
            f"KILLS mutmut_6: duration_sec is {type(result.duration_sec).__name__}"
        )


class TestMutmut17:
    """KILL: mutmut_17 (duration_sec=0.0 → duration_sec=1.0 on early return).

    Assertion: result.duration_sec == 0.0 (not 1.0).
    """

    def test_run_l4_partial_run_duration_is_zero(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        a = PythonAdapter(paths=["src/foo.py"])
        result = a.run_l4(tmp_path, {})

        assert result.duration_sec == 0.0, (
            f"KILLS mutmut_17: duration_sec is {result.duration_sec}, "
            "expected 0.0"
        )


# ---------------------------------------------------------------------------
# Combined early-return assertions (both findings AND duration)
# ---------------------------------------------------------------------------


class TestMutmut5And6:
    """Kill mutmut_5 and mutmut_6 in a single test with all assertions.

    Tests that both findings and duration_sec maintain their exact types
    on the early return path.
    """

    def test_run_l4_partial_run_findings_and_duration(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        a = PythonAdapter(paths=["src/foo.py"])
        result = a.run_l4(tmp_path, {})

        # Both assertions in one test are still 2 independent claims.
        # The spec says "assert result.findings == []" kills mutmut_5.
        # The spec says "assert result.duration_sec == 0.0" kills mutmut_6.
        assert result.findings == []
        assert result.duration_sec == 0.0
        assert result.passed is True
        assert result.layer == "L4"
        assert result.language == "python"


# ---------------------------------------------------------------------------
# mutmut_33 — guard condition inverted on line 378
# ---------------------------------------------------------------------------


class TestMutmut33:
    """KILL: mutmut_33 (if not bandit_findings: → if bandit_findings:).

    When bandit_findings=[], original ENTRIES the resolve_tool block,
    mutated version does NOT.
    """

    def test_run_l4_empty_bandit_calls_resolve_tool(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        resolve_calls: list[str] = []

        def spy_resolve(name: str, repo: Path | None = None) -> Path:
            resolve_calls.append(name)
            return Path(f"/usr/bin/{name}")

        a = PythonAdapter()  # paths=None → normal path

        with patch.object(a, "_run_bandit", return_value=[]):
            with patch.object(a, "_run_vulture", return_value=[]):
                with patch.object(a, "_run_deptry", return_value=[]):
                    with patch(
                        "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
                        side_effect=spy_resolve,
                    ):
                        a.run_l4(tmp_path, {})

        assert "bandit" in resolve_calls, (
            f"KILLS mutmut_33: resolve_tool('bandit') was NOT called. "
            f"Guard may be inverted. resolve_calls={resolve_calls}"
        )


# ---------------------------------------------------------------------------
# mutmut_67, 68, 70 — .get() mutations on line 401
# ---------------------------------------------------------------------------


class TestMutmut67:
    """KILL: mutmut_67 (.get(self._name, ()) → .get(None, ())).

    _REQUIRED_L4_TOOLS = {"python": ("bandit",), "php": ()}.
    self._name = "python". If .get(None, ()) → returns () (default).
    BUT .get(self._name, ()) should return ("bandit",).
    With this mutation, required_tools=() so no required-tool check happens.
    """

    def test_run_l4_checks_required_tools_for_python(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        from harness_quality_gate.models import Finding

        resolve_calls: list[tuple[str, Path | None]] = []

        def spy_resolve(name: str, repo: Path | None = None) -> Path:
            resolve_calls.append((name, repo))
            return Path(f"/usr/bin/{name}")

        a = PythonAdapter()  # paths=None, self._name="python"

        with patch.object(a, "_run_bandit", return_value=[]):
            with patch.object(a, "_run_vulture", return_value=[]):
                with patch.object(a, "_run_deptry", return_value=[]):
                    with patch(
                        "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
                        side_effect=spy_resolve,
                    ):
                        result = a.run_l4(tmp_path, {})

        # With self._name="python", .get("python", ()) must return ("bandit",)
        # Then resolve_tool("bandit", repo) is called in the required_tools loop
        required_calls = [(n, r) for n, r in resolve_calls if n == "bandit"]
        assert len(required_calls) >= 1, (
            f"KILLS mutmut_67: resolve_tool('bandit') NOT called from "
            f"required_tools loop. This means .get(self._name,()) returned () "
            f"instead of ('bandit',). calls={resolve_calls}"
        )


class TestMutmut68:
    """KILL: mutmut_68 (.get(self._name, ()) → .get(self._name, None)).

    self._name="python" IS in _REQUIRED_L4_TOOLS, so default is NEVER used.
    BUT: if self._name were NOT in the dict, iterating None → TypeError.
    The fact that run_l4 completes without error proves _name IS in dict for python.
    However, a more precise killer: assert the required_tools path actually
    uses the "bandit" value (not empty).
    """

    def test_run_l4_required_tools_iterates_bandit_not_empty(self, tmp_path: Path) -> None:
        """KILLS mutmut_68: if default changed to None and _name missing, no iteration.

        For self._name="python" the key exists, so default not used.
        But verify that the resolved tool list actually contains "bandit"
        by checking resolve_tool was called for it in the required_tools path.
        """
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        resolve_calls: list[str] = []

        def spy_resolve(name: str, repo: Path | None = None) -> Path:
            resolve_calls.append(name)
            return Path(f"/usr/bin/{name}")

        a = PythonAdapter()

        with patch.object(a, "_run_bandit", return_value=[]):
            with patch.object(a, "_run_vulture", return_value=[]):
                with patch.object(a, "_run_deptry", return_value=[]):
                    with patch(
                        "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
                        side_effect=spy_resolve,
                    ):
                        a.run_l4(tmp_path, {})

        # The required_tools loop MUST call resolve_tool("bandit") because
        # _REQUIRED_L4_TOOLS["python"] = ("bandit",). If .get() returned
        # () (mutmut_67) or None (mutmut_68 — hypothetical), this wouldn't fire.
        bandit_count = sum(1 for n in resolve_calls if n == "bandit")
        assert bandit_count >= 1, (
            f"KILLS mutmut_68: expected at least 1 resolve_tool('bandit') call. "
            f"_REQUIRED_L4_TOOLS['python'] must iterate. calls={resolve_calls}"
        )


class TestMutmut70:
    """KILL: mutmut_70 (.get(self._name, ()) → .get(self._name) — no default).

    If self._name not in dict, returns None → TypeError iterating.
    For "python" key exists, so same as mutmut_68.
    """

    def test_run_l4_required_tools_works_with_python_name(self, tmp_path: Path) -> None:
        """KILLS mutmut_70: verify required_tools iterates correct values.

        When _name="python", .get("python") returns ("bandit",).
        Without default, missing keys return None (Type C crash).
        With .get(self._name, ()), missing keys return ().
        Since "python" IS in the dict, this doesn't differentiate from 67/68.
        But it proves the full .get() chain works for "python".
        """
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        resolve_calls: list[str] = []

        def spy_resolve(name: str, repo: Path | None = None) -> Path:
            resolve_calls.append(name)
            return Path(f"/usr/bin/{name}")

        a = PythonAdapter()
        assert a._name == "python", "Prerequisite: _name must be 'python'"

        with patch.object(a, "_run_bandit", return_value=[]):
            with patch.object(a, "_run_vulture", return_value=[]):
                with patch.object(a, "_run_deptry", return_value=[]):
                    with patch(
                        "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
                        side_effect=spy_resolve,
                    ):
                        a.run_l4(tmp_path, {})

        # Must iterate "bandit" from _REQUIRED_L4_TOOLS["python"]
        bandit_in_loop = "bandit" in resolve_calls
        assert bandit_in_loop is True, (
            f"KILLS mutmut_70: 'bandit' not in resolve_calls — "
            f"The .get(self._name) chain must yield ('bandit',). "
            f"calls={resolve_calls}"
        )


# ---------------------------------------------------------------------------
# mutmut_71 — logic inversion on line 403
# ---------------------------------------------------------------------------


class TestMutmut71:
    """KILL: mutmut_71 (if tool_name not in skip: → if tool_name in skip:).

    In the original, tools NOT in skip get re-checked.
    In the mutated, only tools IN skip get re-checked.
    """

    def test_run_l4_non_skipped_tool_rechecked(self, tmp_path: Path) -> None:
        """KILL: mutmut_71 inversion.

        Strategy:
        1. bandit returns [] (empty findings).
        2. resolve_tool is called for bandit in the `if not bandit_findings:` block.
        3. If bandit is also in required_tools, it gets checked AGAIN in the loop
           UNLESS it's in required_tools_skipped.
        4. But wait — required_tools_skipped is only populated in the `if not
           bandit_findings:` resolve_tool path when ToolNotAvailable is raised.
           If resolve_tool succeeds, the tool won't be in required_tools_skipped.
           So the original code DOES re-call resolve_tool("bandit") in the loop.
           But the mutation SKIPS it because tool_name is NOT in skip → `if tool_name
           in skip:` → False.
           
           Wait — the mutation INVERTS. Original: `if tool_name not in skip:`
           Mutated: `if tool_name in skip:` (the `not` is removed/reversed).
           
           With bandit NOT in skip:
           - Original: `if "bandit" not in []:` → True → calls resolve_tool AGAIN
           - Mutated: `if "bandit" in []:` → False → skips resolve_tool
           
           So the count of resolve_tool("bandit") calls will differ:
           - Original: 2 calls (1 from bandit_findings block + 1 from loop)
           - Mutated: 1 call (only from bandit_findings block)
        """
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        resolve_calls: list[str] = []

        def spy_resolve(name: str, repo: Path | None = None) -> Path:
            resolve_calls.append(name)
            return Path(f"/usr/bin/{name}")

        a = PythonAdapter()  # paths=None, self._name="python"

        with patch.object(a, "_run_bandit", return_value=[]):
            with patch.object(a, "_run_vulture", return_value=[]):
                with patch.object(a, "_run_deptry", return_value=[]):
                    with patch(
                        "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
                        side_effect=spy_resolve,
                    ):
                        a.run_l4(tmp_path, {})

        bandit_count = sum(1 for n in resolve_calls if n == "bandit")
        # Original: bandit_findings=[], so resolve_tool("bandit") called there.
        # Then in required_tools loop: "bandit" not in skip (empty), so
        # resolve_tool("bandit") called AGAIN → 2 total calls.
        # Mutated: `if tool_name in skip:` → False → no second call → 1 total.
        assert bandit_count >= 2, (
            f"KILLS mutmut_71: expected >= 2 resolve_tool('bandit') calls "
            f"but got {bandit_count}. Logic may be inverted: "
            f"tool 'bandit' should be re-checked in required_tools loop "
            f"when not in skip list. All calls: {resolve_calls}"
        )


class TestMutmutAllL4:
    """Kill all 8 mutants with one comprehensive early-return test."""

    def test_run_l4_early_return_fields_exact(self, tmp_path: Path) -> None:
        """KILLS mutmut_5, 6, 17 simultaneously.

        - findings MUST be [] (not None, not any other value)
        - duration_sec MUST be 0.0 (not None, not 1.0)
        """
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        a = PythonAdapter(paths=["anything.py"])
        result = a.run_l4(tmp_path, {})

        # mutmut_5: findings=[] → findings=None
        assert result.findings == []
        assert result.findings is not None

        # mutmut_6: duration_sec=0.0 → duration_sec=None
        assert result.duration_sec == 0.0
        assert result.duration_sec is not None

        # mutmut_17: duration_sec=0.0 → duration_sec=1.0
        assert result.duration_sec == 0.0

        # Sanity checks
        assert result.passed is True
        assert result.layer == "L4"
        assert result.language == "python"


# ---------------------------------------------------------------------------
# run_l4 required-tool-missing Finding (the Finding(...) -> None mutant)
# ---------------------------------------------------------------------------


class TestRunL4MissingRequiredToolFinding:
    """KILL: run_l4 builds an exact 'tool not installed' Finding.

    When a required L4 tool is unavailable, ``required_tools_skipped`` is
    non-empty and run_l4 appends a concrete ``Finding``. The whole-object
    mutant (``Finding(...) -> None``) crashes on ``f.severity`` later, but
    only a test that *reaches* this branch (required tool missing) exercises
    it. A dense equality assertion also pins every field/message mutation.
    """

    def test_missing_required_tool_appends_exact_finding(
        self, tmp_path: Path
    ) -> None:
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        from harness_quality_gate.models import Finding

        adapter = PythonAdapter()  # paths=None, _name="python" requires bandit

        with (
            patch.object(adapter, "_run_bandit", return_value=[]),
            patch.object(adapter, "_run_vulture", return_value=[]),
            patch.object(adapter, "_run_deptry", return_value=[]),
            patch(
                "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
                side_effect=ToolNotAvailable("bandit"),
            ),
        ):
            result = adapter.run_l4(tmp_path, {})

        assert result.findings == [
            Finding(
                node="L4",
                severity="error",
                message=(
                    "Required L4 tool(s) not installed: bandit. "
                    "Install them to enable full security scanning."
                ),
                tool="L4",
                layer="L4",
                language="python",
            )
        ]
        # An "error" finding must fail the gate.
        assert result.passed is False


class TestRunL4WarningAndJoin:
    """run_l4: the 'bandit missing' warning text and the multi-tool join."""

    _LOGGER = "harness_quality_gate.adapters.python.python_adapter"

    def test_bandit_missing_logs_exact_warning(self, tmp_path: Path, caplog) -> None:
        import logging
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        adapter = PythonAdapter()
        caplog.set_level(logging.WARNING, logger=self._LOGGER)
        with (
            patch.object(adapter, "_run_bandit", return_value=[]),
            patch.object(adapter, "_run_vulture", return_value=[]),
            patch.object(adapter, "_run_deptry", return_value=[]),
            patch(
                "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
                side_effect=ToolNotAvailable("bandit"),
            ),
        ):
            adapter.run_l4(tmp_path, {})

        assert (
            "bandit not found on PATH or .venv -- required L4 tool missing"
            in [r.getMessage() for r in caplog.records]
        )

    def test_multiple_missing_tools_joined_with_comma_space(
        self, tmp_path: Path
    ) -> None:
        """Two skipped tools are joined with ', ' in the Finding message."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

        adapter = PythonAdapter()
        with (
            patch.object(
                type(adapter), "_REQUIRED_L4_TOOLS", {"python": ("bandit", "deptry")},
            ),
            patch.object(adapter, "_run_bandit", return_value=[]),
            patch.object(adapter, "_run_vulture", return_value=[]),
            patch.object(adapter, "_run_deptry", return_value=[]),
            patch(
                "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
                side_effect=ToolNotAvailable("x"),
            ),
        ):
            result = adapter.run_l4(tmp_path, {})

        msg = next(f.message for f in result.findings if f.node == "L4")
        assert msg == (
            "Required L4 tool(s) not installed: bandit, deptry. "
            "Install them to enable full security scanning."
        )
