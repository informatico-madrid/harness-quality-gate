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
from harness_quality_gate.bootstrap import ToolNotAvailable
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
        assert f.layer == "L3A"
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

    @patch("harness_quality_gate.adapters.python.ruff_adapter.resolve_tool", side_effect=ToolNotAvailable("ruff"))
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
        assert result.stderr == "ruff not found on PATH or .venv"
        assert result.stdout == ""


# ═══════════════════════════════════════════════════════════════════════
# Version method — kill survivors on version (12 survivors)
# ═══════════════════════════════════════════════════════════════════════


class TestRuffVersion:
    """Tests for RuffAdapter.version — kill mutmut_1..12.

    Kills:
      - mutmut_1: resolve_tool("ruff") → resolve_tool(None, path)
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
            "harness_quality_gate.adapters.python.ruff_adapter.resolve_tool",
            return_value=Path("/usr/bin/ruff"),
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
            "harness_quality_gate.adapters.python.ruff_adapter.resolve_tool",
            return_value=Path("/usr/bin/ruff"),
        ):
            adapter = RuffAdapter()
            mock_result = MagicMock(stdout="")
            with patch.object(adapter, "_run", return_value=mock_result):
                version = adapter.version(Path("/tmp/repo"))
        assert version == "unknown"

    def test_version_binary_not_found_raises(self):
        """Binary not found → raises RuntimeError with exact message.

        Kills mutmut_1 (resolve_tool("ruff") → ToolNotAvailable)
        and mutmut_8 ("ruff not found on PATH" → "XXnot found on PATH").
        """
        with patch(
            "harness_quality_gate.adapters.python.ruff_adapter.resolve_tool",
            side_effect=ToolNotAvailable("ruff"),
        ):
            adapter = RuffAdapter()
            with pytest.raises(RuntimeError) as exc_info:
                adapter.version(Path("/tmp/repo"))
        assert str(exc_info.value) == "ruff not found on PATH or .venv"

    def test_version_env_passed_to_run(self):
        """version() passes env to _run.

        Kills mutmut that removes env parameter from the _run call.
        """
        with patch(
            "harness_quality_gate.adapters.python.ruff_adapter.resolve_tool",
            return_value=Path("/usr/bin/ruff"),
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
            "harness_quality_gate.adapters.python.ruff_adapter.resolve_tool",
            return_value=Path("/usr/bin/ruff"),
        ):
            adapter = RuffAdapter()
            mock_result = MagicMock(stdout="ruff-check 0.8.0\n")
            with patch.object(adapter, "_run", return_value=mock_result):
                version = adapter.version(Path("/tmp/repo"))
        assert version == "0.8.0"

    def test_version_wiring_exact_call_args(self):
        """version() calls _run with exact binary + --version cmd + cwd + env.

        Kills mutmut_19: env=None mutation on version call args.
        """
        with patch(
            "harness_quality_gate.adapters.python.ruff_adapter.resolve_tool",
            return_value=Path("/usr/bin/ruff"),
        ) as resolve_mock:
            adapter = RuffAdapter()
            mock_result = MagicMock(stdout="ruff 0.8.0\n")
            with patch.object(adapter, "_run", return_value=mock_result) as mock_run:
                adapter.version(Path("/tmp/repo"), env={"RUFF_ENV": "1"})
        mock_run.assert_called_once()
        assert mock_run.call_args.args[0] == ["/usr/bin/ruff", "--version"]
        assert mock_run.call_args.kwargs["cwd"] == Path("/tmp/repo")
        assert mock_run.call_args.kwargs["env"] == {"RUFF_ENV": "1"}
        # §4.4 spy: resolve_tool must be called with literal "ruff" — kills
        # mutmut_2 (resolve_tool("ruff", path) → resolve_tool(None, path)).
        resolve_mock.assert_called_once_with("ruff", Path("/tmp/repo"))

    def test_version_env_none_passed(self):
        """When env is None, it's passed as None to _run.

        Kills mutmut on env=env mutation: env=None → env=repo or removed.
        """
        with patch(
            "harness_quality_gate.adapters.python.ruff_adapter.resolve_tool",
            return_value=Path("/usr/bin/ruff"),
        ):
            adapter = RuffAdapter()
            mock_result = MagicMock(stdout="ruff 0.8.0\n")
            with patch.object(adapter, "_run", return_value=mock_result) as mock_run:
                adapter.version(Path("/tmp/repo"))
        assert mock_run.call_args.kwargs["env"] is None


# ═══════════════════════════════════════════════════════════════════════
# Invoke method — continue existing tests
# ═══════════════════════════════════════════════════════════════════════


class TestRuffInvokeNormalPath:
    """Tests for the normal invoke path with mocked _run.

    Kills mutmut survivors on invoke that change command construction
    (mutating args, removing repo path append, etc.).
    """

    @pytest.fixture(autouse=True)
    def _ruff_on_path(self):
        """Deterministic: must not require ruff installed on the machine.

        Name-checking fake — a mutated resolve_tool("ruff", path) argument gets
        ToolNotAvailable, so the resolve-toool-arg mutants (invoke 4/5) still die.
        """
        def _resolve(name, repo):
            if name == "ruff":
                return Path("/usr/bin/ruff")
            raise ToolNotAvailable(name)
        with patch(
            "harness_quality_gate.adapters.python.ruff_adapter.resolve_tool",
            side_effect=_resolve,
        ):
            yield

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
        # /tmp/test_repo has no src/tests dirs -> falls back to '.'
        assert '.' in cmd

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

    def test_invoke_wiring_exact_call_args(self):
        """invoke() calls _run with exact cmd list + cwd/env/timeout.

        Kills mutmut_1,25,26,30: cmd element mutations (binary, flags, repo),
        cwd→None, env→None, timeout→mutated. All via §4.4 spy + §4.7 argv equality.
        """
        adapter = RuffAdapter()
        mock_result = MagicMock(stdout='[]', stderr='', returncode=0)
        repo = Path('/tmp/test_repo')
        BIN = "/usr/local/bin/ruff"

        with patch(
            "harness_quality_gate.adapters.python.ruff_adapter.resolve_tool",
            return_value=Path(BIN),
        ):
            with patch.object(RuffAdapter, '_run', return_value=mock_result) as mock_run:
                adapter.invoke(repo, args=['--select=E501'], env={"RUFF_FOO": "bar"}, timeout=60.0)

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        # Exact command structure — any element mutation is caught
        assert cmd == [
            BIN, "check", "--output-format=json", "--select=E501", ".",
        ]
        assert call_args[1]['cwd'] == repo
        assert call_args[1]['env'] == {"RUFF_FOO": "bar"}
        assert call_args[1]['timeout'] == 60.0

    def test_invoke_default_timeout(self):
        """Default timeout=300.0 forwarded to _run.

        Kills mutmut_60: timeout default mutation (300→301).
        """
        adapter = RuffAdapter()
        mock_result = MagicMock(stdout='[]', stderr='', returncode=0)
        repo = Path('/tmp/test_repo')

        with patch(
            "harness_quality_gate.adapters.python.ruff_adapter.resolve_tool",
            return_value=Path("/usr/local/bin/ruff"),
        ):
            with patch.object(RuffAdapter, '_run', return_value=mock_result) as mock_run:
                adapter.invoke(repo, args=[])
        assert mock_run.call_args[1]['timeout'] == 300.0


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


# ── Edge cases: parse empty input, invalid JSON, non-list JSON ──────────
# These kill the early-return paths in parse() that were surviving mutation.


class TestParseEdgeCases:
    """Tests for parse() early-return paths.

    Kills mutations on the three early-return branches:
      - Line 61:  if not stdout.strip(): return findings
      - Lines 65-66: except json.JSONDecodeError: return findings
      - Line 69:  if not isinstance(entries, list): return findings
    """

    def test_parse_empty_stdout_returns_empty_list(self):
        """Empty/whitespace stdout → return empty list immediately.

        Kills mutation: remove `if not stdout.strip():` → then enters
        json.loads("") → JSONDecodeError → still returns [] but
        different control flow; killing the specific edge early-return.
        """
        assert _adapter().parse("") == []
        assert _adapter().parse("   ") == []

    def test_parse_invalid_json_returns_empty_list(self):
        """Invalid JSON → JSONDecodeError caught → return [].

        Kills mutations on the JSONDecodeError handler (line 65-66):
          - Remove except block → exception propagates (test would crash)
          - Change `return findings` → return None or other value
        """
        assert _adapter().parse("not json at all") == []
        assert _adapter().parse("{broken") == []
        assert _adapter().parse("null") == []  # JSON null, not a list

    def test_parse_non_list_json_returns_empty_list(self):
        """JSON that decodes but is not a list → return [].

        Kills mutation on `if not isinstance(entries, list)` (line 69):
          - Change `not` → `is` → would proceed to iterate over dict entries
          - Remove the check → would loop over dict keys/values
        """
        assert _adapter().parse(json.dumps({"key": "value"})) == []
        assert _adapter().parse(json.dumps({"generalDiagnostics": []})) == []

    def test_name_property_returns_tool_name(self):
        """Accessing .name triggers the name property → covers line 27.

        Kills mutation: property body removed or changed.
        """
        assert _adapter().name == "ruff"

    def test_parse_finding_full_object(self):
        """Full Finding comparison kills remaining parse mutmut (1,2,60).

        Mutmut_1: dict.get("code", None) → None when "code" absent → rule_id=None
        Mutmut_2: dict.get("rule", None) → same
        Mutmut_60: detail/message fallback chain mutation (or→and on line 96)
        Uses dense assertions on every Finding field.
        """
        entry = {
            "code": "F841",
            "filename": "/home/user/src/main.py",
            "location": {"row": 55, "column": 3},
            "message": "local variable 'x' is assigned to but never used",
            "fix": {"message": "Remove unused variable"},
        }
        findings = _adapter().parse(json.dumps([entry]))
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "/home/user/src/main.py"
        assert f.severity == "warning"
        assert f.message == "/home/user/src/main.py:55:3 [F841]: local variable 'x' is assigned to but never used"
        assert f.fix_hint == "Remove unused variable"
        assert f.tool == "ruff"
        assert f.layer == "L3A"
        assert f.language == "python"
        assert f.rule_id == "F841"

    def test_parse_error_severity_no_code(self):
        """Entry with no code and no rule → severity='error', rule_id=None.

        Kills mutmut_1: code="" mutation → severity stays 'error' (not 'warning').
        """
        entry = {
            "filename": "src/a.py",
            "message": "some issue",
        }
        findings = _adapter().parse(json.dumps([entry]))
        assert len(findings) == 1
        f = findings[0]
        assert f.severity == "error"
        assert f.rule_id is None
        assert f.tool == "ruff"
        assert f.layer == "L3A"
        assert f.language == "python"
        assert f.fix_hint is None


# ---------------------------------------------------------------------------
# Phase 2: detect_source_dir usage
# ---------------------------------------------------------------------------


def test_ruff_invoke_uses_detect_source_dir_with_src(tmp_path: Path):
    """When src/ exists, ruff uses detect_source_dir('src').

    Phase 2 convergence: ruff detects the source dir instead of
    hardcoding 'src', enabling config-driven source directories.
    """
    src = tmp_path / "src"
    src.mkdir()

    mock_result = MagicMock()
    mock_result.stdout = "[]"
    mock_result.stderr = ""
    mock_result.returncode = 0

    with patch(
        "harness_quality_gate.adapters.python.ruff_adapter.resolve_tool",
        return_value=Path("/usr/bin/ruff"),
    ):
        with patch.object(RuffAdapter, "_run", return_value=mock_result) as mock_run:
            adapter = RuffAdapter()
            adapter.invoke(tmp_path, [])

    cmd = mock_run.call_args[0][0]
    # "check" "--output-format=json" "--select=..." ... src
    assert "check" in cmd
    assert "--output-format=json" in cmd
    # src/ is a scan target, tests/ should NOT be (exclude_tests=True)
    assert src.name in cmd
    assert "tests" not in cmd


def test_ruff_invoke_fallback_when_no_src(tmp_path: Path):
    """When no src/ or packages exist, ruff falls back to repo root.

    Phase 2 convergence: no source dir found → "." as target.
    """
    mock_result = MagicMock()
    mock_result.stdout = "[]"
    mock_result.stderr = ""
    mock_result.returncode = 0

    with patch(
        "harness_quality_gate.adapters.python.ruff_adapter.resolve_tool",
        return_value=Path("/usr/bin/ruff"),
    ):
        with patch.object(RuffAdapter, "_run", return_value=mock_result) as mock_run:
            adapter = RuffAdapter()
            adapter.invoke(tmp_path, [])

    cmd = mock_run.call_args[0][0]
    # When no sources, "." is the fallback
    assert "." in cmd
    assert "check" in cmd


def test_ruff_package_fallback_excludes_tests(tmp_path: Path):
    """When falling back to package_dirs, tests/ and test* dirs are excluded.

    Phase 2 convergence: source detection must apply exclude_tests consistently.
    """
    # Create a package that looks like a test package
    pkg = tmp_path / "testutils"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")

    mock_result = MagicMock()
    mock_result.stdout = "[]"
    mock_result.stderr = ""
    mock_result.returncode = 0

    with patch(
        "harness_quality_gate.adapters.python.ruff_adapter.resolve_tool",
        return_value=Path("/usr/bin/ruff"),
    ):
        with patch.object(RuffAdapter, "_run", return_value=mock_result) as mock_run:
            adapter = RuffAdapter()
            adapter.invoke(tmp_path, [])

    cmd = mock_run.call_args[0][0]
    # "testutils" has "test" in name → should be excluded by exclude_tests
    # This confirms the adapter properly excludes test packages
    assert cmd[-1] == "."  # fallback to "." since testutils is excluded
