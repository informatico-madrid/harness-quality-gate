"""Targeted tests to kill surviving mutmut mutants in DepAnalyserAdapter.parse.

Kills:
  mutmut_1  : stderr default "" → "XXXX"  → killed by log assertion
  mutmut_2  : exitcode default 0 → 1      → killed by log assertion
  mutmut_11 : item.get("type", "") → None → killed by log assertion
  mutmut_13 : item.get("type", "") → (none)→ killed by log assertion
  mutmut_16 : item.get("type", "") → "XXXX"→ killed by log assertion
  mutmut_23 : item.get("message", "") → None → killed by message assertion
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
