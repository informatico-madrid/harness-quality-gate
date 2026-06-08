"""Unit tests for Psalm taint-analysis adapter parser.

Covers array format, nested files format, non-taint filter, empty/invalid input.
"""

from __future__ import annotations

import json

from harness_quality_gate.adapters.php.psalm_taint_adapter import (
    PsalmTaintAdapter,
)


def _adapter() -> PsalmTaintAdapter:
    return PsalmTaintAdapter()


# ---------------------------------------------------------------------------
# Array format (canned test format)
# ---------------------------------------------------------------------------


def test_parse_array_tainted_sql() -> None:
    """Array format with TaintedSql finding."""
    data = [
        {
            "type": "TaintedSql",
            "file_name": "src/Query.php",
            "line_from": 42,
            "message": "SQL injection possible",
            "severity": "error",
        }
    ]
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "src/Query.php:42"
    assert f.tool == "psalm-taint"
    assert f.layer == "L4"
    assert f.language == "php"
    assert "TaintedSql" in f.message
    assert f.fix_hint == "TaintedSql"


def test_parse_array_tainted_html() -> None:
    """Array format with TaintedHtml finding."""
    data = [
        {
            "type": "TaintedHtml",
            "file_name": "templates/index.html.php",
            "line_from": 10,
            "message": "XSS possible",
            "severity": "error",
        }
    ]
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert "TaintedHtml" in findings[0].message


# ---------------------------------------------------------------------------
# Nested files format (real Psalm output)
# ---------------------------------------------------------------------------


def test_parse_nested_files_tainted_sql() -> None:
    """Nested files format with TaintedSql."""
    data = {
        "files": {
            "src/Query.php": {
                "psalmErrors": [
                    {
                        "type": "TaintedSql",
                        "line_from": 5,
                        "message": "User input reaches SQL",
                    }
                ]
            }
        }
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].node == "src/Query.php:5"
    assert findings[0].message.startswith("TaintedSql:")


def test_parse_nested_files_multiple() -> None:
    """Multiple files with multiple errors."""
    data = {
        "files": {
            "a.php": {
                "psalmErrors": [
                    {"type": "TaintedSql", "line_from": 1},
                    {"type": "TaintedHtml", "line_from": 2},
                ]
            },
            "b.php": {
                "psalmErrors": [
                    {"type": "TaintedShell", "line_from": 3},
                ]
            },
        }
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 3


# ---------------------------------------------------------------------------
# Filtering — non-taint types excluded
# ---------------------------------------------------------------------------


def test_parse_filters_non_taint_errors() -> None:
    """Non-taint psalmErrors are excluded."""
    data = {
        "files": {
            "src/x.php": {
                "psalmErrors": [
                    {"type": "UndefinedClass", "line_from": 1},
                    {"type": "TaintedSql", "line_from": 5, "message": "injection possible"},
                ]
            }
        }
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].message.startswith("TaintedSql:")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_parse_empty_output() -> None:
    """Empty stdout → no findings."""
    assert _adapter().parse("", "", 0) == []


def test_parse_invalid_json() -> None:
    """Malformed JSON → no findings."""
    assert _adapter().parse("not json", "", 1) == []


def test_parse_empty_array() -> None:
    """Empty array → no findings."""
    assert _adapter().parse("[]", "", 0) == []


def test_parse_no_taint_in_array() -> None:
    """Array with non-taint objects → no findings."""
    data = [{"type": "UndefinedVariable", "file_name": "x.php"}]
    assert _adapter().parse(json.dumps(data), "", 0) == []


def test_parse_array_missing_type_key() -> None:
    """Array item with no 'type' key → treated as non-taint (empty default).

    Kills mutmut mutations that change the default value of .get("type", "")
    to None, removed, or a different string — all should remain outside
    TAINT_RULE_TYPES and be skipped.
    """
    data = [
        {"file_name": "src/x.php", "line_from": 1},  # no "type" key at all
    ]
    findings = _adapter().parse(json.dumps(data), "", 0)
    assert len(findings) == 0


def test_parse_array_non_taint_then_taint() -> None:
    """Non-taint item followed by taint item → both must be inspected.

    Kills the 'continue → break' mutation in the non-taint filter loop.
    If break fires first, the taint item is never examined.
    """
    data = [
        {"type": "UndefinedVariable", "file_name": "src/x.php"},
        {"type": "TaintedSql", "file_name": "src/Query.php", "line_from": 42},
    ]
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].node == "src/Query.php:42"


def test_parse_nested_files_missing_type_key() -> None:
    """Nested files format with item missing 'type' key.

    Covers line 208 (err.get("type", "")). Items with missing type
    are skipped by the `not taint_type` guard.
    """
    data = {
        "files": {
            "src/x.php": {
                "psalmErrors": [
                    {"file_name": "src/x.php", "line_from": 1},  # no "type" key
                ]
            }
        }
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 0


def test_parse_array_non_dict_then_taint() -> None:
    """Non-dict item (e.g. string) followed by taint item → both processed.

    Kills the 'continue → break' mutation in the isinstance item check.
    If break fires, the taint item after the non-dict is skipped.
    """
    data = [
        "not a dict",  # non-dict item
        {"type": "TaintedSql", "file_name": "src/Query.php", "line_from": 42},
    ]
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1


def test_parse_nested_files_empty_type_then_taint() -> None:
    """Item with empty type followed by taint item in same file.

    Kills the 'continue → break' mutation in the `not taint_type` check
    for the nested files format. If break fires, the taint item is skipped.
    """
    data = {
        "files": {
            "src/x.php": {
                "psalmErrors": [
                    {"type": "", "line_from": 1},  # empty type → not taint_type
                    {"type": "TaintedSql", "line_from": 5},
                ]
            }
        }
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].node == "src/x.php:5"


def test_parse_unknown_top_level_key() -> None:
    """JSON neither array nor files dict → no findings."""
    assert _adapter().parse('{"foo": 1}', "", 0) == []


# ---------------------------------------------------------------------------
# _make_finding static method
# ---------------------------------------------------------------------------


def test_make_finding_with_line() -> None:
    """PsalmTaintAdapter._make_finding with line → node includes line."""
    f = PsalmTaintAdapter._make_finding(
        file_name="src/x.php",
        line=10,
        taint_type="TaintedSql",
        message="injection",
        severity="error",
    )
    assert f.node == "src/x.php:10"
    assert f.message == "TaintedSql: injection"
    assert f.rule_id == "TaintedSql"


def test_make_finding_without_line() -> None:
    """PsalmTaintAdapter._make_finding without line → node is just file."""
    f = PsalmTaintAdapter._make_finding(
        file_name="src/x.php",
        line=None,
        taint_type="TaintedHtml",
        message="",
        severity="warning",
    )
    assert f.node == "src/x.php"
    assert f.message == "TaintedHtml"
    assert f.severity == "warning"
