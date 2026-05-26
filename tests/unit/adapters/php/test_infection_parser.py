"""Unit tests for Infection adapter parse_stats.

Covers JSON input, key:value text fallback, all-zero, and partial data.
"""

from __future__ import annotations

import json

from harness_quality_gate.adapters.php.infection_adapter import InfectionAdapter


def _adapter() -> InfectionAdapter:
    return InfectionAdapter()


# ---------------------------------------------------------------------------
# JSON format
# ---------------------------------------------------------------------------


def test_parse_stats_json_all_killed() -> None:
    """Flat JSON with top-level killed/survived → MSI=100%.

    Note: parse_stats() expects keys at the top level, not nested
    under a "metrics" object (that's the fixture format only).
    """
    json_str = json.dumps({
        "tool_name": "Infection",
        "killed": 10,
        "survived": 0,
        "timed_out": 0,
        "escaped": 0,
        "untested": 0,
    })
    stats = _adapter().parse_stats(json_str)
    assert stats.killed == 10
    assert stats.survived == 0
    assert stats.escaped == 0
    assert stats.msi == 1.0
    assert stats.covered_msi == 1.0


def test_parse_stats_json_with_escaped() -> None:
    """Flat JSON with escaped mutants."""
    json_str = json.dumps({
        "killed": 8,
        "survived": 1,
        "timed_out": 0,
        "escaped": 2,
        "untested": 0,
    })
    stats = _adapter().parse_stats(json_str)
    assert stats.killed == 8
    assert stats.escaped == 2
    assert stats.total == 9  # killed+survived+timed_out+untested


# ---------------------------------------------------------------------------
# Key:value text fallback
# ---------------------------------------------------------------------------


def test_parse_stats_kv_text() -> None:
    """Unquoted key:value text → parsed via regex."""
    text = "killed:5,survived:2,escaped:1,timed_out:0"
    stats = _adapter().parse_stats(text)
    assert stats.killed == 5
    assert stats.survived == 2
    assert stats.escaped == 1


def test_parse_stats_kv_text_multiline() -> None:
    """Multi-line key:value format."""
    text = """
killed: 3
survived: 1
escaped: 0
"""
    stats = _adapter().parse_stats(text)
    assert stats.killed == 3
    assert stats.survived == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_parse_stats_empty() -> None:
    """Empty string → all zeros."""
    stats = _adapter().parse_stats("")
    assert stats.killed == 0
    assert stats.total == 0
    assert stats.msi == 0.0


def test_parse_stats_only_killed() -> None:
    """Only 'killed' present, no covered mutations → MSI=0."""
    stats = _adapter().parse_stats("killed:5")
    assert stats.killed == 5
    assert stats.msi == 1.0  # covered=killed=5, msi=5/5=1.0


def test_parse_stats_garbage() -> None:
    """Non-parseable text → all zeros."""
    stats = _adapter().parse_stats("this is not parseable")
    assert stats.killed == 0


def test_parse_stats_untested_only() -> None:
    """Only untested mutants → covered=0 → MSI=0."""
    stats = _adapter().parse_stats("untested:10")
    assert stats.untested == 10
    assert stats.covered_msi == 0.0


def test_adapter_parse_wraps_parse_stats() -> None:
    """parse() delegates to parse_stats()."""
    json_str = '{"killed":3,"survived":1}'
    stats = _adapter().parse(json_str)
    assert stats.killed == 3
