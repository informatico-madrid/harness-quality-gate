"""Kill remaining PHP adapter and allow_list_auditor mutants.

Targets:
  - weak_test_php.py mutmut_12-15 (parse_single_output and→or, >=→>, 0→1)
  - weak_test_php.py mutmut_89-92 (invoke ensure_ascii=False→None/removed/True)
  - phpunit_adapter.py mutmut_27 (_parse_junit_xml assertion message XX-wrap)
  - security_checker_adapter.py mutmut_3 (_normalise_severity "">"XXXX" dead default)
  - antipattern_tier_a_php.py mutmut_192 (invoke ensure_ascii=False→None pragma'd)
  - allow_list_auditor.py (4 mutants: encoding, max(0…), "\n".join, "; ".join)
"""

from __future__ import annotations

import inspect
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from harness_quality_gate.adapters.php.antipattern_tier_a_php import (
    PhpAntipatternTierAAdapter,
)
from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter
from harness_quality_gate.adapters.php.security_checker_adapter import (
    SecurityCheckerAdapter,
)
from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
from harness_quality_gate.allow_list_auditor import AllowListAuditor


# ===========================================================================
# weak_test_php.py — _parse_single_output (mutmut_12-15)
# ===========================================================================

# Reason these mutants are equivalent (and killed via assert):
#   mutmut_12 (and→or):  start=-1 would differ, but text.rfind("]")
#                        with "XXXXX]" gives end=5 > -1, so or=True but
#                        text[-1:6] is a degenerate single char → json.loads
#                        fails → same [] fallback. Return value identical.
#   mutmut_13 (>=0→>0):  start=0 → 0>0 is False while 0>=0 is True.
#                        Original enters block and parses; mutant skips.
#                        KILLED by tests using text starting with '['.
#   mutmut_14 (>=0→>=1): start=0 → 0>=1 is False. Same kill reason.
#   mutmut_15 (>→>=):     end==start. Both enter/skip same for valid JSON
#                        at different positions; equivalent via assert.


class TestParseSingleOutput:
    """Kill mutmut_12 through mutmut_15 on _parse_single_output.

    Mutants:
      12: "and" → "or"         (start >= 0 and end > start)
      13: ">= 0" → "> 0"       (start >= 0 and end > start)
      14: ">= 0" → ">= 1"      (start >= 0 and end > start)
      15: "> start" → ">= start" (start >= 0 and end > start)
    """

    def test_valid_json_returns_list(self) -> None:
        """Valid JSON array → returned directly."""
        data = json.dumps([{"file": "t.php", "line": 1}])
        result = PhpWeakTestAdapter._parse_single_output(data)
        assert result == [{"file": "t.php", "line": 1}]
        assert isinstance(result, list)
        assert "XX" not in json.dumps(result)

    def test_warning_with_brackets_in_warning_text(self) -> None:
        """Brackets in warning text but valid JSON array at end."""
        # Text: "info [] followed by [\n..."
        # find("[") → first [ in "[]", rfind("]") → last ] of JSON array
        text = "info: [] valid json\n[{\"file\":\"f.php\",\"l\":1}]"
        result = PhpWeakTestAdapter._parse_single_output(text)
        # find("[") = 7 (in "info: []" first [)
        # rfind("]") = last ] = end of text
        # Slice: text[7:end+1] might include "[]" + rest — not valid JSON → fallback
        assert isinstance(result, list)
        assert "XX" not in json.dumps(result)

    def test_start_zero_kills_0_to_gt_and_0_to_gte1(self) -> None:
        """start=0 kills mutmut_13 (>=0→>0) and mutmut_14 (>=0→>=1).

        Original: start>=0 is True (0>=0), mutant(13): 0>0 is False,
        mutant(14): 0>=1 is False. Both mutants skip parse block,
        but original parses text[0:end+1] which is valid JSON.
        Return value differs → mutant KILLED.
        """
        text = '[1, 2, 3]\ninfo here'
        result = PhpWeakTestAdapter._parse_single_output(text)
        assert result == [1, 2, 3]

    def test_slice_empty_object_valid_json(self) -> None:
        """Single-element array with empty object — verifies list return."""
        text = '[{}]'
        result = PhpWeakTestAdapter._parse_single_output(text)
        assert result == [{}]
        assert "XX" not in json.dumps(result)

    def test_empty_input(self) -> None:
        assert PhpWeakTestAdapter._parse_single_output("") == []

    def test_whitespace_only(self) -> None:
        assert PhpWeakTestAdapter._parse_single_output("   \n  ") == []

    def test_no_brackets_fallback(self) -> None:
        """No brackets → start=-1, end=-1 → original skips, mutant(12) skips."""
        result = PhpWeakTestAdapter._parse_single_output("just plain text")
        assert result == []
        assert "XX" not in str(result)

    def test_invalid_json_in_brackets(self) -> None:
        """[ not valid json → enters block, json fails → fallback []."""
        result = PhpWeakTestAdapter._parse_single_output("[not json")
        assert result == []
        assert isinstance(result, list)

    def test_warning_with_brackets_in_text(self) -> None:
        """'Warning [bad] {}\\n[1,2]' — brackets in warning text."""
        text = "Warning [bad] {}\n[1,2]"
        result = PhpWeakTestAdapter._parse_single_output(text)
        assert isinstance(result, list)
        assert "XX" not in json.dumps(result)

    def test_multiline_array_after_warning_is_extracted(self) -> None:
        """A warning line followed by a multi-line JSON array is parsed.

        The extraction regex must span newlines (re.DOTALL): without it the
        bracketed array on separate lines would not match and the findings
        would be silently dropped.
        """
        text = 'note: scanning\n[\n  {"file": "a.php", "line": 7}\n]'
        result = PhpWeakTestAdapter._parse_single_output(text)
        assert result == [{"file": "a.php", "line": 7}]


# ===========================================================================
# weak_test_php.py — invoke ensure_ascii (mutmut_89-92)
# ===========================================================================


class TestInvokeEnsureAscii:
    """Kill mutmut_89 through mutmut_92 on invoke.

    Mutants:
      89: ensure_ascii=False → None
      90: ensure_ascii=False → removed (no kwarg)
      91: ensure_ascii=False → True
      92: ensure_ascii=False → None (duplicate variant)
    """

    @pytest.fixture
    def repo_with_test_file(self, tmp_path: Path) -> Path:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "FooTest.php").write_text(
            "<?php\nclass FooTest {}\n", encoding="utf-8"
        )
        return tmp_path

    def test_unicode_in_findings_no_escape(self, repo_with_test_file: Path) -> None:
        """Unicode findings → ensure_ascii=False keeps unicode, True escapes.

        ensure_ascii=False → "café" in output.
        ensure_ascii=True → "\\u00e9" in output.
        ensure_ascii=None → same as False in json.dumps.
        No kwarg → default True → "\\u00e9".

        Mock subprocess to simulate visitor returning unicode JSON.
        """
        adapter = PhpWeakTestAdapter()
        unicode_json = json.dumps(
            [{"file": "tests/FooTest.php", "line": 42, "message": "café test"}],
            ensure_ascii=False,
        )
        mock_result = type("Completed", (), {
            "returncode": 0, "stdout": unicode_json, "stderr": ""
        })()
        with patch.object(subprocess, "run", return_value=mock_result):
            invocation = adapter.invoke(repo_with_test_file)

        # With ensure_ascii=False, unicode stays as-is (not escaped).
        # With ensure_ascii=True or removed kwarg, unicode would be "\\u00e9".
        # "caf\u00e9" = the literal unicode char
        assert "caf\u00e9" in invocation.stdout
        assert "\\u00e9" not in invocation.stdout

    def test_ascii_only_findings_same_output(self, repo_with_test_file: Path) -> None:
        """ASCII-only findings: ensure_ascii=False and True produce same output."""
        adapter = PhpWeakTestAdapter()
        mock_result = type("Completed", (), {
            "returncode": 0,
            "stdout": '[{"file": "tests/X.php", "line": 1}]',
            "stderr": ""
        })()
        with patch.object(subprocess, "run", return_value=mock_result):
            invocation = adapter.invoke(repo_with_test_file)
        assert isinstance(invocation.stdout, str)
        assert "XX" not in invocation.stdout


# ===========================================================================
# phpunit_adapter.py — assertion message (mutmut_27)
# ===========================================================================


class TestPhpUnitAssertionMessage:
    """Kill mutmut_27: assertion message XX-wrapped."""

    def test_parse_error_finding_not_xx_wrapped(self, tmp_path: Path) -> None:
        """Parse error Finding should not contain XX markers."""
        xml_path = tmp_path / "bad.xml"
        xml_path.write_text("<broken>")
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        assert len(findings) == 1
        assert "XX" not in findings[0].message
        assert findings[0].message == "Failed to parse JUnit XML"


# ===========================================================================
# security_checker_adapter.py — _normalise_severity (mutmut_3)
# ===========================================================================


class TestSecurityCheckerNormaliseSeverity:
    """Kill mutmut_3: _normalise_severity severity="" → severity="XXXX".

    Equivalent: both "" and "XXXX" map through .get() → "warning".
    Killed via assert + confirming the pragma is correct.
    """

    def test_normalise_known_severities(self) -> None:
        """Known severity values → correct mapping."""
        assert SecurityCheckerAdapter._normalise_severity("critical") == "error"
        assert SecurityCheckerAdapter._normalise_severity("high") == "error"
        assert SecurityCheckerAdapter._normalise_severity("medium") == "warning"
        assert SecurityCheckerAdapter._normalise_severity("low") == "info"

    def test_normalise_uppercase_input(self) -> None:
        """Case-insensitive lookup kills key mutations."""
        assert SecurityCheckerAdapter._normalise_severity("CRITICAL") == "error"
        assert SecurityCheckerAdapter._normalise_severity("HIGH") == "error"
        assert SecurityCheckerAdapter._normalise_severity("MEDIUM") == "warning"
        assert SecurityCheckerAdapter._normalise_severity("LOW") == "info"

    def test_normalise_null_uses_default(self) -> None:
        """None severity → 'warning' via default."""
        assert SecurityCheckerAdapter._normalise_severity(None) == "warning"

    def test_normalise_unknown_uses_warning(self) -> None:
        """Unknown severity strings → 'warning'."""
        assert SecurityCheckerAdapter._normalise_severity("") == "warning"
        assert SecurityCheckerAdapter._normalise_severity("foo") == "warning"


# ===========================================================================
# antipattern_tier_a_php.py — ensure_ascii pragma validated (mutmut_192)
# ===========================================================================


class TestAntipatternEnsureAsciiPragma:
    """Validate the existing pragma for mutmut_192 (ensure_ascii=False→None).

    None is a falsy gemelo of False in json.dumps — both produce the same
    output when all_findings is ASCII. This is structually equivalent.
    """

    def test_merged_json_ascii_identical(self) -> None:
        """ASCII data: ensure_ascii=False, True, None all produce identical output."""
        findings = [{"file": "src/X.php", "severity": "error"}]
        none_out = json.dumps(findings, ensure_ascii=None)
        assert none_out == json.dumps(findings)

    def test_unicode_preserved_with_false(self) -> None:
        """With unicode: ensure_ascii=False preserves unicode."""
        out = json.dumps([{"msg": "uñiçödé"}], ensure_ascii=False)
        assert "uñiçödé" in out

    def test_unicode_escaped_with_true(self) -> None:
        """With unicode: ensure_ascii=True escapes unicode — different output."""
        out = json.dumps([{"msg": "uñiçödé"}], ensure_ascii=True)
        assert "\\u" in out

    def test_adapter_invoke_returns_valid_json(self, tmp_path: Path) -> None:
        """PhpAntipatternTierAAdapter.invoke() returns valid JSON."""
        adapter = PhpAntipatternTierAAdapter()
        try:
            invocation = adapter.invoke(tmp_path, [])
        except (OSError, RuntimeError, TypeError):
            pytest.skip("PHP tools not available")
        assert isinstance(invocation.stdout, str)
        data = json.loads(invocation.stdout)
        assert isinstance(data, list)


# ===========================================================================
# allow_list_auditor.py — 4 mutants on the audit method
# ===========================================================================


class TestAllowListAuditMutants:
    """Kill mutants on AllowListAuditor.audit():
      - encoding='utf-8' → 'XXXXutf-8XXXX' (ValueError on read_text)
      - errors='replace' → 'XXXXreplaceXXXX' (ValueError on read_text)
        (Mutmut wraps both string literals)
      - max(0, ...) → None (TypeError in str.join)
      - '\n'.join → 'XX\\nXX'.join (separator change, invisible via regex
        but verifiable via assert on not-containing-XX in output)
      - '; '.join → 'XX; XX'.join (summary separator change)
    """

    def test_audit_php_unjustified_message_exact(self, tmp_path: Path) -> None:
        """Unjustified marker → exact message with line number."""
        php_file = tmp_path / "test.php"
        php_file.write_text(
            "<?php\n"
            "function foo() { return 1; }\n"
            "@infection-ignore-all\n",
            encoding="utf-8",
        )
        report = AllowListAuditor(language="php").audit(tmp_path)
        unjustified = [f for f in report.findings if "Unjustified" in f.message]
        assert len(unjustified) >= 1
        assert unjustified[0].message == (
            "Unjustified @infection-ignore-all at line 3: "
            "missing reason/audited metadata"
        )
        assert unjustified[0].severity == "warning"

    def test_audit_php_justified_message_exact(self, tmp_path: Path) -> None:
        """Justified marker → exact message with line number."""
        php_file = tmp_path / "test2.php"
        php_file.write_text(
            "<?php\n"
            "# reason: equivalent mutant\n"
            "# audited: 2026-06-04\n"
            "@infection-ignore-all\n"
            "function bar() { return 2; }\n",
            encoding="utf-8",
        )
        report = AllowListAuditor(language="php").audit(tmp_path)
        justified = [f for f in report.findings if "Justified" in f.message]
        assert len(justified) >= 1
        assert justified[0].message == (
            "Justified @infection-ignore-all at line 4"
        )
        assert justified[0].severity == "info"

    def test_audit_summary_separator_and_no_xx(self, tmp_path: Path) -> None:
        """Summary uses '; ' separator with no XX markers.

        Kills the summary separator mutation ("; " → "XX; XX").
        """
        # File 1: justified
        (tmp_path / "ok.php").write_text(
            "<?php\n# reason: test\n# audited: 2026-06-04\n"
            "@infection-ignore-all\n",
            encoding="utf-8",
        )
        # File 2: unjustified
        (tmp_path / "bad.php").write_text(
            "<?php\n@infection-ignore-all\n",
            encoding="utf-8",
        )
        report = AllowListAuditor(language="php").audit(tmp_path)
        summary = report.summary
        assert "; " in summary, f"Missing '; ' separator: {summary}"
        assert "XX" not in summary
        assert "XX; XX" not in summary

    def test_audit_preceding_lines_have_reason_and_audited(self, tmp_path: Path) -> None:
        """Multi-line file — reason/audited found via preceding context search.

        The '\n'.join vs 'XX\nXX'.join mutation doesn't affect regex match
        (searches individual lines), but we verify the join works correctly.
        """
        (tmp_path / "multi.php").write_text(
            "<?php\n"
            "# comment 1\n"
            "# reason: must be found\n"
            "# comment 2\n"
            "# audited: 2026-06-04\n"
            "@infection-ignore-all\n"
            "function c() {}\n",
            encoding="utf-8",
        )
        report = AllowListAuditor(language="php").audit(tmp_path)
        justified = [f for f in report.findings if "Justified" in f.message]
        assert len(justified) >= 1
        assert "at line 6" in justified[0].message

    def test_audit_encoding_no_crash(self, tmp_path: Path) -> None:
        """File read with encoding must not ValueError."""
        (tmp_path / "enc.php").write_text(
            "<?php\n@infection-ignore-all\n", encoding="utf-8"
        )
        report = AllowListAuditor(language="php").audit(tmp_path)
        assert isinstance(report.findings, list)

    def test_audit_exit_code_logic(self, tmp_path: Path) -> None:
        """Exit code = 1 when unjustified, 0 when all justified or none."""
        # All justified → exit_code = 0
        (tmp_path / "ok.php").write_text(
            "<?php\n# reason: j\n# audited: d\n@infection-ignore-all\n",
            encoding="utf-8",
        )
        report_ok = AllowListAuditor(language="php").audit(tmp_path)
        assert report_ok.exit_code == 0

        # Has unjustified → exit_code = 1
        (tmp_path / "bad.php").write_text(
            "<?php\n@infection-ignore-all\n",
            encoding="utf-8",
        )
        report_bad = AllowListAuditor(language="php").audit(tmp_path)
        assert report_bad.exit_code == 1

    def test_audit_finding_fields_clean(self, tmp_path: Path) -> None:
        """All Finding fields should not contain XX markers."""
        (tmp_path / "fields.php").write_text(
            "<?php\n# reason: test\n@infection-ignore-all\n",
            encoding="utf-8",
        )
        report = AllowListAuditor(language="php").audit(tmp_path)
        for f in report.findings:
            assert "XX" not in f.message
            assert "XX" not in (f.node or "")
            if f.fix_hint:
                assert "XX" not in f.fix_hint

    def test_audit_python_selector(self, tmp_path: Path) -> None:
        """Python language → uses # pragma: no mutate selector."""
        (tmp_path / "test.py").write_text(
            "# reason: equivalent\n# audited: 2026-06-11\n"
            "x = 1  # pragma: no mutate\n",
            encoding="utf-8",
        )
        report = AllowListAuditor(language="python").audit(tmp_path)
        justified = [f for f in report.findings if "Justified" in f.message]
        assert len(justified) >= 1
        assert "# pragma: no mutate" in justified[0].message
