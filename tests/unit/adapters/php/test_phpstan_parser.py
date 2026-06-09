"""Unit tests for PHPStan adapter parser.

Covers file_diagnostics format, legacy files format, empty/invalid input,
and error entries with tip.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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


# ═══════════════════════════════════════════════════════════════════════
# KILL version() SURVIVORS (mutmut 1-18 in version method)
# ═══════════════════════════════════════════════════════════════════════

from unittest.mock import MagicMock, patch


def test_version_binary_not_found_raises() -> None:
    """version() with no phpstan binary → RuntimeError.

    Kills mutmut_1,2: removes or inverts the `if cmd is None` guard.
    """
    with patch.object(PhpStanAdapter, '_phpstan_binary', return_value=None):
        with tempfile.TemporaryDirectory() as tmp:
            with pytest.raises(RuntimeError, match="phpstan not found"):
                _adapter().version(Path(tmp))


def test_version_success_parses_version_string() -> None:
    """version() with valid output → extracts version from stdout.

    Kills mutmut_7 (p[0].isdigit → False), mutmut_9 (p[0] → ord(p[0])),
    mutmut_10 ('.' not in p → True), mutmut_12 (return p → first p),
    mutmut_13 (return p → None), mutmut_15-18 (return fallback).
    """
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "PHP 2.1.34 by.neon configuration"
    mock_result.stderr = ""

    with patch.object(PhpStanAdapter, '_phpstan_binary', return_value=['phpstan']):
        with patch('harness_quality_gate.adapters.php.phpstan_adapter.subprocess.run', return_value=mock_result):
            with tempfile.TemporaryDirectory() as tmp:
                version = _adapter().version(Path(tmp))
                assert version == "2.1.34"


def test_version_version_key_not_first() -> None:
    """version() where version string is not the first token.

    Kills mutmut_14-16: loop order mutation (break/continue vs continue).
    """
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Version 3.0.5 -- some description"
    mock_result.stderr = ""

    with patch.object(PhpStanAdapter, '_phpstan_binary', return_value=['phpstan']):
        with patch('harness_quality_gate.adapters.php.phpstan_adapter.subprocess.run', return_value=mock_result):
            with tempfile.TemporaryDirectory() as tmp:
                version = _adapter().version(Path(tmp))
                assert version == "3.0.5"


def test_version_no_dot_version_fallback() -> None:
    """version() where no token has both digit and dot → fallback to strip.

    Kills mutmut_17,18 (return fallback string mutation).
    """
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "PHPStan dev-master  "
    mock_result.stderr = ""

    with patch.object(PhpStanAdapter, '_phpstan_binary', return_value=['phpstan']):
        with patch('harness_quality_gate.adapters.php.phpstan_adapter.subprocess.run', return_value=mock_result):
            with tempfile.TemporaryDirectory() as tmp:
                version = _adapter().version(Path(tmp))
                assert version == "PHPStan dev-master"


def test_version_nonzero_returncode_raises() -> None:
    """version() with nonzero return code → RuntimeError.

    Kills mutmut_4 ('!=' → '=='), mutmut_5 (remove condition).
    """
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "Error: command not found"

    with patch.object(PhpStanAdapter, '_phpstan_binary', return_value=['phpstan']):
        with patch('harness_quality_gate.adapters.php.phpstan_adapter.subprocess.run', return_value=mock_result):
            with tempfile.TemporaryDirectory() as tmp:
                with pytest.raises(RuntimeError, match="phpstan --version failed"):
                    _adapter().version(Path(tmp))


def test_version_strip_stderr() -> None:
    """version() strips stderr in error message.

    Kills mutations that change .strip() call or default value.
    """
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "  error message  "

    with patch.object(PhpStanAdapter, '_phpstan_binary', return_value=['phpstan']):
        with patch('harness_quality_gate.adapters.php.phpstan_adapter.subprocess.run', return_value=mock_result):
            with tempfile.TemporaryDirectory() as tmp:
                with pytest.raises(RuntimeError, match="error message"):
                    _adapter().version(Path(tmp))


# ═══════════════════════════════════════════════════════════════════════
# KILL invoke() SURVIVORS (mutmut 1-16 in invoke method)
# ═══════════════════════════════════════════════════════════════════════


def test_invoke_raises_when_binary_not_found() -> None:
    """invoke with no binary → RuntimeError.

    Kills mutmut_1,2: removes or inverts the guard check.
    """
    with patch.object(PhpStanAdapter, '_phpstan_binary', return_value=None):
        with tempfile.TemporaryDirectory() as tmp:
            with pytest.raises(RuntimeError, match="phpstan not found"):
                _adapter().invoke(Path(tmp), ["test"])


def test_invoke_calls_run_with_correct_cmd() -> None:
    """invoke forwards args correctly to _run.

    Kills mutmut_9-14 ([*cmd, *args] mutation → corrupted/empty cmd).
    """
    a = _adapter()
    mock_invocation = MagicMock()
    mock_invocation.stdout = '{"file_diagnostics": []}'
    mock_invocation.stderr = ""
    mock_invocation.exitcode = 0

    with patch.object(a, '_phpstan_binary', return_value=['/usr/bin/phpstan']):
        with patch.object(PhpStanAdapter, '_run', return_value=mock_invocation) as mock_run:
            with tempfile.TemporaryDirectory() as tmp:
                a.invoke(Path(tmp), ["--level=max", "--no-progress"])
                mock_run.assert_called_once()
                cmd = mock_run.call_args[0][0]
                assert '/usr/bin/phpstan' in cmd
                assert '--level=max' in cmd
                assert '--no-progress' in cmd


def test_invoke_passes_cwd() -> None:
    """invoke sets cwd to repo.

    Kills mutmut_15,16: cwd mutation (None → str).
    """
    a = _adapter()
    mock_invocation = MagicMock()
    mock_invocation.stdout = '{}'
    mock_invocation.stderr = ""
    mock_invocation.exitcode = 0

    with patch.object(a, '_phpstan_binary', return_value=['phpstan']):
        with patch.object(PhpStanAdapter, '_run', return_value=mock_invocation) as mock_run:
            repo = Path('/tmp/test_repo')
            a.invoke(repo, [])
            assert mock_run.call_args[1]['cwd'] == repo


def test_invoke_passes_env() -> None:
    """invoke forwards env dict.

    Kills mutmut on env merging: (env or {}) → env or None.
    """
    a = _adapter()
    mock_invocation = MagicMock()
    mock_invocation.stdout = '{}'
    mock_invocation.stderr = ""
    mock_invocation.exitcode = 0

    with patch.object(a, '_phpstan_binary', return_value=['phpstan']):
        with patch.object(PhpStanAdapter, '_run', return_value=mock_invocation) as mock_run:
            with tempfile.TemporaryDirectory() as tmp:
                a.invoke(Path(tmp), [], env={'XDEBUG_MODE': 'coverage'})
                env = mock_run.call_args[1]['env']
                assert isinstance(env, dict)


def test_invoke_passes_default_timeout() -> None:
    """invoke uses 300.0 default timeout when not specified.

    Kills mutmut on timeout parameter.
    """
    a = _adapter()
    mock_invocation = MagicMock()
    mock_invocation.stdout = '{}'
    mock_invocation.stderr = ""
    mock_invocation.exitcode = 0

    with patch.object(a, '_phpstan_binary', return_value=['phpstan']):
        with patch.object(PhpStanAdapter, '_run', return_value=mock_invocation) as mock_run:
            with tempfile.TemporaryDirectory() as tmp:
                a.invoke(Path(tmp), [])
                assert mock_run.call_args[1]['timeout'] == 300.0


def test_invoke_passes_custom_timeout() -> None:
    """invoke uses custom timeout when specified.

    Kills mutmut on timeout parameter mutation.
    """
    a = _adapter()
    mock_invocation = MagicMock()
    mock_invocation.stdout = '{}'
    mock_invocation.stderr = ""
    mock_invocation.exitcode = 0

    with patch.object(a, '_phpstan_binary', return_value=['phpstan']):
        with patch.object(PhpStanAdapter, '_run', return_value=mock_invocation) as mock_run:
            with tempfile.TemporaryDirectory() as tmp:
                a.invoke(Path(tmp), [], timeout=600.0)
                assert mock_run.call_args[1]['timeout'] == 600.0


# ═══════════════════════════════════════════════════════════════════════
# KILL _phpstan_binary() SURVIVORS (mutmut 1-5)
# ═══════════════════════════════════════════════════════════════════════


def test_phpstan_binary_system_path() -> None:
    """_phpstan_binary prefers system PATH over vendor/bin.

    Kills mutmut_1,2: shutil.which returns None/inverse system check.
    """
    with tempfile.TemporaryDirectory() as tmp:
        with patch('harness_quality_gate.adapters.php.phpstan_adapter.shutil.which', return_value='/usr/bin/phpstan'):
            result = _adapter()._phpstan_binary(Path(tmp))
            assert result == ['/usr/bin/phpstan']


def test_phpstan_binary_vendor_bin() -> None:
    """_phpstan_binary falls back to vendor/bin/phpstan.

    Kills mutmut_3,4: is_file() → not is_file() or empty string return.
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        vendor_bin = repo / "vendor" / "bin"
        vendor_bin.mkdir(parents=True)
        (vendor_bin / "phpstan").touch()
        with patch('harness_quality_gate.adapters.php.phpstan_adapter.shutil.which', return_value=None):
            result = _adapter()._phpstan_binary(repo)
            assert result is not None
            assert 'vendor/bin/phpstan' in result[0]


def test_phpstan_binary_not_found() -> None:
    """_phpstan_binary when not on PATH and no vendor binary → None.

    Kills mutmut_5: return None → return [] or return "phpstan".
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        with patch('harness_quality_gate.adapters.php.phpstan_adapter.shutil.which', return_value=None):
            result = _adapter()._phpstan_binary(repo)
            assert result is None


# ═══════════════════════════════════════════════════════════════════════
# KILL run_l3a() SURVIVORS (mutmut around lines 187-197)
# ═══════════════════════════════════════════════════════════════════════


def test_run_l3a_calls_invoke_and_parse() -> None:
    """run_l3a invokes PHPStan and returns parsed findings.

    Kills mutations on the invoke/parse chaining:
    - remove invoke call
    - change parse args
    - return instead of parsing
    """
    a = _adapter()
    
    # Mock invoke to return a ToolInvocation with valid JSON output
    mock_result = MagicMock()
    mock_result.stdout = '{"file_diagnostics": [{"file": "src/Foo.php", "messages": ["bug"]}]}'
    mock_result.stderr = ""
    mock_result.exitcode = 1

    with patch.object(a, 'invoke', return_value=mock_result):
        with tempfile.TemporaryDirectory() as tmp:
            findings = a.run_l3a(Path(tmp), {})
            assert len(findings) == 1
            f = findings[0]
            assert f.node == "src/Foo.php"
            assert f.message == "bug"
            assert f.tool == "phpstan"
            assert f.layer == "L3A"


def test_run_l3a_handles_parse_empty_list() -> None:
    """run_l3a with no findings returns empty list.

    Kills 'findings=None' or 'findings=False' mutations on return.
    """
    a = _adapter()
    
    mock_result = MagicMock()
    mock_result.stdout = '{"file_diagnostics": []}'
    mock_result.stderr = ""
    mock_result.exitcode = 0

    with patch.object(a, 'invoke', return_value=mock_result):
        with tempfile.TemporaryDirectory() as tmp:
            findings = a.run_l3a(Path(tmp), {})
            assert isinstance(findings, list)
            assert len(findings) == 0
