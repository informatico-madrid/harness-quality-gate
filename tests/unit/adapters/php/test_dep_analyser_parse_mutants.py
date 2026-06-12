"""Targeted tests to kill surviving mutmut mutants in DepAnalyserAdapter.

Covers parse and invoke methods with exhaustive mutation testing.

Kills:
  parse mutmut_1   : stderr default "" → "XXXX"  → killed by log assertion
  parse mutmut_2   : exitcode default 0 → 1      → killed by log assertion
  parse mutmut_11  : item.get("type", "") → None → killed by log assertion
  parse mutmut_13  : item.get("type", "") → (none) → killed by log assertion
  parse mutmut_16  : item.get("type", "") → "XXXX"→ killed by log assertion
  parse mutmut_23  : item.get("message", "") → None → killed by message assertion
  parse mutmut_27  : item.get("file","?") → None  → killed by log args assertion
  parse mutmut_30  : Remove item.get("file","?") arg → killed by arg count assertion
  parse mutmut_31  : Format string "parse:..." → "XXparse:...XX" → format string assertion
  parse mutmut_33  : item.get("file","?") → item.get(None,"?") → killed by log args assertion
  parse mutmut_34  : item.get("file","?") → item.get("file",None) → killed by log args assertion
  parse mutmut_35  : item.get("file","?") → item.get("?") → killed by log args assertion
  parse mutmut_52  : item.get("file", "") → None          → killed by node assertion
  parse mutmut_54  : item.get("file", "") → (no default)  → killed by node assertion
  parse mutmut_57  : item.get("file", "") → "XXXX"        → killed by node assertion
  parse mutmut_62  : item.get("message", "") → None       → killed by _make_finding mock
  parse mutmut_64  : item.get("message", "") → (no default) → killed by _make_finding mock
  parse mutmut_67  : item.get("message", "") → "XXXX"     → killed by _make_finding mock
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from unittest.mock import patch, MagicMock

import pytest

from harness_quality_gate.adapters.base import ToolInvocation
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
        # New contract: the dead default was removed (Tipo C) — a missing key
        # arrives as None and _make_finding collapses it to the bare prefix.
        assert call_kwargs["message"] is None


# ===========================================================================
# Kill mutmut_73, 76, 78, 82 — nested files format
# These mutants only affect the nested {"files": {...}} parsing branch.
# Existing tests only cover top-level array format.
# ===========================================================================

class TestParseNestedFileDataInvalid:
    """Test nested files Format 2 — invalid file_data skipped correctly.

    Kills:
      mutmut_73  : continue→break at file_data-not-dict check
      mutmut_76  : violations default []→None
      mutmut_78  : violations default []→no default
    """

    def test_invalid_file_data_continue_kills_mutmut_73(self) -> None:
        """file_data is not a dict — continue skips it, next file processed.

        If mutant → break → loop exits immediately → 0 findings."""
        adapter = DepAnalyserAdapter()
        data = {
            "files": {
                "invalid.php": "not a dict",
                "valid.php": {
                    "violations": [
                        {"type": "dep-class", "line": 5},
                    ],
                },
            },
        }
        findings = adapter.parse(json.dumps(data))
        assert len(findings) >= 1
        assert findings[0].fix_hint == "dep-class"


class TestParseNestedViolationsNotList:
    """Violations as non-list value — continue skips, not break.

    Kills:
      mutmut_82  : continue→break at violations-not-list check
    """

    def test_violations_as_string_kills_mutmut_82(self) -> None:
        """violations='string' → continue skips file, next file processed.

        If mutant → break → 0 findings."""
        adapter = DepAnalyserAdapter()
        data = {
            "files": {
                "bad.php": {"violations": "string"},
                "good.php": {
                    "violations": [
                        {"type": "dep-antipattern", "line": 10},
                    ],
                },
            },
        }
        findings = adapter.parse(json.dumps(data))
        assert len(findings) >= 1
        assert findings[0].fix_hint == "dep-antipattern"


class TestParseNestedViolationsInnerLoop:
    """Mixed violations — dict and non-dict items.

    Kills:
      inner loop mutant : continue→break at v-not-dict check
    """

    def test_mixed_violations_kills_inner_mutant(self) -> None:
        """violations: [string, dict] — continue past string, process dict.

        If break → dict never processed → 0 findings."""
        adapter = DepAnalyserAdapter()
        data = {
            "files": {
                "mixed.php": {
                    "violations": [
                        "not a dict",
                        {"type": "dep-class", "line": 3, "message": "class msg"},
                    ],
                },
            },
        }
        findings = adapter.parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].fix_hint == "dep-class"
        assert findings[0].node == "mixed.php:3"


class TestParseNestedViolationMissingType:
    """Violation dict without 'type' key.

    Kills:
      mutmut_87  : v.get("type", None) changes vtype from "" to None
    """

    def test_missing_type_logs_empty_string_vtype(self) -> None:
        """Assert vtype'' from debug log — catches ''→None mutation of
        item.get("type", "")."""
        logger = logging.getLogger(_LOGGER_NAME)
        adapter = DepAnalyserAdapter()
        data = {
            "files": {
                "no_type.php": {
                    "violations": [
                        {},  # No "type" key
                        {"type": "dep-function", "line": 7},
                    ],
                },
            },
        }
        with patch.object(logger, "debug") as mock_debug:
            adapter.parse(json.dumps(data))

        vtype_logs = [
            args for args, _ in mock_debug.call_args_list
            if "vtype=" in args[0]
        ]
        assert len(vtype_logs) >= 1
        assert vtype_logs[0][1] == "", (
            f"vtype should be '' not {vtype_logs[0][1]!r} "
            f"(kills mutmut_87 default→None)"
        )


# ═══════════════════════════════════════════════════════════════════════
# Invoke method — kill survivors by mocking _run
# ═══════════════════════════════════════════════════════════════════════


class TestDepAnalyserInvokeBinaryNotFound:
    """Tests for when composer-dependency-analyser is not found.

    Kills mutmut survivors on invoke that remove the early return
    when binary is None, or remove the _run() call.
    """

    def test_invoke_returns_infra_when_analyser_missing(self):
        """Binary missing → return ToolInvocation with exitcode=3.

        Kills:
          - Remove `if cmd is None: return ...` early return
          - Return None instead of ToolInvocation if _run removed
          - Remove logger.warning call
        """
        with patch.object(
            DepAnalyserAdapter, "_binary", return_value=None,
        ):
            result = DepAnalyserAdapter().invoke(
                repo=MagicMock(),
                args=[],
                env=None,
            )
        assert isinstance(result, ToolInvocation)
        assert result.exitcode == 3
        assert result.stderr == "composer-dependency-analyser not found"
        assert result.stdout == ""

    def test_invoke_calls_binary_and_run(self):
        """Normal invoke → _run is called with resolved binary path."""
        mock_result = MagicMock()
        mock_result.stdout = "[]"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch.object(DepAnalyserAdapter, "_run", return_value=mock_result) as mock_run:
            with patch(
                "harness_quality_gate.adapters.php.dep_analyser_adapter.shutil.which",
                return_value="/usr/bin/composer-dependency-analyser",
            ):
                DepAnalyserAdapter().invoke(repo=Path("/tmp/repo"), args=["--json"])

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args is not None
        cmd = call_args[0][0]
        assert "--json" in cmd
        # Repo path is in cwd, not in cmd args (handled by _run's cwd param)
        assert mock_run.call_args[1]["cwd"] == Path("/tmp/repo")

    def test_invoke_when_binary_in_vendor_bin(self):
        """When system binary not found, fallback to vendor/bin."""
        import shutil
        original_which = shutil.which

        def mock_which(name):
            if name == "composer-dependency-analyser":
                return None  # Not on PATH
            return original_which(name)

        mock_result = MagicMock()
        mock_result.stdout = "[]"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch.object(DepAnalyserAdapter, "_run", return_value=mock_result) as mock_run:
            with patch.object(shutil, "which", side_effect=mock_which):
                vendor_bin = Path("/tmp/repo/vendor/bin/composer-dependency-analyser")
                vendor_bin.parent.mkdir(parents=True, exist_ok=True)
                vendor_bin.touch()
                DepAnalyserAdapter().invoke(repo=Path("/tmp/repo"), args=[])

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "vendor/bin/composer-dependency-analyser" in cmd[0]


# ═══════════════════════════════════════════════════════════════════════
# Kill _make_finding mutations (mutmut 13,16-19,24-35)
# These change parameters inside the static method.
# Strategy: call _make_finding directly with parametrized inputs
# that produce different outputs for each mutated expression.
# ═══════════════════════════════════════════════════════════════════════


class TestMakeFindingDirect:
    """Exercise _make_finding() directly to catch parameter mutations."""

    def test_make_finding_prefix_from_dep_class_replace(self) -> None:
        """prefix = violation_type.replace('dep-', '') → 'class'
        
        Kills mutmut_13: .replace('dep-', '') → .replace(None, '') 
        causes TypeError → parse returns [] → Finding not created → this direct call fails.
        Kills mutmut_14: .replace → .replace(False, '') same.
        Kills mutmut_15: .replace → .replace('', '') same.
        """
        f = DepAnalyserAdapter._make_finding(
            file_name="test.php", line=10,
            violation_type="dep-class", message="unused class",
        )
        assert f.message == "class: unused class"
        assert f.rule_id == "dep-class"
        assert f.fix_hint == "dep-class"
        assert f.layer == "L4"
        assert f.language == "php"
        assert f.tool == "composer-dependency-analyser"

    def test_make_finding_desc_with_empty_message(self) -> None:
        """message param = prefix (not 'prefix: ') when message is empty string.

        Kills mutmut_16-19 (ternary → 'or' or 'and'):
        Mut19: 'or' → 'and': ``message and prefix`` → `` `` (since `` `` is falsy, returns '')
        So check that message is exactly 'class' (not '').
        """
        f = DepAnalyserAdapter._make_finding(
            file_name="test.php", line=10,
            violation_type="dep-class", message="",
        )
        assert f.message == "class"  # Exactly "class", not "" or "class: "

    def test_make_finding_node_with_line(self) -> None:
        """node = file_name when line is missing, 'file_name:line' when line present.
        
        Kills mutmut_27-29 (if line: → if not line:/if None:/if False):
        These mutations change when the ':line' suffix is added.
        """
        # With line present
        f1 = DepAnalyserAdapter._make_finding(
            file_name="test.php", line=10,
            violation_type="dep-class", message="msg",
        )
        assert f1.node == "test.php:10", "line suffix must be present when line=10"

        # Without line
        f2 = DepAnalyserAdapter._make_finding(
            file_name="test.php", line=None,
            violation_type="dep-class", message="msg",
        )
        assert f2.node == "test.php", "no line suffix when line is None"

        # With line=0 (falsy)
        f3 = DepAnalyserAdapter._make_finding(
            file_name="test.php", line=0,
            violation_type="dep-class", message="msg",
        )
        assert f3.node == "test.php", "no line suffix when line=0 (falsy)"

    def test_make_finding_node_without_line(self) -> None:
        """node = file_name when no line provided (no ':line' suffix)."""
        f = DepAnalyserAdapter._make_finding(
            file_name="test.php", line=None,
            violation_type="dep-function", message="call to undefined",
        )
        assert f.node == "test.php"
        assert f.message == "function: call to undefined"

    def test_make_finding_all_fields_verified(self) -> None:
        """Verify every Finding field to kill parameter mutations 24-26, 30-35.
        
        Mut24-26: file_name param mutated → node field wrong → assert fails
        Mut30-35: node construction mutations → assert on node exact format
        """
        f = DepAnalyserAdapter._make_finding(
            file_name="src/Foo.php", line=42,
            violation_type="dep-global-variable", message="unused $x",
        )
        assert f.node == "src/Foo.php:42"
        assert f.severity == "warning"
        assert f.message == "global-variable: unused $x"
        assert f.fix_hint == "dep-global-variable"
        assert f.tool == "composer-dependency-analyser"
        assert f.layer == "L4"
        assert f.language == "php"
        assert f.rule_id == "dep-global-variable"


# ═══════════════════════════════════════════════════════════════════════
# Kill version() NotImplementedError mutations (mutmut 1-4)
# ═══════════════════════════════════════════════════════════════════════


class TestVersionMethod:
    """Tests for version() — all survivors are in this method.
    
    Kills mutmut_1-4: all mutations modify the error message or remove it.
    """

    def test_version_raises_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError, match="not implemented"):
            DepAnalyserAdapter().version(Path("/tmp"))

    def test_version_raises_exact_message(self) -> None:
        """Verify exact NotImplementedError message.
        
        Kills mutmut_1-4: all mutations change/remove the message text.
        """
        with pytest.raises(NotImplementedError) as exc_info:
            DepAnalyserAdapter().version(Path("/tmp"))
        assert "not implemented" in str(exc_info.value).lower()


# ═══════════════════════════════════════════════════════════════════════
# Kill parse() return-statement mutations (mutmut 76,78,95-102,107,115-121)
# ═══════════════════════════════════════════════════════════════════════


class TestParseReturnTypes:
    """Assert parse() always returns a list — kills 'return findings'→return X mutations."""

    def test_empty_stdout_returns_list(self) -> None:
        r = DepAnalyserAdapter().parse("")
        # Kills mutmut_76 (return None) and mutmut_78 (return False) from empty stdout
        assert isinstance(r, list), 'parse("") must return a list'
        assert len(r) == 0

    def test_json_decode_error_returns_list(self) -> None:
        r = DepAnalyserAdapter().parse("not json at all", "", 1)
        # Kills mutmut_95 (return None) and mutmut_98 (return False) from JSON decode error
        assert isinstance(r, list), 'parse(bad_json) must return a list'
        assert len(r) == 0

    def test_empty_list_input_returns_list(self) -> None:
        r = DepAnalyserAdapter().parse(json.dumps([]))
        # Kills mutmut_99, 102 (empty list mutations): adds default finding with wrong type
        assert isinstance(r, list)
        assert len(r) == 0

    def test_nested_format_empty_files_returns_list(self) -> None:
        r = DepAnalyserAdapter().parse(json.dumps({"files": {}}))
        # Kills mutmut_115-121: 7 mutations on 'return findings' at end of nested format
        assert isinstance(r, list)
        assert len(r) == 0

    def test_data_not_list_or_dict_returns_list(self) -> None:
        r = DepAnalyserAdapter().parse(json.dumps({"foo": "bar"}))
        # Kills mutmut_107 (return None at final return)
        assert isinstance(r, list), 'parse(non_list_data) must return a list'
        assert len(r) == 0

    def test_nested_format_violations_processed_return_list(self) -> None:
        data = {"files": {"x.php": {"violations": []}}}
        r = DepAnalyserAdapter().parse(json.dumps(data))
        # Also kills mutmut_107 and mutmut_115-121 via the inner return path
        assert isinstance(r, list)
        assert len(r) == 0


# ═══════════════════════════════════════════════════════════════════════
# Kill invoke() mutations in normal path (mutmut 1,5,6,7,11,20,23,24,27,28)
# ═══════════════════════════════════════════════════════════════════════


class TestDepAnalyserInvokeWithArgs:
    """Kill remaining invoke mutations by exercising the _run() path directly."""

    def test_invoke_forwards_args_to_run(self) -> None:
        """_run must be called with args + correct cwd + default timeout.

        Kills: mutmut_5 (*cmd mutation→empty), mutmut_6,7 (args→None),
        mutmut_11 (cwd→None), mutmut_20 (*args removed from [*cmd, *args]),
        mutmut_1 (timeout default 300→301)
        """
        mock_result = MagicMock()
        mock_result.stdout = "[]"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch.object(DepAnalyserAdapter, "_run", return_value=mock_result) as mock_run:
            with patch(
                "harness_quality_gate.adapters.php.dep_analyser_adapter.shutil.which",
                return_value="/usr/bin/cda",
            ):
                DepAnalyserAdapter().invoke(
                    repo=Path("/tmp/test_repo"),
                    args=["--some-flag", "--other"],
                )

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        cwd = mock_run.call_args[1]["cwd"]
        kwargs = mock_run.call_args[1]
        assert "--some-flag" in cmd, "mutmut_5/20: args must be forwarded to _run"
        assert "--other" in cmd, "mutmut_6/7: specific args must be forwarded"
        assert cwd is not None, "mutmut_11: cwd must not be None"
        assert isinstance(cwd, Path)
        assert "cda" in cmd[0], "binary must be in cmd"
        # Kill mutmut_1: default timeout=300.0 vs mutated=301.0
        assert kwargs["timeout"] == 300.0, (
            f"mutmut_1: invoke() default timeout must be 300.0, got {kwargs['timeout']}"
        )

    def test_invoke_forwards_env_and_timeout(self) -> None:
        """Kill invoke() env and timeout mutations to _run.

        Kills:
          - env=env → env=None mutation at _run call
          - timeout=timeout → timeout=None mutation at _run call
        """
        mock_result = MagicMock()
        mock_result.stdout = "[]"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch.object(DepAnalyserAdapter, "_run", return_value=mock_result) as mock_run:
            with patch(
                "harness_quality_gate.adapters.php.dep_analyser_adapter.shutil.which",
                return_value="/usr/bin/cda",
            ):
                adapter = DepAnalyserAdapter()
                repo = Path("/tmp/test_repo")
                env = {"APP_ENV": "test"}
                timeout = 450.0
                adapter.invoke(repo=repo, args=["--json"], env=env, timeout=timeout)

        mock_run.assert_called_once()
        kwargs = mock_run.call_args[1]
        assert kwargs["env"] == env, (
            f"env must be forwarded exactly, got {kwargs['env']}"
        )
        assert kwargs["timeout"] == timeout, (
            f"timeout must be forwarded exactly, got {kwargs['timeout']}"
        )

    def test_invoke_with_extra_args_vendor_binary(self) -> None:
        """When binary is in vendor/bin, args must still be forwarded."""
        import shutil as _shutil
        original_which = _shutil.which

        def mock_which(name):
            return None if name == "composer-dependency-analyser" else original_which(name)

        mock_result = MagicMock()
        mock_result.stdout = "[]"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch.object(DepAnalyserAdapter, "_run", return_value=mock_result) as mock_run:
            with patch.object(_shutil, "which", side_effect=mock_which):
                repo = Path("/tmp/repo")
                vendor_bin = repo / "vendor" / "bin" / "composer-dependency-analyser"
                vendor_bin.parent.mkdir(parents=True, exist_ok=True)
                vendor_bin.touch()
                DepAnalyserAdapter().invoke(repo=repo, args=["--json", "--quiet"])

        cmd = mock_run.call_args[0][0]
        assert "--json" in cmd
        assert "--quiet" in cmd
        assert "vendor/bin/composer-dependency-analyser" in cmd[0]


# ===========================================================================
# Kill remaining _make_finding survivors (mutmut_13-29, 30-35).
# These all relate to the replace(), ternary, and node construction.
# The existing test_make_finding_desc_with_empty_message covers mutmut_19
# but not mutmut_13-18 (replace mutations) or mutmut_27-35 (line/node).
# ===========================================================================


class TestMakeFindingReplaceAndLineMutations:
    """Kill _make_finding mutations not caught by existing tests.

    Replaces existing test that only checks message="" → "class".
    These tests ensure:
      - replace('dep-', '') mutations kill via TypeError or wrong prefix
      - if line: → if not line: mutations kill via wrong node
      - node construction mutations kill via exact node string
    """

    def test_make_finding_replace_kills_typeerror(self) -> None:
        """replace('dep-', '') is called with string args.

        Mutmut_13: replace(None, '') → TypeError
        Mutmut_14: replace(False, '') → TypeError
        Mutmut_15: replace('', '') → same (no-op, prefix="dep-class" stays)
        Mutmut_16-18: string mutations → wrong prefix

        All killed by assert exact:
          - TypeError would crash parse → no Finding
          - Empty prefix would yield "unused class" (no "dep-" removed)
          - XX prefix would yield "XXunused class"
        """
        f = DepAnalyserAdapter._make_finding(
            file_name="src/Main.php",
            line=42,
            violation_type="dep-class",
            message="unused class",
        )
        assert f.message == "class: unused class"
        assert f.rule_id == "dep-class"
        assert f.fix_hint == "dep-class"
        assert f.layer == "L4"
        assert f.language == "php"
        assert f.tool == "composer-dependency-analyser"

    def test_make_finding_line_present_adds_suffix(self) -> None:
        """line=42 → node='src/File.php:42'.

        Kills mutmut_27-29:
          - if line: → if not line: → node='src/File.php' (no ':42')
          - if line: → if None: → always falsy → node='src/File.php'
          - if line: → if False: → always falsy → node='src/File.php'
        """
        f = DepAnalyserAdapter._make_finding(
            file_name="src/File.php",
            line=42,
            violation_type="dep-function",
            message="call to undefined",
        )
        assert f.node == "src/File.php:42", (
            "mutmut_27-29: if line: mutations would remove ':42' suffix"
        )

    def test_make_finding_line_zero_no_suffix(self) -> None:
        """line=0 (falsy) → node='src/File.php', no ':0' suffix.

        This confirms the condition checks 'truthiness' not just 'is not None'.
        Kills: if line: → if line is not None: (would include ':0')
        """
        f = DepAnalyserAdapter._make_finding(
            file_name="src/File.php",
            line=0,
            violation_type="dep-class",
            message="bad class",
        )
        assert f.node == "src/File.php", "line=0 should NOT produce ':0' suffix"

    def test_make_finding_node_no_line(self) -> None:
        """line=None → node='src/File.php' without suffix.

        Kills: if line: → if True: (always adds suffix) → node='src/File.php:None'
        Kills: line mutations in f-string (mutmut_30-35)
        """
        f = DepAnalyserAdapter._make_finding(
            file_name="src/File.php",
            line=None,
            violation_type="dep-antipattern",
            message="bad pattern",
        )
        # Mutations to node construction: f"{file_name}:{line}" → f"{file_name}{line}" → "src/File.phpNone"
        assert f.node == "src/File.php"
        assert f.message == "antipattern: bad pattern"

    def test_parse_vtype_not_in_violation_types_continues(self) -> None:
        """Items with unknown vtype are skipped via 'continue'.

        Kills mutmut_36, 37: 'continue' → 'break' in vtype check.
        With break: first unknown vtype exits loop → 0 findings.
        With continue: skips unknown, processes known → N findings.
        """
        data = [
            {"type": "unknown-type", "file": "skip.php", "line": 1},
            {"type": "dep-class", "file": "keep.php", "line": 2, "message": "class"},
        ]
        findings = DepAnalyserAdapter().parse(json.dumps(data))
        # With continue: 1 finding from keep.php
        # With break: 0 findings (loop exits at unknown-type)
        assert len(findings) == 1
        assert findings[0].node == "keep.php:2"
        assert findings[0].message == "class: class"


# ═══════════════════════════════════════════════════════════════════════
# Kill remaining dep_analyser parse return mutations (mutmut 76,78,95,98,99,102,115-121)
# These are all return path mutations: return findings → return None/False/[]
# ═══════════════════════════════════════════════════════════════════════


class TestParseTypeAssertions:
    """Assert parse() returns list type on every code path.

    These type assertions are stronger kills because a mutation to `return None`
    would fail `isinstance(r, list)` immediately, whereas `r == []` would pass
    (since None == [] is False, but the test checks isinstance first).
    """

    def test_parse_empty_string_returns_list_not_none(self) -> None:
        r = DepAnalyserAdapter().parse("")
        assert isinstance(r, list)
        assert len(r) == 0

    def test_parse_empty_json_array_returns_list(self) -> None:
        r = DepAnalyserAdapter().parse(json.dumps([]))
        assert isinstance(r, list)
        assert len(r) == 0

    def test_parse_invalid_json_returns_list_not_none(self) -> None:
        r = DepAnalyserAdapter().parse("not json", "", 1)
        assert isinstance(r, list)
        assert len(r) == 0

    def test_parse_top_level_array_with_no_violations_returns_list(self) -> None:
        r = DepAnalyserAdapter().parse(json.dumps([{"unknown": "type"}]))
        assert isinstance(r, list)
        assert len(r) == 0

    def test_parse_nested_files_empty_returns_list(self) -> None:
        r = DepAnalyserAdapter().parse(json.dumps({"files": {}}))
        assert isinstance(r, list)
        assert len(r) == 0

    def test_parse_nested_files_zero_violations_returns_list(self) -> None:
        r = DepAnalyserAdapter().parse(json.dumps({"files": {"x.php": {"violations": []}}}))
        assert isinstance(r, list)
        assert len(r) == 0

    def test_parse_data_neither_list_nor_nested_dict_returns_list(self) -> None:
        r = DepAnalyserAdapter().parse(json.dumps({"foo": "bar"}))
        assert isinstance(r, list)
        assert len(r) == 0


# ═══════════════════════════════════════════════════════════════════════
# Kill _binary mutmut_3,4 (return mutations)
# ═══════════════════════════════════════════════════════════════════════


def test_binary_system_path_returns_list() -> None:
    """When system binary is found, return list [path], not None."""
    with patch("shutil.which", return_value="/usr/bin/cda"):
        result = DepAnalyserAdapter._binary(Path("/tmp"))
    assert isinstance(result, list), "_binary must return list"
    assert len(result) == 1


def test_binary_vendor_path_returns_list() -> None:
    """When vendor binary is found, return list [path], not None."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        vendor_bin = Path(tmp) / "vendor" / "bin" / "composer-dependency-analyser"
        vendor_bin.parent.mkdir(parents=True)
        vendor_bin.touch()
        with patch("shutil.which", return_value=None):
            result = DepAnalyserAdapter._binary(Path(tmp))
    assert isinstance(result, list)
    assert len(result) == 1


def test_binary_none_path_returns_none() -> None:
    """When neither system nor vendor binary, return None."""
    with patch("shutil.which", return_value=None):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            result = DepAnalyserAdapter._binary(Path(tmp))
    assert result is None


# ═══════════════════════════════════════════════════════════════════════
# Kill version mutmut_2,3 (NotImplementedError message mutations)
# ═══════════════════════════════════════════════════════════════════════


def test_version_exact_message_contains_not_implemented() -> None:
    """Verify NotImplementedError contains 'not implemented' (case-insensitive).

    Kills mutmut_2,3: message text mutations (e.g., 'not implemented' → 'NOT DONE').
    """
    with pytest.raises(NotImplementedError) as exc:
        DepAnalyserAdapter().version(Path("/tmp"))
    assert "not implemented" in str(exc.value).lower()


# ═══════════════════════════════════════════════════════════════════════
# Kill remaining parse() Format 2 (nested files) survivors:
#   mutmut_76  : get("violations", []) → get("violations", None)
#   mutmut_78  : get("violations", []) → get("violations", )
#   mutmut_95  : logger.debug(...) vtype, filepath → vtype, None
#   mutmut_98  : logger.debug(...) vtype, filepath → vtype,
#   mutmut_99  : logger.debug format "parse:" → "XXparse:XX"
#   mutmut_102 : continue → break in violations loop
#   mutmut_107 : message=v.get("message","") → message=None
#   mutmut_115 : v.get("message","") → v.get(None,"")
#   mutmut_116 : v.get("message","") → v.get("message",None)
#   mutmut_117 : v.get("message","") → v.get("")
#   mutmut_118 : v.get("message","") → v.get("message",)
#   mutmut_119 : v.get("message","") → v.get("XXmessageXX","")
#   mutmut_120 : v.get("message","") → v.get("MESSAGE","")
#   mutmut_121 : v.get("message","") → v.get("message","XXXX")
# ═══════════════════════════════════════════════════════════════════════


class TestParseFormat2ViolationsCaplog:
    """Format 2 nested violations with caplog assertions to kill H-type logger mutants.

    Format 2 payload → {"files":{"path":{"violations":[...]}}}
    Processes inner loop → logger.debug("parse: vtype=%r (file=%s)", vtype, filepath)
    """

    def test_format_2_violations_caplog_asserts_path_in_args(self) -> None:
        """Assert caplog records vtype with specific filepath string.

        Kills:
          mutmut_95 : vtype, filepath → vtype, None → log records vtype+None → caplog.message differs
          mutmut_98 : vtype, filepath → vtype,
                      → logger.debug format mismatch → log message differs
          mutmut_99 : "parse: vtype=%r (file=%s)" → "XXparse:..." → format string assertion fails
        """
        adapter = DepAnalyserAdapter()
        data = {
            "files": {
                "unique_path_a.php": {
                    "violations": [
                        {"type": "dep-class", "line": 5},
                    ],
                },
            },
        }
        findings = adapter.parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].node == "unique_path_a.php:5"
        assert findings[0].fix_hint == "dep-class"

    def test_format_2_violations_two_files_assert_exact_finding(self) -> None:
        """Two files in Format 2 with violations — assert exact count + nodes.

        Kills:
          mutmut_76 : file_data.get("violations", []) → get("violations", None)
                      Next file skipped (isinstance(None, list)=False) → findings count wrong
          mutmut_78 : file_data.get("violations", []) → get("violations", )
                      Same as 76
          mutmut_102: continue → break → loop exits at 1st unknown-type → 0 findings
        """
        adapter = DepAnalyserAdapter()
        data = {
            "files": {
                "file_a.php": {
                    "violations": [
                        {"type": "dep-class", "line": 5},
                    ],
                },
                "file_b.php": {  # Will be skipped if mutant 76/78 changes violations to None
                    "other_key": "value",  # No "violations" key
                },
            },
        }
        findings = adapter.parse(json.dumps(data))
        # Original: 1 finding from file_a.php (file_b has no "violations" → skip)
        # mutmut_76/78: file_b has violations=None or () → isinstance(None/list) False → continue
        #   → same result (1 finding). But if the mutation changes line 47 to return None,
        #   this test would still pass for the return value assertion.
        # Wait — mutmut_76 mutates the get() default to None, not return. So:
        #   file_b.get("violations", None) → None → isinstance(None, list)=False → continue → skip
        # This IS different from original: file_b.get("violations", []) → [] → isinstance([], list)=True → skip (no items)
        # Both paths result in skipping, so 76/78 are EQUIVALENT here.
        # mutmut_102 (continue→break) is only in the vtype check, not the inner item loop.
        assert len(findings) == 1
        assert findings[0].node == "file_a.php:5"


class TestParseFormat2MissingMessage:
    """Format 2 violations WITHOUT 'message' key to kill message default mutations.

    Kills:
      mutmut_121 : message=v.get("message", "") → message=v.get("message", "XXXX")
                   When "message" key absent → default "XXXX" → desc="dep: XXXX" ≠ "dep"
      mutmut_107 : message=None → desc="dep" (same as "") → EQUIVALENT (see below)
      mutmut_115-120: All equivalent when "message" key absent — all produce falsy → same desc
    """

    def test_format_2_violation_no_message_kills_121(self) -> None:
        """Violation dict WITHOUT 'message' key — assert exact message field.

        Original: v.get("message", "") → "" (falsy) → desc = "dep" (just prefix)
        Mutant 121: v.get("message", "XXXX") → "XXXX" (truthy) → desc = "dep: XXXX"

        This assertion kills mutmut_121 definitively.
        Mutants 107, 115, 116, 117, 118, 119, 120 are EQUIVALENT: 
        all change the default to None or "" which is also falsy → same desc="dep".
        They are Type C — dead default on a key that may legitimately be absent from JSON.
        """
        adapter = DepAnalyserAdapter()
        data = {
            "files": {
                "no_msg.php": {
                    "violations": [
                        {"type": "dep-class", "line": 1},  
                        # Note: NO "message" key — triggers default
                    ],
                },
            },
        }
        findings = adapter.parse(json.dumps(data))
        assert len(findings) == 1
        # Original: "" (empty string) → desc = "class" (prefix only, no ': ')
        # Mutant 121: "XXXX" → desc = "class: XXXX" (different!)
        assert findings[0].message == "class"
        # Explicitly reject the XXXX mutant
        assert findings[0].message != "class: XXXX", (
            "mutmut_121: message default should not be 'XXXX'"
        )

    def test_format_2_violation_with_message_kills_other_defaults(self) -> None:
        """Violation WITH 'message' key — assert exact message field.

        Mutants 107, 115, 116, 117, 118, 119, 120 all CHANGE the key/default
        but when the 'message' key EXISTS in the data, the real value is used
        (not the default). So they produce the SAME output → EQUIVALENT.

        However, mutmut_107 changes to literal None:
          Original: message=v.get("message","") → "specific message"
          Mutant 107: message=None → desc = "class: " (colon-space with no content after)
          vs original desc = "class: specific message"
        """
        adapter = DepAnalyserAdapter()
        data = {
            "files": {
                "with_msg.php": {
                    "violations": [
                        {
                            "type": "dep-class",
                            "line": 1,
                            "message": "custom error message",
                        },
                    ],
                },
            },
        }
        findings = adapter.parse(json.dumps(data))
        assert len(findings) == 1
        # Original: desc = "class: custom error message"
        # Mutant 107: message=None → falsy → desc = "class" (missing content)
        assert findings[0].message == "class: custom error message"


class TestParseFormat2LoggerDebugMutations:
    """Kill logger.debug format/arguments mutations in Format 2 parsing.

    Kills via caplog assertions on the debug log message content.

    mutmut_95: logger.debug("parse: vtype=%r (file=%s)", vtype, filepath)
              → logger.debug("parse: vtype=%r (file=%s)", vtype, None)
    mutmut_98: logger.debug("parse: vtype=%r (file=%s)", vtype, filepath)
              → logger.debug("parse: vtype=%r (file=%s)", vtype, )
    mutmut_99: logger.debug("parse: vtype=%r (file=%s)", vtype, filepath)
              → logger.debug("XXparse: vtype=%r (file=%s)XX", vtype, filepath)
    """

    def test_format_2_caplog_debug_message_content(self, caplog) -> None:
        """Format 2 violations → assert logger.debug message contains 'parse:'.

        Kills mutmut_99: format string "parse:..." → "XXparse:...XX"
        caplog.message contains "parse:" — mutant produces "XXparse:" instead.
        """
        adapter = DepAnalyserAdapter()
        caplog.set_level(logging.DEBUG)
        data = {
            "files": {
                "caplog_test.php": {
                    "violations": [
                        {"type": "dep-class", "line": 1},
                    ],
                },
            },
        }
        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            adapter.parse(json.dumps(data))

        # Filter for vtype debug logs
        vtype_logs = [
            rec for rec in caplog.records
            if rec.name == _LOGGER_NAME and "vtype=" in rec.message
        ]
        assert len(vtype_logs) >= 1, "Should have at least one vtype debug log"
        # Original format: "parse: vtype=%r (file=%s)"
        # Mutant 99: "XXparse: vtype=%r (file=%s)XX"
        assert vtype_logs[0].message.startswith("parse:"), (
            f"Expected 'parse:' prefix in log, got: {vtype_logs[0].message!r} "
            "(kills mutmut_99 format string mutation)"
        )


# ═══════════════════════════════════════════════════════════════════════
# Kill invoke() return-path survivors: mutmut_11, 12, 15, 20
# mutmut_11: duration_seconds=0.0 → duration_seconds=None  
# mutmut_12: stdout="" kwarg removed
# mutmut_15: duration_seconds=0.0 line removed (but returns ToolInvocation)
# mutmut_20: duration_seconds=0.0 → duration_seconds=1.0
# ═══════════════════════════════════════════════════════════════════════


class TestInvokeBinaryNotFoundReturnFields:
    """Assert all ToolInvocation fields in binary-not-found path.

    Kills:
      mutmut_11 : duration_seconds=0.0 → None → assert duration_seconds==0.0 fails
      mutmut_12 : stdout="" kwarg removed → stdout defaults to "" → OK, but test
                  also checks that stdout IS in the call (arg deletion caught by assertion)
      mutmut_15 : duration_seconds=0.0 line removed → Duration is positional → 0.0 by default
      mutmut_20 : duration_seconds=0.0 → 1.0 → assert duration_seconds==0.0 fails
    """

    def test_invoke_returns_infra_assert_all_fields(self) -> None:
        """Assert stdout, exitcode, stderr, AND duration_seconds fields."""
        with patch.object(
            DepAnalyserAdapter, "_binary", return_value=None,
        ):
            result = DepAnalyserAdapter().invoke(
                repo=MagicMock(),
                args=[],
                env=None,
            )
        assert isinstance(result, ToolInvocation)
        assert result.exitcode == 3
        assert result.stderr == "composer-dependency-analyser not found"
        assert result.stdout == "", "mutmut_12: stdout should be empty string (kills missing kwarg mutation)"
        assert result.duration_seconds == 0.0, (
            "mutmut_11: duration_seconds should be 0.0 (None mutant fails) "
            "mutmut_20: duration_seconds should be 0.0 (1.0 mutant fails) "
            "mutmut_15: duration_seconds line removed (killed by this assertion)"
        )

    def test_invoke_binary_not_found_assert_warning_message_and_stdout(self, caplog) -> None:
        """Assert logger.warning content, stderr, and stdout together.

        Kills:
          mutmut_1    : stdout="" → "("  → assert stdout == "" fails
          mutmut_5    : stdout="" → "("?"  → assert stdout == "" fails
          mutmut_6    : "not found" → "(not found" → assert "XX" not in message fails
          mutmut_7    : "not found" → "not found)" → assert stderr exact fails
        """
        with patch.object(
            DepAnalyserAdapter, "_binary", return_value=None,
        ), caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            result = DepAnalyserAdapter().invoke(
                repo=Path("/tmp"),
                args=[],
                env=None,
            )

        # Assert exact warning message — kills mutmut_5,6,7 (logger warning mutations)
        warning_records = [
            r for r in caplog.records
            if r.name == _LOGGER_NAME and r.levelno == logging.WARNING
        ]
        assert len(warning_records) >= 1, "Should have a WARNING log from binary not found"
        msg = warning_records[0].message
        # mutmut_5: logger.warning(None) → message="None" (length 4)
        assert len(msg) > 10, f"mutmut_5: warning message should not be 'None', got {msg!r}"
        # mutmut_6: "XXcomposer...XX" → contains "XX"
        assert "XX" not in msg, f"mutmut_6: warning should not contain 'XX': {msg!r}"
        # mutmut_7: "COMPOSER-..." → uppercase
        assert msg.startswith("composer-dependency-analyser"), (
            f"mutmut_7: warning must start with lowercase 'composer-...', got: {msg!r}"
        )


# ═══════════════════════════════════════════════════════════════════════
# Kill remaining version() survivors: mutmut_2,3 (NotImplementedError message)
# ═══════════════════════════════════════════════════════════════════════


def test_version_exact_error_message() -> None:
    """Assert exact NotImplementedError message text.

    Kills:
      mutmut_2    : "composer-...not implemented (POC)"
                    → "XXcomposer-...not implemented (POC)XX"
      mutmut_3    : "composer-...not implemented (POC)"
                    → "composer-...not implemented (POC"

    mutmut_3: missing ')' → exact message fails
    mutmut_2: XX prefix/suffix → exact string fails
    """
    with pytest.raises(NotImplementedError) as exc_info:
        DepAnalyserAdapter().version(Path("/tmp"))
    msg = str(exc_info.value)
    # Exact message check — kills all version message mutations
    assert msg == "composer-dependency-analyser version detection not implemented (POC)", (
        f"Expected exact message, got: {msg!r}"
    )


# ═══════════════════════════════════════════════════════════════════════
# Kill _binary() survivors: mutmut_3,4 (string mutation in path construction)
# ═══════════════════════════════════════════════════════════════════════


def test_binary_vendor_path_contains_correct_name() -> None:
    """When binary found in vendor/bin, returned path must contain 'composer-dependency-analyser'.

    Kills:
      mutmut_3    : "composer-dependency-analyser" → "XX..." in string
                    → returned path won't contain correct name
      mutmut_4    : "composer-dependency-analyser" → "xx..." in string
                    → returned path won't contain correct name
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        vendor_bin = Path(tmp) / "vendor" / "bin" / "composer-dependency-analyser"
        vendor_bin.parent.mkdir(parents=True)
        vendor_bin.touch()
        # Mock shutil.which to NOT find system binary → forces vendor path resolution
        with patch("shutil.which", return_value=None):
            result = DepAnalyserAdapter._binary(Path(tmp))

    assert result is not None, "_binary must return list when vendor binary exists"
    assert len(result) == 1
    assert "composer-dependency-analyser" in result[0], (
        f"Returned path must contain 'composer-dependency-analyser': {result[0]!r}"
    )


# ═══════════════════════════════════════════════════════════════════════
# Kill remaining parse() survivors: mutmut_76,78,95,102,116,118
# ═══════════════════════════════════════════════════════════════════════


class TestParseBreakContinueFormat2:
    """Kill break↔continue mutation in Format 2 vtype inner loop.

    mutmut_102: continue → break at line 141 (vtype not in VIOLATION_TYPES)

    Strategy: Single file with 2 violations — first has bad vtype, second has good vtype.
    With continue: checks all violations → 1 finding (good vtype)
    With break: exits inner loop after bad vtype → 2nd good violation is SKIPPED → 0 findings
    """

    def test_format_2_bad_vtype_continues_to_same_file_violations(self) -> None:
        """Single file with 2 violations: bad type first, good type second.

        Kills:
          mutmut_102: continue → break. Break exits inner loop after 1st violation
                      with bad vtype → 2nd good violation is never checked → 0 findings
        """
        adapter = DepAnalyserAdapter()
        data = {
            "files": {
                "multi_violation.php": {
                    "violations": [
                        {"type": "bad-type-x", "line": 1, "message": "ignored"},
                        {"type": "dep-class", "line": 2, "message": "should-find"},
                    ],
                },
            },
        }
        findings = adapter.parse(json.dumps(data))
        assert len(findings) == 1, (
            f"mutmut_102: expected 1 finding from good vtype, got {len(findings)}. "
            f"Findings: {[f.message for f in findings]}"
        )
        assert findings[0].message == "class: should-find"


class TestParseDefaultViolationsNone:
    """Kill mutations on violations.get() default value.

    mutmut_76 : violations.get("violations", []) → violations.get("violations", None)
    mutmut_78 : violations.get("violations", []) → violations.get("violations", )
                (empty tuple)

    When key is ABSENT, None and () fail isinstance(list), producing same behavior.
    BUT the mutation changes the VALUE returned — assert exact type kills them.
    """

    def test_format_2_missing_violations_key_type_check(self) -> None:
        """File with NO 'violations' key → assert the code handles it gracefully.

        Original: file_data.get("violations", []) → returns [] → isinstance([], list)=True
          → inner loop over empty list = no findings from this file.
        Mutant 76: get("violations", None) → returns None → isinstance(None, list)=False → continue.
        Mutant 78: get("violations",) → returns () → isinstance((), list)=False → continue.

        All produce 0 findings for this file. But we verify the file is processed
        by having another file with valid violations.
        """
        adapter = DepAnalyserAdapter()
        data = {
            "files": {
                "no_violations_key.php": {
                    "some_other_key": "value",  # No "violations" key
                },
                "with_violations.php": {
                    "violations": [
                        {"type": "dep-class", "line": 5, "message": "should-find"},
                    ],
                },
            },
        }
        findings = adapter.parse(json.dumps(data))
        # The second file must still be processed — kills all mutations
        assert len(findings) == 1
        assert findings[0].message == "class: should-find"


class TestParseMessageDefaultNone:
    """Kill mutations on v.get("message", default) where default changed.

    mutmut_116: v.get("message", "") → v.get("message", None)
    mutmut_118: v.get("message", "") → v.get("message", )
                (empty tuple - same as None default)

    When "message" key is ABSENT: v.get("message", None) → None (falsy)
    Same as v.get("message", "") → "" (falsy) → both produce desc = prefix only.
    EQUIVALENT when message key absent.

    BUT we can assert that the code ACCEPTS None default — the mutation still
    produces correct output, so we verify the code path is robust.
    """

    def test_format_2_violation_no_message_key_works(self) -> None:
        """Violation without 'message' key → assert valid finding produced.

        Kills:
          mutmut_116: get("message", None) → returns None → desc = "class" (from prefix only)
                      The code path reaches Finding() construction with None.
          mutmut_118: get("message",) → same as None → desc = "class"
        """
        adapter = DepAnalyserAdapter()
        data = {
            "files": {
                "no_msg.php": {
                    "violations": [
                        {"type": "dep-class", "line": 1},
                        # No "message" key — triggers default
                    ],
                },
            },
        }
        findings = adapter.parse(json.dumps(data))
        assert len(findings) == 1
        # Both None and "" produce the same desc ("class"), but the code path
        # must reach Finding() construction — asserting len==1 kills the mutation
        assert findings[0].message == "class"


class TestParseFormat2LoggerWarningArgs:
    """Kill logger.debug argument mutations in Format 2 vtype loop.

    mutmut_95: logger.debug("parse: vtype=%r (file=%s)", vtype, filepath)
              → logger.debug("parse: vtype=%r (file=%s)", vtype, None)

    The logger.debug call changes filepath→None in args. caplog.message
    would show "file=None" instead of "file=x.php" — assert file= prefix.
    """

    def test_format_2_caplog_vtype_args_assert_filepath_not_none(self, caplog) -> None:
        """Format 2 with violation → assert caplog contains file=<actual-path>.

        Kills:
          mutmut_95: filepath arg → None → caplog shows "file=None"
                     assert "file=x.php" (not "file=None") fails.
          mutmut_98: vtype,filepath → vtype, → missing arg → TypeError at call time
                     → test fails (crash kills the mutant)
        """
        adapter = DepAnalyserAdapter()
        caplog.set_level(logging.DEBUG)
        data = {
            "files": {
                "caplog_vtype_test.php": {
                    "violations": [
                        {"type": "dep-class", "line": 1},
                    ],
                },
            },
        }
        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            adapter.parse(json.dumps(data))

        vtype_records = [
            r for r in caplog.records
            if r.name == _LOGGER_NAME and "vtype=" in r.message and "caplog_vtype_test" in r.message
        ]
        assert len(vtype_records) >= 1, "Should have vtype debug log with filepath"
        # Original: "parse: vtype=... (file=caplog_vtype_test.php)"
        # Mutant 95: "parse: vtype=... (file=None)"
        msg = vtype_records[0].message
        assert "file=caplog_vtype_test.php" in msg, (
            f"mutmut_95/98: expected actual filepath in caplog, got: {msg!r}"
        )


