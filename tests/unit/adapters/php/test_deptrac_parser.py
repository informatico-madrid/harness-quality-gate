"""Unit tests for Deptrac adapter parser.

Covers report-level violation count, per-violation list format,
parse_stats() convenience wrapper, and invalid input.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
    assert isinstance(arch, dict), "parse_stats must return a dict (not None/False)"
    assert arch == {"violations": 0, "uncovered_classes": 0}


def test_parse_stats_missing_report() -> None:
    """parse_stats without Report key → zeroed dict."""
    arch = _adapter().parse_stats('{"other": 1}')
    assert isinstance(arch, dict), "parse_stats must return a dict (not None/False)"
    assert arch == {"violations": 0, "uncovered_classes": 0}


def test_parse_stats_returns_dict_type() -> None:
    """parse_stats always returns a dict — kills 'return' → return None/False mutations.

    Kills mutmut_11, 13 (return → return None/False from try block),
    mutmut_21-23 (return → None/False/empty from if-not-dict guard).
    """
    # Valid data
    arch1 = _adapter().parse_stats('{"Report": {"Violations": 1}}')
    assert isinstance(arch1, dict)

    # Empty
    arch2 = _adapter().parse_stats("")
    assert isinstance(arch2, dict)

    # Bad JSON
    arch3 = _adapter().parse_stats("not json")
    assert isinstance(arch3, dict)

    # Report not a dict
    arch4 = _adapter().parse_stats('{"Report": "string"}')
    assert isinstance(arch4, dict)


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


# ═══════════════════════════════════════════════════════════════════════
# Kill parse() return-statement mutations (mutmut 94-103, 108-111)
# ═══════════════════════════════════════════════════════════════════════


def test_parse_returns_list_on_empty_output() -> None:
    """parse('') → list (kills 'return None'/return False mutations).

    Kills mutmut_94 and nearby: 'return findings' → 'return None/False'.
    """
    findings = _adapter().parse("", "", 0)
    assert isinstance(findings, list), "parse('') must return a list"
    assert len(findings) == 0


def test_parse_returns_list_on_invalid_json() -> None:
    """parse('bad json') → list (kills 'return findings' mutations).

    Kills mutmut_95-96 and mutmut_108-109: mutations on early return.
    """
    findings = _adapter().parse("not json at all", "", 1)
    assert isinstance(findings, list), "parse(bad_json) must return a list"
    assert len(findings) == 0


def test_parse_returns_list_on_non_dict_report() -> None:
    """parse('{"Report":"str"}') → list (kills mid-return mutations).

    Kills mutmut_101-103: mutations on 'return findings' at line 138.
    """
    findings = _adapter().parse('{"Report": "string"}', "", 0)
    assert isinstance(findings, list)
    assert len(findings) == 0


def test_parse_returns_list_on_count_violations() -> None:
    """parse with Violations as int → list with count finding.

    Kills mutmut_110-111: mutations on 'return findings' at line 180.
    """
    data = {"Report": {"Violations": 3, "UncoveredClasses": 1}}
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert isinstance(findings, list)
    assert len(findings) == 1


def test_parse_returns_list_on_list_violations() -> None:
    """parse with Violations as list → list with per-violation findings.

    Also kills mutmut_110-111 if the loop is taken.
    """
    data = {
        "Report": {
            "Violations": [
                {"file": "a.php", "message": "V1"},
            ]
        }
    }
    findings = _adapter().parse(json.dumps(data), "", 1)
    assert isinstance(findings, list)
    assert len(findings) == 1
    assert findings[0].node == "a.php"


# ═══════════════════════════════════════════════════════════════════════
# kill parse_stats() return-statement mutations
# ═══════════════════════════════════════════════════════════════════════


def test_parse_stats_returns_dict() -> None:
    """parse_stats always returns a dict — kills 'return None/{}' mutations.

    Kills mutmut_11 (return None), 13 (return {}), 21-23 (return mutations).
    """
    import json
    result = _adapter().parse_stats(json.dumps({"Report": {"Violations": 5, "UncoveredClasses": 2}}))
    assert isinstance(result, dict), "parse_stats must return dict"
    assert result["violations"] == 5
    assert result["uncovered_classes"] == 2


def test_parse_stats_bad_json_returns_default_dict() -> None:
    """parse_stats('bad') → default dict (not None/False).

    Kills mutmut_11-13: mutations on return in except block.
    """
    result = _adapter().parse_stats("garbage")
    assert isinstance(result, dict), "parse_stats('bad') must return dict"
    assert result == {"violations": 0, "uncovered_classes": 0}


def test_parse_stats_missing_report_returns_default_dict() -> None:
    """parse_stats with missing Report → default dict.

    Kills mutmut_21-23: mutations on return at line 208.
    """
    result = _adapter().parse_stats('{"foo": "bar"}')
    assert isinstance(result, dict)
    assert result == {"violations": 0, "uncovered_classes": 0}


def test_parse_stats_not_dict_report_returns_default_dict() -> None:
    """parse_stats with non-dict Report → default dict.

    Kills mutmut_21-23: mutations on return at line 204-208.
    """
    result = _adapter().parse_stats('{"Report": "not a dict"}')
    assert isinstance(result, dict)
    assert result == {"violations": 0, "uncovered_classes": 0}


# ═══════════════════════════════════════════════════════════════════════
# Kill invoke mutations (mutmut 1, 14, 17-29)
# ═══════════════════════════════════════════════════════════════════════


def test_invoke_raises_when_binary_missing() -> None:
    """invoke with missing deptrac binary → raises RuntimeError.

    Kills mutmut_1: remove if not deptrac_bin.is_file(): early return guard.
    Kills mutmut_14: change condition (is_file → not is_file or similar).
    """
    import tempfile
    adapter = DeptracAdapter()
    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path
        repo = Path(tmp)
        # No deptrac binary — is_file() → False
        with pytest.raises(RuntimeError, match="deptrac not found"):
            adapter.invoke(repo, [])


def test_invoke_calls_run_with_correct_cmd() -> None:
    """invoke creates correct command and passes through _run.

    Kills mutmut_17 (cmd mutation → empty), 18-19 (analyse/formatter mutations),
    20-21 ([*cmd, *args] mutation → empty/corrupted), 27-29 (return path mutations).
    """
    import tempfile
    adapter = DeptracAdapter()
    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path
        repo = Path(tmp)
        # Create the deptrac binary
        bin_path = repo / "vendor" / "bin"
        bin_path.mkdir(parents=True)
        (bin_path / "deptrac").touch()

        mock_result = MagicMock()
        mock_result.stdout = '{"Report": {}}'
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch.object(DeptracAdapter, "_run", return_value=mock_result) as mock_run:
            adapter.invoke(repo, ["--some-flag"])

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        cwd = mock_run.call_args[1]["cwd"]

        # Kills mutmut_19, 20: command args forwarded
        assert "deptrac" in cmd[0] or "deptrac" in cmd
        assert "--formatter=json" in cmd
        assert "analyse" in cmd
        assert "--some-flag" in cmd

        # Kills mutmut_27, 28: cwd must be set to repo
        assert cwd == repo, "cwd must be repo path"


# ═══════════════════════════════════════════════════════════════════════
# Kill version() NotImplementedError mutations (mutmut 1-4)
# ═══════════════════════════════════════════════════════════════════════


def test_version_raises_not_implemented() -> None:
    """version() always raises NotImplementedError.

    Kills mutmut_1, 2, 3, 4: all mutations on the raise statement or message.
    """
    adapter = DeptracAdapter()
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        exc_info = pytest.raises(NotImplementedError)
        with exc_info as info:
            adapter.version(Path(tmp))
        # Kill string mutations on the error message
        assert "deptrac version detection" in str(info.value)
        assert "POC" in str(info.value)
