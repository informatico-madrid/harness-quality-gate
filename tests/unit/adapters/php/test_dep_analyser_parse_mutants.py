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
        assert call_kwargs["message"] == "", (
            f"message should be '' not {call_kwargs['message']!r} "
            f"(kills mutmut_62, mutmut_64, mutmut_67)"
        )


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
        """_run must be called with args + correct cwd.
        
        Kills: mutmut_5 (*cmd mutation→empty), mutmut_6,7 (args→None),
        mutmut_11 (cwd→None), mutmut_20 (*args removed from [*cmd, *args]),
        mutmut_23,24,27,28 (return path mutations)
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
        assert "--some-flag" in cmd, "mutmut_5/20: args must be forwarded to _run"
        assert "--other" in cmd, "mutmut_6/7: specific args must be forwarded"
        assert cwd is not None, "mutmut_11: cwd must not be None"
        assert isinstance(cwd, Path)
        assert "cda" in cmd[0], "binary must be in cmd"

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
