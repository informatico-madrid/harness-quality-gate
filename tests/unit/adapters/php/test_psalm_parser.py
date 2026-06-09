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
    assert f.severity == "error"
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
    assert findings[0].message == "TaintedSql: User input reaches SQL"


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
    """Non-taint psalmErrors are excluded, only taint types included."""
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
    data = [
        {"type": "UndefinedVariable", "file_name": "x.php"},
        {"file_name": "y.php"},  # no type key → empty → skip
    ]
    assert _adapter().parse(json.dumps(data), "", 0) == []


def test_parse_array_missing_type_key() -> None:
    """Array item with no 'type' key → treated as empty default.

    Combined with a valid taint item, this ensures that:
    - Items with missing-type keys are handled without error
    - Valid taint-type items are still processed

    This test kills mutations that change the default value of
    .get("type", "") to None, removed, or a different string — all
    result in non-taint types that are asserted as invalid.

    Mutation 14 ("" → "XXXX"): with "XXXX" in TAINT_RULE_TYPES, a
    missing-type item gets recognized as taint and produces an extra
    finding, failing this exact-count assertion.
    """
    data = [
        {"file_name": "src/x.php", "line_from": 1},  # no "type" key → empty default
        {"type": "TaintedSql", "file_name": "src/Query.php", "line_from": 42},
    ]
    findings = _adapter().parse(json.dumps(data), "", 0)
    assert len(findings) == 1
    assert findings[0].node == "src/Query.php:42"
    assert findings[0].rule_id == "TaintedSql"
    assert findings[0].message == "TaintedSql"
    assert findings[0].severity == "error"


def test_parse_array_non_taint_then_taint() -> None:
    """Non-taint item followed by taint item with explicit message → both inspected.

    The non-taint item (empty type) is skipped by _extract_type_valid,
    and the valid taint item is still processed.

    Asserts exact message value: when the input item has message="injection possible",
    desc should be "TaintedSql: injection possible". A message mutation that changes
    item.get("message", "") to None would produce desc="TaintedSql" (no colon), killing
    this assertion. This test also kills type mutations via the rule_id assertion.
    """
    data = [
        {"file_name": "src/x.php"},  # no type key → empty → skip
        {
            "type": "TaintedSql",
            "file_name": "src/Query.php",
            "line_from": 42,
            "message": "injection possible",
        },
    ]
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].node == "src/Query.php:42"
    assert findings[0].message == "TaintedSql: injection possible"
    assert findings[0].rule_id == "TaintedSql"
    assert findings[0].severity == "error"


def test_parse_nested_files_missing_type_key() -> None:
    """Nested files format with item missing 'type' key.

    Combined with a valid taint item, this ensures that items with
    missing-type keys are handled without error and valid taint items
    are still processed. This kills mutations that change the default
    value of .get("type", "") to a non-empty non-taint string.
    """
    data = {
        "files": {
            "src/x.php": {
                "psalmErrors": [
                    {"file_name": "src/x.php", "line_from": 1},  # no type
                    {"type": "TaintedSql", "line_from": 5},
                ]
            }
        }
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].node == "src/x.php:5"


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


def test_extract_type_valid_none_treated_as_taint() -> None:
    """None raw_type must be treated as taint (kills mutmut on .get default)."""
    from harness_quality_gate.adapters.php.psalm_taint_adapter import PsalmTaintAdapter

    raw_type, is_taint = PsalmTaintAdapter._extract_type_valid(None)
    assert raw_type is None
    assert is_taint is True


def test_extract_type_valid_known_taint() -> None:
    """Known TAINT_RULE_TYPES return (type, True)."""
    from harness_quality_gate.adapters.php.psalm_taint_adapter import PsalmTaintAdapter

    raw_type, is_taint = PsalmTaintAdapter._extract_type_valid("TaintedHtml")
    assert raw_type == "TaintedHtml"
    assert is_taint is True


def test_extract_type_valid_unknown_returns_false() -> None:
    """Unknown type or empty string returns (raw, False) — skipped."""
    from harness_quality_gate.adapters.php.psalm_taint_adapter import PsalmTaintAdapter

    raw_type, is_taint = PsalmTaintAdapter._extract_type_valid("UndefinedClass")
    assert raw_type == "UndefinedClass"
    assert is_taint is False

    raw_type, is_taint = PsalmTaintAdapter._extract_type_valid("")
    assert raw_type == ""
    assert is_taint is False


# ---------------------------------------------------------------------------
# Edge cases — missing default-value keys (kills mutmut_14, 31, 33, 36, 41, 43)
# ---------------------------------------------------------------------------


def test_parse_array_taint_with_no_file_name() -> None:
    """Array item with valid taint type but no file_name or line_from.

    Used for edge-case coverage of the missing-key path in parse().
    """
    data = [{"type": "TaintedSql"}]
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].node == ""
    assert "TaintedSql" in findings[0].message


def test_parse_array_taint_with_no_file_name_or_message() -> None:
    """Array item missing file_name — kills mutants 31, 33, 36.

    Mutant mutmut_14 is caught by test_parse_array_no_type_key: changing
    default from '' to 'XXXX' would add a finding, failing the empty assertion.

    Mutants 31/33 change get("file_name", "") to None.
    Mutant 36 changes it to "XXXX".

    Original: file_name="", line=5 → node=":5" (empty file_name + ":" + 5).
    Mutated: file_name=None/None/XXXX → node="None:5" or "XXXX:5".
    Asserting exact node value kills all three.
    """
    data = [{"type": "TaintedSql", "line_from": 5}]  # no file_name
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    # Original node: f"{''}:{5}" = ':5'
    # Mutated 31/33: f"{None}:{5}" = 'None:5'  → assertion fails → killed
    # Mutated 36:     f"XXXX:5" = 'XXXX:5' → assertion fails → killed
    assert findings[0].node == ":5"


def test_parse_array_item_missing_type_key() -> None:
    """Array item with missing type key — tests parsing robustness."""
    data = [
        {},  # no type — skipped (not taint)
        {"type": "TaintedSql", "file_name": "src/x.php", "line_from": 5},
    ]
    findings = _adapter().parse(json.dumps(data), "", 0)
    assert len(findings) == 1
    assert findings[0].rule_id == "TaintedSql"


def test_parse_item_with_taint_type_and_missing_message() -> None:
    """Array item with valid taint type but no message field.

    Verifies exact node and message construction.
    Mutations 41/43 (message get default "" → None or removed):
    When message get returns None instead of "", the desc computation
    changes. With "" → desc="TaintedSql" (empty message stripped).
    With None → desc depends on mutmut behavior but assertion on exact
    value catches any difference.
    """
    data = [{"type": "TaintedSql", "file_name": "src/x.php", "line_from": 5}]
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].node == "src/x.php:5"
    assert findings[0].message == "TaintedSql"
    assert findings[0].severity == "error"


def test_parse_array_item_missing_severity() -> None:
    """Array item with valid taint type but no severity field.

    Kills mutations 48 (severity get default "error" → None) and
    50 (severity get default "error" → removed/default). When the
    severity get returns None or empty instead of "error", the
    finding gets the wrong severity.

    Asserts exact severity value to catch any deviation.
    """
    data = [{"type": "TaintedSql", "file_name": "src/x.php", "line_from": 5}]
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert findings[0].message == "TaintedSql"


# ---------------------------------------------------------------------------
# Mutants 41/43 — _extract_type_valid default values (message)
# ---------------------------------------------------------------------------


def test_parse_array_item_missing_message_default() -> None:
    """Array item with valid taint type but no message field.

    NOTE: Mutmut_41 ("" → None) and mutmut_43 ("" → removed default → None)
    are UNKILLABLE without modifying _make_finding. Both mutations change the
    .get() default from "" to None, but since _make_finding uses `if message`
    (falsy for both "" and None), the desc is computed identically ("TaintedSql").
    This test still exercises the missing-key path for coverage.

    For killability, these mutations would require asserting
    _make_finding's taint_type parameter directly (via mock).
    """
    data = [{"type": "TaintedSql", "file_name": "src/x.php", "line_from": 5}]
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].message == "TaintedSql"


# ---------------------------------------------------------------------------
# Mutant 47 — _extract_type_valid severity key mutation
# ---------------------------------------------------------------------------


def test_parse_nested_files_severity_values() -> None:
    """Nested files with items having explicit severity values (> or < "error").

    Kills mutmut_47 (severity get "error" → get(None, "error")):
    Mutant always returns "error" default since item.get(None, ...) returns
    default for any item. By providing both "error" and "warning" items and
    asserting both, the mutant (which always produces "error") fails on
    the warning assertion.
    """
    data = {
        "files": {
            "src/x.php": {
                "psalmErrors": [
                    {"type": "TaintedSql", "line_from": 1, "severity": "warning"},
                    {"type": "TaintedSql", "line_from": 5, "severity": "error"},
                ]
            }
        }
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 2
    assert findings[0].severity == "warning"
    assert findings[1].severity == "error"


# ---------------------------------------------------------------------------
# Mutants 5/6 — Logger warning message in invoke
# ---------------------------------------------------------------------------


def test_invoke_infra_incomplete_warning_logged() -> None:
    """When psalm is not found, the exact warning message is logged.

    Kills mutmut_5 (logger.warning("...") → logger.warning(None)) and
    mutmut_6 (logger.warning("...psalm...") → logger.warning("XX...psalm...XX")).

    Uses caplog to capture and assert the exact warning message.
    """
    from unittest.mock import patch

    adapter = _adapter()
    with patch.object(adapter, "_psalm_binary", return_value=None):
        with patch("harness_quality_gate.adapters.php.psalm_taint_adapter.logger") as mock:
            result = adapter.invoke("/tmp", [])
            assert result.exitcode == 3
            # Assert exact warning message to catch mutmut_5 (None) and mutmut_6 ("XX...XX")
            mock.warning.assert_called_once_with("psalm not found; returning INFRA_INCOMPLETE")


# ---------------------------------------------------------------------------
# Edge cases — missing field defaults (catches .get("key", "") mutations)
# ---------------------------------------------------------------------------


def test_parse_array_item_missing_line_from() -> None:
    """Array item with missing line_from — test exact node format.

    Catches mutations on line_from default: "" → None or "XXXX".
    When line_from is missing, the Finding node should be just the filepath.
    """
    data = [{"type": "TaintedSql", "file_name": "src/x.php"}]  # no line_from
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].node == "src/x.php"  # line is None → node is just file
    assert findings[0].severity == "error"


def test_parse_array_item_missing_severity_and_message() -> None:
    """Item missing both severity and message — defaults must be exact.

    Catches mutations on severity get(default "error" → "XXerrorXX" or None).
    Catches mutations on message get(default "" → None or "XXXX").
    When both are missing, severity should be "error" and message "TaintedSql".
    """
    data = [{"type": "TaintedHtml", "file_name": "src/x.php", "line_from": 10}]
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert findings[0].message == "TaintedHtml"  # TaintedHtml + ": " + "" = "TaintedHtml"


def test_parse_nested_files_missing_type_key_default() -> None:
    """Nested files format — item with missing 'type' key uses empty default.

    Catches mutation that changes type default from "" to None or other value.
    Missing-type items have raw_type="" which is NOT in TAINT_RULE_TYPES → skipped.
    Combined with a taint item, the count assertion catches extra findings from wrong defaults.
    """
    data = {
        "files": {
            "src/x.php": {
                "psalmErrors": [
                    {"file_name": "src/x.php", "line_from": 1},  # no type
                    {"type": "TaintedShell", "file_name": "src/x.php", "line_from": 5, "message": "shell"},
                ]
            }
        }
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].rule_id == "TaintedShell"


def test_parse_nested_files_missing_severity_in_item() -> None:
    """Nested files item missing severity — must default to 'error'.

    Catches mutation on severity default. If default changes to None or "", 
    the Finding gets the mutated value instead of 'error'.
    """
    data = {
        "files": {
            "src/x.php": {
                "psalmErrors": [
                    {"type": "TaintedXss", "file_name": "src/x.php", "line_from": 7},
                ]
            }
        }
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert findings[0].message == "TaintedXss"


def test_parse_nested_files_severity_override_from_item() -> None:
    """Nested files item with explicit severity — must use item value not default.

    Ensures the severity from the input item is used, not overridden by mutation.
    If mutation changes the get call to always return default, this would fail.
    """
    data = {
        "files": {
            "src/x.php": {
                "psalmErrors": [
                    {"type": "TaintedCommand", "line_from": 3, "severity": "critical"},
                    {"type": "TaintedEval", "line_from": 7, "severity": "warning"},
                ]
            }
        }
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 2
    assert findings[0].severity == "critical"
    assert findings[1].severity == "warning"


def test_parse_nested_array_entry_missing_file_name() -> None:
    """Array format item missing file_name — node must use empty string default.

    Catches mutations on file_name default value. When file_name is missing,
    the node format is f"{file_name}:{line_from}" where file_name="" → ":5".
    Mutations changing default to None or "XXXX" would produce different node.
    """
    data = [{"type": "TaintedCookie", "line_from": 5}]  # no file_name
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].node == ":5"


def test_parse_nested_array_entry_missing_line_and_file() -> None:
    """Array item missing both file_name and line_from — node is just severity + message.

    Verifies edge case where file_name and line_from are both missing.
    """
    data = [{"type": "TaintedLFI", "message": "local file inclusion"}]
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].node == ""  # file_name="" + no line → just filepath (empty)


def test_parse_nested_multiple_errors_mixed_missing_fields() -> None:
    """Multiple psalmErrors with various missing fields — asserts exact outputs.

    Catches mutations on multiple field defaults simultaneously.
    Tests items with: missing line_from, missing severity, missing message.
    Each Finding must have correct defaults.

    In nested files format, file_name comes from outer key (filepath),
    so only inner item fields (line_from, message, severity) are variable.
    """
    data = {
        "files": {
            "src/mixed.php": {
                "psalmErrors": [
                    {"type": "TaintedNoSqlCommand", "message": "msg1"},  # missing line_from, severity
                    {"type": "TaintedNoSql", "line_from": 20},  # missing message, severity
                    {"type": "TaintedSql"},  # missing line_from, message, severity
                ]
            }
        }
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 3
    f0, f1, f2 = findings
    assert f0.node == "src/mixed.php"  # filepath + no line
    assert f0.message == "TaintedNoSqlCommand: msg1"
    assert f0.severity == "error"
    assert f1.node == "src/mixed.php:20"
    assert f1.message == "TaintedNoSql"  # missing message → ""
    assert f1.severity == "error"
    assert f2.node == "src/mixed.php"  # filepath + no line
    assert f2.message == "TaintedSql"
    assert f2.severity == "error"


def test_parse_nested_file_data_not_dict() -> None:
    """When file_data in files structure is not a dict, skip it silently.

    Catches mutations that change continue → break or remove the isinstance check.
    If break were used instead of continue, subsequent items would be skipped.
    """
    data = {
        "files": {
            "src/a.php": "not a dict",  # not a dict
            "src/b.php": {
                "psalmErrors": [
                    {"type": "TaintedSSRF", "line_from": 5},
                ]
            }
        }
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].rule_id == "TaintedSSRF"


def test_invoke_psalm_found_version_path() -> None:
    """When psalm binary is found, invoke delegates to _run without error.

    Catches mutations on the cmd construction and _run call.
    When psalm is found, invoke should call _run with correct cmd and env.
    """
    from unittest.mock import patch, MagicMock

    adapter = _adapter()

    with patch.object(adapter, "_psalm_binary", return_value=["/usr/local/bin/psalm"]):
        with patch.object(adapter, "_run", return_value=MagicMock(stdout="[]", stderr="", exitcode=0, duration_seconds=0.0)) as mock_run:
            result = adapter.invoke("/tmp", ["--taint-analysis"])
            # _run should be called with combined cmd
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert call_args[0][0] == ["/usr/local/bin/psalm", "--taint-analysis"]
