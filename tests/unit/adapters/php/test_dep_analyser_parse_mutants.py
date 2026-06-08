"""Targeted tests to kill surviving mutmut mutants in DepAnalyserAdapter.parse.

Kills:
  mutmut_1   : stderr default "" → "XXXX"  → killed by log assertion
  mutmut_2   : exitcode default 0 → 1      → killed by log assertion
  mutmut_11  : item.get("type", "") → None → killed by log assertion
  mutmut_13  : item.get("type", "") → (none) → killed by log assertion
  mutmut_16  : item.get("type", "") → "XXXX"→ killed by log assertion
  mutmut_23  : item.get("message", "") → None → killed by message assertion
  mutmut_27  : item.get("file","?") → None  → killed by log args assertion
  mutmut_30  : Remove item.get("file","?") arg → killed by arg count assertion
  mutmut_31  : Format string "parse:..." → "XXparse:...XX" → format string assertion
  mutmut_33  : item.get("file","?") → item.get(None,"?") → killed by log args assertion
  mutmut_34  : item.get("file","?") → item.get("file",None) → killed by log args assertion
  mutmut_35  : item.get("file","?") → item.get("?") → killed by log args assertion
  mutmut_52  : item.get("file", "") → None          → killed by node assertion
  mutmut_54  : item.get("file", "") → (no default)  → killed by node assertion
  mutmut_57  : item.get("file", "") → "XXXX"        → killed by node assertion
  mutmut_62  : item.get("message", "") → None       → killed by _make_finding mock
  mutmut_64  : item.get("message", "") → (no default) → killed by _make_finding mock
  mutmut_67  : item.get("message", "") → "XXXX"     → killed by _make_finding mock
"""

from __future__ import annotations

import json
import logging

from unittest.mock import patch

import pytest

from harness_quality_gate.adapters.php.dep_analyser_adapter import (
    DepAnalyserAdapter,
)

_LOGGER_NAME = "harness_quality_gate.adapters.php.dep_analyser_adapter"


# ===========================================================================
# Kill mutmut_27, 30, 31, 33, 34, 35 (item.get("file","?") mutations)
# All 6 mutate the SECOND argument of logger.debug() in the top-level array
# parsing section. They change item.get("file","?") to something else.
#
# Strategy: provide TWO items — one WITH "file" key and one WITHOUT.
# Assert on BOTH vtype log calls. Mutations affecting the call pattern will
# be caught by arg count, value, and format string assertions.
# ===========================================================================

class TestParseTopLevelItemMissingFile:
    """Assert vtype + file logged when items have/don't have 'file' key.

    Kills:
      mutmut_27: .get("file","?") → None        → log arg[2] fails on 2nd item
      mutmut_30: .get("file","?") removed entirely → arg count wrong
      mutmut_31: Format string "parse:..." → "XXparse:...XX" → format assertion
      mutmut_33: .get("file","?") → .get(None,"?") → arg[2] == "valid.php" fails
      mutmut_34: .get("file","?") → .get("file",None) → arg[2] fails on 2nd item
      mutmut_35: .get("file","?") → .get("?") → arg[2] fails on 2nd item
    """

    def test_item_missing_file_key_logs_default_question_mark(self) -> None:
        """Two items: one with real file, one without.

        First item HAS "file" key — catches format string mutants (31, 33).
        Second item MISSING "file" key — catches default-value mutants (27, 34, 35).
        Mutant 30 removes the argument entirely — caught by arg count.
        """
        logger = logging.getLogger(_LOGGER_NAME)
        adapter = DepAnalyserAdapter()
        data = [
            {"type": "dep-class", "file": "valid.php", "line": 1},
            {"type": "dep-antipattern"},  # No "file" key
        ]
        with patch.object(logger, "debug") as mock_debug:
            adapter.parse(json.dumps(data))

        vtype_logs = [
            args for args, _ in mock_debug.call_args_list
            if "vtype=" in args[0]
        ]
        assert len(vtype_logs) >= 2

        # --- FIRST item (HAS "file" key) ---
        # Catches mutmut_31 (format string mutation) and mutmut_33
        #   item.get(None, "?") on {"file":"valid.php"} returns "?" (not "valid.php")
        first_fmt = vtype_logs[0][0]
        assert first_fmt == "parse: vtype=%r (item=%s)"
        assert vtype_logs[0][1] == "dep-class"
        # This assertion alone kills mutmut_31, 33 (arg mismatch on first item)
        assert vtype_logs[0][2] == "valid.php"

        # --- SECOND item (NO "file" key) ---
        # Catches mutmut_27 (None), mutmut_34 (None default), mutmut_35 (key="?")
        assert vtype_logs[1][0] == "parse: vtype=%r (item=%s)"
        assert vtype_logs[1][1] == "dep-antipattern"
        assert vtype_logs[1][2] == "?"

    def test_item_with_file_key(self) -> None:
        """Item with all keys produces correct Finding."""
        data = [
            {"type": "dep-class", "file": "x.php", "line": 1},
        ]
        findings = DepAnalyserAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].node == "x.php:1"


# ===========================================================================
# Kill mutmut_1 (stderr default) and mutmut_2 (exitcode default)
# ===========================================================================

class TestParseDefaultParamsObserved:
    """Assert debug log output to make stderr/exitcode defaults observable."""

    def test_stderr_default_is_empty_string(self) -> None:
        """Call parse with default stderr; assert log shows empty string.

        Kills mutmut_1: stderr default "" → "XXXX" changes log → assertion fails.
        """
        logger = logging.getLogger(_LOGGER_NAME)
        adapter = DepAnalyserAdapter()
        data = [{"type": "dep-class", "file": "x.php", "line": 1}]
        with patch.object(logger, "debug") as mock_debug:
            adapter.parse(json.dumps(data))
        # Default params: stderr=""
        calls = mock_debug.call_args_list
        assert len(calls) >= 1
        # First debug call is the parse-level log
        args = calls[0][0]
        assert args[0] == "parse: exitcode=%d stderr=%r"
        assert args[1] == 0  # exitcode
        assert args[2] == ""  # stderr (kills default→"XXXX")

    def test_exitcode_default_is_zero(self) -> None:
        """Call parse with default exitcode; assert log shows 0.

        Kills mutmut_2: exitcode default 0 → 1 changes log → assertion fails.
        """
        logger = logging.getLogger(_LOGGER_NAME)
        adapter = DepAnalyserAdapter()
        data = [{"type": "dep-antipattern", "file": "y.php", "line": 5}]
        with patch.object(logger, "debug") as mock_debug:
            adapter.parse(json.dumps(data))
        args = mock_debug.call_args_list[0][0]
        assert args[1] == 0  # exitcode (kills default→1)


# ===========================================================================
# Kill mutmut_11, 13, 16 (type default mutations)
# These all change the default value of item.get("type", "")
# The vtype is now logged before the VIOLATION_TYPES check.
# ===========================================================================

class TestParseTopLevelItemTypeDefault:
    """Assert logged vtype value to kill type-default mutations."""

    def test_top_level_item_missing_type_logs_empty(self) -> None:
        """Item without 'type' key → vtype='' in log.

        Kills:
          mutmut_11: default becomes None → log shows None → assertion fails.
          mutmut_13: default becomes None → log shows None → assertion fails.
          mutmut_16: default becomes "XXXX" → log shows 'XXXX' → assertion fails.
        """
        logger = logging.getLogger(_LOGGER_NAME)
        adapter = DepAnalyserAdapter()
        data = [
            {"file": "x.php", "line": 1},  # Missing type
            {"type": "dep-class", "file": "y.php", "line": 2},
        ]
        with patch.object(logger, "debug") as mock_debug:
            adapter.parse(json.dumps(data))
        # Find the vtype log call
        for args, kwargs in mock_debug.call_args_list:
            msg = args[0]
            if "vtype=" in msg:
                vtype_val = args[1]  # second positional arg is the vtype value
                # For the item with missing type, vtype should be ''
                # The first vtype log call should show ''
                pass
        # First vtype log is for first item (missing type)
        vtype_logs = [
            args for args, _ in mock_debug.call_args_list
            if "vtype=" in args[0]
        ]
        assert len(vtype_logs) >= 1
        # First item has no "type" key, so vtype should be empty string
        assert vtype_logs[0][1] == ""  # kills None, None, "XXXX" defaults

    def test_top_level_item_with_valid_type_logs_type(self) -> None:
        """Item with valid type → vtype='dep-class' in log."""
        logger = logging.getLogger(_LOGGER_NAME)
        adapter = DepAnalyserAdapter()
        data = [{"type": "dep-class", "file": "x.php", "line": 1}]
        with patch.object(logger, "debug") as mock_debug:
            adapter.parse(json.dumps(data))
        vtype_logs = [
            args for args, _ in mock_debug.call_args_list
            if "vtype=" in args[0]
        ]
        assert len(vtype_logs) >= 1
        assert "dep-class" in vtype_logs[0]


# ===========================================================================
# Kill mutmut_23 (message default → None)
# ===========================================================================

class TestParseTopLevelItemMissingMessage:
    """Item with missing 'message' key.

    Kills mutmut_23: .get("message", "") → None
    """

    def test_item_with_message_kills_mutant_23(self) -> None:
        """Item WITH message — mutant passes None → "class" instead of "class: ...".

        Kills mutmut_23: .get("message", "") → None (literal)
        Original: message="bad import" → desc = "class: bad import"
        Mutant:   message=None → desc = "class"
        """
        data = [
            {"type": "dep-class", "file": "x.php", "line": 1, "message": "bad import"},
        ]
        findings = DepAnalyserAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        # Original: message="bad import" → truthy → desc = "class: bad import"
        assert findings[0].message == "class: bad import"
        # Mutant: message=None → falsy → desc = "class" (no ": " part)
        # This assertion fails for the mutant → kills it


# ===========================================================================
# Kill mutmut_52, 54, 57 (file default mutations in top-level array)
# ===========================================================================

class TestParseTopLevelItemMissingFileDefault:
    """Item without 'file' key to kill file-default mutations.

    Kills:
      mutmut_52: .get("file", "") → None            → node="None:1" != "?:1"
      mutmut_54: .get("file", "") → (no default)    → node="None:1" != "?:1"
      mutmut_57: .get("file", "") → "XXXX"          → node="XXXX:1" != "?:1"
    """

    def test_item_missing_file_key_uses_empty_string_default(self) -> None:
        """Item without 'file' key → Finding node does not contain 'None' or 'XXXX'.

        Original: file_name="" → node=":1" (empty string default)
        Mutant 52: file_name=None   → node="None:1"   → fails asserts
        Mutant 54: file_name=None   → node="None:1"   → fails asserts
        Mutant 57: file_name="XXXX" → node="XXXX:1"   → fails asserts
        """
        data = [
            {"type": "dep-class", "line": 1},  # No "file" key
        ]
        findings = DepAnalyserAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        # Original node should be ":1" (empty string for file_name)
        assert findings[0].node == ":1"
        # Explicitly reject mutated values
        assert findings[0].node != "None:1", "mutmut_52/54: file_name should not be None"
        assert findings[0].node != "XXXX:1", "mutmut_57: file_name should not be 'XXXX'"


# ===========================================================================
# Kill mutmut_62, 64, 67 (message default mutations in top-level array)
# ===========================================================================

class TestParseTopLevelItemMissingMessageDefault:
    """Item without 'message' key to kill message-default mutations.

    Kills:
      mutmut_62: .get("message", "") → None       → captured by mock assertion
      mutmut_64: .get("message", "") → (no default) → captured by mock assertion
      mutmut_67: .get("message", "") → "XXXX"     → desc="class: XXXX" ≠ "class"
    """

    def test_message_default_is_empty_string_not_none_or_XXXX(self) -> None:
        """Item without 'message' key — verify _make_finding receives "" not None/XXXX.

        Original: message="" → desc = "class"
        Mutant 62: message=None  (both falsy → desc="class", same output)
        Mutant 64: message=None  (same as 62)
        Mutant 67: message="XXXX" → desc = "class: XXXX" ≠ "class"

        Since 62/64 produce the same desc as original (both falsy), we mock
        _make_finding to directly assert the message argument passed to it.
        """
        data = [
            {"type": "dep-class", "file": "x.php", "line": 1},
        ]
        adapter = DepAnalyserAdapter()
        with patch.object(adapter, "_make_finding", wraps=adapter._make_finding) as mock_make:
            adapter.parse(json.dumps(data))

        assert mock_make.called
        call_kwargs = mock_make.call_args[1]
        # Mutant 67: "XXXX" → desc = "class: XXXX" (also caught here)
        # Mutants 62/64: None → desc = "class" (same desc but different arg)
        assert call_kwargs["message"] == "", (
            f"message should be '' not {call_kwargs['message']!r} "
            f"(kills mutmut_62, mutmut_64, mutmut_67)"
        )
