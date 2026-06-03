"""Unit tests for Infection adapter parse_stats.

Covers Infection v0.29.x text output, JSON legacy format, and edge cases.
"""

from __future__ import annotations

import json

from harness_quality_gate.adapters.php.infection_adapter import InfectionAdapter


def _adapter() -> InfectionAdapter:
    return InfectionAdapter()


# Realistic Infection v0.29.x text output (trimmed to relevant parts)
_INFECTION_PASS_TEXT = """
6 mutations were generated:
       6 mutants were killed
       0 mutants were configured to be ignored
       0 mutants were not covered by tests
       0 covered mutants were not detected
       0 errors were encountered
       0 syntax errors were encountered
       0 time outs were encountered
       0 mutants required more time than configured

Metrics:
         Mutation Score Indicator (MSI): 100%
         Mutation Code Coverage: 100%
         Covered Code MSI: 100%
"""

_INFECTION_FAIL_TEXT = """
6 mutations were generated:
       4 mutants were killed
       0 mutants were configured to be ignored
       0 mutants were not covered by tests
       2 covered mutants were not detected
       0 errors were encountered
       0 syntax errors were encountered
       0 time outs were encountered
       0 mutants required more time than configured

Metrics:
         Mutation Score Indicator (MSI): 66%
         Mutation Code Coverage: 100%
         Covered Code MSI: 66%
"""


# ---------------------------------------------------------------------------
# Infection v0.29.x text format (primary)
# ---------------------------------------------------------------------------


def test_parse_stats_text_all_killed() -> None:
    """Infection text output — all killed → MSI=100%."""
    stats = _adapter().parse_stats(_INFECTION_PASS_TEXT)
    assert stats.killed == 6
    assert stats.survived == 0
    assert stats.total == 6
    assert stats.msi == 100.0
    assert stats.covered_msi == 100.0


def test_parse_stats_text_escaped() -> None:
    """Infection text output — 2 escaped → MSI=66%, covered_msi=66%."""
    stats = _adapter().parse_stats(_INFECTION_FAIL_TEXT)
    assert stats.killed == 4
    assert stats.survived == 2
    assert stats.msi == 66.0
    assert stats.covered_msi == 66.0


def test_parse_stats_text_timed_out() -> None:
    """Infection text output — with timeouts."""
    text = """
3 mutations were generated:
       2 mutants were killed
       0 covered mutants were not detected
       0 mutants were not covered by tests
       1 time outs were encountered

Metrics:
         Mutation Score Indicator (MSI): 66%
         Covered Code MSI: 66%
"""
    stats = _adapter().parse_stats(text)
    assert stats.killed == 2
    assert stats.timed_out == 1


# ---------------------------------------------------------------------------
# JSON legacy format (forward-compat)
# ---------------------------------------------------------------------------


def test_parse_stats_json_all_killed() -> None:
    """JSON with killed/survived/msi keys → MSI returned as-is."""
    json_str = json.dumps({
        "killed": 10, "survived": 0, "timed_out": 0,
        "escaped": 0, "untested": 0, "msi": 100.0, "covered_msi": 100.0,
    })
    stats = _adapter().parse_stats(json_str)
    assert stats.killed == 10
    assert stats.survived == 0
    assert stats.msi == 100.0


def test_parse_stats_json_with_escaped() -> None:
    """JSON with escaped mutants."""
    json_str = json.dumps({
        "killed": 8, "survived": 1, "timed_out": 0,
        "escaped": 2, "untested": 0, "msi": 72.72, "covered_msi": 72.72,
    })
    stats = _adapter().parse_stats(json_str)
    assert stats.killed == 8
    assert stats.escaped == 2
    assert stats.total == 11  # 8+1+0+2+0


def test_parse_stats_json_total_calculation() -> None:
    """JSON path computes total=killed+survived+timed_out+escaped+untested.

    Mutants 97 (+→-) and 99 (+→-) would produce wrong totals. This test
    verifies the arithmetic is correct to kill those survivors.
    """
    json_str = json.dumps({
        "killed": 5, "survived": 3, "timed_out": 1,
        "escaped": 2, "untested": 4, "msi": 50.0,
    })
    stats = _adapter().parse_stats(json_str)
    # total = 5+3+1+2+4 = 15
    assert stats.total == 15


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_parse_stats_empty() -> None:
    """Empty string → all zeros."""
    stats = _adapter().parse_stats("")
    assert stats.killed == 0
    assert stats.total == 0
    assert stats.msi == 0.0


def test_parse_stats_garbage() -> None:
    """Non-parseable text → all zeros."""
    stats = _adapter().parse_stats("this is not parseable")
    assert stats.killed == 0


def test_adapter_parse_wraps_parse_stats() -> None:
    """parse() delegates to parse_stats() and returns MutationStats."""
    stats = _adapter().parse(_INFECTION_PASS_TEXT)
    assert stats.killed == 6
    assert stats.msi == 100.0
