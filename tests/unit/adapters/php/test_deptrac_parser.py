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
    a = _adapter()
    data = {"Report": {"Violations": 3, "UncoveredClasses": 1}}
    # Keyword for exitcode → stderr defaults to "" (kills mutmut_1: ""→"XXXX")
    findings = a.parse(json.dumps(data), exitcode=1)
    # Kill mutmut_91: Finding → None (entire finding creation removed)
    assert len(findings) == 1
    f = findings[0]
    # Kill mutmut_92: node="deptrac" → None
    assert f.node == "deptrac"
    # Kill mutmut_93: severity="error" → None
    assert f.severity == "error"
    # Kill mutmut_94: message → None
    assert f.message == "3 architecture violation(s) detected"
    # Kill mutmut_95: fix_hint → None
    assert f.fix_hint == "Review deptrac.yaml configuration; 1 uncovered class(es)"
    assert a.architecture.get("violations") == 3
    assert a.architecture.get("uncovered_classes") == 1
    assert a.architecture.get("stderr") == ""
    assert a.architecture.get("exitcode") == 1


# ---------------------------------------------------------------------------
# parse() — per-violation list
# ---------------------------------------------------------------------------


def test_parse_violations_list() -> None:
    """Report with Violations as list → one finding per violation."""
    a = _adapter()
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
    findings = a.parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "src/Controller.php"
    assert f.severity == "error"
    assert f.message == "Controller calls Repository"
    assert f.fix_hint == "Use Service instead"
    assert f.tool == "deptrac"
    assert f.layer == "L4"
    assert f.language == "php"
    # Violations is a list, so violations_count = the list itself
    assert isinstance(a.architecture.get("violations"), list)
    assert a.architecture.get("uncovered_classes") == 0


def test_parse_violations_list_multiple() -> None:
    """Multiple violations → multiple findings."""
    a = _adapter()
    data = {
        "Report": {
            "Violations": [
                {"file": "a.php", "message": "V1"},
                {"file": "b.php", "message": "V2"},
            ]
        }
    }
    findings = a.parse(json.dumps(data), "", 1)
    assert len(findings) == 2
    for f in findings:
        assert f.severity == "error"
        assert f.tool == "deptrac"
        assert f.layer == "L4"
        assert f.language == "php"
    assert findings[0].message == "V1"
    assert findings[1].message == "V2"
    # Violations is a list → violations_count = the list
    assert isinstance(a.architecture.get("violations"), list)
    assert a.architecture.get("uncovered_classes") == 0


# ---------------------------------------------------------------------------
# parse() — edge cases
# ---------------------------------------------------------------------------


def test_parse_empty_output() -> None:
    """Empty stdout → no findings."""
    a = _adapter()
    findings = a.parse("", "", 0)
    assert len(findings) == 0
    # Early return at line 128-129 — _architecture never set
    assert a.architecture == {}


def test_parse_invalid_json() -> None:
    """Non-JSON stdout → no findings."""
    a = _adapter()
    findings = a.parse("not json at all", "", 1)
    assert len(findings) == 0
    # _architecture never set — JSON parse fails
    assert a.architecture == {}


def test_parse_missing_report_key() -> None:
    """Valid JSON but no Report key → _architecture stores defaults."""
    a = _adapter()
    findings = a.parse('{"foo": "bar"}', "", 0)
    assert len(findings) == 0
    # "Report" missing → get() returns {} (empty dict) → isinstance check passes
    # "Violations" missing → count defaults to 0 → no findings
    # architecture has full defaults: kills mutmut_9, mutmut_11
    assert a.architecture.get("violations") == 0
    assert a.architecture.get("uncovered_classes") == 0


def test_parse_report_non_dict() -> None:
    """Report is not a dict → no findings."""
    a = _adapter()
    findings = a.parse('{"Report": "string"}', "", 0)
    assert len(findings) == 0
    # Report value is "string" → isinstance check fails → early return
    assert a.architecture == {}


# ---------------------------------------------------------------------------
# Missing fields in violation dicts — default values are used
# ---------------------------------------------------------------------------


def test_parse_violation_missing_file_key() -> None:
    """Violation dict missing 'file' key uses default 'unknown'."""
    a = _adapter()
    data = {
        "Report": {
            "Violations": [
                {"message": "Some violation"},
            ]
        }
    }
    findings = a.parse(json.dumps(data), "", 0)
    assert len(findings) == 1
    # Default "unknown" is used when file key is missing
    assert findings[0].node == "unknown"
    assert findings[0].message == "Some violation"
    assert findings[0].fix_hint is None
    assert findings[0].tool == "deptrac"


def test_parse_violation_missing_message_key() -> None:
    """Violation dict missing 'message' key uses default 'Architecture violation'."""
    a = _adapter()
    data = {
        "Report": {
            "Violations": [
                {"file": "src/Foo.php"},
            ]
        }
    }
    findings = a.parse(json.dumps(data), "", 0)
    assert len(findings) == 1
    assert findings[0].node == "src/Foo.php"
    # Default "Architecture violation" is used when message key is missing
    assert findings[0].message == "Architecture violation"
    assert findings[0].fix_hint is None
    assert findings[0].tool == "deptrac"


def test_parse_violation_missing_both_file_and_message() -> None:
    """Violation dict missing both 'file' and 'message' uses both defaults."""
    a = _adapter()
    data = {
        "Report": {
            "Violations": [
                {},
            ]
        }
    }
    findings = a.parse(json.dumps(data), "", 0)
    assert len(findings) == 1
    assert findings[0].node == "unknown"
    assert findings[0].message == "Architecture violation"
    assert findings[0].fix_hint is None
    assert findings[0].tool == "deptrac"


def test_parse_violation_list_none_element() -> None:
    """Non-dict elements in Violations list are safely skipped."""
    a = _adapter()
    data = {
        "Report": {
            "Violations": [
                {"file": "good.php", "message": "ok"},
                "not_a_dict",
                None,
                42,
            ]
        }
    }
    findings = a.parse(json.dumps(data), "", 0)
    assert len(findings) == 1
    assert findings[0].node == "good.php"
    assert findings[0].message == "ok"


# ---------------------------------------------------------------------------
# Missing Violations / UncoveredClasses keys → default values
# ---------------------------------------------------------------------------


def test_parse_missing_violations_key() -> None:
    """Report present but Violations key missing → counts default to 0."""
    a = _adapter()
    data = {"Report": {"UncoveredClasses": 2}}
    # Only positional stdout → stderr defaults to "" (kill mutmut_1: ""→"XXXX"), exitcode defaults to 0 (kill mutmut_2: 0→1)
    a.parse(json.dumps(data))
    assert a.architecture.get("violations") == 0
    assert a.architecture.get("uncovered_classes") == 2
    assert a.architecture.get("stderr") == ""
    assert a.architecture.get("exitcode") == 0


def test_parse_missing_uncovered_key() -> None:
    """Report present but UncoveredClasses key missing → defaults to 0."""
    a = _adapter()
    data = {"Report": {"Violations": 4}}
    # Same call pattern → tests defaults (kills mutmut_1 & mutmut_2)
    a.parse(json.dumps(data))
    assert a.architecture.get("violations") == 4
    assert a.architecture.get("uncovered_classes") == 0
    assert a.architecture.get("stderr") == ""
    assert a.architecture.get("exitcode") == 0


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
    data = {"Report": {"Violations": 5, "UncoveredClasses": 2}}
    a.parse(json.dumps(data), "", 0)
    assert a.architecture.get("violations") == 5
    assert a.architecture.get("uncovered_classes") == 2


def test_architecture_property_unset() -> None:
    """architecture property before parse → empty dict."""
    assert _adapter().architecture == {}
