"""Unit tests for DeadCodeAdapter — ShipMonk dead-code-detector parser.

Covers:
- ShipMonk JSON format: {'references': [{'file': ..., 'message': ..., 'tip': ...}]}
- Generic per-file format: {'files': {'path': {'messages': [...]}}}
- Fallback _parse_lines: non-JSON stdout, one line = one finding
- Empty output, invalid JSON, non-dict top-level values
- invoke() — binary not found / binary found
- version() — NotImplementedError
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.php.dead_code_adapter import DeadCodeAdapter
from harness_quality_gate.models import Finding


def _adapter() -> DeadCodeAdapter:
    """Helper to create a fresh adapter instance."""
    return DeadCodeAdapter()


# ====================================================================
# parse() — empty / invalid input
# ====================================================================


def test_parse_empty() -> None:
    """Empty stdout → no findings."""
    findings = _adapter().parse("")
    assert findings == []


def test_parse_whitespace_only() -> None:
    """Whitespace-only stdout → no findings (stripped)."""
    findings = _adapter().parse("   \n  \n  ")
    assert findings == []


def test_parse_invalid_json() -> None:
    """Non-JSON stdout → falls through to _parse_lines."""
    findings = _adapter().parse("not json at all")
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "not json at all"
    assert f.severity == "warning"
    assert f.message == "not json at all"
    assert f.fix_hint is None
    assert f.tool == "dead-code-detector"
    assert f.layer == "L4"
    assert f.language == "php"


# ====================================================================
# parse() — ShipMonk JSON format (single reference)
# ====================================================================


def test_parse_shipmonk_single_reference_full() -> None:
    """Reference with file + message + tip → one Finding with correct fields."""
    data = {"references": [{"file": "src/Foo.php", "message": "Unused class", "tip": "Remove it"}]}
    findings = _adapter().parse(json.dumps(data))
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "src/Foo.php"
    assert f.severity == "warning"
    assert f.message == "Unused class"
    assert f.fix_hint == "Remove it"
    assert f.tool == "dead-code-detector"
    assert f.layer == "L4"
    assert f.language == "php"


def test_parse_shipmonk_single_reference_message_only() -> None:
    """Reference with only message (no tip) → fix_hint = None."""
    data = {"references": [{"file": "src/Bar.php", "message": "Dead code"}]}
    findings = _adapter().parse(json.dumps(data))
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "src/Bar.php"
    assert f.severity == "warning"
    assert f.message == "Dead code"
    assert f.fix_hint is None
    assert f.tool == "dead-code-detector"
    assert f.layer == "L4"
    assert f.language == "php"


def test_parse_shipmonk_single_reference_tip_only() -> None:
    """Reference with only tip (no message) → message = tip, fix_hint = tip."""
    data = {"references": [{"file": "src/Baz.php", "tip": "Consider deleting"}]}
    findings = _adapter().parse(json.dumps(data))
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "src/Baz.php"
    assert f.severity == "warning"
    assert f.message == "Consider deleting"
    assert f.fix_hint == "Consider deleting"
    assert f.tool == "dead-code-detector"
    assert f.layer == "L4"
    assert f.language == "php"


def test_parse_shipmonk_reference_no_file_field() -> None:
    """Reference missing 'file' key → node defaults to ''."""
    data = {"references": [{"message": "orphaned function", "tip": "Remove"}]}
    findings = _adapter().parse(json.dumps(data))
    assert len(findings) == 1
    f = findings[0]
    assert f.node == ""
    assert f.severity == "warning"
    assert f.message == "orphaned function"
    assert f.fix_hint == "Remove"
    assert f.tool == "dead-code-detector"
    assert f.layer == "L4"
    assert f.language == "php"


# ====================================================================
# parse() — ShipMonk JSON format (default message fallback)
# ====================================================================


def test_parse_shipmonk_reference_no_message_no_tip() -> None:
    """Reference without message AND tip → default 'Dead code reference'."""
    data = {"references": [{"file": "src/Empty.php"}]}
    findings = _adapter().parse(json.dumps(data))
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "src/Empty.php"
    assert f.severity == "warning"
    assert f.message == "Dead code reference"
    assert f.fix_hint is None
    assert f.tool == "dead-code-detector"
    assert f.layer == "L4"
    assert f.language == "php"


# ====================================================================
# parse() — ShipMonk JSON format (multiple references, filtering)
# ====================================================================


def test_parse_shipmonk_multiple_references() -> None:
    """Multiple references → one Finding per reference, all fields correct."""
    data = {
        "references": [
            {"file": "src/A.php", "message": "MsgA", "tip": "TipA"},
            {"file": "src/B.php", "message": "MsgB"},
            {"file": "src/C.php", "tip": "TipC"},
        ],
    }
    findings = _adapter().parse(json.dumps(data))
    assert len(findings) == 3

    for i, (expected_node, expected_msg, expected_fix) in enumerate(
        [
            ("src/A.php", "MsgA", "TipA"),
            ("src/B.php", "MsgB", None),
            ("src/C.php", "TipC", "TipC"),
        ],
    ):
        f = findings[i]
        assert f.node == expected_node
        assert f.severity == "warning"
        assert f.message == expected_msg
        assert f.fix_hint == expected_fix
        assert f.tool == "dead-code-detector"
        assert f.layer == "L4"
        assert f.language == "php"


def test_parse_shipmonk_mixed_ref_types() -> None:
    """References list containing non-dict items → those are skipped."""
    data = {
        "references": [
            {"file": "src/Good.php", "message": "OK"},
            "not a dict",
            None,
            42,
        ],
    }
    findings = _adapter().parse(json.dumps(data))
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "src/Good.php"
    assert f.severity == "warning"
    assert f.message == "OK"
    assert f.tool == "dead-code-detector"
    assert f.layer == "L4"
    assert f.language == "php"


def test_parse_shipmonk_empty_references_list() -> None:
    """Empty references list → no findings."""
    data = {"references": []}
    findings = _adapter().parse(json.dumps(data))
    assert findings == []


def test_parse_shipmonk_references_not_list() -> None:
    """'references' value is not a list → falls through (no 'files', not dict)."""
    data = {"references": "string_not_list"}
    findings = _adapter().parse(json.dumps(data))
    # 'string_not_list' is truthy, but not a list → falls through to
    # 'files' check; it is not a dict → no files path.
    # Falls through to final return → [].
    assert findings == []


# ====================================================================
# parse() — generic per-file format (str messages)
# ====================================================================


def test_parse_generic_files_single() -> None:
    """Single file with messages → one Finding per message."""
    data = {"files": {"src/Foo.php": {"messages": ["Unused class"]}}}
    findings = _adapter().parse(json.dumps(data))
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "src/Foo.php"
    assert f.severity == "warning"
    assert f.message == "Unused class"
    assert f.fix_hint is None
    assert f.tool == "dead-code-detector"
    assert f.layer == "L4"
    assert f.language == "php"


def test_parse_generic_files_multiple() -> None:
    """Multiple files with multiple messages."""
    data = {
        "files": {
            "src/A.php": {"messages": ["Msg1", "Msg2"]},
            "src/B.php": {"messages": ["Msg3"]},
        },
    }
    findings = _adapter().parse(json.dumps(data))
    assert len(findings) == 3

    expected = [
        ("src/A.php", "Msg1"),
        ("src/A.php", "Msg2"),
        ("src/B.php", "Msg3"),
    ]
    for i, (node, msg) in enumerate(expected):
        f = findings[i]
        assert f.node == node
        assert f.severity == "warning"
        assert f.message == msg
        assert f.fix_hint is None
        assert f.tool == "dead-code-detector"
        assert f.layer == "L4"
        assert f.language == "php"


def test_parse_generic_files_empty_messages() -> None:
    """File with empty messages list → no findings for that file."""
    data = {"files": {"src/Empty.php": {"messages": []}}}
    findings = _adapter().parse(json.dumps(data))
    assert findings == []


def test_parse_generic_files_non_dict_file_data() -> None:
    """File data is not a dict (e.g. a string) → skipped, no findings."""
    data = {"files": {"src/Bad.php": "string_not_dict"}}
    findings = _adapter().parse(json.dumps(data))
    assert findings == []


def test_parse_generic_files_dict_with_empty_messages_key() -> None:
    """File data is a dict but missing 'messages' key → empty list → no findings."""
    data = {"files": {"src/Absent.php": {"other": "value"}}}
    findings = _adapter().parse(json.dumps(data))
    assert findings == []


# ====================================================================
# parse() — generic per-file format (dict messages)
# ====================================================================


def test_parse_generic_files_dict_messages() -> None:
    """Messages are dicts with 'message' and 'tip' keys."""
    data = {
        "files": {
            "src/Mixed.php": {
                "messages": [
                    {"message": "Hello msg", "tip": "Hello tip"},
                    "plain string message",
                ],
            },
        },
    }
    findings = _adapter().parse(json.dumps(data))
    assert len(findings) == 2

    f0 = findings[0]
    assert f0.node == "src/Mixed.php"
    assert f0.severity == "warning"
    assert f0.message == "Hello msg"
    assert f0.fix_hint == "Hello tip"
    assert f0.tool == "dead-code-detector"
    assert f0.layer == "L4"
    assert f0.language == "php"

    f1 = findings[1]
    assert f1.node == "src/Mixed.php"
    assert f1.severity == "warning"
    assert f1.message == "plain string message"
    assert f1.fix_hint is None
    assert f1.tool == "dead-code-detector"
    assert f1.layer == "L4"
    assert f1.language == "php"


def test_parse_generic_files_dict_msg_missing_message_key() -> None:
    """Dict message missing 'message' key → message defaults to ''."""
    data = {"files": {"src/X.php": {"messages": [{"tip": "Only tip"}]}}}
    findings = _adapter().parse(json.dumps(data))
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "src/X.php"
    assert f.severity == "warning"
    assert f.message == ""
    assert f.fix_hint == "Only tip"
    assert f.tool == "dead-code-detector"
    assert f.layer == "L4"
    assert f.language == "php"


# ====================================================================
# parse() — edge cases: non-dict top-level values
# ====================================================================


def test_parse_list_top_level() -> None:
    """Top-level value is a list (not dict) → no findings."""
    findings = _adapter().parse('["item1", "item2"]')
    assert findings == []


def test_parse_string_top_level() -> None:
    """Top-level value is a JSON string → no findings."""
    findings = _adapter().parse('"just a string"')
    assert findings == []


def test_parse_number_top_level() -> None:
    """Top-level value is a number → no findings."""
    findings = _adapter().parse("42")
    assert findings == []


# ====================================================================
# parse() — non-JSON fallback via _parse_lines
# ====================================================================


def test_parse_lines_single_line() -> None:
    """Single non-JSON line → one Finding per line."""
    findings = _adapter().parse("src/Unused.php")
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "src/Unused.php"
    assert f.severity == "warning"
    assert f.message == "src/Unused.php"
    assert f.fix_hint is None
    assert f.tool == "dead-code-detector"
    assert f.layer == "L4"
    assert f.language == "php"


def test_parse_lines_multiple_lines() -> None:
    """Multiple non-empty lines → one Finding per line."""
    stdout = "src/A.php\nsrc/B.php\nsrc/C.php"
    findings = _adapter().parse(stdout)
    assert len(findings) == 3
    for i, filepath in enumerate(["src/A.php", "src/B.php", "src/C.php"]):
        f = findings[i]
        assert f.node == filepath
        assert f.severity == "warning"
        assert f.message == filepath
        assert f.fix_hint is None
        assert f.tool == "dead-code-detector"
        assert f.layer == "L4"
        assert f.language == "php"


def test_parse_lines_empty_lines_skipped() -> None:
    """Lines containing only whitespace are skipped."""
    stdout = "  \n\nsrc/Real.php\n\t\nsrc/Real2.php\n"
    findings = _adapter().parse(stdout)
    assert len(findings) == 2
    assert findings[0].node == "src/Real.php"
    assert findings[1].node == "src/Real2.php"


def test_parse_lines_multiple_with_trailing_newline() -> None:
    """Trailing newlines do not produce extra empty findings."""
    stdout = "src/A.php\nsrc/B.php\n\n\n"
    findings = _adapter().parse(stdout)
    assert len(findings) == 2


# ====================================================================
# invoke() — binary not found (graceful skip)
# ====================================================================


def test_invoke_binary_not_found_returns_empty(tmp_path: Path) -> None:
    """When vendor/bin/dead-code-detector is not present → empty ToolInvocation."""
    a = _adapter()
    result = a.invoke(tmp_path, [])
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.exitcode == 0
    assert result.duration_seconds == 0.0


# ====================================================================
# invoke() — binary present (mocked _run)
# ====================================================================

def test_invoke_binary_present_calls_run(tmp_path: Path) -> None:
    """When binary exists → delegate to _run with correct cmd & cwd."""
    a = _adapter()
    binary = tmp_path / "vendor" / "bin" / "dead-code-detector"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.touch()

    with patch.object(a, "_run", return_value=MagicMock(stdout="out", stderr="err", exitcode=1)) as mock_run:
        result = a.invoke(tmp_path, ["--json"])
        mock_run.assert_called_once_with(
            ["php", str(binary), "--json"],
            cwd=tmp_path,
            env=None,
            timeout=300.0,
        )
    assert result.stdout == "out"
    assert result.stderr == "err"
    assert result.exitcode == 1


def test_invoke_binary_present_custom_timeout(tmp_path: Path) -> None:
    """Custom timeout argument is forwarded to _run."""
    a = _adapter()
    binary = tmp_path / "vendor" / "bin" / "dead-code-detector"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.touch()

    with patch.object(a, "_run", return_value=MagicMock(stdout="out")) as mock_run:
        a.invoke(tmp_path, [], timeout=10.0)
        mock_run.assert_called_once_with(
            ["php", str(binary)],
            cwd=tmp_path,
            env=None,
            timeout=10.0,
        )


def test_invoke_binary_with_args(tmp_path: Path) -> None:
    """Additional args are appended to the command."""
    a = _adapter()
    binary = tmp_path / "vendor" / "bin" / "dead-code-detector"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.touch()

    with patch.object(a, "_run", return_value=MagicMock(stdout="out")) as mock_run:
        a.invoke(tmp_path, ["--option1", "--option2"])
        mock_run.assert_called_once_with(
            ["php", str(binary), "--option1", "--option2"],
            cwd=tmp_path,
            env=None,
            timeout=300.0,
        )


# ====================================================================
# invoke() — custom env forwarding
# ====================================================================


def test_invoke_forward_custom_env(tmp_path: Path) -> None:
    """Custom env dict passed through to _run."""
    a = _adapter()
    binary = tmp_path / "vendor" / "bin" / "dead-code-detector"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.touch()

    with patch.object(a, "_run", return_value=MagicMock(stdout="out")) as mock_run:
        a.invoke(tmp_path, [], env={"FOO": "bar"})
        mock_run.assert_called_once_with(
            ["php", str(binary)],
            cwd=tmp_path,
            env={"FOO": "bar"},
            timeout=300.0,
        )


# ====================================================================
# version() — not implemented
# ====================================================================


def test_version_raises_not_implemented(tmp_path: Path) -> None:
    """version() always raises NotImplementedError."""
    a = _adapter()
    with pytest.raises(NotImplementedError, match="not implemented"):
        a.version(tmp_path)


def test_version_with_env_raises_not_implemented(tmp_path: Path) -> None:
    """version() raises NotImplementedError regardless of env arg."""
    a = _adapter()
    with pytest.raises(NotImplementedError, match="not implemented"):
        a.version(tmp_path, env={"PHP": "8.3"})


# ====================================================================
# name property
# ====================================================================


def test_name() -> None:
    """name property returns the tool name."""
    assert _adapter().name == "dead-code-detector"
