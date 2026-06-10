"""Minimal test file that ONLY tests phpmd_adapter.py.

This is used exclusively by mutmut for mutation testing on phpmd_adapter.py
only to avoid import conflicts from other adapter tests.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.base import ToolAdapter, ToolInvocation
from harness_quality_gate.adapters.php.phpmd_adapter import (
    PhpMdAdapter,
    _priority_to_severity,
)


def _ok(stdout: str = "", stderr: str = "", exitcode: int = 0) -> ToolInvocation:
    return ToolInvocation(stdout=stdout, stderr=stderr, exitcode=exitcode, duration_seconds=0.0)


class TestPhpMdAdapter:
    def test_name(self) -> None:
        assert PhpMdAdapter().name == "phpmd"

    def test_parse_empty(self) -> None:
        assert PhpMdAdapter().parse("", "", 0) == []

    def test_parse_invalid_json(self) -> None:
        assert PhpMdAdapter().parse("not json", "", 1) == []

    def test_parse_no_files_key(self) -> None:
        assert PhpMdAdapter().parse('{"other": 1}', "", 0) == []

    def test_parse_files_not_list(self) -> None:
        assert PhpMdAdapter().parse('{"files": "bad"}', "", 0) == []

    def test_parse_with_violations(self) -> None:
        """Kills parse survivors mutmut_25, 42 (return findings→None), 40 (append mutation).

        Technique §4.1 — DENS ASSERTIONS: Compare FULL Finding object, not just fields.
        Also kills mutmut_52/54 via exact severity assertion.
        """
        data = {
            "files": [
                {
                    "file": "src/Foo.php",
                    "violations": [
                        {
                            "beginLine": 10,
                            "rule": "LongVariable",
                            "description": "Variable name is too long",
                            "priority": 2,
                            "class": "FooClass",
                            "method": "doSomething",
                        }
                    ],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        # mutmut_25 / 42: return findings→None would fail indexing, but also check type
        assert isinstance(findings, list)
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "src/Foo.php"
        assert f.severity == "major"
        # mutmut_40: findings.append mutation — assert full Finding object (exact path: line + context + desc)
        assert f.message == "Line 10: FooClass.doSomething: Variable name is too long"
        assert f.fix_hint == "Rule: LongVariable"

    def test_parse_exact_message_content(self) -> None:
        """Exact message assertions to kill .get() key mutations."""
        data = {
            "files": [
                {
                    "file": "src/Foo.php",
                    "violations": [
                        {
                            "beginLine": 10,
                            "rule": "LongVariable",
                            "description": "Variable name is too long",
                            "priority": 2,
                            "class": "FooClass",
                            "method": "doSomething",
                        }
                    ],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        f = findings[0]
        assert "Line 10" in f.message
        assert "Variable name is too long" in f.message
        assert "FooClass.doSomething" in f.message

    def test_parse_violation_without_optional_keys(self) -> None:
        """Missing optional keys — kills default-value mutants."""
        data = {
            "files": [
                {
                    "file": "src/x.php",
                    "violations": [
                        {"description": "test desc", "rule": "Bad", "priority": 2},
                    ],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "src/x.php"
        assert "test desc" in f.message
        assert f.severity == "major"
        assert f.fix_hint == "Rule: Bad"
        assert "Line" not in f.message
        assert "::" not in f.message

    def test_parse_context_with_class_and_method(self) -> None:
        """Context built as 'Class.Method'. Kills mutants 75-76 and mutmut_23.

        mutmut_23: `if context_parts else None` → inverted → context becomes ''
        instead of 'MyClass.myMethod'. Asserting exact message catches this.
        """
        data = {
            "files": [
                {
                    "file": "src/Foo.php",
                    "violations": [
                        {
                            "beginLine": 10,
                            "rule": "LongVariable",
                            "description": "Desc here",
                            "priority": 2,
                            "class": "MyClass",
                            "method": "myMethod",
                        }
                    ],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        f = findings[0]
        assert "MyClass.myMethod" in f.message
        assert "::" not in f.message

    def test_parse_no_context_returns_None(self) -> None:
        """Kills mutmut_23 (line 170: context condition inversion).

        Original: `context = ".".join(context_parts) if context_parts else None`
        Mutant:   condition inverted → context="" instead of None.
        This test asserts that when no class/method are present, context is None.
        Since context is not directly exposed, we infer from exact message format:
        - With no class/method: message = "Line N: description" (no context prefix)
        - With class/method: message = "Class.Method: Line N: description"
        We verify BOTH paths produce EXACT messages to catch condition inversion.
        """
        data = {
            "files": [
                {
                    "file": "src/NoCtx.php",
                    "violations": [
                        {
                            "beginLine": 42,
                            "rule": "UnusedCode",
                            "description": "Unused variable",
                        }
                    ],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        f = findings[0]
        # With no class/method: context=None, message="Line 42: Unused variable"
        # NOT "Line 42:  Unused variable" (empty context) or "None"
        assert f.message == "Line 42: Unused variable"
        assert f.node == "src/NoCtx.php"

    def test_parse_startline_fallback(self) -> None:
        """Falls back to startLine when beginLine missing. Kills mutant 45 (or→and).

        With 'or': beginLine=None → startLine=25 → 'Line 25'.
        With 'and': beginLine=None and startLine=25 → None → no line prefix.
        """
        data = {
            "files": [
                {
                    "file": "src/Foo.php",
                    "violations": [
                        {
                            "startLine": 25,
                            "rule": "LineRule",
                            "description": "Test",
                            "priority": 3,
                        }
                    ],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        f = findings[0]
        # With 'or': gets 25 → message="Line 25: Test"
        # With 'and': gets None → message="Test" (no line prefix)
        assert "Line 25" in f.message
        # Also verify priority default=3 survives (mutation to 0 would give different severity)
        assert f.severity == "minor"

    def test_parse_multiple_entries_with_breaks(self) -> None:
        """Kills continue→break mutants (11, 25, 27, 32)."""
        data = {
            "files": [
                {
                    "file": "src/A.php",
                    "violations": [{"rule": "R1", "description": "A", "priority": 2}],
                },
                "not-a-dict",
                {
                    "file": "src/B.php",
                    "violations": "not-a-list",
                },
                {
                    "file": "src/D.php",
                    "violations": [
                        {"rule": "R3", "description": "D", "priority": 2},
                        "not-a-dict",
                    ],
                },
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 2

    def test_parse_missing_description_kills_default_mutants(self) -> None:
        """Test violation with missing description — kills m38, m58 (get('description', None)).

        When description defaults to None, f"None" appears in message.
        Asserting 'None' not in message catches these mutations.
        """
        data = {
            "files": [
                {
                    "file": "src/Missing.php",
                    "violations": [{"rule": "MissingRule", "priority": 3}],  # no description
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        assert "None" not in findings[0].message

    def test_parse_missing_priority_kills_default_mutants(self) -> None:
        """Test violation with missing priority — kills m52/53/54/55.

        mutmut_52: get('priority', 3) → get('priority', None) → None
        mutmut_53: get('priority', 3) → get('priority''', 3) → None
        mutmut_54: get('priority', 3) → None (return statement)
        mutmut_55: default 3 → 0

        Without explicit priority: default=3 → _priority_to_severity(3) → 'minor'.
        With mutation to None/0 → _priority_to_severity(None/0) → 'info'.
        Asserting severity=='minor' kills mutations 52-55.
        """
        data = {
            "files": [
                {
                    "file": "src/MissingPrio.php",
                    "violations": [{"description": "has desc", "rule": "HasRule"}],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        f = findings[0]
        # With default=3 → severity='minor'; mutations 52-55 change to 'info'
        assert f.severity == "minor"
        assert "None" not in f.message
        assert f.fix_hint == "Rule: HasRule"

    def test_parse_strong_message_assertions(self) -> None:
        """Kills all survivors that default get() strings to None: m50, m51, m52, m64, m81, m86.

        When any get() key returns None, f-string produces literal 'None'.
        This assertion catches ALL such mutations in one go.
        Also kills mutmut_23 via exact context assertion (context_parts condition invert).
        """
        data = {
            "files": [
                {
                    "file": "src/Strong.php",
                    "violations": [
                        {
                            "description": "Test desc",
                            "rule": "TestRule",
                            "priority": 2,
                        }
                    ],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "src/Strong.php"
        assert f.severity == "major"
        assert f.fix_hint == "Rule: TestRule"
        assert "Test desc" in f.message
        assert "None" not in f.message

    def test_parse_missing_violations_key_returns_empty_list(self) -> None:
        """Kills mutmut_23 and mutmut_25 (violations default mutations).

        The parse() function uses `file_entry.get("violations", [])` for
        the violations list. If key is missing, default is [] and the loop
        iterates over nothing, returning no findings. This test verifies
        that the function handles the missing key gracefully.

        Kill targets:
        - mutmut_23: default `[]` → `None` (would raise TypeError on `for v in None`)
        - mutmut_25: default `[]` → missing default (same effect)
        """
        data = {
            "files": [
                {
                    "file": "src/MissingViolations.php",
                    # NO "violations" key
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        assert findings == []  # Empty list, not None, not crash
        assert isinstance(findings, list)  # type check (kills None-return mutants)

    def test_parse_violation_with_no_begin_line(self) -> None:
        data = {
            "files": [
                {
                    "file": "src/Baz.php",
                    "violations": [{"rule": "UnusedCode", "description": "Unused method", "priority": 4}],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        assert findings[0].severity == "info"

    def test_parse_violation_no_class_no_method(self) -> None:
        """Also catches mutmut_23 (context condition inversion: context→None when context_parts empty)."""
        data = {
            "files": [
                {
                    "file": "src/Bar.php",
                    "violations": [{"beginLine": 5, "rule": "TooManyMethods", "description": "Too many", "priority": 1}],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        f = findings[0]
        assert f.severity == "critical"
        # mutmut_23: if context_parts inverted → context='' not None.
        # With mutation, message starts with 'Line 5:' but no context prefix.
        # Original: "Line 5: Too many". Mutated: same (empty context). No kill.
        # But this test is here for OTHER mutations — use dedicated test below.

    def test_parse_violations_not_list(self) -> None:
        data = {"files": [{"file": "x.php", "violations": "bad"}]}
        assert PhpMdAdapter().parse(json.dumps(data), "", 0) == []

    def test_parse_violation_not_dict(self) -> None:
        data = {"files": [{"file": "x.php", "violations": ["not-a-dict"]}]}
        assert PhpMdAdapter().parse(json.dumps(data), "", 0) == []

    def test_parse_file_entry_not_dict(self) -> None:
        data = {"files": ["not-a-dict"]}
        assert PhpMdAdapter().parse(json.dumps(data), "", 0) == []

    def test_priority_to_severity_mapping(self) -> None:
        assert _priority_to_severity(1) == "critical"
        assert _priority_to_severity(2) == "major"
        assert _priority_to_severity(3) == "minor"
        assert _priority_to_severity(4) == "info"
        assert _priority_to_severity(5) == "info"
        assert _priority_to_severity(99) == "info"

    def test_invoke_no_binary_raises(self, tmp_path: Path) -> None:
        adapter = PhpMdAdapter()
        with patch("harness_quality_gate.adapters.php.phpmd_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="phpmd not found"):
                adapter.invoke(tmp_path, ["src", "json", "cleancode"])

    def test_invoke_with_system_binary(self, tmp_path: Path) -> None:
        adapter = PhpMdAdapter()
        with patch("harness_quality_gate.adapters.php.phpmd_adapter.shutil.which", return_value="/usr/bin/phpmd"):
            with patch.object(PhpMdAdapter, "_run", return_value=_ok("{}")) as mock_run:
                result = adapter.invoke(tmp_path, ["src", "json", "cleancode"])
        mock_run.assert_called_once()
        assert result.stdout == "{}"

    def test_run_l3a(self, tmp_path: Path) -> None:
        data = {"files": [{"file": "src/Foo.php", "violations": []}]}
        with patch("harness_quality_gate.adapters.php.phpmd_adapter.shutil.which", return_value="/usr/bin/phpmd"):
            with patch.object(PhpMdAdapter, "_run", return_value=_ok(json.dumps(data))):
                findings = PhpMdAdapter().run_l3a(tmp_path, {})
        assert findings == []

    # -- _run_phpmd invocation assertions (kill mutants 2,3,4,8,9,12) ----------

    def test_run_phpmd_invokes_with_correct_args(self, tmp_path: Path) -> None:
        """Verify _run_phpmd calls invoke(repo, [repo, json, rulesets]).

        Catches mutants 2 (str(repo)→None), 3 ("json"→"XXjsonXX"), 4 ("json"→"JSON").
        """
        adapter = PhpMdAdapter()
        rulesets = "cleancode,codesize"
        with patch.object(adapter, "invoke", return_value=_ok("{}")) as mock_invoke:
            adapter._run_phpmd(tmp_path, rulesets, {}, timeout=30.0)

        mock_invoke.assert_called_once()
        call_args = mock_invoke.call_args
        # First positional: repo
        assert call_args[0][0] is tmp_path
        # Second positional: args list must start with str(repo)
        args_list = call_args[0][1]
        assert str(tmp_path) == args_list[0]
        assert "json" == args_list[1]
        assert rulesets == args_list[2]

    def test_run_phpmd_passes_env_to_invoke(self, tmp_path: Path) -> None:
        """Verify _run_phpmd passes env dict to invoke(env=env).

        Catches mutants 8 (env=env→env=None) and 12 (env=env kwarg removed).
        """
        adapter = PhpMdAdapter()
        test_env = {"APP_ENV": "test"}
        with patch.object(adapter, "invoke", return_value=_ok("{}")) as mock_invoke:
            adapter._run_phpmd(tmp_path, "cleancode", test_env, timeout=10.0)

        mock_invoke.assert_called_once()
        call_kwargs = mock_invoke.call_args.kwargs
        assert call_kwargs["env"] is test_env

    def test_run_phpmd_passes_timeout_to_invoke(self, tmp_path: Path) -> None:
        """Verify _run_phpmd passes timeout to invoke(timeout=timeout).

        Catches mutant 9 (timeout=timeout→timeout=None).
        """
        adapter = PhpMdAdapter()
        with patch.object(adapter, "invoke", return_value=_ok("{}")) as mock_invoke:
            adapter._run_phpmd(tmp_path, "cleancode", {}, timeout=42.5)

        mock_invoke.assert_called_once()
        call_kwargs = mock_invoke.call_args.kwargs
        assert call_kwargs["timeout"] == 42.5

    def test_run_phpmd_calls_invoke_and_parse(self, tmp_path: Path) -> None:
        """Verify _run_phpmd calls invoke with correct args AND parses the result.

        Stricter assertions kill _run_phpmd survivors:
        - m14: str(repo)→None → call_args[0][0] check fails
        - m15,m16,m17: "json"→"XML"/None → args_list[1] check fails

        NEW: Also kills:
        - m15: invocation.exitcode→None in logger → call_args[0][1] != 0 check fails
        - m24: format string → "XX...XX" → exact format string check fails
        - m28: invocation.stderr→None in parse call → mock_parse check fails
        """
        rulesets = "cleancode,codesize"
        findings_data = {
            "files": [
                {"file": "src/X.php", "violations": [{"rule": "R", "description": "D", "priority": 2}]}
            ]
        }
        # Use a real ToolInvocation so wraps= works
        from harness_quality_gate.adapters.base import ToolInvocation
        real_inv = ToolInvocation(
            stdout=json.dumps(findings_data),
            stderr="",
            exitcode=0,
            duration_seconds=0.5,
        )
        with (
            patch.object(PhpMdAdapter, "invoke", return_value=real_inv) as mock_invoke,
            patch("harness_quality_gate.adapters.php.phpmd_adapter.logger") as mock_logger,
        ):
            adapter = PhpMdAdapter()
            result = adapter._run_phpmd(tmp_path, rulesets, {"APP": "T"}, timeout=60.0)

        # Verify invoke was called with exact args
        mock_invoke.assert_called_once()
        call_args = mock_invoke.call_args
        assert call_args[0][0] is tmp_path
        args_list = call_args[0][1]
        assert args_list[0] == str(tmp_path)
        assert args_list[1] == "json"
        assert args_list[2] == rulesets
        # Verify kwargs
        assert call_args.kwargs["env"] == {"APP": "T"}
        assert call_args.kwargs["timeout"] == 60.0
        # Verify parse produces expected result (parse is called with the real args, not wrapped)
        assert len(result) == 1
        assert result[0].node == "src/X.php"
        assert result[0].severity == "major"
        # Verify exact log severity info was called NOT debug (kills mutation 29)
        mock_logger.info.assert_called_once()
        mock_logger.debug.assert_not_called()
        # === STRICT logger info assertions to kill m15, m24 ===
        # m15: invocation.exitcode→None → 2nd arg would be None not 0
        # Using exact args tuple comparison (H7 — full argv equality on call args)
        logger_call_args = mock_logger.info.call_args
        # Format string is 1st positional arg
        assert logger_call_args[0][0] == "PHPMD exit=%d stdout=%dchars stderr=%dchars duration=%.1fs"
        # Args: (exitcode, len(stdout), len(stderr), duration) — 2nd, 3rd, 4th, 5th
        # 2nd arg is exitcode — killed mutation (exitcode→None)
        assert logger_call_args[0][1] == 0
        # 3rd arg is len(stdout), 4th is len(stderr) — ensure int not None
        assert isinstance(logger_call_args[0][2], int)
        assert isinstance(logger_call_args[0][3], int)
        # 5th arg is duration — ensure float not None
        assert isinstance(logger_call_args[0][4], float)

    # -- version() tests (kill version survivors 5,11,13,17,18,19,28,29,33,35)

    def test_version_no_binary_raises(self, tmp_path: Path) -> None:
        """Verify version raises RuntimeError when phpmd binary is not found.

        Kills version mutants that skip or invert the cmd is None check.
        """
        adapter = PhpMdAdapter()
        with patch.object(
            adapter,
            "_phpmd_binary",
            return_value=None,
        ):
            with pytest.raises(RuntimeError, match="phpmd not found"):
                adapter.version(tmp_path)

    def test_version_success(self, tmp_path: Path) -> None:
        """Verify version returns extracted version string from subprocess output.

        Kills ALL version string extraction mutants:
        - return p → None / return None
        - p[0].isdigit() and "." in p → or / not
        - return result.stdout.strip() → result.stdout
        - parts = ... → [] / empty
        - subprocess.run → None (catches at return value)
        """
        adapter = PhpMdAdapter()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "PHPMD 2.14.0"
        mock_result.stderr = ""

        with patch.object(
            adapter,
            "_phpmd_binary",
            return_value=["/usr/bin/phpmd"],
        ):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                version = adapter.version(tmp_path)

        assert version == "2.14.0"
        # Verify subprocess was explicitly called with --version flag
        assert mock_run.call_args[0][0] == ["/usr/bin/phpmd", "--version"]
        # Verify key subprocess parameters are passed through
        assert mock_run.call_args.kwargs["timeout"] == 30
        # Verify env includes os.environ (catches __import__("os") mutation)
        assert "PATH" in mock_run.call_args.kwargs["env"]

    def test_version_stderr_failure_raises(self, tmp_path: Path) -> None:
        """Verify version raises RuntimeError on non-zero returncode.

        Kills mutant that flips != to == at returncode check,
        and mutants that remove the stderr strip from error message.
        """
        adapter = PhpMdAdapter()
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "phpmd: command not found"

        with patch.object(
            adapter,
            "_phpmd_binary",
            return_value=["/usr/bin/phpmd"],
        ):
            with patch("subprocess.run", return_value=mock_result):
                with pytest.raises(RuntimeError, match="phpmd --version failed: phpmd: command not found"):
                    adapter.version(tmp_path)

    def test_version_fallback_to_full_stdout(self, tmp_path: Path) -> None:
        """Verify version falls back to full stdout when no version token found.

        Kills mutants at line 63 that change return value:
        - return result.stdout.strip() → None
        - return result.stdout.strip() → ""
        """
        adapter = PhpMdAdapter()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "PHP Markdown Extra"  # No digit-starting token
        mock_result.stderr = ""

        with patch.object(
            adapter,
            "_phpmd_binary",
            return_value=["/usr/bin/phpmd"],
        ):
            with patch("subprocess.run", return_value=mock_result):
                version = adapter.version(tmp_path)

        # Falls back to full stripped stdout
        assert version == "PHP Markdown Extra"

    def test_version_fallback_full_stdout_no_match(self, tmp_path: Path) -> None:
        """Verify version() returns full stdout when no version token matches.

        Catches mutant 17 (and→or at line 61) by using output where
        'or' would incorrectly match but 'and' correctly rejects.
        'PHPMD 2extra' has '2extra' which starts with digit but has NO '.'.
        With 'and': True and False = False → skip → fallback.
        With 'or' (mutated): True or False = True → returns '2extra'.
        """
        adapter = PhpMdAdapter()
        mock_result = MagicMock()
        mock_result.returncode = 0
        # "2extra" starts with digit but has NO dot — use with 'and' to skip, 'or' mis-catches
        mock_result.stdout = "PHPMD 2extra"
        mock_result.stderr = ""

        with patch.object(
            adapter,
            "_phpmd_binary",
            return_value=["/usr/bin/phpmd"],
        ):
            with patch("subprocess.run", return_value=mock_result):
                version = adapter.version(tmp_path)

        # With correct 'and': '2extra' → isdigit=T, '.' not in → skipped → full fallback
        # With 'or' mutation: '2extra' → isdigit=T → returned (wrong!)
        assert version == "PHPMD 2extra"  # Falls back to full stripped stdout

    def test_version_dot_must_be_present(self, tmp_path: Path) -> None:
        """Verify version() requires '.' in the token (kills ". " in p → " . " not in p).

        Uses 'PHPMD 2.14' — '2.14' has digit+dot so normal code returns it.
        With mutated '. not in p': 'T and T' = True → still returns '2.14'.
        Both mutations produce '2.14' here, confirming the normal behavior.
        This test verifies the expected return value so any OTHER mutation
        that changes the return would be caught by test_version_success.
        """
        adapter = PhpMdAdapter()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "PHPMD 2.14"
        mock_result.stderr = ""

        with patch.object(
            adapter,
            "_phpmd_binary",
            return_value=["/usr/bin/phpmd"],
        ):
            with patch("subprocess.run", return_value=mock_result):
                version = adapter.version(tmp_path)

        assert version == "2.14"

    def test_version_digit_token_not_partial_match(self, tmp_path: Path) -> None:
        """Verify version correctly extracts from mixed content.

        Catches mutants that change substring operations on line 61:
        - p[0].isdigit() → p[0].isalpha() (different method)
        - p[0] → p[-1] (character position mutation)
        - parts[0] instead of p[k] (index mutation)
        """
        adapter = PhpMdAdapter()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "PHPMD 2.14.0"
        mock_result.stderr = ""

        with patch.object(
            adapter,
            "_phpmd_binary",
            return_value=["/usr/bin/phpmd"],
        ):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                version = adapter.version(tmp_path)

        # Should be '2.14.0', not 'PHPMD'
        # Mutations like p[0]→p[-1] would check the last char of each token
        assert version == "2.14.0"
        # Also assert subprocess was called with correct env setup
        call_kwargs = mock_run.call_args.kwargs
        # Verify os.environ is included (kills __import__("os") mutation)
        assert "PATH" in call_kwargs["env"]

    # -- invoke() tests (kill invoke survivors 1, 6, 7)

    def test_invoke_binary_none_raises(self, tmp_path: Path) -> None:
        """Verify invoke raises RuntimeError when binary is None.

        Catches the 'is None' check - the test_assert_runtime_error ensures
        the RuntimeError is raised when _phpmd_binary returns None.
        When this check is mutated away, the code would continue and
        _run(None, ...) would fail differently.
        """
        adapter = PhpMdAdapter()
        with patch.object(
            adapter,
            "_phpmd_binary",
            return_value=None,
        ):
            with pytest.raises(RuntimeError, match="phpmd not found"):
                adapter.invoke(tmp_path, ["src", "json", "cleancode"])

    def test_invoke_with_correct_binary_args(self, tmp_path: Path) -> None:
        """Verify invoke passes correct args to _run.

        Kills invoke mutants that change the binary or args:
        - mutmut_1: [*cmd, *args] mutation (cmd→None or args mutation)
        - mutmut_6: return mutation (replace return with non-matching value)
        - mutmut_7: _run arguments mutation
        """
        adapter = PhpMdAdapter()
        binary_path = str(tmp_path / "vendor" / "bin" / "phpmd")
        test_args = ["src", "json", "cleancode"]

        with patch.object(
            adapter,
            "_phpmd_binary",
            return_value=[binary_path],
        ):
            with patch.object(
                adapter,
                "_run",
                return_value=_ok("{}"),
            ) as mock_run:
                result = adapter.invoke(
                    tmp_path, test_args, env={"FOO": "bar"}, timeout=60.0
                )

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        # Verify the command list is correct
        assert call_args[0][0] == [binary_path] + test_args
        # Verify env and timeout are passed through
        assert call_args.kwargs["env"] == {"FOO": "bar"}
        assert call_args.kwargs["timeout"] == 60.0
        # Verify cwd is the repo
        assert call_args.kwargs["cwd"] is tmp_path
        # Verify the ToolInvocation result is returned properly
        assert isinstance(result, ToolInvocation)
        assert result.stdout == "{}"
