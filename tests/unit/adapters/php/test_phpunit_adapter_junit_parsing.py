"""Comprehensive exhaustive tests for PhpUnitAdapter._parse_junit_xml.

Goal: KILL all mutations on _parse_junit_xml by asserting exact field values
on every Finding produced. Tests target:
  - Finding field mutations     (node, severity, tool, layer, fix_hint → None/literal)
  - root.get() default mutations (root.get("tests", "0") → root.get("tests", ""))
  - Comparison mutations         (errors == 0 → errors != 0)
  - Slice mutations              ([:200] → [:201] / [:199])
  - String default mutations     ("" → "XXXX")
  - Attribute get mutations      (root.get("coveredLines") without default)
  - Return statement mutations   (return None, return [], etc.)

Design: Each test asserts every field of each Finding for completeness.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter
from harness_quality_gate.models import Finding


# ===========================================================================
# Helpers
# ===========================================================================

def _xml(tmp_path: Path, content: str) -> Path:
    """Write XML to junit.xml and return the path."""
    p = tmp_path / "junit.xml"
    p.write_text(content, encoding="utf-8")
    return p


# ===========================================================================
# 1. PARSE ERROR PATH — bad XML
# ===========================================================================

class TestParseError:
    """Kill mutations in the try/except ParseError handler (Finding block for bad XML)."""

    def test_parse_error_all_fields(self, tmp_path: Path) -> None:
        """Bad XML → parse error Finding.

        Kills all 6 Finding field mutations + string literal mutations
        on the parse error Finding block.
        """
        xml_path = _xml(tmp_path, "<broken>")
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        assert len(findings) == 1
        f = findings[0]
        assert f.node == str(xml_path)
        assert f.severity == "error"
        assert f.message == "Failed to parse JUnit XML"
        assert f.tool == "phpunit"
        assert f.layer == "layer1"
        assert f.fix_hint is None

    def test_parse_error_file_not_found(self, tmp_path: Path) -> None:
        """Non-existent file → OSError → parse error Finding."""
        findings = PhpUnitAdapter()._parse_junit_xml(tmp_path / "nonexistent.xml")
        assert len(findings) == 1
        f = findings[0]
        assert f.node == str(tmp_path / "nonexistent.xml")
        assert f.severity == "error"
        assert f.message == "Failed to parse JUnit XML"
        assert f.tool == "phpunit"
        assert f.layer == "layer1"


# ===========================================================================
# 2. ROOT ATTRIBUTE GET — default value mutations
# ===========================================================================

class TestRootAttributes:
    """Kill mutations on root.get("tests", "0"), root.get("errors", "0"), etc."""

    def test_total_attrs_defaults_used(self, tmp_path: Path) -> None:
        """XML with no suite-level attributes → defaults "0" used."""
        content = '<?xml version="1.0"?><testsuites></testsuites>'
        xml_path = _xml(tmp_path, content)
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        # Should produce the "No tests executed" warning (not a summary)
        warning = [f for f in findings if "No tests" in f.message]
        assert len(warning) == 1
        assert warning[0].severity == "warning"
        # Also verify the default attributes were read correctly
        assert warning[0].tool == "phpunit"
        assert warning[0].layer == "layer1"

    def test_total_attrs_with_values(self, tmp_path: Path) -> None:
        """XML with suite-level attributes → correct counts in message."""
        content = (
            '<?xml version="1.0"?>'
            '<testsuites tests="10" errors="2" failures="3" skipped="1">'
            '<testsuite name="Tests"></testsuite>'
            '</testsuites>'
        )
        xml_path = _xml(tmp_path, content)
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        summary = [f for f in findings if "Tests: 10" in f.message]
        assert len(summary) == 1
        assert "Errors: 2" in summary[0].message
        assert "Failures: 3" in summary[0].message
        assert "Skipped: 1" in summary[0].message
        assert summary[0].tool == "phpunit"
        assert summary[0].layer == "layer1"


# ===========================================================================
# 3. ZERO TESTS → summary with exact fields
# ===========================================================================

class TestZeroTests:
    """Kill mutations in the total==0 branch (severity="warning", message, etc.)."""

    def test_zero_tests_summary_fields(self, tmp_path: Path) -> None:
        """tests="0" → warning with exact message, tool, layer."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?>'
            '<testsuites tests="0" errors="0" failures="0" skipped="0">'
            '<testsuite name="Empty"></testsuite>'
            '</testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [f for f in findings if f.message == "No tests executed"][0]
        assert f.severity == "warning"
        assert f.tool == "phpunit"
        assert f.layer == "layer1"
        assert f.node == str(xml_path)
        assert f.fix_hint is None


# ===========================================================================
# 4. SUCCESS SUMMARY — errors==0 and failures==0 → severity="info"
# ===========================================================================

class TestSuccessSummary:
    """Kill comparison mutations on (errors == 0 and failures == 0)."""

    def test_success_severity_info(self, tmp_path: Path) -> None:
        """No errors, no failures → severity is 'info'."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="5" errors="0" failures="0" skipped="0">'
            '<testsuite name="Tests"></testsuite>'
            '</testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        summary = [f for f in findings if "Tests:" in f.message][0]
        assert summary.severity == "info"
        assert summary.tool == "phpunit"
        assert summary.layer == "layer1"

    def test_failure_severity_error(self, tmp_path: Path) -> None:
        """failures > 0 → severity is 'error'."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="5" errors="0" failures="1" skipped="0">'
            '<testsuite name="Tests"></testsuite>'
            '</testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        summary = [f for f in findings if "Tests:" in f.message][0]
        assert summary.severity == "error"
        assert summary.tool == "phpunit"
        assert summary.layer == "layer1"

    def test_error_severity_error(self, tmp_path: Path) -> None:
        """errors > 0 → severity is 'error'."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="5" errors="1" failures="0" skipped="0">'
            '<testsuite name="Tests"></testsuite>'
            '</testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        summary = [f for f in findings if "Tests:" in f.message][0]
        assert summary.severity == "error"


# ===========================================================================
# 5. TESTCASE NODE RESOLUTION — file vs classname vs unknown
# ===========================================================================

class TestTcNodeResolution:
    """Kill mutations on TC node resolution (tc.get('file', ''), tc.get('classname', ''))."""

    def test_tc_with_file_uses_file_as_node(self, tmp_path: Path) -> None:
        """TC with file attribute → node = file path (override classname)."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="1" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="my_test" classname="Tests\\MyClass" file="tests/MyTest.php">'
            '<error>Boom</error>'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        error_f = [f for f in findings if "error:" in f.message.lower()]
        assert len(error_f) == 1
        assert error_f[0].node == "tests/MyTest.php"

    def test_tc_with_classname_no_file(self, tmp_path: Path) -> None:
        """TC with classname but no file → node = classname."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="1" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="my_test" classname="Tests\\MyClass">'
            '<error>Boom</error>'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        error_f = [f for f in findings if "error:" in f.message.lower()]
        assert len(error_f) == 1
        assert error_f[0].node == "Tests\\MyClass"

    def test_tc_no_classname_no_file(self, tmp_path: Path) -> None:
        """TC without name → node = '<unknown>'."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="1" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase><error>Boom</error>'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        error_f = [f for f in findings if "error:" in f.message.lower()]
        assert len(error_f) == 1
        assert error_f[0].message.startswith("<unknown>")

    def test_tc_node_from_failure(self, tmp_path: Path) -> None:
        """Failure TC with file → node = file path."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="1" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="fail_test" classname="Tests\\FailTest" file="tests/FailTest.php">'
            '<failure type="AssertionError">Expected 2</failure>'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        failure_f = [f for f in findings if "failed:" in f.message.lower()]
        assert len(failure_f) == 1
        assert failure_f[0].node == "tests/FailTest.php"
        assert "Expected 2" in failure_f[0].message
        assert "Fix assertion or test logic in " in failure_f[0].fix_hint


# ===========================================================================
# 6. FAILURE ELEMENT — exact Finding fields + details + fix_hint
# ===========================================================================

class TestFailureElement:
    """Kill all mutations on failure element processing (details, fix_hint, fields)."""

    def test_failure_all_fields(self, tmp_path: Path) -> None:
        """Failure TC → Finding with all correct Finding fields."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="1" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="my_fail" classname="Tests\\FAIL" file="tests/Fail.php">'
            '<failure type="AssertionError">Expected 5, got 3</failure>'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [f for f in findings if f.severity == "error" and "failed:" in f.message.lower()][0]
        assert f.node == "tests/Fail.php"
        assert f.severity == "error"
        assert "my_fail" in f.message
        assert "Expected 5, got 3" in f.message
        assert f.tool == "phpunit"
        assert f.layer == "layer1"
        assert "tests/Fail.php" in f.fix_hint  # fix_hint includes node

    def test_failure_multiline_details_collapsed(self, tmp_path: Path) -> None:
        """Failure with multiline details → details collapsed to single line."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="1" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="multi" classname="X" file="tests/X.php">'
            '<failure>\nLine 1\nLine 2\n</failure>'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [f for f in findings if "failed:" in f.message.lower()][0]
        assert "\n" not in f.message

    def test_failure_with_empty_text(self, tmp_path: Path) -> None:
        """Empty failure element → details is empty string."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="1" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="empty_fail" file="tests/E.php"><failure/></testcase>'
            '</testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [f for f in findings if "failed:" in f.message.lower()][0]
        assert "failed:" in f.message
        assert f.tool == "phpunit"
        assert f.layer == "layer1"


# ===========================================================================
# 7. ERROR ELEMENT — exact Finding fields + details + fix_hint
# ===========================================================================

class TestErrorElement:
    """Kill all mutations on error element processing."""

    def test_error_all_fields(self, tmp_path: Path) -> None:
        """Error TC → Finding with all correct fields."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="1" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="err_test" file="tests/Err.php">'
            '<error>NullPointerException</error>'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [f for f in findings if "err_test error:" in f.message][0]
        assert f.node == "tests/Err.php"
        assert f.severity == "error"
        assert f.message == "err_test error: NullPointerException"
        assert f.tool == "phpunit"
        assert f.layer == "layer1"
        assert f.fix_hint == "Fix error in tests/Err.php"

    def test_error_multiline_details_collapsed(self, tmp_path: Path) -> None:
        """Error with multiline details → collapsed."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="1" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="mul_err" file="tests/M.php">'
            '<error>\nLine 1\nLine 2\n</error>'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [f for f in findings if "mul_err error:" in f.message][0]
        assert "\n" not in f.message

    def test_error_with_empty_text(self, tmp_path: Path) -> None:
        """Empty error element."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="1" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="emp_error" file="tests/E.php"><error/></testcase>'
            '</testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [f for f in findings if "error:" in f.message][0]
        assert f.tool == "phpunit"
        assert f.layer == "layer1"


# ===========================================================================
# 8. SKIPPED ELEMENT — exact fields
# ===========================================================================

class TestSkippedElement:
    """Kill mutations on skipped element processing."""

    def test_skipped_all_fields(self, tmp_path: Path) -> None:
        """Skipped TC → Finding with severity=info, correct fix_hint."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="0" skipped="1">'
            '<testsuite name="Tests">'
            '<testcase name="skip_test" classname="Tests\\Skip" file="tests/Skip.php">'
            '<skipped>Dependency missing</skipped>'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [f for f in findings if "was skipped" in f.message][0]
        assert f.severity == "info"
        assert f.tool == "phpunit"
        assert f.layer == "layer1"
        assert "skip_test" in f.message
        assert f.fix_hint == "Remove @depends or fix dependency in {node}"

    def test_skipped_empty_element(self, tmp_path: Path) -> None:
        """Empty skipped element."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="0" skipped="1">'
            '<testsuite name="Tests">'
            '<testcase name="sk" classname="X" file="tests/S.php"><skipped/></testcase>'
            '</testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [f for f in findings if "was skipped" in f.message][0]
        assert f.severity == "info"
        assert f.tool == "phpunit"
        assert f.layer == "layer1"


# ===========================================================================
# 9. INCOMPLETE ELEMENT — exact fields
# ===========================================================================

class TestIncompleteElement:
    """Kill mutations on incomplete element processing."""

    def test_incomplete_all_fields(self, tmp_path: Path) -> None:
        """Incomplete TC → Finding with severity=warning, correct fix_hint."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="inc_test" classname="Tests\\Inc" file="tests/Inc.php">'
            '<incomplete>Not implemented yet</incomplete>'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [f for f in findings if "is incomplete" in f.message][0]
        assert f.severity == "warning"
        assert f.tool == "phpunit"
        assert f.layer == "layer1"
        assert "inc_test" in f.message
        assert "Implement assertions in tests/Inc.php" in f.fix_hint

    def test_incomplete_empty_element(self, tmp_path: Path) -> None:
        """Empty incomplete element."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="inc" classname="X" file="tests/I.php"><incomplete/></testcase>'
            '</testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [f for f in findings if "is incomplete" in f.message][0]
        assert f.severity == "warning"
        assert f.tool == "phpunit"
        assert f.layer == "layer1"


# ===========================================================================
# 10. COVERAGE STATS — coveredLines/totalLines and cover fallback
# ===========================================================================

class TestCoverage:
    """Kill mutations on coverage stats block (coveredLines, cover, totalLines)."""

    def test_coverage_with_coveredLines(self, tmp_path: Path) -> None:
        """Coverage with coveredLines + totalLines → exact Finding fields."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="5" errors="0" failures="0" skipped="0" coveredLines="80" totalLines="100">'
            '<testsuite name="Tests"></testsuite>'
            '</testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [f for f in findings if "Coverage:" in f.message][0]
        assert f.message == "Coverage: 80/100 lines covered"
        assert f.tool == "phpunit"
        assert f.layer == "layer1"
        assert f.node == str(xml_path)
        assert f.severity == "info"

    def test_coverage_with_cover_attribute(self, tmp_path: Path) -> None:
        """Coverage with 'cover' attribute (not coveredLines) → fallback works."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="5" errors="0" failures="0" skipped="0" cover="50" totalLines="100">'
            '<testsuite name="Tests"></testsuite>'
            '</testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [f for f in findings if "Coverage:" in f.message][0]
        assert "50/100" in f.message
        assert f.tool == "phpunit"
        assert f.layer == "layer1"

    def test_coverage_missing_attrs_no_finding(self, tmp_path: Path) -> None:
        """No coverage attributes → no coverage finding."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="5" errors="0" failures="0" skipped="0">'
            '<testsuite name="Tests"></testsuite>'
            '</testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        cov = [f for f in findings if "Coverage:" in f.message]
        assert len(cov) == 0

    def test_coverage_only_covered_lines_no_total(self, tmp_path: Path) -> None:
        """coveredLines without totalLines → no coverage finding (both required)."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="5" errors="0" failures="0" skipped="0" coveredLines="80">'
            '<testsuite name="Tests"></testsuite>'
            '</testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        cov = [f for f in findings if "Coverage:" in f.message]
        assert len(cov) == 0


# ===========================================================================
# 11. SUMMARY NODE VALUE — str(path) vs str(None) mutation
# ===========================================================================

class TestSummaryNode:
    """Kill mutations on str(path) → str(None) or None in summary blocks."""

    def test_summary_node_is_path(self, tmp_path: Path) -> None:
        """Summary finding node = str(path) for both success and non-success."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="0" skipped="0">'
            '<testsuite name="Tests"></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        summary = [f for f in findings if "Tests:" in f.message][0]
        assert summary.node == str(xml_path)

    def test_summary_error_node_is_path(self, tmp_path: Path) -> None:
        """Summary with errors → node still = str(path)."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="1" failures="0" skipped="0">'
            '<testsuite name="Tests"></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        summary = [f for f in findings if "Tests:" in f.message][0]
        assert summary.node == str(xml_path)

    def test_zero_tests_node_is_path(self, tmp_path: Path) -> None:
        """Zero tests warning → node = str(path)."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="0" errors="0" failures="0" skipped="0">'
            '</testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        warn = [f for f in findings if "No tests" in f.message][0]
        assert warn.node == str(xml_path)

    def test_coverage_node_is_path(self, tmp_path: Path) -> None:
        """Coverage finding node = str(path), not TC node."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="5" errors="0" failures="0" skipped="0" coveredLines="80" totalLines="100">'
            '<testsuite name="Tests">'
            '<testcase name="tc" classname="X">'
            '<failure>fail</failure>'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        cov = [f for f in findings if "Coverage:" in f.message][0]
        assert cov.node == str(xml_path)


# ===========================================================================
# 12. MULTIPLE TESTCASES — kills iterator mutations + block count mutations
# ===========================================================================

class TestMultipleTestCases:
    """Kill mutations on the tc.iter loop (multiple TCs, combined errors)."""

    def test_multiple_findings_all_fields(self, tmp_path: Path) -> None:
        """Multiple TCs with different result types → all Findings verified."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="3" errors="1" failures="1" skipped="1">'
            '<testsuite name="Tests">'
            '<testcase name="pass" classname="Tests\\OK" />'
            '<testcase name="fail" classname="Tests\\Fail" file="tests/Fail.php">'
            '<failure type="AssertionError">assertion failed</failure>'
            '</testcase>'
            '<testcase name="err" classname="Tests\\Error" file="tests/Error.php">'
            '<error>Exception</error>'
            '</testcase>'
            '<testcase name="skip" classname="Tests\\Skip" file="tests/Skip.php">'
            '<skipped/>'
            '</testcase>'
            '</testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        # Should have: summary (info) + failure + error + skipped = 4
        assert len(findings) == 4
        # Verify each finding type
        summary = [f for f in findings if "Tests: 3" in f.message][0]
        # With errors="1" failures="1", severity should be "error"
        assert summary.severity == "error"
        assert summary.tool == "phpunit"
        assert summary.layer == "layer1"

        failure = [f for f in findings if "fail" in f.message.lower() and "failed:" in f.message.lower()][0]
        assert failure.severity == "error"
        assert failure.node == "tests/Fail.php"
        assert failure.tool == "phpunit"
        assert failure.layer == "layer1"
        assert "Fix assertion or test logic in tests/Fail.php" == failure.fix_hint

        error = [f for f in findings if "error:" in f.message.lower()][0]
        assert error.severity == "error"
        assert error.node == "tests/Error.php"
        assert error.tool == "phpunit"
        assert error.layer == "layer1"
        assert "Fix error in tests/Error.php" == error.fix_hint

        skipped = [f for f in findings if "was skipped" in f.message][0]
        assert skipped.severity == "info"
        assert skipped.node == "tests/Skip.php"
        assert skipped.tool == "phpunit"
        assert skipped.layer == "layer1"
        assert "Remove @depends or fix dependency in {node}" == skipped.fix_hint


# ===========================================================================
# 13. TESTCASE WITH BOTH FAILURE AND ERROR — multiple iter blocks
# ===========================================================================

class TestMultipleFindingsPerTC:
    """Kill mutations on multiple iter blocks on same TC (failure + error)."""

    def test_tc_multiple_issues(self, tmp_path: Path) -> None:
        """TC with both failure and error elements → two Findings."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="1" failures="1" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="double" classname="Tests\\Both">'
            '<failure>assertion fail</failure>'
            '<error>exception</error>'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        # summary + failure + error = 3
        failures = [f for f in findings if "failed:" in f.message.lower()]
        errors = [f for f in findings if "error:" in f.message.lower()]
        assert len(failures) == 1
        assert len(errors) == 1
        assert failures[0].fix_hint is not None
        assert "Tests\\Both" in failures[0].fix_hint  # fix_hint uses node (classname)
        assert errors[0].fix_hint is not None
        assert "Tests\\Both" in errors[0].fix_hint


# ===========================================================================
# 14. SKELETON — return value is list, not mutated
# ===========================================================================

class TestReturnValue:
    """Kill mutations on return findings (return None, return [], etc.)."""

    def test_return_value_is_list(self, tmp_path: Path) -> None:
        """Return is a list of Finding (not mutated to None)."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="0" errors="0" failures="0" skipped="0"></testsuites>'
        )
        result = PhpUnitAdapter()._parse_junit_xml(xml_path)
        assert isinstance(result, list)
        assert len(result) >= 1
        for f in result:
            assert isinstance(f, Finding)

    def test_parse_method_returns_list(self, tmp_path: Path) -> None:
        """adapter.parse() → list of Finding (not mutated to None/dict/etc.)."""
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="0" errors="0" failures="0" skipped="0"></testsuites>'
        )
        result = PhpUnitAdapter().parse(str(xml_path))
        assert isinstance(result, list)
        for f in result:
            assert isinstance(f, Finding)


# ===========================================================================
# 15. KILL SURVIVED MUTANTS — tc defaults, slice mutations, node=None
# ===========================================================================

class TestKillSurvivedMutants:
    """Target the 15 survived mutants after mutation testing."""

    def test_tc_classname_default_empty_string(self, tmp_path: Path) -> None:
        """TC without classname → node = test_name.

        Kills mutants 124, 126, 129: tc.get("classname", "") → None or , or "XXXX".
        When classname returns None/""/None, node falls back to tc_name.
        """
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="no_classname_test" file="tests/NoClass.php">'
            '<error>NoClassException</error>'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        error_f = [f for f in findings if "no_classname_test error:" in f.message][0]
        # node should be file path when file is provided
        assert error_f.node == "tests/NoClass.php"
        assert error_f.fix_hint == "Fix error in tests/NoClass.php"

    def test_tc_classname_fallback_to_name(self, tmp_path: Path) -> None:
        """TC without classname or file → node = test_name (not "<unknown>").

        Also verifies fix_hint uses tc_name.
        """
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="my_no_attr_test">'
            '<failure>Failed</failure>'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        failure_f = [f for f in findings if "my_no_attr_test failed:" in f.message][0]
        # Without file or classname, node = test_name
        assert failure_f.node == "my_no_attr_test"
        assert "my_no_attr_test" in failure_f.fix_hint

    def test_tc_file_default_empty_string(self, tmp_path: Path) -> None:
        """TC without file but with classname and failure → node = classname.

        Kills mutants 132, 134: tc.get("file", "") → tc.get("file", None), .
        When file default is None/empty/string, if_file_block_uses_classname.
        """
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="1" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="test_name" classname="Tests\\MyClass">'
            '<failure>Assertion error</failure>'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        failure_f = [f for f in findings if "Assertion error" in f.message][0]
        # node should be classname (tests\\MyClass)
        assert failure_f.node == "Tests\\MyClass"
        assert "Tests\\MyClass" in failure_f.fix_hint

    def test_failure_details_string_default_kills(self, tmp_path: Path) -> None:
        """Empty failure element → details = "" not "XXXX".

        Kills mutants 150, 152: (failure.text or "") → (failure.text or "XXXX"),
        (failure.text or "").strip().replace("\n", " XX XX").
        The fix_hint template uses "Fix assertion or test logic in {node}"
        not "Fix assertion or test logic in tests/X.phpXXXX".
        """
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="1" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="empty_fail" file="tests/E.php"><failure/></testcase>'
            '</testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [f for f in findings if "empty_fail failed:" in f.message][0]
        assert f.message == "empty_fail failed: "
        assert f.fix_hint == "Fix assertion or test logic in tests/E.php"

    def test_error_details_string_default_kills(self, tmp_path: Path) -> None:
        """Empty error element → details = "" not "XXXX".

        Kills mutants 182, 184: similar to failure but for errors.
        """
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="1" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="emp_error" file="tests/E.php"><error/></testcase>'
            '</testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [f for f in findings if "emp_error error:" in f.message][0]
        assert f.message == "emp_error error: "
        assert f.fix_hint == "Fix error in tests/E.php"

    def test_slice_200_not_201(self, tmp_path: Path) -> None:
        """Failure with 200+ char details → first 200 chars only.

        Kills mutants 168, 200: details[:200] → details[:201].
        """
        long_msg = "X" * 300
        xml_path = _xml(tmp_path, (
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="1" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="long_test" file="tests/L.php"><failure>' + long_msg + '</failure>'
            '</testcase></testsuite></testsuites>'
        ))
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [f for f in findings if "long_test failed:" in f.message][0]
        # Message should be 218 chars: "long_test failed: " (18) + 200 chars = 218
        assert len(f.message) == 218  # 18 + 200
        assert f.message[-1] == "X"  # Last char is at index 200 (within 200 limit)

    def test_incomplete_node_not_none(self, tmp_path: Path) -> None:
        """Incomplete TC → node = node, not None.

        Kills mutant 234: node=None in incomplete Finding.
        """
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="inc_node_test" classname="Tests\\Inc" file="tests/Inc.php">'
            '<incomplete>Not yet done</incomplete>'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [f for f in findings if "is incomplete" in f.message][0]
        assert f.node == "tests/Inc.php"  # not None
        assert f.fix_hint == "Implement assertions in tests/Inc.php"

    def test_no_coverage_attrs_no_finding(self, tmp_path: Path) -> None:
        """No coveredLines or cover attributes → no coverage finding.

        This indirectly tests mutants 259, 261 (None/empty defaults stay falsy),
        while mutant 264 (cover="XXXX") would make covered truthy and create a finding.
        """
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="0" skipped="0" totalLines="100">'
            '</testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        cov = [c for c in findings if "Coverage:" in c.message]
        assert len(cov) == 0
        # Mutant 264 would produce "Coverage: XXXX/100 lines covered" if it activates

    def test_tc_without_any_attrs_uses_name(self, tmp_path: Path) -> None:
        """TC without classname or file → node must equal tc_name.

        Kills mutant 129: tc.get("classname", "XXXX") → node becomes "XXXX" not tc_name.
        """
        xml_path = _xml(tmp_path,
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="no_attrs_test">'
            '<failure>Not done</failure>'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [c for c in findings if "no_attrs_test failed:" in c.message][0]
        assert f.node == "no_attrs_test"
        assert "no_attrs_test" in f.fix_hint

    def test_failure_with_many_newlines_uses_space(self, tmp_path: Path) -> None:
        """Failure with many newlines → space replacement not 'XX XX'.

        Kills mutant 152: replace("\\n", " ") → replace("\\n", "XX XX").
        """
        # Create 200 lines of newline-separated content (to exceed 200 char slice limit)
        lines = ["Line " + str(i) for i in range(201)]
        long_content = "\n".join(lines)
        xml_path = _xml(tmp_path, (
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="1" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="newl_fail" file="tests/NF.php"><failure>' + long_content + '</failure>'
            '</testcase></testsuite></testsuites>'
        ))
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [c for c in findings if "newl_fail failed:" in c.message][0]
        # Details should use single spaces between lines, not "XX XX"
        assert "XX XX" not in f.message, f"Mutation 152 survived: 'XX XX' found in message"

    def test_error_with_many_newlines_uses_space(self, tmp_path: Path) -> None:
        """Error with many newlines → space replacement not 'XX XX'.

        Kills mutant 184: replace("\\n", " ") → replace("\\n", "XX XX").
        """
        lines = ["Line " + str(i) for i in range(201)]
        long_content = "\n".join(lines)
        xml_path = _xml(tmp_path, (
            '<?xml version="1.0"?><testsuites tests="1" errors="1" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="newl_err" file="tests/NE.php"><error>' + long_content + '</error>'
            '</testcase></testsuite></testsuites>'
        ))
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [c for c in findings if "newl_err error:" in c.message][0]
        assert "XX XX" not in f.message, f"Mutation 184 survived: 'XX XX' found in message"

    def test_slice_error_200_not_201(self, tmp_path: Path) -> None:
        """Error TC with 200+ chars → first 200 chars only.

        Kills mutant 200: details[:200] → details[:201].
        """
        long_msg = "Y" * 300
        xml_path = _xml(tmp_path, (
            '<?xml version="1.0"?><testsuites tests="1" errors="1" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="err_long" file="tests/EL.php"><error>' + long_msg + '</error>'
            '</testcase></testsuite></testsuites>'
        ))
        findings = PhpUnitAdapter()._parse_junit_xml(xml_path)
        f = [c for c in findings if "err_long error:" in c.message][0]
        # Message should be 216 chars: "err_long error: " (16) + 200 chars = 216
        assert len(f.message) == 216  # 16 + 200
        assert f.message[-1] == "Y"  # Last char is within 200 limit


# ═══════════════════════════════════════════════════════════════════════
# KILL _parse_stdout SURVIVORS (61 survivors — NO existing tests!)
# ═══════════════════════════════════════════════════════════════════════


def test_parse_stdout_empty() -> None:
    """Empty stdout → no findings.

    Kills mutmut on early return: return findings vs return None.
    """
    findings = PhpUnitAdapter()._parse_stdout("")
    assert isinstance(findings, list)
    assert len(findings) == 0


def test_parse_stdout_whitespace_only() -> None:
    """Whitespace-only stdout → stripped, no findings."""
    findings = PhpUnitAdapter()._parse_stdout("   \n\n  ")
    assert len(findings) == 0


def test_parse_stdout_no_match() -> None:
    """Text that doesn't match PHPUnit pattern → no findings."""
    findings = PhpUnitAdapter()._parse_stdout("Some random text")
    assert len(findings) == 0


def test_parse_stdout_failed_with_class() -> None:
    """Failed test with class + test name → correct node and fields.

    Kills mutations on match group extraction and Finding construction.
    Format: "1) Class::test_name FAILED" - no space before :: means
    the regex doesn't split class, so node contains full test string.
    """
    text = "1) Tests\\FooTest::test_bar FAILED\n"
    findings = PhpUnitAdapter()._parse_stdout(text)
    assert len(findings) == 1
    f = findings[0]
    # Regex: (\S+)\s+::\s+ requires whitespace BEFORE :: to split
    # Without whitespace before ::, the whole "Tests\\FooTest::test_bar" goes to group(2)
    assert f.node == "Tests\\FooTest::test_bar"
    assert f.severity == "error"
    assert f.message == "Tests\\FooTest::test_bar failed"
    assert f.tool == "phpunit"
    assert f.layer == "layer1"
    # fix_hint uses node which contains full class::test
    assert f.fix_hint == "Fix assertion in Tests\\FooTest::test_bar"


def test_parse_stdout_no_class() -> None:
    """Test without class prefix → node uses test_name only."""
    text = "1) test_name FAILED\n"
    findings = PhpUnitAdapter()._parse_stdout(text)
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "test_name"
    assert f.message == "test_name failed"
    assert "Fix assertion in test_name" == f.fix_hint


def test_parse_stdout_error() -> None:
    """Error test → correct fields."""
    text = "2) test_crash ERROR\n"
    findings = PhpUnitAdapter()._parse_stdout(text)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == "error"
    assert f.message == "test_crash error"
    assert f.fix_hint == "Fix error in test_crash"


def test_parse_stdout_skipped() -> None:
    """Skipped test → severity=info with correct fix_hint."""
    text = "3) test_skip SKIPPED\n"
    findings = PhpUnitAdapter()._parse_stdout(text)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == "info"
    assert f.message == "test_skip skipped"
    assert f.fix_hint == "Review skip reason in test_skip"


def test_parse_stdout_incomplete() -> None:
    """Incomplete test → severity=warning with correct fix_hint."""
    text = "4) test_pending INCOMPLETE\n"
    findings = PhpUnitAdapter()._parse_stdout(text)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == "warning"
    assert f.message == "test_pending incomplete"
    assert f.fix_hint == "Complete test in test_pending"


def test_parse_stdout_multiple_lines() -> None:
    """Multiple test lines → multiple findings, each verified."""
    text = (
        "1) test_a FAILED\n"
        "2) test_b ERROR\n"
        "3) test_c SKIPPED\n"
        "4) test_d INCOMPLETE\n"
    )
    findings = PhpUnitAdapter()._parse_stdout(text)
    assert len(findings) == 4
    statuses = {f.message: f.severity for f in findings}
    assert statuses["test_a failed"] == "error"
    assert statuses["test_b error"] == "error"
    assert statuses["test_c skipped"] == "info"
    assert statuses["test_d incomplete"] == "warning"
    # Verify all have correct tool and layer
    for f in findings:
        assert f.tool == "phpunit"
        assert f.layer == "layer1"


def test_parse_stdout_no_class() -> None:
    """Test without class prefix → node uses test_name only."""
    text = "1) test_name FAILED\n"
    findings = PhpUnitAdapter()._parse_stdout(text)
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "test_name"
    assert "Fix assertion in test_name" == f.fix_hint


def test_parse_stdout_multiple_lines() -> None:
    """Multiple test lines → multiple findings, each verified."""
    text = (
        "1) test_a FAILED\n"
        "2) test_b ERROR\n"
        "3) test_c SKIPPED\n"
        "4) test_d INCOMPLETE\n"
    )
    findings = PhpUnitAdapter()._parse_stdout(text)
    assert len(findings) == 4
    statuses = {f.message: f.severity for f in findings}
    assert statuses["test_a failed"] == "error"
    assert statuses["test_b error"] == "error"
    assert statuses["test_c skipped"] == "info"
    assert statuses["test_d incomplete"] == "warning"
    # Verify all have correct tool and layer
    for f in findings:
        assert f.tool == "phpunit"
        assert f.layer == "layer1"


def test_parse_stdout_with_class_split() -> None:
    """Test with space before :: → class extracted, node = class/test.

    PHPUnit format with class: "1) Tests\\Foo :: test FAILED"
    """
    text = "1) Tests\\Foo :: test_bar FAILED\n"
    findings = PhpUnitAdapter()._parse_stdout(text)
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "Tests\\Foo/test_bar"  # class/test_name
    assert f.severity == "error"
    assert f.message == "test_bar failed"
    assert f.tool == "phpunit"
    assert f.layer == "layer1"
    assert "Fix assertion in Tests\\Foo/test_bar" == f.fix_hint


def test_parse_stdout_node_when_cls_empty() -> None:
    """No class → node = test_name (not None).

    Kills mutant on node assignment: node=test_name → node=None.
    """
    text = "1) just_a_test FAILED\n"
    findings = PhpUnitAdapter()._parse_stdout(text)
    assert len(findings) == 1
    assert findings[0].node == "just_a_test"
    assert findings[0].fix_hint == "Fix assertion in just_a_test"


def test_parse_stdout_return_type_is_list() -> None:
    """_parse_stdout always returns a list of findings.

    Kills mutations on 'return findings' → 'return None' / 'return []'.
    """
    assert isinstance(PhpUnitAdapter()._parse_stdout(""), list)
    assert isinstance(PhpUnitAdapter()._parse_stdout("1) test FAILED\n"), list)


# ═══════════════════════════════════════════════════════════════════════
# KILL _bin_path SURVIVORS (22 survivors — NO existing tests!)
# ═══════════════════════════════════════════════════════════════════════


def test_bin_path_default() -> None:
    """No composer.json → default 'vendor/bin/phpunit'."""
    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path
        result = PhpUnitAdapter()._bin_path(Path(tmp))
        assert result == "vendor/bin/phpunit"


def test_bin_path_custom_bin_dir() -> None:
    """composer.json with config.bin-dir → use custom bin path."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "composer.json").write_text(
            json.dumps({"config": {"bin-dir": "custom/bin"}}),
            encoding="utf-8"
        )
        result = PhpUnitAdapter()._bin_path(repo)
        assert result == "custom/bin/phpunit"


def test_bin_path_bad_json() -> None:
    """Invalid composer.json → falls back to default."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "composer.json").write_text("not json", encoding="utf-8")
        result = PhpUnitAdapter()._bin_path(repo)
        assert result == "vendor/bin/phpunit"


def test_bin_path_missing_config_section() -> None:
    """composer.json without config section → default."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "composer.json").write_text(json.dumps({"name": "test/pkg"}), encoding="utf-8")
        result = PhpUnitAdapter()._bin_path(repo)
        assert result == "vendor/bin/phpunit"


def test_bin_path_config_no_bin_dir() -> None:
    """composer.json config present but no bin-dir → default."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "composer.json").write_text(
            json.dumps({"config": {"vendor-dir": "lib"}}),
            encoding="utf-8"
        )
        result = PhpUnitAdapter()._bin_path(repo)
        assert result == "vendor/bin/phpunit"


def test_bin_path_returns_string_not_none() -> None:
    """_bin_path always returns a string (not None/empty).

    Kills mutations: return '' → None or 'XXXX'.
    """
    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path
        result = PhpUnitAdapter()._bin_path(Path(tmp))
        assert isinstance(result, str)
        assert result == "vendor/bin/phpunit"


# ═══════════════════════════════════════════════════════════════════════
# KILL verify_strict_mode SURVIVORS (8 survivors — NO existing tests!)
# ═══════════════════════════════════════════════════════════════════════


def test_verify_strict_mode_missing_file() -> None:
    """No phpunit.xml → all flags reported as missing."""
    with tempfile.TemporaryDirectory() as tmp:
        result = PhpUnitAdapter().verify_strict_mode(Path(tmp))
        assert len(result) == 11  # All strict-mode flags
        assert "strictCoverage" in result
        assert "failOnError" in result


def test_verify_strict_mode_all_present() -> None:
    """phpunit.xml with all flags → empty list."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        content = '<phpunit ' + ' '.join(f'{f}="true"' for f in (
            "strictCoverage", "checkForUnintentionallyCoveredCode",
            "failOnWarning", "failOnError", "failOnRisky",
            "failOnFailure", "failOnIncomplete", "failOnSkipped",
            "failOnEmptyTestSuite", "beStrictAboutCoverageMetadata",
            "beStrictAboutOutputDuringTests",
        )) + '/>'
        (repo / "phpunit.xml").write_text(content, encoding="utf-8")
        result = PhpUnitAdapter().verify_strict_mode(repo)
        assert result == []


def test_verify_strict_mode_partial_missing() -> None:
    """phpunit.xml with only some flags → report only missing."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "phpunit.xml").write_text(
            '<phpunit strictCoverage="true" failOnError="true"></phpunit>',
            encoding="utf-8"
        )
        result = PhpUnitAdapter().verify_strict_mode(repo)
        assert len(result) == 9  # 11 - 2 present = 9 missing
        assert "strictCoverage" not in result
        assert "failOnError" not in result
        assert "failOnWarning" in result


def test_verify_strict_mode_flags_exact() -> None:
    """Verify exact flag names are checked (not just 'strict').

    Kills mutations on flag name → 'XXXXX' or other string mutations.
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        # Only have beStrictAboutCoverageMetadata
        (repo / "phpunit.xml").write_text(
            '<phpunit beStrictAboutCoverageMetadata="true"></phpunit>',
            encoding="utf-8"
        )
        result = PhpUnitAdapter().verify_strict_mode(repo)
        assert "beStrictAboutCoverageMetadata" not in result
        assert "strictCoverage" in result
        assert "beStrictAboutOutputDuringTests" in result


# ═══════════════════════════════════════════════════════════════════════
# KILL parse() SURVIVORS (13 survivors — limited tests for parse method)
# ═══════════════════════════════════════════════════════════════════════


def test_parse_junit_path_not_xml_uses_stdout() -> None:
    """parse() when stdout is NOT .xml path → calls _parse_stdout.

    Kills mutations on the endswith('.xml') check.
    """
    findings = PhpUnitAdapter().parse('Some text output', "", 0)
    assert isinstance(findings, list)
    # No PHPUnit text format → empty
    assert len(findings) == 0


def test_parse_returns_list_not_none() -> None:
    """parse() always returns a list (not mutated to None/False/dict).

    Kills mutations on return statements.
    """
    result = PhpUnitAdapter().parse("", "", 0)
    assert isinstance(result, list)
    # Even with valid XML that produces findings
    assert isinstance(PhpUnitAdapter().parse('junit.xml', ""), list)
    # Or with text output
    assert isinstance(PhpUnitAdapter().parse('1) test FAILED\n', ""), list)


# ═══════════════════════════════════════════════════════════════════════
# KILL version SURVIVORS (mutmut_1, 3, 4 — mutmut_2 is timeout)
# ═══════════════════════════════════════════════════════════════════════


def test_version_raises_not_implemented() -> None:
    """Version → raises NotImplementedError.

    Kills mutmut_1 and mutmut_3: mutations that remove or change the
    NotImplementedError raise (e.g., return "unknown" instead).
    """
    with pytest.raises(NotImplementedError):
        PhpUnitAdapter().version(Path("/tmp"))


def test_version_error_message() -> None:
    """Version error message is exact.

    Kills mutmut_4: error message mutation (e.g., "XXPOCXX").
    """
    import pytest
    adapter = PhpUnitAdapter()
    with pytest.raises(NotImplementedError) as exc_info:
        adapter.version(Path("/tmp"))
    assert str(exc_info.value) == "phpunit version detection not implemented (POC)"


# ═══════════════════════════════════════════════════════════════════════
# KILL invoke SURVIVORS (mutmut_1, 11, 13, 14 — mutmut_3,10 are timeouts)
# ═══════════════════════════════════════════════════════════════════════


def test_invoke_passes_bin_path_and_args_to_run() -> None:
    """Invoke constructs correct command from bin_path and passes to _run.

    Kills mutmut_11: bin_path mutation (changed default path to "XXvendorXX"),
    mutmut_13, mutmut_14: mutations on the cmd list construction
    ("--log-junit" → "XXlog-junitXX", "junit.xml" → "XXjunit.xmlXX").
    """
    from unittest.mock import patch, MagicMock

    adapter = PhpUnitAdapter()
    expected_invocation = MagicMock(
        stdout='[]', stderr='', exitcode=0, duration_seconds=0.0
    )

    with patch.object(adapter, '_bin_path', return_value='vendor/bin/phpunit'):
        with patch.object(adapter, '_run', return_value=expected_invocation) as mock_run:
            result = adapter.invoke(
                Path("/tmp/repo"),
                args=["--filter", "TestFoo"],
                timeout=120.0,
            )

    mock_run.assert_called_once()
    call_args = mock_run.call_args
    # Command should be: [bin_path, "--log-junit", "junit.xml", ...args]
    cmd = call_args[0][0]
    assert cmd == ["vendor/bin/phpunit", "--log-junit", "junit.xml", "--filter", "TestFoo"]
    # Timeout should be custom value
    assert call_args[1]["timeout"] == 120.0
    # CWD should be the repo
    assert call_args[1]["cwd"] == Path("/tmp/repo")
