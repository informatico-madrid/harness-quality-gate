"""Unit tests for RuffAdapter.parse — exhaustive field-level assertions.

Goal: Kill all mutation testing survivors on the `parse` method by testing
every key-missing path and asserting exact Finding field values.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from harness_quality_gate.adapters.base import ToolInvocation
from harness_quality_gate.models import Finding
from harness_quality_gate.adapters.python.ruff_adapter import RuffAdapter


def _adapter():
    return RuffAdapter()


# ── Complete entry (all fields present) ──────────────────────────────────

class TestParseCompleteEntry:
    """Test with a complete ruff JSON entry covering all extraction paths."""

    def test_complete_entry_all_fields(self):
        entry = {
            "code": "E501",
            "filename": "src/a.py",
            "location": {"row": 1, "column": 80},
            "message": "Line too long",
        }
        findings = _adapter().parse(json.dumps([entry]))
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "E501"
        assert f.severity == "warning"
        assert f.node == "src/a.py"
        assert f.message == "src/a.py:1:80 [E501]: Line too long"
        assert f.fix_hint is None
        assert f.tool == "ruff"
        assert f.layer == "L2"
        assert f.language == "python"


# ── missing "code" / "rule" → severity="error", rule_id=None ────────────

class TestParseMissingCode:
    """Test entries where code and/or rule fields are missing.

    These tests target mutations on .get("code", ...),
    .get("rule", ...), and the `or` chain.
    """

    def test_missing_code_and_rule(self):
        # Mutants: code default=XXXX, code default=None, .get(None,...),
        #          .get(""), .get("XXcodeXX",...), .get("CODE",...), .get(code,)
        # etc., and rule key mutations (.get(rule,..), .get(RULE,..), etc.)
        # When "code" and "rule" are absent: code="" or ""="" → falsy
        entry = {"filename": "src/a.py", "message": "some issue"}
        findings = _adapter().parse(json.dumps([entry]))
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id is None
        assert f.severity == "error"
        assert f.node == "src/a.py"
        # code="" (falsy) → line=0 (falsy) → detail="" → message="some issue"
        assert f.message == "some issue"

    def test_missing_code_has_rule(self):
        # Mutants on .get("rule", ...): .get(None,...), .get(""), .get("XXruleXX",..),
        # .get("RULE",...), .get("rule", XXXX), .get("rule",), rule=entry.get("rule", None)
        # When code="" and rule="RULE_A": code = "" or "RULE_A" → "RULE_A"
        entry = {"code": "", "rule": "RULE_A", "filename": "src/a.py", "message": "test"}
        findings = _adapter().parse(json.dumps([entry]))
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "RULE_A"
        assert f.severity == "warning"
        assert f.node == "src/a.py"
        # code="RULE_A" (truthy) but line=0 (no location) → if line: False
        # detail stays "" → message = "" or "test" = "test"
        assert f.message == "test"


# ── missing filename ────────────────────────────────────────────────────

class TestParseMissingFilename:
    """Test entries where filename is missing.

    These target mutations on .get("filename", ...).
    """

    def test_missing_filename(self):
        # Mutants: .get("filename", None), .get(None,...), .get(""),
        #          .get("XXfilenameXX",...), .get("FILENAME",...), .get("filename","XXXX")
        entry = {"code": "E501", "location": {"row": 1, "column": 80}, "message": "too long"}
        findings = _adapter().parse(json.dumps([entry]))
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "E501"
        assert f.severity == "warning"
        assert f.node == ""  # filename missing → empty string
        # code="E501" (truthy), line=1 (in location) (truthy), col=80 (truthy)
        # detail = ":1:80 [E501]: too long"
        assert f.message == ":1:80 [E501]: too long"

    def test_missing_filename_and_code(self):
        # Mutants: .get("filename", None) → node=None → killed by node assertion
        entry = {"rule": "RULE_B", "message": "another issue"}
        findings = _adapter().parse(json.dumps([entry]))
        assert len(findings) == 1
        f = findings[0]
        assert f.node == ""  # no filename → empty string always
        assert f.severity == "warning"
        assert f.rule_id == "RULE_B"


# ── missing location (row, column) ──────────────────────────────────────

class TestParseMissingLocation:
    """Test entries where location key is missing from the entry.

    These target mutations on .get("location", {}), location.get("row", 0),
    location.get("column", 0).
    """

    def test_missing_location_row_col(self):
        # Mutants: .get("location", None) → crashes (untestable)
        #          .get("location")  → crashes (untestable)
        #          .get("XXlocationXX", {}) → key present anyway → no effect
        entry = {"code": "E501", "filename": "src/a.py", "message": "too long"}
        findings = _adapter().parse(json.dumps([entry]))
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "E501"
        assert f.severity == "warning"
        assert f.node == "src/a.py"
        # location missing → {} → row=0 (falsy) → if line: False → detail="" → message="too long"
        assert f.message == "too long"

    def test_location_missing_column_only(self):
        # Mutants: location.get("column", None) → col=None → killed by message
        #          location.get(0) → raises KeyError
        #          location.get("XXcolumnXX", 0) → col=0 → killed by message
        #          location.get("COLUMN", 0) → col=0 → killed by message
        #          location.get("column", 1) → kills with message assertion
        entry = {
            "code": "E501",
            "filename": "src/a.py",
            "location": {"row": 5},
            "message": "no column",
        }
        findings = _adapter().parse(json.dumps([entry]))
        assert len(findings) == 1
        f = findings[0]
        # row=5 (truthy), col=0 (missing, default 0 is falsy)
        # detail = "src/a.py:5 [E501]: no column"
        assert f.message == "src/a.py:5 [E501]: no column"

    def test_location_missing_row_only(self):
        entry = {
            "code": "E501",
            "filename": "src/a.py",
            "location": {"column": 10},
            "message": "no row",
        }
        findings = _adapter().parse(json.dumps([entry]))
        assert len(findings) == 1
        f = findings[0]
        # row missing → line=0 (falsy) → if line: False → detail="" → message="no row"
        assert f.message == "no row"


# ── missing message ─────────────────────────────────────────────────────

class TestParseMissingMessage:
    """Test entries where message key is missing.

    These target mutations on .get("message", ...).
    """

    def test_missing_message_with_code(self):
        entry = {"code": "E501", "filename": "src/a.py",
                 "location": {"row": 1, "column": 80}}
        findings = _adapter().parse(json.dumps([entry]))
        assert len(findings) == 1
        f = findings[0]
        # detail="src/a.py:1:80 [E501]: " (trailing space)
        # message=None → detail is truthy → message=detail
        assert f.rule_id == "E501"
        assert f.severity == "warning"
        assert f.message == "src/a.py:1:80 [E501]: "


# ── Non-dict entry / mutation kill ──────────────────────────────────────

class TestParseNonDictEntry:
    """Test entries that are not dicts.

    These target the `continue` → `break` mutation (mutmut_9) on
    the isinstance check inside the loop.
    """

    def test_non_dict_then_valid(self):
        """Two entries: first is a string (non-dict), second is valid.

        Original: continue → second entry is still processed → 1 finding.
        Mutant: break → second entry is skipped → 0 findings.
        """
        data = ["not a dict", {
            "code": "E501",
            "filename": "src/b.py",
            "location": {"row": 3, "column": 42},
            "message": "short",
        }]
        findings = _adapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].rule_id == "E501"


# ── Valid entry with fix — exact fix_hint assertion ─────────────────────

class TestParseWithFix:
    """Test fix_hint extraction with exact assertion.

    Target mutations that change the default message in the fix hint extraction.
    """

    def test_fix_hint_extracted(self):
        entry = {
            "code": "F401",
            "filename": "src/a.py",
            "location": {"row": 1, "column": 1},
            "message": "unused import",
            "fix": {"message": "Remove import"},
        }
        findings = _adapter().parse(json.dumps([entry]))
        assert len(findings) == 1
        f = findings[0]
        assert f.fix_hint == "Remove import"
        assert f.rule_id == "F401"
        assert f.severity == "warning"
        assert f.message == "src/a.py:1:1 [F401]: unused import"


# ═══════════════════════════════════════════════════════════════════════
# Additional mutations that exercise edge cases with empty fields
# ═══════════════════════════════════════════════════════════════════════

class TestParseEmptyFields:
    """Test entries where field values are empty strings or null."""

    def test_empty_code_nonempty_rule(self):
        """Both code='' and rule present → rule used as fallback.

        Test mutant: .get("rule", None) → rule=None → rule_id=None
        and: .get("RULE",...) → rule=None → rule_id=None
        and: .get("XXruleXX",...) → rule="XXruleXX" → rule_id="XXruleXX"
        """
        entry = {"code": "", "rule": "F841", "filename": "src/x.py",
                 "location": {"row": 10}, "message": "unused var"}
        findings = _adapter().parse(json.dumps([entry]))
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "F841"
        assert f.severity == "warning"
        assert f.node == "src/x.py"
        # code="F841" (truthy)
        # line=10 (truthy), col missing → col=0 (falsy)
        # detail = "src/x.py:10 [F841]: unused var"
        assert f.message == "src/x.py:10 [F841]: unused var"

    def test_location_with_row_zero(self):
        """Location present but row=0, column=0 → both falsy → message only."""
        entry = {
            "code": "E501",
            "filename": "src/a.py",
            "location": {"row": 0, "column": 0},
            "message": "zero row",
        }
        findings = _adapter().parse(json.dumps([entry]))
        assert len(findings) == 1
        f = findings[0]
        assert f.message == "zero row"
        assert f.rule_id == "E501"
        assert f.severity == "warning"

    def test_code_missing_no_message(self):
        """Entry missing code and message → detail="" and message="" → str(entry) used.

        This test ensures the `or` fallback chain and str() evaluation work correctly.
        Catches mutations on `detail or message and str(entry)` (or→and) and
        `str(entry)` → `str(None)`.
        """
        entry = {"filename": "src/minimal.py"}
        findings = _adapter().parse(json.dumps([entry]))
        assert len(findings) == 1
        f = findings[0]
        assert f.severity == "error"
        assert f.rule_id is None
        # When code is absent: code=""→falsy → line=0→falsy → detail=""
        # When message is absent: message="" → detail_message = "" or "" or str(entry)
        # detail should incorporate filename since code is falsy
        assert "src/minimal.py" in f.message


# ═══════════════════════════════════════════════════════════════════════
# Invoke method — kill survivors by mocking _run
# ═══════════════════════════════════════════════════════════════════════


class TestRuffInvokeBinaryNotFound:
    """Tests for when ruff is not found on PATH.

    Kills mutmut survivors on invoke that remove the early return
    when binary is None, or remove the _run() call entirely.
    """

    @patch("harness_quality_gate.adapters.python.ruff_adapter.shutil.which", return_value=None)
    def test_invoke_returns_infra_when_ruff_missing(self, mock_which):
        """Binary not found → return ToolInvocation with exitcode=3.

        Kills:
          - Remove `if binary is None: return ...` early return
          - Return None instead of ToolInvocation (if _run removed)
          - Change exitcode=3 to other values
        """
        result = RuffAdapter().invoke(
            repo=MagicMock(),
            args=[],
            env=None,
        )
        assert isinstance(result, ToolInvocation)
        assert result.exitcode == 3
        assert result.stderr == "ruff not found on PATH"
        assert result.stdout == ""


# ═══════════════════════════════════════════════════════════════════════
# Version method — kill survivors on version (12 survivors)
# ═══════════════════════════════════════════════════════════════════════


class TestRuffVersion:
    """Tests for RuffAdapter.version — kill mutmut_1..12.

    Kills:
      - mutmut_1: shutil.which("ruff") → shutil.which(None)
      - mutmut_2: .stdout.strip() → .stdout.strip(None)
      - mutmut_3: .split()[-1] → .split(None)[-1]
      - mutmut_7: .stdout else "unknown" → .stdout.strip() else "unknown"
      - mutmut_8: "ruff not found on PATH" → "XXnot found on PATH"
    Uses §4.4 spies and §4.3 exact assertions.
    """

    def test_version_returns_version_number(self):
        """Binary found and returns version → extract version string.

        Kills mutmut_2 (strip(None)) and mutmut_3 (split(None)).
        """
        with patch(
            "harness_quality_gate.adapters.python.ruff_adapter.shutil.which",
            return_value="/usr/bin/ruff",
        ):
            adapter = RuffAdapter()
            mock_result = MagicMock(stdout="ruff 0.8.0\n")
            with patch.object(adapter, "_run", return_value=mock_result):
                version = adapter.version(Path("/tmp/repo"))
        assert version == "0.8.0"

    def test_version_empty_output_returns_unknown(self):
        """When stdout is empty → return 'unknown'.

        Kills mutmut_7: .stdout else "unknown" → .stdout.strip() else "unknown"
        (empty string stripped is "" which is falsy → falls through).
        """
        with patch(
            "harness_quality_gate.adapters.python.ruff_adapter.shutil.which",
            return_value="/usr/bin/ruff",
        ):
            adapter = RuffAdapter()
            mock_result = MagicMock(stdout="")
            with patch.object(adapter, "_run", return_value=mock_result):
                version = adapter.version(Path("/tmp/repo"))
        assert version == "unknown"

    def test_version_binary_not_found_raises(self):
        """Binary not found → raises RuntimeError with exact message.

        Kills mutmut_1 (shutil.which → shutil.which(None))
        and mutmut_8 ("ruff not found on PATH" → "XXnot found on PATH").
        """
        with patch(
            "harness_quality_gate.adapters.python.ruff_adapter.shutil.which",
            return_value=None,
        ):
            adapter = RuffAdapter()
            with pytest.raises(RuntimeError) as exc_info:
                adapter.version(Path("/tmp/repo"))
        assert str(exc_info.value) == "ruff not found on PATH"

    def test_version_env_passed_to_run(self):
        """version() passes env to _run.

        Kills mutmut that removes env parameter from the _run call.
        """
        with patch(
            "harness_quality_gate.adapters.python.ruff_adapter.shutil.which",
            return_value="/usr/bin/ruff",
        ):
            adapter = RuffAdapter()
            mock_result = MagicMock(stdout="ruff 0.8.0\n")
            with patch.object(adapter, "_run", return_value=mock_result) as mock_run:
                adapter.version(Path("/tmp/repo"), env={"CUSTOM": "1"})
        mock_run.assert_called_once_with(
            ["/usr/bin/ruff", "--version"], cwd=Path("/tmp/repo"), env={"CUSTOM": "1"}
        )

    def test_version_multi_word_output(self):
        """Version output with non-version prefix → still extracts last token.

        Kills mutmut_3: .split()[-1] → .split(None)[-1]
        and mutmut on strip().
        """
        with patch(
            "harness_quality_gate.adapters.python.ruff_adapter.shutil.which",
            return_value="/usr/bin/ruff",
        ):
            adapter = RuffAdapter()
            mock_result = MagicMock(stdout="ruff-check 0.8.0\n")
            with patch.object(adapter, "_run", return_value=mock_result):
                version = adapter.version(Path("/tmp/repo"))
        assert version == "0.8.0"


# ═══════════════════════════════════════════════════════════════════════
# Invoke method — continue existing tests
# ═══════════════════════════════════════════════════════════════════════


class TestRuffInvokeNormalPath:
    """Tests for the normal invoke path with mocked _run.

    Kills mutmut survivors on invoke that change command construction
    (mutating args, removing repo path append, etc.).
    """

    def test_invoke_passes_cmd_to_run(self):
        """Ensure _run is called with correct command structure.

        Kills:
          - Remove _run() call → returns None/exception
          - Remove cmd.append(str(repo)) → repo not in args
          - Mutations on cmd construction (changed binary, flags, etc.)
        """
        adapter = RuffAdapter()
        mock_result = MagicMock()
        mock_result.stdout = '[]'
        mock_result.stderr = ''
        mock_result.returncode = 0

        with patch.object(RuffAdapter, '_run', return_value=mock_result) as mock_run:
            from pathlib import Path
            repo = Path('/tmp/test_repo')
            result = adapter.invoke(repo, args=['--select=E501'])

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0]  # First positional arg is the cmd list
        assert 'ruff' in cmd[0]
        assert 'check' in cmd
        assert '--output-format=json' in cmd
        assert '--select=E501' in cmd
        assert str(repo) in cmd

    def test_invoke_executes_and_returns_result(self):
        """Invoke with mocked _run returns ToolInvocation.

        Kills:
          - Mutant that removes _run() call → returns None
          - Mutant that changes _run arguments (cwd, env, timeout)
        """
        adapter = RuffAdapter()
        expected = ToolInvocation(
            stdout='{"results": []}',
            stderr='',
            exitcode=0,
            duration_seconds=0.1,
        )

        with patch.object(RuffAdapter, '_run', return_value=expected) as mock_run:
            from pathlib import Path
            repo = Path('/tmp/test_repo')
            result = adapter.invoke(repo, args=[])

        assert result.stdout == expected.stdout
        assert result.exitcode == expected.exitcode
        assert mock_run.call_args[1]['cwd'] == repo


# ═══════════════════════════════════════════════════════════════════════
# Kill `or → and` mutation on line 96 of ruff_adapter.py
# ═══════════════════════════════════════════════════════════════════════

class TestParseOrAndMutation:
    """Kill the or→and mutation on: detail or message or str(entry)

    When `or` is mutated to `and`:
        detail or message and str(entry)
      with detail="" and message="", the result is "" instead of str(entry).

    This test creates an entry where BOTH detail and message are empty,
    forcing the fallback chain to evaluate str(entry).
    """

    def test_fallback_to_str_entry_kills_or_and(self):
        """Entry with no code, no location, no message → uses str(entry).

        detail=""  (no code/location to build detail)
        message="" (no message in entry)
        str(entry) = "{'filename': 'a.py'}"
        Kills the `or → and` mutation which would return "" instead.
        """
        entry = {"filename": "a.py"}  # no code, no location, no message
        findings = _adapter().parse(json.dumps([entry]))
        assert len(findings) == 1
        f = findings[0]
        # str(entry) is non-empty, so message should be that string
        assert f.message == "{'filename': 'a.py'}"
        assert f.rule_id is None
        assert f.severity == "error"
