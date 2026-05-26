"""Unit tests for Deptrac adapter parser.

Covers report-level violation count, per-violation list format,
parse_stats() convenience wrapper, and invalid input.
"""

from __future__ import annotations

import json

from harness_quality_gate.adapters.php.deptrac_adapter import DeptracAdapter


def _adapter() -> DeptracAdapter:
    return DeptracAdapter()


# ---------------------------------------------------------------------------
# parse() — report-level count
# ---------------------------------------------------------------------------


def test_parse_violations_count() -> None:
    """Report with Violations count (int) → single finding with count."""
    data = {"Report": {"Violations": 3, "UncoveredClasses": 1}}
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    f = findings[0]
    assert f.tool == "deptrac"
    assert f.layer == "L4"
    assert f.language == "php"
    assert "3 architecture violation" in f.message
    assert f.fix_hint is not None
    assert "1 uncovered" in f.fix_hint


# ---------------------------------------------------------------------------
# parse() — per-violation list
# ---------------------------------------------------------------------------


def test_parse_violations_list() -> None:
    """Report with Violations as list → one finding per violation."""
    data = {
        "Report": {
            "Violations": [
                {
                    "file": "src/Controller.php",
                    "message": "Controller calls Repository",
                    "fix": "Use Service instead",
                }
            ]
        }
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "src/Controller.php"
    assert f.message == "Controller calls Repository"
    assert f.fix_hint == "Use Service instead"


def test_parse_violations_list_multiple() -> None:
    """Multiple violations → multiple findings."""
    data = {
        "Report": {
            "Violations": [
                {"file": "a.php", "message": "V1"},
                {"file": "b.php", "message": "V2"},
            ]
        }
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 2
    assert findings[0].message == "V1"
    assert findings[1].message == "V2"


# ---------------------------------------------------------------------------
# parse() — edge cases
# ---------------------------------------------------------------------------


def test_parse_empty_output() -> None:
    """Empty stdout → no findings."""
    findings = _adapter().parse("", "", 0)
    assert len(findings) == 0


def test_parse_invalid_json() -> None:
    """Non-JSON stdout → no findings."""
    findings = _adapter().parse("not json at all", "", 1)
    assert len(findings) == 0


def test_parse_missing_report_key() -> None:
    """Valid JSON but no Report key → no findings."""
    findings = _adapter().parse('{"foo": "bar"}', "", 0)
    assert len(findings) == 0


def test_parse_report_non_dict() -> None:
    """Report is not a dict → no findings."""
    findings = _adapter().parse('{"Report": "string"}', "", 0)
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# parse_stats() — architecture block
# ---------------------------------------------------------------------------


def test_parse_stats_valid() -> None:
    """parse_stats returns architecture dict."""
    data = {"Report": {"Violations": 3, "UncoveredClasses": 2}}
    arch = _adapter().parse_stats(json.dumps(data))
    assert arch == {"violations": 3, "uncovered_classes": 2}


def test_parse_stats_invalid_json() -> None:
    """parse_stats with bad JSON → zeroed dict."""
    arch = _adapter().parse_stats("garbage")
    assert arch == {"violations": 0, "uncovered_classes": 0}


def test_parse_stats_missing_report() -> None:
    """parse_stats without Report key → zeroed dict."""
    arch = _adapter().parse_stats('{"other": 1}')
    assert arch == {"violations": 0, "uncovered_classes": 0}


# ---------------------------------------------------------------------------
# architecture property
# ---------------------------------------------------------------------------


def test_architecture_property() -> None:
    """architecture property reflects last parse() call."""
    a = _adapter()
    data = {"Report": {"Violations": 5, "UncoveredClasses": 3}}
    a.parse(json.dumps(data), "", 1)
    assert a.architecture == {"violations": 5, "uncovered_classes": 3}


def test_architecture_property_unset() -> None:
    """architecture property before parse → empty dict."""
    assert _adapter().architecture == {}
