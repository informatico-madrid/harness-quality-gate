"""Unit tests for PHPStan adapter parser.

Covers file_diagnostics format, legacy files format, empty/invalid input,
and error entries with tip.
"""

from __future__ import annotations

import json

from harness_quality_gate.adapters.php.phpstan_adapter import PhpStanAdapter


def _adapter() -> PhpStanAdapter:
    return PhpStanAdapter()


# ---------------------------------------------------------------------------
# file_diagnostics format
# ---------------------------------------------------------------------------


def test_parse_file_diagnostics_messages() -> None:
    """file_diagnostics format → findings from messages."""
    data: dict = {
        "file_diagnostics": [
            {
                "file": "src/Foo.php",
                "messages": ["Property $x is never read", "Second message"],
            }
        ]
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 2
    # Verify each finding has all fields (catches mutations that change/strip fields)
    for f in findings:
        assert f.node == "src/Foo.php"
        assert f.severity == "error"
        assert f.fix_hint is None
        assert f.tool == "phpstan"
        assert f.layer == "L3A"
        assert f.language == "php"
    assert findings[0].message == "Property $x is never read"
    assert findings[1].message == "Second message"


def test_parse_file_diagnostics_errors_with_tip() -> None:
    """file_diagnostics errors → Finding with fix_hint from tip."""
    data: dict = {
        "file_diagnostics": [
            {
                "file": "src/Bar.php",
                "messages": [],
                "errors": [
                    {
                        "message": "Unknown method",
                        "tip": "Did you mean 'bar()'? ",  # trailing space tests rstrip on message
                    }
                ],
            }
        ]
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "src/Bar.php"
    assert f.severity == "error"
    assert f.fix_hint == "Did you mean 'bar()'? "  # fix_hint is the raw tip
    assert f.message == "Unknown method (Did you mean 'bar()'? "[:-1]  # strip trailing space
    assert f.tool == "phpstan"
    assert f.layer == "L3A"
    assert f.language == "php"


def test_parse_file_diagnostics_mixed() -> None:
    """file_diagnostics with both messages and errors."""
    data: dict = {
        "file_diagnostics": [
            {
                "file": "src/Baz.php",
                "messages": ["Message 1", "Message 2"],
                "errors": [
                    {"message": "E1", "tip": "T1"},
                ],
            }
        ]
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 3
    # Verify ALL fields on ALL findings (catches mutations that change/strip fields)
    for i in range(3):
        assert findings[i].node == "src/Baz.php"
        assert findings[i].severity == "error"
        assert findings[i].tool == "phpstan"
        assert findings[i].layer == "L3A"
        assert findings[i].language == "php"
    assert findings[0].message == "Message 1"
    assert findings[0].fix_hint is None
    assert findings[1].message == "Message 2"
    assert findings[1].fix_hint is None
    # rstrip(" ()") strips trailing ) from "E1 (T1)"
    assert findings[2].message == "E1 (T1"
    assert findings[2].fix_hint == "T1"


def test_parse_file_diagnostics_error_empty_tip() -> None:
    """file_diagnostics error with empty tip → empty message stripped by rstrip."""
    data: dict = {
        "file_diagnostics": [
            {
                "file": "src/Bad.php",
                "messages": [],
                "errors": [
                    {"message": "Something wrong", "tip": ""},
                ],
            }
        ]
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    f = findings[0]
    # "Something wrong ()".rstrip(" ()") = "Something wrong"
    assert f.node == "src/Bad.php"
    assert f.severity == "error"
    assert f.message == "Something wrong"
    assert f.fix_hint == ""
    assert f.tool == "phpstan"
    assert f.layer == "L3A"
    assert f.language == "php"


def test_parse_file_diagnostics_error_only_tip() -> None:
    """file_diagnostics error with no message key → message includes tip."""
    data: dict = {
        "file_diagnostics": [
            {
                "file": "src/TipOnly.php",
                "messages": [],
                "errors": [
                    {"tip": "Fix this"},
                ],
            }
        ]
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    f = findings[0]
    # " (Fix this)".rstrip(" ()") = " (Fix this" (no trailing chars to strip)
    assert f.node == "src/TipOnly.php"
    assert f.severity == "error"
    assert f.message == " (Fix this"
    assert f.fix_hint == "Fix this"
    assert f.tool == "phpstan"
    assert f.layer == "L3A"
    assert f.language == "php"


def test_parse_file_diagnostics_missing_file_key() -> None:
    """file_diagnostics with missing 'file' key → node defaults to ''."""
    data: dict = {
        "file_diagnostics": [
            {"messages": ["orphaned finding"]},
        ]
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    f = findings[0]
    assert f.node == ""
    assert f.severity == "error"
    assert f.message == "orphaned finding"
    assert f.fix_hint is None
    assert f.tool == "phpstan"
    assert f.layer == "L3A"
    assert f.language == "php"


def test_parse_file_diagnostics_missing_messages_key() -> None:
    """file_diagnostics with missing 'messages' key → defaults to []."""
    data: dict = {
        "file_diagnostics": [
            {"file": "x.php", "errors": []},
        ]
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert findings == []


def test_parse_file_diagnostics_missing_errors_key() -> None:
    """file_diagnostics with missing 'errors' key → defaults to []."""
    data: dict = {
        "file_diagnostics": [
            {"file": "x.php", "messages": ["one"]},
        ]
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].message == "one"


def test_parse_file_diagnostics_non_dict_item() -> None:
    """file_diagnostics list contains non-dict item → skipped, no finding."""
    data: dict = {
        "file_diagnostics": [
            {"file": "valid.php", "messages": ["ok"]},
            "not a dict",
            42,
            None,
        ]
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "valid.php"
    assert f.severity == "error"
    assert f.message == "ok"
    assert f.fix_hint is None
    assert f.tool == "phpstan"
    assert f.layer == "L3A"
    assert f.language == "php"


def test_parse_file_diagnostics_non_dict_items_first() -> None:
    """Non-dict items FIRST in file_diagnostics → break mutation would skip valid items."""
    data: dict = {
        "file_diagnostics": [
            "bad_item",
            42,
            {"file": "should_be_reached.php", "messages": ["msg"]},
        ]
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    # With 'continue', the valid item should still be processed
    # With 'break' mutation, it would be skipped
    assert len(findings) == 1
    assert findings[0].node == "should_be_reached.php"
    assert findings[0].message == "msg"
    assert findings[0].severity == "error"


def test_parse_file_diagnostics_multiple_files() -> None:
    """file_diagnostics with multiple file_diagnostic entries."""
    data: dict = {
        "file_diagnostics": [
            {"file": "src/A.php", "messages": ["A-msg"]},
            {"file": "src/B.php", "messages": ["B-msg"]},
            {"file": "src/C.php", "messages": [], "errors": [{"message": "C-err", "tip": "C-tip"}]},
        ]
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 3
    # All fields must be verified to kill mutations that change/strip fields
    for i in range(3):
        assert findings[i].severity == "error"
        assert findings[i].tool == "phpstan"
        assert findings[i].layer == "L3A"
        assert findings[i].language == "php"
    assert findings[0].node == "src/A.php"
    assert findings[0].message == "A-msg"
    assert findings[0].fix_hint is None
    assert findings[1].node == "src/B.php"
    assert findings[1].message == "B-msg"
    assert findings[1].fix_hint is None
    assert findings[2].node == "src/C.php"
    assert findings[2].message == "C-err (C-tip"
    assert findings[2].fix_hint == "C-tip"


# ---------------------------------------------------------------------------
# Legacy files format - edge cases
# ---------------------------------------------------------------------------


def test_parse_legacy_files_non_dict_file_data() -> None:
    """Legacy format: file_data is not a dict → skipped."""
    data: dict = {"files": {"bad.php": "string_not_dict", "good.php": {"messages": ["ok"]}}}
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "good.php"
    assert f.severity == "error"
    assert f.message == "ok"
    assert f.fix_hint is None
    assert f.tool == "phpstan"
    assert f.layer == "L3A"
    assert f.language == "php"


def test_parse_legacy_files_missing_messages_key() -> None:
    """Legacy format: file_data dict missing 'messages' → empty list."""
    data: dict = {"files": {"x.php": {"other": "value"}}}
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert findings == []


def test_parse_legacy_files_non_string_non_dict_messages() -> None:
    """Legacy format: messages contain non-string, non-dict items → skipped."""
    data: dict = {
        "files": {
            "good.php": {"messages": ["valid"]},
            "mixed.php": {
                "messages": [
                    "string_msg",
                    {"message": "dict_msg"},
                    None,
                    42,
                    ["list_not_allowed"],
                ]
            },
        }
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 3
    for f in findings:
        assert f.severity == "error"
        assert f.fix_hint is None
        assert f.tool == "phpstan"
        assert f.layer == "L3A"
        assert f.language == "php"
    assert findings[0].message == "valid"
    assert findings[1].message == "string_msg"
    assert findings[2].message == "dict_msg"


def test_parse_legacy_files_non_dict_first() -> None:
    """Non-string/non-dict items FIRST in messages → break mutation would skip valid items."""
    data: dict = {
        "files": {
            "x.php": {"messages": [None, 42, "valid_msg", {"message": "dict_msg"}]},
        }
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    # With 'continue', both valid items should be found
    # With 'break' mutation, none would be found after the first non-match
    assert len(findings) == 2
    assert findings[0].message == "valid_msg"
    assert findings[1].message == "dict_msg"


def test_parse_error_missing_tip_key() -> None:
    """Error entry missing 'tip' key triggers default '' in message construction.
    
    Kills mutants 80 (get('tip', None)), 82 (get('tip', )), 85 (get('tip', 'XXXX')).
    Mutations change the default → different message string.
    """
    data: dict = {
        "file_diagnostics": [
            {
                "file": "src/X.php",
                "messages": [],
                "errors": [
                    {"message": "Some error"},  # no 'tip' key
                ],
            }
        ]
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    f = findings[0]
    # Default for err.get('tip', '') is '' → message = "Some error ()" → rstrip = "Some error"
    # If default is None → "Some error (None)" → rstrip = "Some error (None"
    # If default is 'XXXX' → "Some error (XXXX)" → rstrip = "Some error (XXXX"
    assert f.message == "Some error"


def test_parse_error_messages_rstrip_arg() -> None:
    """Error message rstrip arg mutation.
    
    Kills mutant 86: rstrip(" ()") → rstrip("XX ()XX") which does nothing.
    We verify exact rstrip behavior with trailing ) in constructed message.
    """
    data: dict = {
        "file_diagnostics": [
            {
                "file": "src/X.php",
                "messages": [],
                "errors": [
                    {"message": "Ends with paren", "tip": "x"},
                ],
            }
        ]
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    f = findings[0]
    # "Ends with paren (x)".rstrip(" ()") = "Ends with paren (x"
    # If rstrip("XX ()XX") → "Ends with paren (x))" (rstrip still only removes from end)
    assert f.message == "Ends with paren (x"


def test_parse_legacy_files_dict_message_no_message_key() -> None:
    """Legacy format: dict message without 'message' key → message defaults to ''."""
    data: dict = {"files": {"x.php": {"messages": [{"tip": "only tip"}]}}}
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].message == ""
    assert findings[0].fix_hint is None


def test_parse_legacy_empty_files_dict() -> None:
    """Legacy format with empty files dict → no findings."""
    data: dict = {"files": {}}
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert findings == []


def test_parse_legacy_files_with_none_value() -> None:
    """Legacy format: file_data value is None → skipped (not a dict)."""
    data: dict = {"files": {"x.php": None}}
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert findings == []


# ---------------------------------------------------------------------------
# Legacy files format
# ---------------------------------------------------------------------------


def test_parse_legacy_files_format() -> None:
    """Legacy {files: {path: {messages: [...]}}} format."""
    data: dict = {
        "files": {
            "src/Legacy.php": {
                "messages": [
                    {"message": "Legacy error 1"},
                    "Legacy string error",
                ]
            }
        }
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 2
    assert findings[0].message == "Legacy error 1"
    assert findings[1].message == "Legacy string error"


def test_parse_legacy_files_string_messages() -> None:
    """Legacy format with string (non-dict) messages."""
    data: dict = {"files": {"x.php": {"messages": ["just a string"]}}}
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    assert findings[0].message == "just a string"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_parse_empty_output() -> None:
    """Empty stdout → no findings."""
    assert _adapter().parse("", "", 0) == []


def test_parse_invalid_json() -> None:
    """Malformed JSON → no findings."""
    assert _adapter().parse("not json at all", "", 1) == []


def test_parse_no_errors() -> None:
    """file_diagnostics with no messages/errors → empty."""
    data: dict = {"file_diagnostics": [{"file": "x.php", "messages": [], "errors": []}]}
    assert _adapter().parse(json.dumps(data), "", 0) == []


def test_parse_unknown_top_level_key() -> None:
    """JSON with neither file_diagnostics nor files → empty."""
    assert _adapter().parse('{"unknown": 1}', "", 0) == []
