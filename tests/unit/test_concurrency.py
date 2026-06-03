"""Unit tests for the concurrency resolver.

Covers explicit parallel, explicit sequential, and auto-detection
per Coverage Table.
"""

from __future__ import annotations

from harness_quality_gate.concurrency import resolve  # pyright: ignore[reportMissingImports]


def test_resolve_parallel() -> None:
    """Explicit parallel mode → parallel regardless of CI env."""
    plan = resolve("parallel", {})
    assert plan.mode == "parallel"
    assert plan.ci_detected is False
    assert plan.max_threads == 1


def test_resolve_sequential() -> None:
    """Explicit sequential mode → sequential regardless of CI env."""
    plan = resolve("sequential", {})
    assert plan.mode == "sequential"
    assert plan.ci_detected is False
    assert plan.max_threads == 1


def test_resolve_auto_no_ci() -> None:
    """Auto mode without CI env → parallel."""
    # Pass the env explicitly (resolve reads its argument, not os.environ).
    # Do NOT clear os.environ — that strips mutmut's MUTANT_UNDER_TEST and
    # crashes the mutation baseline.
    plan = resolve("auto", {})
    assert plan.mode == "parallel"
    assert plan.ci_detected is False


def test_resolve_auto_with_ci() -> None:
    """Auto mode with CI env → sequential."""
    plan = resolve("auto", {"CI": "true"})
    assert plan.mode == "sequential"
    assert plan.ci_detected is True


def test_resolve_auto_with_github_actions() -> None:
    """Auto mode with GITHUB_ACTIONS env → sequential."""
    plan = resolve("auto", {"GITHUB_ACTIONS": "true"})
    assert plan.mode == "sequential"
    assert plan.ci_detected is True
