"""Unit tests for RuffAdapter.parse — exhaustive field-level assertions.

Goal: Kill all mutation testing survivors on the `parse` method by testing
every key-missing path and asserting exact Finding field values.
"""

from __future__ import annotations

import json
import pytest

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
