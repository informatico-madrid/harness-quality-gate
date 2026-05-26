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
                "messages": ["Property $x is never read"],
            }
        ]
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "src/Foo.php"
    assert f.severity == "error"
    assert f.message == "Property $x is never read"
    assert f.tool == "phpstan"
    assert f.layer == "L3A"
    assert f.language == "php"


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
    assert f.fix_hint == "Did you mean 'bar()'? "  # fix_hint is the raw tip
    assert f.message == "Unknown method (Did you mean 'bar()'? "[:-1]  # strip trailing space


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
