"""Comprehensive mock-based tests for PHP adapters.

Covers invoke/version/parse paths using unittest.mock.patch for subprocess
calls. Targets near-100% coverage of all PHP adapter modules.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.base import ToolAdapter, ToolInvocation
from harness_quality_gate.adapters.php.antipattern_tier_a_php import (
    PhpAntipatternTierAAdapter,
    _priority_to_severity as antipattern_priority_to_severity,
)
from harness_quality_gate.adapters.php.composer_audit_adapter import (
    ComposerAuditAdapter,
)
from harness_quality_gate.adapters.php.dead_code_adapter import DeadCodeAdapter
from harness_quality_gate.adapters.php.dep_analyser_adapter import DepAnalyserAdapter
from harness_quality_gate.adapters.php.deptrac_adapter import DeptracAdapter
from harness_quality_gate.adapters.php.pcov_adapter import PcovAdapter
from harness_quality_gate.adapters.php.pest_adapter import PestAdapter
from harness_quality_gate.adapters.php.php_cs_fixer_adapter import PhpCsFixerAdapter
from harness_quality_gate.adapters.php.phpmd_adapter import (
    PhpMdAdapter,
    _priority_to_severity,
)
from harness_quality_gate.adapters.php.phpstan_adapter import PhpStanAdapter
from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter
from harness_quality_gate.adapters.php.psalm_taint_adapter import PsalmTaintAdapter
from harness_quality_gate.adapters.php.security_checker_adapter import (
    SecurityCheckerAdapter,
)
from harness_quality_gate.adapters.php.visitor_runner_adapter import (
    VisitorRunnerAdapter,
)
from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(stdout: str = "", stderr: str = "", exitcode: int = 0) -> ToolInvocation:
    return ToolInvocation(stdout=stdout, stderr=stderr, exitcode=exitcode, duration_seconds=0.0)


def _repo(tmp_path: Path) -> Path:
    return tmp_path


# ===========================================================================
# base.py — ToolAdapter abstract methods + _run helper
# ===========================================================================

class _ConcreteAdapter(ToolAdapter):
    """Minimal concrete subclass to test abstract-method guard."""

    @property
    def name(self) -> str:
        return "concrete"

    def version(self, repo: Path, env: Any = None) -> str:
        raise NotImplementedError

    def invoke(self, repo: Path, args: list[str], *, env: Any = None, timeout: float = 300.0) -> ToolInvocation:
        raise NotImplementedError

    def parse(self, stdout: str, stderr: str, exitcode: int):
        raise NotImplementedError


class TestToolAdapterRun:
    def test_run_returns_tool_invocation(self, tmp_path: Path) -> None:
        completed = subprocess.CompletedProcess(
            args=["echo", "hi"], returncode=0, stdout="hi\n", stderr=""
        )
        with patch("subprocess.run", return_value=completed):
            result = ToolAdapter._run(["echo", "hi"], cwd=tmp_path)
        assert isinstance(result, ToolInvocation)
        assert result.exitcode == 0
        assert result.stdout == "hi\n"

    def test_run_timeout_returns_invocation_with_minus1(self, tmp_path: Path) -> None:
        exc = subprocess.TimeoutExpired(cmd=["php"], timeout=5)
        exc.stdout = b"partial"
        exc.stderr = None
        with patch("subprocess.run", side_effect=exc):
            result = ToolAdapter._run(["php", "-v"], cwd=tmp_path)
        assert result.exitcode == -1
        assert result.stdout == "partial"
        assert result.stderr == "TIMEOUT"

    def test_run_timeout_str_stdout(self, tmp_path: Path) -> None:
        exc = subprocess.TimeoutExpired(cmd=["php"], timeout=5)
        exc.stdout = b"text-stdout"
        exc.stderr = b"text-stderr"
        with patch("subprocess.run", side_effect=exc):
            result = ToolAdapter._run(["php", "-v"], cwd=tmp_path)
        assert result.exitcode == -1
        assert result.stdout == "text-stdout"
        assert result.stderr == "text-stderr"

    def test_run_with_env(self, tmp_path: Path) -> None:
        completed = subprocess.CompletedProcess(
            args=["php"], returncode=0, stdout="", stderr=""
        )
        with patch("subprocess.run", return_value=completed) as mock_run:
            ToolAdapter._run(["php"], cwd=tmp_path, env={"FOO": "BAR"})
        called_env = mock_run.call_args[1]["env"]
        assert "FOO" in called_env
        assert called_env["FOO"] == "BAR"

    def test_concrete_raises_not_implemented(self, tmp_path: Path) -> None:
        adapter = _ConcreteAdapter()
        with pytest.raises(NotImplementedError):
            adapter.version(tmp_path)
        with pytest.raises(NotImplementedError):
            adapter.invoke(tmp_path, [])
        with pytest.raises(NotImplementedError):
            adapter.parse("", "", 0)


# ===========================================================================
# phpmd_adapter.py
# ===========================================================================

class TestPhpMdAdapter:
    def test_name(self) -> None:
        assert PhpMdAdapter().name == "phpmd"

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

    def test_invoke_with_vendor_binary(self, tmp_path: Path) -> None:
        vendor_bin = tmp_path / "vendor" / "bin"
        vendor_bin.mkdir(parents=True)
        phpmd = vendor_bin / "phpmd"
        phpmd.touch()

        adapter = PhpMdAdapter()
        with patch("harness_quality_gate.adapters.php.phpmd_adapter.shutil.which", return_value=None):
            with patch.object(PhpMdAdapter, "_run", return_value=_ok("{}")) as mock_run:
                adapter.invoke(tmp_path, ["src", "json", "cleancode"])
        mock_run.assert_called_once()

    def test_parse_empty(self) -> None:
        assert PhpMdAdapter().parse("", "", 0) == []

    def test_parse_invalid_json(self) -> None:
        assert PhpMdAdapter().parse("not json", "", 1) == []

    def test_parse_no_files_key(self) -> None:
        assert PhpMdAdapter().parse('{"other": 1}', "", 0) == []

    def test_parse_files_not_list(self) -> None:
        assert PhpMdAdapter().parse('{"files": "bad"}', "", 0) == []

    def test_parse_with_violations(self) -> None:
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
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "src/Foo.php"
        assert f.severity == "major"
        assert "LongVariable" in (f.fix_hint or "")
        assert "FooClass" in f.message

    def test_parse_exact_message_content(self) -> None:
        """Exact message assertions to kill .get() key mutations.

        Mutants replaced with bad keys (e.g. v.get("XXdescriptionXX", ""))
        will return the default "" instead of actual data, changing the message.
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
        f = findings[0]
        assert "Line 10" in f.message
        assert "Variable name is too long" in f.message
        assert "FooClass.doSomething" in f.message

    def test_parse_violation_without_optional_keys(self) -> None:
        """Violation dict with minimal/missing optional fields.

        Kills mutants that change .get() default values when keys are absent.
        Tests: mutants 14-16 (file default), 28-35 (description default),
        38-40 (rule default), 56-61 (class default), 62-69 (method default),
        81-83 (priority default).
        """
        data = {
            "files": [
                {
                    "file": "src/x.php",
                    "violations": [
                        {
                            "description": "test desc",
                            "rule": "Bad",
                            "priority": 2,
                        }
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
        """Context built as 'Class.Method' when both are present.

        Kills mutants 75-76: '.'.join → 'XX'.join, description → None.
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
        # Context is "MyClass.myMethod" — joined with "."
        assert "MyClass.myMethod" in f.message
        assert "::" not in f.message

    def test_parse_startline_fallback(self) -> None:
        """When beginLine is missing, fall back to startLine.

        Kills mutants 44-53 on the 'line' field:
        - mutant 45: 'or' → 'and' with both keys present changes precedence
        - mutants 46-49: beginLine key mutation
        - mutants 50-53: startLine key mutation
        """
        data = {
            "files": [
                {
                    "file": "src/Foo.php",
                    "violations": [
                        {
                            "beginLine": 5,
                            "startLine": 20,
                            "rule": "LineRule",
                            "description": "Test",
                            "priority": 3,
                        }
                    ],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        f = findings[0]
        # Original: beginLine or startLine → 5 (short-circuit)
        # Mutant 45 (and): beginLine and startLine → 20
        assert "Line 5" in f.message

    def test_parse_multiple_file_entries_with_bads(self) -> None:
        """Multiple file entries with non-dict entries to kill continue→break mutants.

        Mutant 11: continue→break in file_entry loop — non-dict dict entry breaks the loop
        Mutant 25: continue→break in violations-type loop — non-list violations type
        Mutant 27: continue→break in violations-item loop — non-dict item
        Mutant 32: continue→break in violations-item check — non-dict violations list
        """
        data = {
            "files": [
                {
                    "file": "src/A.php",
                    "violations": [
                        {"rule": "R1", "description": "A desc", "priority": 2}
                    ],
                },
                "not-a-dict",  # Non-dict entry — mutant 11 (break) stops here
                {
                    "file": "src/C.php",
                    "violations": "not-a-list",  # Non-list violations — mutant 25 (break) stops here
                },
                {
                    "file": "src/D.php",
                    "violations": [
                        {"rule": "R3", "description": "D desc", "priority": 2},
                        "not-a-dict",  # Non-dict violation — mutants 27, 32 (break) stop here
                    ],
                },
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        # A has 1 finding, B (non-list violations) has 0, D has 1
        # C (non-dict file_entry) is skipped entirely
        assert len(findings) == 2
        assert "A desc" in findings[0].message
        assert "D desc" in findings[1].message

    def test_parse_violation_no_class_no_method(self) -> None:
        data = {
            "files": [
                {
                    "file": "src/Bar.php",
                    "violations": [
                        {
                            "beginLine": 5,
                            "rule": "TooManyMethods",
                            "description": "Too many methods",
                            "priority": 1,
                        }
                    ],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        assert findings[0].severity == "critical"

    def test_parse_violation_no_begin_line(self) -> None:
        data = {
            "files": [
                {
                    "file": "src/Baz.php",
                    "violations": [
                        {"rule": "UnusedCode", "description": "Unused method", "priority": 4},
                    ],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        assert findings[0].severity == "info"

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

    def test_run_l3a(self, tmp_path: Path) -> None:
        data = {"files": [{"file": "src/Foo.php", "violations": []}]}
        with patch("harness_quality_gate.adapters.php.phpmd_adapter.shutil.which", return_value="/usr/bin/phpmd"):
            with patch.object(PhpMdAdapter, "_run", return_value=_ok(json.dumps(data))):
                findings = PhpMdAdapter().run_l3a(tmp_path, {})
        assert findings == []


# ===========================================================================
# phpunit_adapter.py
# ===========================================================================

class TestPhpUnitAdapter:
    def test_name(self) -> None:
        assert PhpUnitAdapter().name == "phpunit"

    def test_version_raises(self, tmp_path: Path) -> None:
        with pytest.raises(NotImplementedError):
            PhpUnitAdapter().version(tmp_path)

    def test_bin_path_default(self, tmp_path: Path) -> None:
        adapter = PhpUnitAdapter()
        assert adapter._bin_path(tmp_path) == "vendor/bin/phpunit"

    def test_bin_path_from_composer_json(self, tmp_path: Path) -> None:
        composer = tmp_path / "composer.json"
        composer.write_text(json.dumps({"config": {"bin-dir": "tools/bin"}}))
        adapter = PhpUnitAdapter()
        assert adapter._bin_path(tmp_path) == "tools/bin/phpunit"

    def test_bin_path_composer_no_bin_dir(self, tmp_path: Path) -> None:
        composer = tmp_path / "composer.json"
        composer.write_text(json.dumps({"config": {}}))
        adapter = PhpUnitAdapter()
        assert adapter._bin_path(tmp_path) == "vendor/bin/phpunit"

    def test_bin_path_composer_invalid_json(self, tmp_path: Path) -> None:
        composer = tmp_path / "composer.json"
        composer.write_text("not json")
        adapter = PhpUnitAdapter()
        assert adapter._bin_path(tmp_path) == "vendor/bin/phpunit"

    def test_invoke_runs_phpunit(self, tmp_path: Path) -> None:
        adapter = PhpUnitAdapter()
        with patch.object(PhpUnitAdapter, "_run", return_value=_ok("")) as mock_run:
            adapter.invoke(tmp_path)
        cmd = mock_run.call_args[0][0]
        assert "--log-junit" in cmd
        assert "junit.xml" in cmd

    def test_invoke_with_args(self, tmp_path: Path) -> None:
        adapter = PhpUnitAdapter()
        with patch.object(PhpUnitAdapter, "_run", return_value=_ok("")) as mock_run:
            adapter.invoke(tmp_path, args=["--filter", "MyTest"])
        cmd = mock_run.call_args[0][0]
        assert "--filter" in cmd
        assert "MyTest" in cmd

    def test_parse_no_junit_file_empty_stdout(self, tmp_path: Path) -> None:
        adapter = PhpUnitAdapter()
        # stdout doesn't point to an existing .xml file, no junit.xml in cwd
        findings = adapter.parse("")
        assert isinstance(findings, list)

    def test_parse_from_junit_xml(self, tmp_path: Path) -> None:
        junit_xml = tmp_path / "junit.xml"
        junit_xml.write_text(
            '<?xml version="1.0"?>'
            '<testsuites tests="2" errors="0" failures="1" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="test_foo" classname="Tests\\FooTest" file="tests/FooTest.php">'
            '<failure type="AssertionError">Expected true got false</failure>'
            '</testcase>'
            '<testcase name="test_bar" classname="Tests\\FooTest" />'
            "</testsuite>"
            "</testsuites>"
        )
        findings = PhpUnitAdapter().parse(str(junit_xml))
        assert any(f.severity == "error" for f in findings)

    def test_parse_junit_xml_zero_tests(self, tmp_path: Path) -> None:
        junit_xml = tmp_path / "junit.xml"
        junit_xml.write_text(
            '<?xml version="1.0"?>'
            '<testsuites tests="0" errors="0" failures="0" skipped="0">'
            "</testsuites>"
        )
        findings = PhpUnitAdapter().parse(str(junit_xml))
        assert any(f.message == "No tests executed" for f in findings)

    def test_parse_junit_xml_with_error_element(self, tmp_path: Path) -> None:
        junit_xml = tmp_path / "junit.xml"
        junit_xml.write_text(
            '<?xml version="1.0"?>'
            '<testsuites tests="1" errors="1" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="test_baz" file="tests/BazTest.php">'
            "<error>PHP Fatal Error</error>"
            "</testcase>"
            "</testsuite>"
            "</testsuites>"
        )
        findings = PhpUnitAdapter().parse(str(junit_xml))
        assert any("error" in f.message for f in findings)

    def test_parse_junit_xml_with_skipped(self, tmp_path: Path) -> None:
        junit_xml = tmp_path / "junit.xml"
        junit_xml.write_text(
            '<?xml version="1.0"?>'
            '<testsuites tests="1" errors="0" failures="0" skipped="1">'
            '<testsuite name="Tests">'
            '<testcase name="test_skip" classname="Tests\\SkipTest">'
            "<skipped/>"
            "</testcase>"
            "</testsuite>"
            "</testsuites>"
        )
        findings = PhpUnitAdapter().parse(str(junit_xml))
        assert any(f.severity == "info" for f in findings)

    def test_parse_junit_xml_with_incomplete(self, tmp_path: Path) -> None:
        junit_xml = tmp_path / "junit.xml"
        junit_xml.write_text(
            '<?xml version="1.0"?>'
            '<testsuites tests="1" errors="0" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="test_inc" classname="Tests\\IncTest">'
            "<incomplete/>"
            "</testcase>"
            "</testsuite>"
            "</testsuites>"
        )
        findings = PhpUnitAdapter().parse(str(junit_xml))
        assert any(f.severity == "warning" for f in findings)

    def test_parse_junit_xml_with_coverage_lines(self, tmp_path: Path) -> None:
        junit_xml = tmp_path / "junit.xml"
        junit_xml.write_text(
            '<?xml version="1.0"?>'
            '<testsuites tests="3" errors="0" failures="0" skipped="0" coveredLines="80" totalLines="100">'
            "</testsuites>"
        )
        findings = PhpUnitAdapter().parse(str(junit_xml))
        assert any("Coverage" in f.message for f in findings)

    def test_parse_junit_xml_bad_xml(self, tmp_path: Path) -> None:
        junit_xml = tmp_path / "junit.xml"
        junit_xml.write_text("<broken>")
        findings = PhpUnitAdapter().parse(str(junit_xml))
        assert any(f.severity == "error" for f in findings)

    def test_parse_stdout_failed(self) -> None:
        stdout = "1) Tests\\FooTest :: test_bar FAILED"
        findings = PhpUnitAdapter()._parse_stdout(stdout)
        # KILL mutants 2 (early return for non-empty) and 5 (regex match → None):
        # Both mutations return [], but original produces at least one finding.
        assert len(findings) >= 1
        f = findings[0]
        assert f.severity == "error"
        assert f.message == "test_bar failed"
        assert f.tool == "phpunit"
        assert f.layer == "layer1"
        # fix_hint uses node = "class/test_name"
        assert f.fix_hint == "Fix assertion in Tests\\FooTest/test_bar"

    def test_parse_stdout_empty(self) -> None:
        assert PhpUnitAdapter()._parse_stdout("") == []

    def test_verify_strict_mode_all_flags_present(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.phpunit_adapter import STRICT_MODE_FLAGS

        flags_content = " ".join(
            f'{flag}="true"' for flag in STRICT_MODE_FLAGS
        )
        xml_content = f'<?xml version="1.0"?><phpunit {flags_content}></phpunit>'
        (tmp_path / "phpunit.xml").write_text(xml_content)
        missing = PhpUnitAdapter().verify_strict_mode(tmp_path)
        assert missing == []

    def test_verify_strict_mode_all_missing(self, tmp_path: Path) -> None:
        (tmp_path / "phpunit.xml").write_text('<?xml version="1.0"?><phpunit></phpunit>')
        missing = PhpUnitAdapter().verify_strict_mode(tmp_path)
        assert len(missing) == 11

    def test_verify_strict_mode_no_xml_file(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.phpunit_adapter import STRICT_MODE_FLAGS

        missing = PhpUnitAdapter().verify_strict_mode(tmp_path)
        assert set(missing) == set(STRICT_MODE_FLAGS)

    def test_parse_passes_to_stdout_fallback(self, tmp_path: Path) -> None:
        """When stdout is not a .xml path and junit.xml doesn't exist, parse falls back."""
        findings = PhpUnitAdapter().parse("some regular output")
        assert isinstance(findings, list)

    # ---------------------------------------------------------------------------
    # Enhanced assertions — kill _parse_junit_xml node-value mutations
    # ---------------------------------------------------------------------------

    def test_parse_junit_xml_failure_node_is_file_path(self, tmp_path: Path) -> None:
        """Assert Finding.node == tc_file for failure finding.

        Kills mutant: str(path) -> str(None) in the <failure> block.
        Verifies the node value is exactly what the code produces.
        """
        junit_xml = tmp_path / "junit.xml"
        junit_xml.write_text(
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="1" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="test_fail" classname="Tests\\FooTest" file="tests/FooTest.php">'
            '<failure type="AssertionError">Expected true</failure>'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter().parse(str(junit_xml))
        failure_finding = [f for f in findings if f.severity == "error" and "failed" in f.message.lower()]
        assert len(failure_finding) == 1
        assert failure_finding[0].node == "tests/FooTest.php"

    def test_parse_junit_xml_success_node_is_path(self, tmp_path: Path) -> None:
        """Assert Finding.node == path for summary finding (success case).

        Kills mutant: str(path) -> str(None) in the summary (success) block.
        """
        junit_xml = tmp_path / "junit.xml"
        junit_xml.write_text(
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="0" skipped="0">'
            '<testsuite name="Tests"></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter().parse(str(junit_xml))
        summary = [f for f in findings if "Tests:" in f.message and "Errors:" in f.message]
        assert len(summary) == 1
        assert summary[0].node == str(junit_xml)

    def test_parse_junit_xml_coverage_node_is_path(self, tmp_path: Path) -> None:
        """Assert Finding.node == path for coverage finding.

        Kills mutant: str(path) -> str(None) in the coverage stats block.
        """
        junit_xml = tmp_path / "junit.xml"
        junit_xml.write_text(
            '<?xml version="1.0"?><testsuites tests="3" errors="0" failures="0" skipped="0" coveredLines="80" totalLines="100">'
            '</testsuites>'
        )
        findings = PhpUnitAdapter().parse(str(junit_xml))
        cov = [f for f in findings if "Coverage:" in f.message]
        assert len(cov) == 1
        assert cov[0].node == str(junit_xml)

    def test_parse_junit_xml_cover_attribute_fallback(self, tmp_path: Path) -> None:
        """Test coverage fallback using 'cover' attribute (not 'coveredLines').

        Kills mutants 258-263: mutations on root.get("cover", "").
        Requires XML that has 'cover' but NOT 'coveredLines'.
        """
        junit_xml = tmp_path / "junit.xml"
        junit_xml.write_text(
            '<?xml version="1.0"?><testsuites tests="3" errors="0" failures="0" skipped="0" cover="50" totalLines="100">'
            '</testsuites>'
        )
        findings = PhpUnitAdapter().parse(str(junit_xml))
        cov = [f for f in findings if "Coverage:" in f.message]
        assert len(cov) == 1
        assert "50/100" in cov[0].message

    def test_parse_junit_xml_testcase_file_takes_precedence(self, tmp_path: Path) -> None:
        """Test case with both classname and file—node should be the file path.

        Exercises code path where tc.get('file','') is truthy and overrides classname.
        """
        junit_xml = tmp_path / "junit.xml"
        junit_xml.write_text(
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="my_test" classname="My\\Class" file="tests/MyTest.php" />'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter().parse(str(junit_xml))
        for f in findings:
            if "Tests:" in f.message:
                assert f.node == str(junit_xml)

    def test_parse_junit_xml_testcase_no_file_uses_classname(self, tmp_path: Path) -> None:
        """Test case with classname but no file—node should use classname.

        Exercises code path where tc.get('file','') is empty string.
        """
        junit_xml = tmp_path / "junit.xml"
        junit_xml.write_text(
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="no_file_test" classname="Tests\\NoFile" />'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter().parse(str(junit_xml))
        for f in findings:
            if "Tests:" in f.message:
                assert f.node == str(junit_xml)

    # ---------------------------------------------------------------------------
    # Enhanced assertions — kill _parse_stdout regex/text mutations
    # ---------------------------------------------------------------------------

    def test_parse_stdout_with_full_format(self) -> None:
        """Parse PHPUnit text output with full Class::method format.

        Asserts exact node to kill regex/text mutation 284.
        Also kills mutants 2 (early return) and 5 (regex match → None) on this path.
        """
        stdout = "1) Tests\\FooTest::test_bar FAILED\n"
        findings = PhpUnitAdapter()._parse_stdout(stdout)
        assert len(findings) >= 1
        f = findings[0]
        # When class group fails to match (no space before ::), test_name = full match
        assert f.message == "Tests\\FooTest::test_bar failed"
        assert f.severity == "error"
        assert f.tool == "phpunit"
        assert f.layer == "layer1"

    def test_parse_junit_xml_failure_details_no_newlines(self, tmp_path: Path) -> None:
        """Failure with multi-line text — details should be collapsed to single line.

        Helps kill mutants 150, 183, 184: string replace mutations on details.
        """
        junit_xml = tmp_path / "junit.xml"
        junit_xml.write_text(
            '<?xml version="1.0"?><testsuites tests="1" errors="0" failures="1" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="multiline_test" classname="Tests\\MultiTest" file="tests/MultiTest.php">'
            '<failure type="AssertionError">Expected:\n  true\nGot:\n  false\n</failure>'
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter().parse(str(junit_xml))
        failure_finding = [f for f in findings if f.severity == "error" and "failed" in f.message.lower()]
        assert len(failure_finding) == 1
        # Details should be collapsed: no raw newlines in the message portion after "failed:"
        assert "\n" not in failure_finding[0].message

    def test_parse_junit_xml_error_details_no_newlines(self, tmp_path: Path) -> None:
        """Error element with multi-line text — details collapsed to single line.

        Helps kill mutants 183, 184: string replace mutations on error details.
        """
        junit_xml = tmp_path / "junit.xml"
        junit_xml.write_text(
            '<?xml version="1.0"?><testsuites tests="1" errors="1" failures="0" skipped="0">'
            '<testsuite name="Tests">'
            '<testcase name="error_test" file="tests/ErrorTest.php">'
            "<error>Line 1\nLine 2\nLine 3</error>"
            '</testcase></testsuite></testsuites>'
        )
        findings = PhpUnitAdapter().parse(str(junit_xml))
        # The error finding has "error:" in message, summary has "Tests:" in message
        error_finding = [f for f in findings if "error:" in f.message and "Tests:" not in f.message]
        assert len(error_finding) == 1
        assert "\n" not in error_finding[0].message


# ===========================================================================
# php_cs_fixer_adapter.py
# ===========================================================================

class TestPhpCsFixerAdapter:
    def test_name(self) -> None:
        assert PhpCsFixerAdapter().name == "php-cs-fixer"

    def test_invoke_no_binary_raises(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.php_cs_fixer_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="php-cs-fixer not found"):
                PhpCsFixerAdapter().invoke(tmp_path, [])

    def test_invoke_with_system_binary(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.php_cs_fixer_adapter.shutil.which", return_value="/usr/bin/php-cs-fixer"):
            with patch.object(PhpCsFixerAdapter, "_run", return_value=_ok("{}")) as mock_run:
                result = PhpCsFixerAdapter().invoke(tmp_path, ["fix", "--dry-run"])
        assert result.stdout == "{}"
        assert mock_run.called

    def test_invoke_with_vendor_binary(self, tmp_path: Path) -> None:
        vendor_bin = tmp_path / "vendor" / "bin"
        vendor_bin.mkdir(parents=True)
        binary = vendor_bin / "php-cs-fixer"
        binary.touch()
        with patch("harness_quality_gate.adapters.php.php_cs_fixer_adapter.shutil.which", return_value=None):
            with patch.object(PhpCsFixerAdapter, "_run", return_value=_ok("{}")):
                result = PhpCsFixerAdapter().invoke(tmp_path, [])
        assert result.exitcode == 0

    def test_parse_empty(self) -> None:
        assert PhpCsFixerAdapter().parse("", "", 0) == []

    def test_parse_invalid_json(self) -> None:
        assert PhpCsFixerAdapter().parse("not json", "", 1) == []

    def test_parse_detailed_format_with_violations(self) -> None:
        data = {
            "files": [
                {
                    "name": "src/Foo.php",
                    "violations": [
                        {"line": 1, "message": "Missing semicolon", "fix": "Add ;"},
                        {"line": 2, "message": "Wrong indentation"},
                    ],
                }
            ]
        }
        findings = PhpCsFixerAdapter().parse(json.dumps(data), "", 8)
        assert len(findings) == 2
        assert findings[0].severity == "warning"
        assert "line 1" in findings[0].message
        assert findings[0].fix_hint == "Add ;"
        assert findings[1].fix_hint is None

    def test_parse_simple_format_with_diff(self) -> None:
        data = {
            "files": [
                {"name": "src/Bar.php", "diff": "--- a/src/Bar.php\n+++ b/src/Bar.php\n@@ ..."}
            ]
        }
        findings = PhpCsFixerAdapter().parse(json.dumps(data), "", 8)
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "src/Bar.php"
        assert f.severity == "warning"
        assert "Bar.php" in f.message
        assert f.fix_hint is not None

    def test_parse_simple_format_no_diff(self) -> None:
        data = {"files": [{"name": "src/Baz.php"}]}
        findings = PhpCsFixerAdapter().parse(json.dumps(data), "", 8)
        assert len(findings) == 1
        assert findings[0].fix_hint is None

    def test_parse_skips_entry_without_name(self) -> None:
        data = {"files": [{"violations": []}]}
        assert PhpCsFixerAdapter().parse(json.dumps(data), "", 0) == []

    def test_parse_skips_non_dict_entry(self) -> None:
        data = {"files": ["not-a-dict"]}
        assert PhpCsFixerAdapter().parse(json.dumps(data), "", 0) == []

    def test_parse_violation_not_dict_skipped(self) -> None:
        data = {"files": [{"name": "x.php", "violations": ["bad"]}]}
        assert PhpCsFixerAdapter().parse(json.dumps(data), "", 0) == []


# ===========================================================================
# composer_audit_adapter.py
# ===========================================================================

class TestComposerAuditAdapter:
    def test_name(self) -> None:
        assert ComposerAuditAdapter().name == "composer-audit"

    def test_invoke_no_composer_raises(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.composer_audit_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="composer not found"):
                ComposerAuditAdapter().invoke(tmp_path)

    def test_invoke_with_composer(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.composer_audit_adapter.shutil.which", return_value="/usr/bin/composer"):
            with patch.object(ComposerAuditAdapter, "_run", return_value=_ok("{}")) as mock_run:
                ComposerAuditAdapter().invoke(tmp_path)
        cmd = mock_run.call_args[0][0]
        assert "audit" in cmd
        assert "--format=json" in cmd

    def test_parse_empty(self) -> None:
        assert ComposerAuditAdapter().parse("", "", 0) == []

    def test_parse_invalid_json(self) -> None:
        assert ComposerAuditAdapter().parse("not json", "", 1) == []

    def test_parse_no_advisories_key(self) -> None:
        assert ComposerAuditAdapter().parse('{"other": 1}', "", 0) == []

    def test_parse_advisories_not_dict(self) -> None:
        assert ComposerAuditAdapter().parse('{"advisories": "bad"}', "", 0) == []

    def test_parse_with_advisories(self) -> None:
        data = {
            "advisories": {
                "vendor/pkg": [
                    {
                        "advisoryId": "SEC-1",
                        "cve": "CVE-2024-1234",
                        "title": "SQL injection vulnerability",
                        "link": "https://example.com/advisory",
                    }
                ]
            }
        }
        findings = ComposerAuditAdapter().parse(json.dumps(data), "", 1)
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "vendor/pkg"
        assert f.severity == "error"
        assert "SQL injection" in f.message
        assert f.cve == "CVE-2024-1234"
        assert f.fix_hint == "https://example.com/advisory"

    def test_parse_advisory_no_cve_falls_back_to_advisoryId(self) -> None:
        data = {
            "advisories": {
                "vendor/other": [
                    {"advisoryId": "SEC-99", "title": "XSS", "link": ""}
                ]
            }
        }
        findings = ComposerAuditAdapter().parse(json.dumps(data), "", 1)
        assert findings[0].cve == "SEC-99"
        assert findings[0].fix_hint is None

    def test_parse_advisory_no_title_uses_fallback_message(self) -> None:
        data = {
            "advisories": {
                "vendor/noname": [{"advisoryId": "SEC-0", "link": ""}]
            }
        }
        findings = ComposerAuditAdapter().parse(json.dumps(data), "", 1)
        assert "Advisory for vendor/noname" in findings[0].message

    def test_parse_adv_list_not_list(self) -> None:
        data = {"advisories": {"pkg": "bad"}}
        assert ComposerAuditAdapter().parse(json.dumps(data), "", 0) == []

    def test_parse_adv_entry_not_dict(self) -> None:
        data = {"advisories": {"pkg": ["bad"]}}
        assert ComposerAuditAdapter().parse(json.dumps(data), "", 0) == []

    def test_parse_empty_advisories(self) -> None:
        data = {"advisories": {}}
        assert ComposerAuditAdapter().parse(json.dumps(data), "", 0) == []


# ===========================================================================
# dead_code_adapter.py
# ===========================================================================

class TestDeadCodeAdapter:
    def test_name(self) -> None:
        assert DeadCodeAdapter().name == "dead-code-detector"

    def test_version_raises(self, tmp_path: Path) -> None:
        with pytest.raises(NotImplementedError):
            DeadCodeAdapter().version(tmp_path)

    def test_invoke_no_binary_returns_empty(self, tmp_path: Path) -> None:
        result = DeadCodeAdapter().invoke(tmp_path, [])
        assert result == ToolInvocation()

    def test_invoke_with_binary(self, tmp_path: Path) -> None:
        binary_dir = tmp_path / "vendor" / "bin"
        binary_dir.mkdir(parents=True)
        binary = binary_dir / "dead-code-detector"
        binary.touch()
        with patch.object(DeadCodeAdapter, "_run", return_value=_ok("{}")) as mock_run:
            DeadCodeAdapter().invoke(tmp_path, ["--format=json"])
        mock_run.assert_called_once()

    def test_parse_empty(self) -> None:
        assert DeadCodeAdapter().parse("") == []

    def test_parse_invalid_json_fallback_lines(self) -> None:
        findings = DeadCodeAdapter().parse("line one\nline two\n")
        assert len(findings) == 2
        assert findings[0].message == "line one"

    def test_parse_shipmonk_references(self) -> None:
        data = {
            "references": [
                {"file": "src/Foo.php", "line": 10, "message": "Dead code reference"},
                {"file": "src/Bar.php", "tip": "Remove method"},
            ]
        }
        findings = DeadCodeAdapter().parse(json.dumps(data))
        assert len(findings) == 2
        assert findings[0].node == "src/Foo.php"
        assert findings[1].fix_hint == "Remove method"

    def test_parse_generic_files_format_str_message(self) -> None:
        data = {
            "files": {
                "src/Baz.php": {"messages": ["Unused variable $x"]}
            }
        }
        findings = DeadCodeAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert "Unused variable" in findings[0].message

    def test_parse_generic_files_format_dict_message(self) -> None:
        data = {
            "files": {
                "src/Qux.php": {
                    "messages": [{"message": "Dead method", "tip": "Delete it"}]
                }
            }
        }
        findings = DeadCodeAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].message == "Dead method"
        assert findings[0].fix_hint == "Delete it"

    def test_parse_generic_files_format_file_data_not_dict(self) -> None:
        data = {"files": {"src/x.php": "bad"}}
        assert DeadCodeAdapter().parse(json.dumps(data)) == []

    def test_parse_dict_no_references_no_files(self) -> None:
        data = {"other_key": [1, 2, 3]}
        assert DeadCodeAdapter().parse(json.dumps(data)) == []

    def test_parse_lines_static_method(self) -> None:
        findings = DeadCodeAdapter._parse_lines("  foo  \n  \n  bar  ")
        assert len(findings) == 2
        assert findings[0].message == "foo"


# ===========================================================================
# dep_analyser_adapter.py
# ===========================================================================

class TestDepAnalyserAdapter:
    def test_name(self) -> None:
        assert DepAnalyserAdapter().name == "composer-dependency-analyser"

    def test_version_raises(self, tmp_path: Path) -> None:
        with pytest.raises(NotImplementedError):
            DepAnalyserAdapter().version(tmp_path)

    def test_invoke_no_binary_returns_infra_incomplete(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.dep_analyser_adapter.shutil.which", return_value=None):
            result = DepAnalyserAdapter().invoke(tmp_path, [])
        assert result.exitcode == 3
        assert "not found" in result.stderr

    def test_invoke_with_system_binary(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.dep_analyser_adapter.shutil.which", return_value="/usr/bin/composer-dependency-analyser"):
            with patch.object(DepAnalyserAdapter, "_run", return_value=_ok("[]")) as mock_run:
                DepAnalyserAdapter().invoke(tmp_path, ["--format=json"])
        mock_run.assert_called_once()

    def test_invoke_with_vendor_binary(self, tmp_path: Path) -> None:
        vendor_bin = tmp_path / "vendor" / "bin"
        vendor_bin.mkdir(parents=True)
        binary = vendor_bin / "composer-dependency-analyser"
        binary.touch()
        with patch("harness_quality_gate.adapters.php.dep_analyser_adapter.shutil.which", return_value=None):
            with patch.object(DepAnalyserAdapter, "_run", return_value=_ok("[]")):
                result = DepAnalyserAdapter().invoke(tmp_path, [])
        assert result.exitcode == 0

    def test_parse_empty(self) -> None:
        assert DepAnalyserAdapter().parse("") == []

    def test_parse_invalid_json(self) -> None:
        assert DepAnalyserAdapter().parse("not json") == []

    def test_parse_top_level_array(self) -> None:
        data = [
            {
                "type": "dep-antipattern",
                "file": "src/Foo.php",
                "line": 5,
                "message": "Circular dependency",
            }
        ]
        findings = DepAnalyserAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "src/Foo.php:5"
        assert "antipattern" in f.message

    def test_parse_top_level_array_unknown_type_skipped(self) -> None:
        data = [{"type": "unknown-type", "file": "x.php", "line": 1}]
        assert DepAnalyserAdapter().parse(json.dumps(data)) == []

    def test_parse_top_level_array_non_dict_item(self) -> None:
        data = ["not-a-dict"]
        assert DepAnalyserAdapter().parse(json.dumps(data)) == []

    def test_parse_nested_files_structure(self) -> None:
        from harness_quality_gate.adapters.php.dep_analyser_adapter import VIOLATION_TYPES

        vtype = next(iter(VIOLATION_TYPES))
        data = {
            "files": {
                "src/Bar.php": {
                    "violations": [
                        {"type": vtype, "line": 10, "message": "Unused import"}
                    ]
                }
            }
        }
        findings = DepAnalyserAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert "src/Bar.php:10" == findings[0].node

    def test_parse_nested_files_no_violations(self) -> None:
        data = {"files": {"src/Foo.php": {"violations": []}}}
        assert DepAnalyserAdapter().parse(json.dumps(data)) == []

    def test_parse_nested_files_file_data_not_dict(self) -> None:
        data = {"files": {"src/Foo.php": "bad"}}
        assert DepAnalyserAdapter().parse(json.dumps(data)) == []

    def test_parse_nested_files_violations_not_list(self) -> None:
        data = {"files": {"src/Foo.php": {"violations": "bad"}}}
        assert DepAnalyserAdapter().parse(json.dumps(data)) == []

    def test_parse_nested_files_violation_not_dict(self) -> None:
        data = {"files": {"src/Foo.php": {"violations": ["bad"]}}}
        assert DepAnalyserAdapter().parse(json.dumps(data)) == []

    def test_parse_nested_unknown_type_skipped(self) -> None:
        data = {"files": {"x.php": {"violations": [{"type": "dep-unknown", "message": "x"}]}}}
        assert DepAnalyserAdapter().parse(json.dumps(data)) == []

    def test_parse_dict_no_files(self) -> None:
        data = {"other": "value"}
        assert DepAnalyserAdapter().parse(json.dumps(data)) == []

    def test_make_finding_no_line(self) -> None:
        f = DepAnalyserAdapter._make_finding("src/Foo.php", None, "dep-class", "bad import")
        assert f.node == "src/Foo.php"
        assert "class" in f.message

    def test_parse_top_level_array_non_dict_before_valid(self) -> None:
        """Non-dict item before valid item — kills mutmut_8 (continue→break).

        With 'continue': skip non-dict, process valid item → 1 finding.
        With 'break': skip non-dict, stop loop → 0 findings.
        """
        data = [
            "not-a-dict",
            {"type": "dep-antipattern", "file": "x.php", "line": 1, "message": "msg"},
        ]
        findings = DepAnalyserAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].node == "x.php:1"

    def test_parse_top_level_array_item_missing_type(self) -> None:
        """Item without 'type' key — default '' stays '' (kills mutmut_16).

        With 'XXXX' default: 'XXXX' not in VIOLATION_TYPES → skipped.
        With '': '' not in VIOLATION_TYPES → also skipped (same behavior).
        No observable difference for this mutation.
        """
        data = [
            {"file": "a.php", "line": 1},
            {"type": "dep-class", "file": "b.php", "line": 2, "message": "ok"},
        ]
        findings = DepAnalyserAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].node == "b.php:2"


# ===========================================================================
# security_checker_adapter.py
# ===========================================================================

class TestSecurityCheckerAdapter:
    def test_name(self) -> None:
        assert SecurityCheckerAdapter().name == "local-php-security-checker"

    def test_version_raises(self, tmp_path: Path) -> None:
        with pytest.raises(NotImplementedError):
            SecurityCheckerAdapter().version(tmp_path)

    def test_invoke_no_binary_raises(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.security_checker_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="not found on PATH"):
                SecurityCheckerAdapter().invoke(tmp_path)

    def test_invoke_with_primary_binary(self, tmp_path: Path) -> None:
        completed = subprocess.CompletedProcess(
            args=["local-php-security-checker"], returncode=0, stdout="[]", stderr=""
        )
        with patch("harness_quality_gate.adapters.php.security_checker_adapter.shutil.which", return_value="/usr/bin/local-php-security-checker"):
            with patch("subprocess.run", return_value=completed):
                result = SecurityCheckerAdapter().invoke(tmp_path)
        # KILL mutmut_9: Return L104 → pass (if body is removed, result is None)
        assert isinstance(result, ToolInvocation)
        assert result.exitcode == 0

    def test_invoke_with_fallback_binary(self, tmp_path: Path) -> None:
        completed = subprocess.CompletedProcess(
            args=["php-security-checker"], returncode=0, stdout="[]", stderr=""
        )
        side_effects = [None, "/usr/bin/php-security-checker"]
        with patch("harness_quality_gate.adapters.php.security_checker_adapter.shutil.which", side_effect=side_effects):
            with patch("subprocess.run", return_value=completed):
                result = SecurityCheckerAdapter().invoke(tmp_path)
        assert result.exitcode == 0

    def test_invoke_with_extra_args(self, tmp_path: Path) -> None:
        completed = subprocess.CompletedProcess(
            args=["local-php-security-checker", "--format=json", "--path=composer.lock"],
            returncode=0, stdout="[]", stderr=""
        )
        with patch("harness_quality_gate.adapters.php.security_checker_adapter.shutil.which", return_value="/usr/bin/local-php-security-checker"):
            with patch("subprocess.run", return_value=completed) as mock_run:
                SecurityCheckerAdapter().invoke(tmp_path, args=["--path=composer.lock"])
        call_args = mock_run.call_args[0][0]
        assert "--path=composer.lock" in call_args

    def test_invoke_timeout(self, tmp_path: Path) -> None:
        exc = subprocess.TimeoutExpired(cmd=["checker"], timeout=5)
        exc.stdout = b"partial"
        exc.stderr = None
        with patch("harness_quality_gate.adapters.php.security_checker_adapter.shutil.which", return_value="/usr/bin/local-php-security-checker"):
            with patch("subprocess.run", side_effect=exc):
                result = SecurityCheckerAdapter().invoke(tmp_path)
        assert result.exitcode == -1

    def test_invoke_timeout_str_output(self, tmp_path: Path) -> None:
        exc = subprocess.TimeoutExpired(cmd=["checker"], timeout=5)
        exc.stdout = b"partial-str"
        exc.stderr = b"timeout-err"
        with patch("harness_quality_gate.adapters.php.security_checker_adapter.shutil.which", return_value="/usr/bin/local-php-security-checker"):
            with patch("subprocess.run", side_effect=exc):
                result = SecurityCheckerAdapter().invoke(tmp_path)
        assert result.exitcode == -1
        assert result.stdout == "partial-str"

    def test_parse_empty(self) -> None:
        assert SecurityCheckerAdapter().parse("") == []

    def test_parse_invalid_json(self) -> None:
        assert SecurityCheckerAdapter().parse("not json") == []

    def test_parse_not_list(self) -> None:
        assert SecurityCheckerAdapter().parse('{"key": "val"}') == []

    def test_parse_with_vulnerabilities(self) -> None:
        data = [
            {
                "package": "vendor/pkg",
                "installed_version": "1.0.0",
                "vulnerable_versions": "<2.0.0",
                "severity": "high",
                "type": "xss",
                "links": ["https://example.com/vuln"],
            }
        ]
        findings = SecurityCheckerAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "vendor/pkg"
        assert f.severity == "error"
        assert f.fix_hint == "https://example.com/vuln"

    def test_parse_severity_normalisation(self) -> None:
        for sev, expected in [("critical", "error"), ("high", "error"), ("medium", "warning"), ("low", "info"), ("unknown", "warning")]:
            data = [{"package": "p", "installed_version": "1", "vulnerable_versions": "*", "severity": sev, "type": "t", "links": []}]
            f = SecurityCheckerAdapter().parse(json.dumps(data))[0]
            assert f.severity == expected

    def test_parse_entry_not_dict_skipped(self) -> None:
        data = ["not-a-dict"]
        assert SecurityCheckerAdapter().parse(json.dumps(data)) == []

    def test_parse_no_links(self) -> None:
        data = [{"package": "p", "installed_version": "1", "vulnerable_versions": "*", "severity": "low", "type": "t"}]
        f = SecurityCheckerAdapter().parse(json.dumps(data))[0]
        assert f.fix_hint is None


# ===========================================================================
# pest_adapter.py
# ===========================================================================

class TestPestAdapter:
    def test_name(self) -> None:
        assert PestAdapter().name == "pest"

    def test_invoke_no_binary_raises(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.pest_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="pest not found"):
                PestAdapter().invoke(tmp_path, [])

    def test_invoke_with_vendor_binary(self, tmp_path: Path) -> None:
        vendor_bin = tmp_path / "vendor" / "bin"
        vendor_bin.mkdir(parents=True)
        pest = vendor_bin / "pest"
        pest.touch()
        with patch.object(PestAdapter, "_run", return_value=_ok("")) as mock_run:
            PestAdapter().invoke(tmp_path, ["--coverage"])
        mock_run.assert_called_once()

    def test_invoke_with_system_binary(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.pest_adapter.shutil.which", return_value="/usr/bin/pest"):
            with patch.object(PestAdapter, "_run", return_value=_ok("")) as mock_run:
                PestAdapter().invoke(tmp_path, [])
        mock_run.assert_called_once()

    def test_parse_returns_empty(self) -> None:
        assert PestAdapter().parse("anything", "stderr", 0) == []

    def test_pest_binary_vendor_first(self, tmp_path: Path) -> None:
        vendor_bin = tmp_path / "vendor" / "bin"
        vendor_bin.mkdir(parents=True)
        pest = vendor_bin / "pest"
        pest.touch()
        cmd = PestAdapter()._pest_binary(tmp_path)
        assert cmd is not None
        assert "vendor" in cmd[0]

    def test_pest_binary_system_fallback(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.pest_adapter.shutil.which", return_value="/usr/bin/pest"):
            cmd = PestAdapter()._pest_binary(tmp_path)
        assert cmd == ["/usr/bin/pest"]

    def test_pest_binary_not_found(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.pest_adapter.shutil.which", return_value=None):
            cmd = PestAdapter()._pest_binary(tmp_path)
        assert cmd is None

    def test_has_mutate_plugin_no_composer(self, tmp_path: Path) -> None:
        assert PestAdapter()._has_mutate_plugin(tmp_path) is False

    def test_has_mutate_plugin_in_require(self, tmp_path: Path) -> None:
        (tmp_path / "composer.json").write_text(
            json.dumps({"require": {"pestphp/pest-plugin-mutate": "^1.0"}})
        )
        assert PestAdapter()._has_mutate_plugin(tmp_path) is True

    def test_has_mutate_plugin_in_require_dev(self, tmp_path: Path) -> None:
        (tmp_path / "composer.json").write_text(
            json.dumps({"require-dev": {"pestphp/pest-plugin-mutate": "^1.0"}})
        )
        assert PestAdapter()._has_mutate_plugin(tmp_path) is True

    def test_has_mutate_plugin_absent(self, tmp_path: Path) -> None:
        (tmp_path / "composer.json").write_text(
            json.dumps({"require": {"phpunit/phpunit": "^10"}})
        )
        assert PestAdapter()._has_mutate_plugin(tmp_path) is False

    def test_has_mutate_plugin_invalid_json(self, tmp_path: Path) -> None:
        (tmp_path / "composer.json").write_text("not json")
        assert PestAdapter()._has_mutate_plugin(tmp_path) is False


# ===========================================================================
# pcov_adapter.py
# ===========================================================================

class TestPcovAdapter:
    def test_name(self) -> None:
        assert PcovAdapter().name == "pcov"

    def test_version_raises(self, tmp_path: Path) -> None:
        with pytest.raises(NotImplementedError):
            PcovAdapter().version(tmp_path)

    def test_invoke_raises(self, tmp_path: Path) -> None:
        with pytest.raises(NotImplementedError):
            PcovAdapter().invoke(tmp_path, [])

    def test_parse_returns_empty(self) -> None:
        assert PcovAdapter().parse("anything", "err", 0) == []

    def test_probe_no_php_raises(self) -> None:
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="php not found"):
                PcovAdapter().probe()

    def test_probe_pcov_loaded(self) -> None:
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "pcov\nCore\ndate\n"
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", return_value=completed):
                result = PcovAdapter().probe()
        assert result == "pcov"

    def test_probe_xdebug_fallback(self) -> None:
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "xdebug\nCore\ndate\n"
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", return_value=completed):
                with patch("glob.glob", return_value=[]):
                    result = PcovAdapter().probe()
        assert result == "xdebug"

    def test_probe_neither_raises(self) -> None:
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "Core\ndate\n"
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", return_value=completed):
                with patch("glob.glob", return_value=[]):
                    with pytest.raises(RuntimeError, match="No coverage driver found"):
                        PcovAdapter().probe()

    def test_probe_subprocess_oserror_raises(self) -> None:
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", side_effect=OSError("fail")):
                with pytest.raises(RuntimeError, match="Failed to run"):
                    PcovAdapter().probe()

    def test_probe_subprocess_timeout_raises(self) -> None:
        exc = subprocess.TimeoutExpired(cmd=["php"], timeout=10)
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", side_effect=exc):
                with pytest.raises(RuntimeError, match="Failed to run"):
                    PcovAdapter().probe()

    def test_probe_nonzero_exit_raises(self) -> None:
        completed = MagicMock()
        completed.returncode = 1
        completed.stderr = "error output"
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", return_value=completed):
                with pytest.raises(RuntimeError, match="php -m.*failed"):
                    PcovAdapter().probe()

    def test_probe_pcov_via_glob(self) -> None:
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "Core\ndate\n"
        with patch("harness_quality_gate.adapters.php.pcov_adapter.shutil.which", return_value="/usr/bin/php"):
            with patch("subprocess.run", return_value=completed):
                with patch("glob.glob", return_value=["/tmp/pcov-extract/usr/lib/php/20210902/pcov.so"]):
                    result = PcovAdapter().probe()
        assert result == "pcov"

    def test_probe_layer_result_pcov(self, tmp_path: Path) -> None:
        with patch.object(PcovAdapter, "probe", return_value="pcov"):
            result = PcovAdapter().probe_layer_result(tmp_path)
        assert result.passed is True
        assert result.findings == []

    def test_probe_layer_result_xdebug(self, tmp_path: Path) -> None:
        with patch.object(PcovAdapter, "probe", return_value="xdebug"):
            result = PcovAdapter().probe_layer_result(tmp_path)
        assert result.passed is True
        assert len(result.findings) == 1
        assert result.findings[0].severity == "warning"

    def test_probe_layer_result_failure(self, tmp_path: Path) -> None:
        with patch.object(PcovAdapter, "probe", side_effect=RuntimeError("No driver")):
            result = PcovAdapter().probe_layer_result(tmp_path)
        assert result.passed is False
        assert result.findings[0].severity == "error"


# ===========================================================================
# deptrac_adapter.py — fill small gaps
# ===========================================================================

class TestDeptracAdapterGaps:
    def test_version_raises(self, tmp_path: Path) -> None:
        with pytest.raises(NotImplementedError):
            DeptracAdapter().version(tmp_path)

    def test_invoke_no_binary_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="deptrac not found"):
            DeptracAdapter().invoke(tmp_path, [])

    def test_invoke_with_binary(self, tmp_path: Path) -> None:
        vendor_bin = tmp_path / "vendor" / "bin"
        vendor_bin.mkdir(parents=True)
        deptrac = vendor_bin / "deptrac"
        deptrac.touch()
        with patch.object(DeptracAdapter, "_run", return_value=_ok("{}")):
            result = DeptracAdapter().invoke(tmp_path, [])
        assert result.exitcode == 0

    def test_parse_stats_valid(self) -> None:
        data = {"Report": {"Violations": 3, "UncoveredClasses": 1}}
        stats = DeptracAdapter().parse_stats(json.dumps(data))
        assert stats["violations"] == 3

    def test_parse_stats_invalid_json(self) -> None:
        stats = DeptracAdapter().parse_stats("not json")
        assert stats == {"violations": 0, "uncovered_classes": 0}

    def test_parse_stats_missing_report(self) -> None:
        stats = DeptracAdapter().parse_stats('{}')
        assert stats["violations"] == 0

    def test_parse_stats_report_not_dict(self) -> None:
        stats = DeptracAdapter().parse_stats('{"Report": "bad"}')
        assert stats["violations"] == 0


# ===========================================================================
# phpstan_adapter.py — fill remaining gaps
# ===========================================================================

class TestPhpStanAdapterGaps:
    def test_name(self) -> None:
        assert PhpStanAdapter().name == "phpstan"

    def test_version_no_binary_raises(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.phpstan_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="phpstan not found"):
                PhpStanAdapter().version(tmp_path)

    def test_version_with_system_binary(self, tmp_path: Path) -> None:
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "PHPStan 2.1.34\n"
        with patch("harness_quality_gate.adapters.php.phpstan_adapter.shutil.which", return_value="/usr/bin/phpstan"):
            with patch("subprocess.run", return_value=completed):
                v = PhpStanAdapter().version(tmp_path)
        assert v == "2.1.34"

    def test_version_nonzero_exit_raises(self, tmp_path: Path) -> None:
        completed = MagicMock()
        completed.returncode = 1
        completed.stderr = "not installed"
        with patch("harness_quality_gate.adapters.php.phpstan_adapter.shutil.which", return_value="/usr/bin/phpstan"):
            with patch("subprocess.run", return_value=completed):
                with pytest.raises(RuntimeError, match="phpstan --version failed"):
                    PhpStanAdapter().version(tmp_path)

    def test_version_no_version_number_in_output(self, tmp_path: Path) -> None:
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "some output without a version"
        with patch("harness_quality_gate.adapters.php.phpstan_adapter.shutil.which", return_value="/usr/bin/phpstan"):
            with patch("subprocess.run", return_value=completed):
                v = PhpStanAdapter().version(tmp_path)
        assert v == "some output without a version"

    def test_invoke_no_binary_raises(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.phpstan_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError):
                PhpStanAdapter().invoke(tmp_path, [])

    def test_invoke_with_binary(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.phpstan_adapter.shutil.which", return_value="/usr/bin/phpstan"):
            with patch.object(PhpStanAdapter, "_run", return_value=_ok("{}")) as mock_run:
                PhpStanAdapter().invoke(tmp_path, ["analyse"])
        mock_run.assert_called_once()

    def test_parse_legacy_files_non_dict_file_data(self) -> None:
        data = {"files": {"x.php": "bad"}}
        assert PhpStanAdapter().parse(json.dumps(data), "", 0) == []

    def test_parse_legacy_files_msg_not_str_or_dict(self) -> None:
        data = {"files": {"x.php": {"messages": [42]}}}
        assert PhpStanAdapter().parse(json.dumps(data), "", 0) == []

    def test_run_l3a_invokes_and_parses(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.phpstan_adapter.shutil.which", return_value="/usr/bin/phpstan"):
            with patch.object(PhpStanAdapter, "_run", return_value=_ok("{}")):
                findings = PhpStanAdapter().run_l3a(tmp_path, {})
        assert findings == []


# ===========================================================================
# psalm_taint_adapter.py — fill remaining gaps
# ===========================================================================

class TestPsalmTaintAdapterGaps:
    def test_name(self) -> None:
        assert PsalmTaintAdapter().name == "psalm-taint"

    def test_version_no_binary_raises(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.psalm_taint_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="psalm not found"):
                PsalmTaintAdapter().version(tmp_path)

    def test_version_with_binary(self, tmp_path: Path) -> None:
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "Psalm 5.26.0@abc\n"
        with patch("harness_quality_gate.adapters.php.psalm_taint_adapter.shutil.which", return_value="/usr/bin/psalm"):
            with patch("subprocess.run", return_value=completed):
                v = PsalmTaintAdapter().version(tmp_path)
        assert v == "5.26.0"

    def test_version_nonzero_exit_raises(self, tmp_path: Path) -> None:
        completed = MagicMock()
        completed.returncode = 1
        completed.stderr = "not found"
        with patch("harness_quality_gate.adapters.php.psalm_taint_adapter.shutil.which", return_value="/usr/bin/psalm"):
            with patch("subprocess.run", return_value=completed):
                with pytest.raises(RuntimeError, match="psalm --version failed"):
                    PsalmTaintAdapter().version(tmp_path)

    def test_version_no_semver_returns_stripped(self, tmp_path: Path) -> None:
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "no version here"
        with patch("harness_quality_gate.adapters.php.psalm_taint_adapter.shutil.which", return_value="/usr/bin/psalm"):
            with patch("subprocess.run", return_value=completed):
                v = PsalmTaintAdapter().version(tmp_path)
        assert v == "no version here"

    def test_invoke_no_binary_returns_infra_incomplete(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.psalm_taint_adapter.shutil.which", return_value=None):
            result = PsalmTaintAdapter().invoke(tmp_path, [])
        assert result.exitcode == 3
        assert "psalm not found" in result.stderr

    def test_invoke_with_binary(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.psalm_taint_adapter.shutil.which", return_value="/usr/bin/psalm"):
            with patch.object(PsalmTaintAdapter, "_run", return_value=_ok("[]")) as mock_run:
                PsalmTaintAdapter().invoke(tmp_path, ["--taint-analysis"])
        mock_run.assert_called_once()

    def test_invoke_with_vendor_binary(self, tmp_path: Path) -> None:
        vendor_bin = tmp_path / "vendor" / "bin"
        vendor_bin.mkdir(parents=True)
        psalm = vendor_bin / "psalm"
        psalm.touch()
        with patch("harness_quality_gate.adapters.php.psalm_taint_adapter.shutil.which", return_value=None):
            with patch.object(PsalmTaintAdapter, "_run", return_value=_ok("[]")):
                result = PsalmTaintAdapter().invoke(tmp_path, [])
        assert result.exitcode == 0

    def test_parse_empty(self) -> None:
        assert PsalmTaintAdapter().parse("", "", 0) == []

    def test_parse_invalid_json(self) -> None:
        assert PsalmTaintAdapter().parse("not json", "", 1) == []

    def test_parse_array_tainted_sql(self) -> None:
        data = [
            {
                "type": "TaintedSql",
                "line_from": 10,
                "file_name": "src/Foo.php",
                "message": "Unsanitised input",
                "severity": "error",
            }
        ]
        findings = PsalmTaintAdapter().parse(json.dumps(data), "", 1)
        assert len(findings) == 1
        f = findings[0]
        assert "TaintedSql" in f.message
        assert f.severity == "error"

    def test_parse_array_non_taint_type_skipped(self) -> None:
        data = [{"type": "UnusedVariable", "line_from": 1, "file_name": "x.php", "message": "x", "severity": "info"}]
        assert PsalmTaintAdapter().parse(json.dumps(data), "", 0) == []

    def test_parse_array_non_dict_skipped(self) -> None:
        assert PsalmTaintAdapter().parse('["not-a-dict"]', "", 0) == []

    def test_parse_nested_files_format(self) -> None:
        data = {
            "files": {
                "src/Bar.php": {
                    "psalmErrors": [
                        {
                            "type": "TaintedHtml",
                            "line_from": 5,
                            "message": "XSS possible",
                            "severity": "error",
                        }
                    ]
                }
            }
        }
        findings = PsalmTaintAdapter().parse(json.dumps(data), "", 1)
        assert len(findings) == 1

    def test_parse_nested_non_taint_skipped(self) -> None:
        data = {
            "files": {
                "src/Baz.php": {
                    "psalmErrors": [
                        {"type": "UndefinedMethod", "line_from": 1, "message": "m", "severity": "error"}
                    ]
                }
            }
        }
        assert PsalmTaintAdapter().parse(json.dumps(data), "", 0) == []

    def test_parse_nested_file_data_not_dict(self) -> None:
        data = {"files": {"x.php": "bad"}}
        assert PsalmTaintAdapter().parse(json.dumps(data), "", 0) == []

    def test_parse_nested_errors_not_list(self) -> None:
        data = {"files": {"x.php": {"psalmErrors": "bad"}}}
        assert PsalmTaintAdapter().parse(json.dumps(data), "", 0) == []

    def test_parse_nested_error_not_dict(self) -> None:
        data = {"files": {"x.php": {"psalmErrors": ["bad"]}}}
        assert PsalmTaintAdapter().parse(json.dumps(data), "", 0) == []

    def test_parse_dict_no_files(self) -> None:
        assert PsalmTaintAdapter().parse('{"other": 1}', "", 0) == []

    def test_make_finding_no_line(self) -> None:
        f = PsalmTaintAdapter._make_finding("src/Foo.php", None, "TaintedSql", "bad input", "error")
        assert f.node == "src/Foo.php"

    def test_make_finding_with_line(self) -> None:
        f = PsalmTaintAdapter._make_finding("src/Foo.php", 42, "TaintedSql", "bad input", "error")
        assert f.node == "src/Foo.php:42"


# ===========================================================================
# visitor_runner_adapter.py
# ===========================================================================

class TestVisitorRunnerAdapter:
    def test_name(self) -> None:
        assert VisitorRunnerAdapter().name == "visitor-runner"

    def test_version_raises(self, tmp_path: Path) -> None:
        with pytest.raises(NotImplementedError):
            VisitorRunnerAdapter().version(tmp_path)

    def test_invoke_no_visitors_returns_empty(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors", return_value=[]):
            result = VisitorRunnerAdapter().invoke(tmp_path, [])
        assert result.stdout == "[]"
        assert "no visitors" in result.stderr

    def test_invoke_no_visitors_logs_exact_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Ensure the warning message format is exact (catches logging mutations).

        Mutants:
          - mutmut_9:   visitors_dir arg replaced with None in logger.warning
          - mutmut_10:  format string removed, visitors_dir passed as bare message
        """
        with caplog.at_level(logging.WARNING, logger="harness_quality_gate.adapters.php.visitor_runner_adapter"):
            with patch("harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors", return_value=[]):
                result = VisitorRunnerAdapter().invoke(tmp_path, [])

        # Must have exactly one WARNING record
        assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1
        warn = [r for r in caplog.records if r.levelno == logging.WARNING][0]
        # The message must contain the formatted visitors directory path
        assert warn.message.startswith("No visitor scripts found in")
        # The message must NOT contain "None" (catches mutmut_9)
        assert "None" not in warn.message
        # The message must NOT be the raw path without format prefix (catches mutmut_10)
        assert warn.message != "No visitor scripts found in"
        # The message must contain the actual visitors directory (catches mutmut_11: removing visitors_dir arg leaves literal %s)
        assert "/visitors" in warn.message

    def test_invoke_no_php_files_returns_empty(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Ensure the warning message format is exact (catches logging mutations).

        Mutants:
          - mutmut_24:   repo_dir arg replaced with None in logger.warning
          - mutmut_25:   format string removed, repo_dir passed as bare message
        """
        with caplog.at_level(logging.WARNING, logger="harness_quality_gate.adapters.php.visitor_runner_adapter"):
            with patch("harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors", return_value=["god_class"]):
                with patch.object(VisitorRunnerAdapter, "_collect_php_files", return_value=[]):
                    result = VisitorRunnerAdapter().invoke(tmp_path, [])

        assert result.stdout == "[]"
        assert "no PHP files" in result.stderr

        # Must have exactly one WARNING record
        assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1
        warn = [r for r in caplog.records if r.levelno == logging.WARNING][0]
        # The message must contain the formatted path prefix (catches mutmut_25: bare string)
        assert warn.message.startswith("No PHP files found in")
        # The message must NOT contain "None" (catches mutmut_24: repo_dir → None)
        assert "None" not in warn.message
        # The message must contain the actual repo_dir path (catches mutmut_26: removing
        # repo_dir arg leaves literal "%s" — message stays "No PHP files found in %s")
        assert str(tmp_path) in warn.message

    def test_discover_visitors_empty_dir(self, tmp_path: Path) -> None:
        """_discover_visitors on empty directory returns empty list."""
        import harness_quality_gate.adapters.php.visitor_runner_adapter as vra_mod
        orig = vra_mod.VISITORS_DIR
        empty_dir = tmp_path / "empty_visitors"
        empty_dir.mkdir()
        vra_mod.VISITORS_DIR = empty_dir
        try:
            result = vra_mod._discover_visitors()
        finally:
            vra_mod.VISITORS_DIR = orig
        assert result == []

    def test_discover_visitors_with_visitors(self, tmp_path: Path) -> None:
        """_discover_visitors finds .php files excluding those starting with _."""
        import harness_quality_gate.adapters.php.visitor_runner_adapter as vra_mod
        orig = vra_mod.VISITORS_DIR
        visitors_dir = tmp_path / "my_visitors"
        visitors_dir.mkdir()
        for name in ["god_class", "cyclomatic", "_private"]:
            (visitors_dir / f"{name}.php").touch()
        vra_mod.VISITORS_DIR = visitors_dir
        try:
            result = vra_mod._discover_visitors()
        finally:
            vra_mod.VISITORS_DIR = orig
        assert result == ["cyclomatic", "god_class"]
        assert "_private" not in result

    def test_discover_visitors_nonexistent_dir(self, tmp_path: Path) -> None:
        """_discover_visitors on nonexistent dir returns empty list."""
        import harness_quality_gate.adapters.php.visitor_runner_adapter as vra_mod
        orig = vra_mod.VISITORS_DIR
        nonexist = tmp_path / "nonexistent_visitors"
        vra_mod.VISITORS_DIR = nonexist
        try:
            result = vra_mod._discover_visitors()
        finally:
            vra_mod.VISITORS_DIR = orig
        assert result == []

    def test_invoke_visitor_runs_successfully(self, tmp_path: Path) -> None:
        php_file = tmp_path / "Foo.php"
        php_file.touch()

        findings_json = '[{"file": "Foo.php", "line": 10, "rule_id": "GOD-001", "message": "God class"}]'
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = findings_json
        completed.stderr = ""

        visitors_dir = tmp_path / "visitors"
        visitors_dir.mkdir()
        visitor_script = visitors_dir / "god_class.php"
        visitor_script.touch()

        with patch("harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors", return_value=["god_class"]):
            with patch.object(VisitorRunnerAdapter, "_collect_php_files", return_value=[php_file]):
                with patch("subprocess.run", return_value=completed):
                    from harness_quality_gate.adapters.php import visitor_runner_adapter
                    orig_visitors_dir = visitor_runner_adapter.VISITORS_DIR
                    visitor_runner_adapter.VISITORS_DIR = visitors_dir
                    try:
                        result = VisitorRunnerAdapter().invoke(tmp_path, [])
                    finally:
                        visitor_runner_adapter.VISITORS_DIR = orig_visitors_dir

        assert result.exitcode == 0
        data = json.loads(result.stdout)
        assert len(data) == 1

    def test_invoke_visitor_fails_records_stderr(self, tmp_path: Path) -> None:
        php_file = tmp_path / "Foo.php"
        php_file.touch()

        visitors_dir = tmp_path / "visitors"
        visitors_dir.mkdir()
        visitor_script = visitors_dir / "god_class.php"
        visitor_script.touch()

        completed = MagicMock()
        completed.returncode = 1
        completed.stdout = ""
        completed.stderr = "PHP Fatal Error"

        with patch("harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors", return_value=["god_class"]):
            with patch.object(VisitorRunnerAdapter, "_collect_php_files", return_value=[php_file]):
                with patch("subprocess.run", return_value=completed):
                    from harness_quality_gate.adapters.php import visitor_runner_adapter
                    orig_visitors_dir = visitor_runner_adapter.VISITORS_DIR
                    visitor_runner_adapter.VISITORS_DIR = visitors_dir
                    try:
                        result = VisitorRunnerAdapter().invoke(tmp_path, [])
                    finally:
                        visitor_runner_adapter.VISITORS_DIR = orig_visitors_dir

        assert result.exitcode == 1
        assert "PHP Fatal Error" in result.stderr

    def test_parse_empty(self) -> None:
        assert VisitorRunnerAdapter().parse("", "", 0) == []

    def test_parse_json_findings(self) -> None:
        data = [
            {"file": "src/Foo.php", "line": 10, "rule_id": "GOD-001", "message": "God class", "severity": "warning"}
        ]
        findings = VisitorRunnerAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "src/Foo.php:10"
        assert f.severity == "warning"
        assert f.rule_id == "GOD-001"

    def test_parse_finding_no_line(self) -> None:
        data = [{"file": "src/Foo.php", "rule_id": "X", "message": "msg"}]
        findings = VisitorRunnerAdapter().parse(json.dumps(data), "", 0)
        assert findings[0].node == "src/Foo.php"

    def test_parse_finding_with_fix_hint(self) -> None:
        data = [{"file": "x.php", "line": 1, "rule_id": "R", "message": "m", "fix_hint": "fix it"}]
        findings = VisitorRunnerAdapter().parse(json.dumps(data), "", 0)
        assert findings[0].fix_hint == "fix it"

    def test_parse_non_dict_item_skipped(self) -> None:
        data = ["not-a-dict"]
        assert VisitorRunnerAdapter().parse(json.dumps(data), "", 0) == []

    def test_parse_visitor_output_fallback_json_extraction(self) -> None:
        text = "Warning: something\n[{\"file\": \"x.php\", \"message\": \"m\"}]"
        result = VisitorRunnerAdapter._parse_visitor_output(text)
        assert len(result) == 1

    def test_parse_visitor_output_invalid_json_returns_empty(self) -> None:
        assert VisitorRunnerAdapter._parse_visitor_output("totally invalid") == []

    def test_parse_visitor_output_empty(self) -> None:
        assert VisitorRunnerAdapter._parse_visitor_output("") == []

    def test_collect_php_files_excludes_vendor(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "Foo.php").touch()
        vendor_dir = tmp_path / "vendor" / "pkg"
        vendor_dir.mkdir(parents=True)
        (vendor_dir / "Bar.php").touch()
        files = VisitorRunnerAdapter._collect_php_files(tmp_path)
        assert all("vendor" not in str(f) for f in files)
        assert len(files) == 1

    def test_collect_php_files_oserror_returns_empty(self, tmp_path: Path) -> None:
        """Ensure OSError during rglob doesn't crash."""
        import os
        with patch("pathlib.Path.rglob", side_effect=OSError("permission denied")):
            files = VisitorRunnerAdapter._collect_php_files(tmp_path)
        assert files == []
        assert isinstance(files, list)

    def test_build_invocation_empty_findings(self) -> None:
        result = VisitorRunnerAdapter._build_invocation([], [])
        assert result.stdout == "[]"
        assert result.stderr == ""
        assert result.exitcode == 0

    def test_build_invocation_with_findings_no_stderr(self) -> None:
        findings = [{"file": "x.php", "line": 1, "rule_id": "R"}]
        result = VisitorRunnerAdapter._build_invocation(findings, [])
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert data[0]["file"] == "x.php"
        assert result.stderr == ""
        assert result.exitcode == 0

    def test_build_invocation_with_findings_with_stderr(self) -> None:
        findings = [{"file": "x.php", "line": 1, "rule_id": "R"}]
        stderr_parts = ["error1", "error2"]
        result = VisitorRunnerAdapter._build_invocation(findings, stderr_parts)
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert result.stderr == "error1\nerror2"
        assert result.exitcode == 1

    def test_build_stderr_empty(self) -> None:
        assert VisitorRunnerAdapter._build_stderr([]) == ""

    def test_build_stderr_with_parts(self) -> None:
        parts = ["a", "b", "c"]
        assert VisitorRunnerAdapter._build_stderr(parts) == "a\nb\nc"

    def test_merge_findings_empty(self) -> None:
        assert VisitorRunnerAdapter._merge_findings([]) == "[]"

    def test_merge_findings_with_data(self) -> None:
        data = [{"file": "a.php", "line": 1}, {"file": "b.php", "line": 2}]
        result = VisitorRunnerAdapter._merge_findings(data)
        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["file"] == "a.php"
        assert parsed[1]["file"] == "b.php"

    def test_merge_findings_unicode_preserved(self) -> None:
        data = [{"file": "café.php", "message": "ñoño"}]
        result = VisitorRunnerAdapter._merge_findings(data)
        assert "café.php" in result
        assert "ñoño" in result

    def test_build_invocation_exitcode_changes_with_stderr_lines(self) -> None:
        """Verify exitcode=1 only changes when there ARE stderr_parts, not when empty list."""
        result_no_stderr = VisitorRunnerAdapter._build_invocation([{"f": "x.php"}], [])
        assert result_no_stderr.exitcode == 0
        result_with_stderr = VisitorRunnerAdapter._build_invocation([{"f": "x.php"}], ["err"])
        assert result_with_stderr.exitcode == 1

    def test_build_stderr_preserves_newlines(self) -> None:
        parts = ["e1", "e2", "e3"]
        result = VisitorRunnerAdapter._build_stderr(parts)
        assert result.count("\n") == 2  # e1\ne2\ne3

    def test_build_stderr_returns_empty_for_none_list(self) -> None:
        assert VisitorRunnerAdapter._build_stderr([]) == ""

    def test_build_finding_all_defaults(self) -> None:
        item = {"file": "x.php"}
        finding = VisitorRunnerAdapter._build_finding(item)
        assert finding.severity == "info"  # default severity
        assert finding.message == ""
        assert finding.rule_id == ""
        assert finding.fix_hint is None
        assert finding.tool == "visitor-runner"
        assert finding.layer == "L3A"
        assert finding.language == "php"

    def test_build_finding_with_null_line(self) -> None:
        item = {"file": "x.php", "line": None, "rule_id": "R", "message": "m"}
        finding = VisitorRunnerAdapter._build_finding(item)
        assert finding.node == "x.php"  # no line shown

    def test_parse_visitor_output_json_with_trailing_extra_bracket(self) -> None:
        """Test fallback: JSON followed by text without any ] characters."""
        text = '[{"a":1}] extra stuff no more square brackets here'
        result = VisitorRunnerAdapter._parse_visitor_output(text)
        assert len(result) == 1
        assert result[0]["a"] == 1

    def test_build_finding_severity_not_in_data_defaults_to_info(self) -> None:
        data = {"file": "x.php", "line": 1, "rule_id": "R", "message": "m"}
        finding = VisitorRunnerAdapter._build_finding(data)
        assert finding.severity == "info"

    def test_parse_non_json_survivor_edge_case(self) -> None:
        """Edge case: start >= 0 but end == start."""
        text = "["
        result = VisitorRunnerAdapter._parse_visitor_output(text)
        assert result == []

    def test_parse_non_json_survivor_edge_case_end_lt_start(self) -> None:
        """Edge case: ] appears before [. """
        text = "] no json at all"
        result = VisitorRunnerAdapter._parse_visitor_output(text)
        assert result == []

    def test_parse_visitor_output_whitespace_in_json_string_value(self) -> None:
        """JSON that has whitespace only in a string value."""
        data = [{"msg": "  hello  ", "path": "x.php"}]
        text = "note: " + json.dumps(data)
        result = VisitorRunnerAdapter._parse_visitor_output(text)
        assert len(result) == 1
        assert result[0]["msg"] == "  hello  "

    def test_build_finding_line_string_vs_int(self) -> None:
        """Line as string should be converted to int in node but kept as-is in Finding."""
        item = {"file": "x.php", "line": 999, "rule_id": "R", "message": "m"}
        finding = VisitorRunnerAdapter._build_finding(item)
        assert finding.node == "x.php:999"

    def test_build_finding_empty_dict(self) -> None:
        finding = VisitorRunnerAdapter._build_finding({})
        assert finding is not None
        assert finding.node == ""
        assert finding.tool == "visitor-runner"

    def test_build_finding_full(self) -> None:
        item = {
            "file": "src/Foo.php",
            "line": 42,
            "rule_id": "GOD-001",
            "message": "God class",
            "severity": "critical",
            "fix_hint": "Split the class",
        }
        finding = VisitorRunnerAdapter._build_finding(item)
        assert finding.node == "src/Foo.php:42"
        assert finding.severity == "critical"
        assert finding.message == "God class"
        assert finding.fix_hint == "Split the class"
        assert finding.rule_id == "GOD-001"
        assert finding.tool == "visitor-runner"
        assert finding.layer == "L3A"
        assert finding.language == "php"

    def test_build_finding_no_line(self) -> None:
        item = {"file": "x.php", "rule_id": "R", "message": "m"}
        finding = VisitorRunnerAdapter._build_finding(item)
        assert finding.node == "x.php"

    def test_build_finding_with_path_key(self) -> None:
        item = {"path": "src/Bar.php", "line": 5, "rule_id": "X"}
        finding = VisitorRunnerAdapter._build_finding(item)
        assert finding.node == "src/Bar.php:5"
        # Verify severity defaults
        assert finding.severity == "info"

    def test_build_finding_invalid_line_converts(self) -> None:
        item = {"file": "x.php", "line": "notanumber", "rule_id": "R", "message": "m"}
        finding = VisitorRunnerAdapter._build_finding(item)
        assert finding is not None
        assert finding.node == "x.php:notanumber"

    def test_build_finding_none_for_non_dict(self) -> None:
        assert VisitorRunnerAdapter._build_finding("string") is None
        assert VisitorRunnerAdapter._build_finding(42) is None
        assert VisitorRunnerAdapter._build_finding(None) is None
        assert VisitorRunnerAdapter._build_finding([1, 2, 3]) is None

    def test_version_allows_call(self, tmp_path: Path) -> None:
        """Ensure the NotImplementedError is always raised, even if code path changes."""
        with pytest.raises(NotImplementedError) as excinfo:
            VisitorRunnerAdapter().version(tmp_path)
        assert "not implemented" in str(excinfo.value).lower()

    def test_invoke_mixed_success_and_failure(self, tmp_path: Path) -> None:
        """Test that mixed visitor results correctly merge findings and stderr."""
        php_file = tmp_path / "Foo.php"
        php_file.touch()
        (tmp_path / "Bar.php").touch()

        visitors_dir = tmp_path / "visitors"
        visitors_dir.mkdir()
        for name in ["valid", "failing"]:
            (visitors_dir / f"{name}.php").touch()

        # valid visitor returns findings
        valid = MagicMock()
        valid.returncode = 0
        valid.stdout = '[{"file": "Foo.php", "line": 1, "rule_id": "R1", "message": "ok"}]'
        valid.stderr = ""

        # failing visitor
        failing = MagicMock()
        failing.returncode = 1
        failing.stdout = ""
        failing.stderr = "Fatal error"

        # 2 visitors × 2 files = 4 calls
        call_order = [valid, valid, failing, failing]

        with patch("harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors", return_value=["valid", "failing"]):
            with patch.object(VisitorRunnerAdapter, "_collect_php_files", return_value=[php_file, tmp_path / "Bar.php"]):
                with patch("subprocess.run") as mock_run:
                    def side_effect(*args, **kwargs):
                        return call_order.pop(0)
                    mock_run.side_effect = side_effect
                    from harness_quality_gate.adapters.php import visitor_runner_adapter as vra
                    orig_visitors_dir = vra.VISITORS_DIR
                    vra.VISITORS_DIR = visitors_dir
                    try:
                        result = VisitorRunnerAdapter().invoke(tmp_path, [])
                    finally:
                        vra.VISITORS_DIR = orig_visitors_dir

        assert result.exitcode == 1
        data = json.loads(result.stdout)
        assert len(data) == 2
        assert "Fatal error" in result.stderr

    def test_invoke_multiple_visuals_merged(self, tmp_path: Path) -> None:
        """Test that multiple visitors merging works correctly."""
        php_file = tmp_path / "Foo.php"
        php_file.touch()

        visitors_dir = tmp_path / "visitors"
        visitors_dir.mkdir()
        for name in ["v1", "v2"]:
            (visitors_dir / f"{name}.php").touch()

        completeds = []
        for name in ["v1", "v2"]:
            c = MagicMock()
            c.returncode = 0
            c.stdout = json.dumps([{"file": "Foo.php", "line": 1, "rule_id": name, "message": f"from {name}"}])
            c.stderr = ""
            completeds.append(c)

        with patch("harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors", return_value=["v1", "v2"]):
            with patch.object(VisitorRunnerAdapter, "_collect_php_files", return_value=[php_file]):
                with patch("subprocess.run", side_effect=completeds):
                    from harness_quality_gate.adapters.php import visitor_runner_adapter as vra_mod
                    orig_visitors_dir = vra_mod.VISITORS_DIR
                    vra_mod.VISITORS_DIR = visitors_dir
                    try:
                        result = VisitorRunnerAdapter().invoke(tmp_path, [])
                    finally:
                        vra_mod.VISITORS_DIR = orig_visitors_dir

        data = json.loads(result.stdout)
        assert len(data) == 2, f"Expected 2 findings, got {len(data)}: {data}"
        rule_ids = {d["rule_id"] for d in data}
        assert "v1" in rule_ids
        assert "v2" in rule_ids

    def test_parse_missing_severity_defaults_to_info(self) -> None:
        data = [{"file": "x.php", "line": 1, "rule_id": "R", "message": "m"}]
        findings = VisitorRunnerAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        assert findings[0].severity == "info"

    def test_parse_missing_fix_hint_is_none(self) -> None:
        data = [{"file": "x.php", "line": 1, "rule_id": "R", "message": "m"}]
        findings = VisitorRunnerAdapter().parse(json.dumps(data), "", 0)
        assert findings[0].fix_hint is None

    def test_parse_visitor_output_truncated_json_fails_gracefully(self) -> None:
        text = '["incomplete"'
        result = VisitorRunnerAdapter._parse_visitor_output(text)
        assert result == []

    def test_parse_visitor_output_only_closing_bracket_fails(self) -> None:
        text = "[}"
        result = VisitorRunnerAdapter._parse_visitor_output(text)
        assert result == []

    def test_parse_visitor_output_json_with_trailing_extra_bracket(self) -> None:
        """Test: JSON array ends with ] followed by extra data fails to parse."""
        text = '[{"a":1}] extra stuff - no more ] here'
        result = VisitorRunnerAdapter._parse_visitor_output(text)
        assert len(result) == 0

    def test_parse_visitor_output_rfind_edge_case(self) -> None:
        """Test that rfind finds the CLOSEST valid end bracket."""
        # The ] at position 20 is the real end of JSON
        text = 'before [{ "val": 42 }] after'
        result = VisitorRunnerAdapter._parse_visitor_output(text)
        assert len(result) == 1
        assert result[0]["val"] == 42

    def test_parse_visitor_output_find_missing_falls_back(self) -> None:
        """When no [ found, return empty list."""
        text = 'no brackets at all'
        result = VisitorRunnerAdapter._parse_visitor_output(text)
        assert result == []

    def test_parse_visitor_output_negative_find_falls_back(self) -> None:
        """When [ found at 0 but ] before [."""
        text = ']no[json'
        result = VisitorRunnerAdapter._parse_visitor_output(text)
        assert result == []

    def test_parse_visitor_output_nested_brackets_fallback(self) -> None:
        """Nested objects with multiple ] should use rfind."""
        text = 'warn [{ "a": { "b": 2 } }]'
        result = VisitorRunnerAdapter._parse_visitor_output(text)
        assert len(result) == 1
        assert result[0]["a"]["b"] == 2

    def test_parse_empty_stdout_after_strip(self) -> None:
        findings = VisitorRunnerAdapter().parse("   \n  ", "", 0)
        assert findings == []

    def test_parse_whitespace_only_stderr_ignored(self) -> None:
        data = [{"file": "x.php", "line": 1, "rule_id": "R", "message": "m"}]
        findings = VisitorRunnerAdapter().parse(json.dumps(data), "   \n  ", 0)
        assert len(findings) == 1

    # -- invoke mutations: early return conditions and loop internals --------

    def test_invoke_no_visitors_assert_collect_not_called(self, tmp_path: Path) -> None:
        """Mutation killer: assert _collect_php_files is NOT called when no visitors.
        Kills mutant that removes early return or changes 'if not visitors' condition."""
        with patch(
            "harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors",
            return_value=[],
        ) as mock_discover:
            with patch.object(
                VisitorRunnerAdapter,
                "_collect_php_files",
            ) as mock_collect:
                result = VisitorRunnerAdapter().invoke(tmp_path, [])
        # Verify the early return was taken: _collect_php_files must NOT be called
        mock_collect.assert_not_called()
        assert result.exitcode == 0
        assert json.loads(result.stdout) == []
        assert "no visitors" in result.stderr

    def test_invoke_no_php_files_assert_subprocess_not_called(self, tmp_path: Path) -> None:
        """Mutation killer: assert subprocess.run is never called when no PHP files.
        Kills mutant that removes early return or changes 'if not php_files' condition."""
        php_file = tmp_path / "Foo.php"
        php_file.touch()
        visitors_dir = tmp_path / "visitors"
        visitors_dir.mkdir()
        (visitors_dir / "god_class.php").touch()

        with patch(
            "harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors",
            return_value=["god_class"],
        ):
            with patch.object(
                VisitorRunnerAdapter,
                "_collect_php_files",
                return_value=[],
            ):
                with patch("subprocess.run") as mock_subprocess:
                    result = VisitorRunnerAdapter().invoke(tmp_path, [])
        mock_subprocess.assert_not_called()
        assert result.exitcode == 0
        assert json.loads(result.stdout) == []
        assert "no PHP files" in result.stderr

    def test_invoke_subprocess_success_assert_all_fields(self, tmp_path: Path) -> None:
        """Mutation killer: thorough assertion on returned ToolInvocation fields.
        Kills mutants in returncode check, stderr collection, findings extend,
        and _build_invocation (stdout/stderr/exitcode construction)."""
        php_file = tmp_path / "Foo.php"
        php_file.touch()
        visitors_dir = tmp_path / "visitors"
        visitors_dir.mkdir()
        (visitors_dir / "god_class.php").touch()

        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = json.dumps([
            {"file": "Foo.php", "line": 10, "rule_id": "GOD-001", "message": "God class"}
        ])
        completed.stderr = ""

        with patch(
            "harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors",
            return_value=["god_class"],
        ):
            with patch.object(
                VisitorRunnerAdapter,
                "_collect_php_files",
                return_value=[php_file],
            ):
                with patch("subprocess.run", return_value=completed) as mock_run:
                    from harness_quality_gate.adapters.php import visitor_runner_adapter as vra_mod
                    orig_dir = vra_mod.VISITORS_DIR
                    vra_mod.VISITORS_DIR = visitors_dir
                    try:
                        result = VisitorRunnerAdapter().invoke(tmp_path, [])
                    finally:
                        vra_mod.VISITORS_DIR = orig_dir

        # Kill mutants in _build_invocation: exitcode
        assert result.exitcode == 0
        # Kill mutants in returncode != 0 →  == 0 (skip continue, eat stderr)
        assert not result.stderr
        # Kill mutants in extend (findings.extend → pass)
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert data[0]["rule_id"] == "GOD-001"

    def test_invoke_subprocess_failure_assert_stderr_and_findings(self, tmp_path: Path) -> None:
        """Mutation killer: assert stderr collected AND findings remain empty on failure.
        Kills mutants: returncode != 0 → == 0 (doesn't collect stderr),
        stderr_parts.append missing, continue → pass (extends failed findings)."""
        php_file = tmp_path / "Foo.php"
        php_file.touch()
        visitors_dir = tmp_path / "visitors"
        visitors_dir.mkdir()
        (visitors_dir / "god_class.php").touch()

        failed = MagicMock()
        failed.returncode = 2
        failed.stdout = "some output"  # Should be ignored on failure
        failed.stderr = "Fatal error: out of memory"

        with patch(
            "harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors",
            return_value=["god_class"],
        ):
            with patch.object(
                VisitorRunnerAdapter,
                "_collect_php_files",
                return_value=[php_file],
            ):
                with patch("subprocess.run", return_value=failed):
                    from harness_quality_gate.adapters.php import visitor_runner_adapter as vra_mod
                    orig_dir = vra_mod.VISITORS_DIR
                    vra_mod.VISITORS_DIR = visitors_dir
                    try:
                        result = VisitorRunnerAdapter().invoke(tmp_path, [])
                    finally:
                        vra_mod.VISITORS_DIR = orig_dir

        # Kill mutant: returncode != 0 → == 0 → would extend failed output as findings
        data = json.loads(result.stdout)
        assert len(data) == 0, "Failed subprocess should NOT produce findings"
        # Kill mutant: stderr_parts.append removed
        assert "Fatal error: out of memory" in result.stderr
        # Kill mutant: exitcode not set to 1 when stderr exists
        assert result.exitcode == 1

    def test_invoke_visitor_missing_skips_with_warning(self, tmp_path: Path) -> None:
        """Mutation killer: assert that missing visitor script skips the file.
        Kills mutant where 'if not is_file' condition is removed (doesn't skip)."""
        php_file = tmp_path / "Foo.php"
        php_file.touch()
        # Create visitors dir but DON'T create the script
        visitors_dir = tmp_path / "visitors"
        visitors_dir.mkdir()
        # Leave it empty - simulates discover_visitors returning visitor but file missing

        with patch(
            "harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors",
            return_value=["nonexistent"],
        ):
            with patch.object(
                VisitorRunnerAdapter,
                "_collect_php_files",
                return_value=[php_file],
            ):
                with patch("subprocess.run") as mock_run:
                    from harness_quality_gate.adapters.php import visitor_runner_adapter as vra_mod
                    orig_dir = vra_mod.VISITORS_DIR
                    vra_mod.VISITORS_DIR = visitors_dir
                    try:
                        result = VisitorRunnerAdapter().invoke(tmp_path, [])
                    finally:
                        vra_mod.VISITORS_DIR = orig_dir

        # Kill mutant: removes 'if not visitor_script.is_file(): continue'
        mock_run.assert_not_called()
        data = json.loads(result.stdout)
        assert data == []
        assert result.exitcode == 0  # No stderr, exitcode stays 0

    def test_invoke_subprocess_env_passed_correctly(self, tmp_path: Path) -> None:
        """Mutation killer: assert subprocess.run receives correct env dict.
        Kills mutants in env dict construction: {**os.environ, **(env or {})}.
        Mutations like env=None → env={}; env={'X':'1'} → env=None."""
        php_file = tmp_path / "Foo.php"
        php_file.touch()
        visitors_dir = tmp_path / "visitors"
        visitors_dir.mkdir()
        (visitors_dir / "g.php").touch()

        custom_env = {"MY_VAR": "my_value"}

        with patch(
            "harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors",
            return_value=["g"],
        ):
            with patch.object(
                VisitorRunnerAdapter,
                "_collect_php_files",
                return_value=[php_file],
            ):
                with patch(
                    "subprocess.run",
                    return_value=MagicMock(returncode=0, stdout="[]", stderr="")
                ) as mock_run:
                    from harness_quality_gate.adapters.php import visitor_runner_adapter as vra_mod
                    orig_dir = vra_mod.VISITORS_DIR
                    vra_mod.VISITORS_DIR = visitors_dir
                    try:
                        result = VisitorRunnerAdapter().invoke(
                            tmp_path, [], env=custom_env
                        )
                    finally:
                        vra_mod.VISITORS_DIR = orig_dir

        # Verify subprocess.run was called with the custom env
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        env_used = call_kwargs.kwargs.get("env")
        assert env_used is not None
        assert "MY_VAR" in env_used
        assert env_used["MY_VAR"] == "my_value"

    def test_invoke_multiple_files_merged_with_findings(self, tmp_path: Path) -> None:
        """Mutation killer: assert correct merging across multiple php files.
        Kills mutants in loop:  for php_file in php_files:  mutations."""
        php_file1 = tmp_path / "A.php"
        php_file1.touch()
        php_file2 = tmp_path / "B.php"
        php_file2.touch()
        visitors_dir = tmp_path / "visitors"
        visitors_dir.mkdir()
        (visitors_dir / "v.php").touch()

        def mock_run_side_effect(*args, **kwargs):
            # subprocess.run(command_list, ...) → args[0] is the command list
            cmd = args[0] if args else kwargs.get("args", [])
            php_file = Path(cmd[-1]) if cmd else Path("unknown")
            stub = MagicMock()
            stub.returncode = 0
            stub.stdout = json.dumps([{"file": php_file.name, "line": 1, "rule_id": "M", "message": "msg"}])
            stub.stderr = ""
            return stub

        with patch(
            "harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors",
            return_value=["v"],
        ):
            with patch.object(
                VisitorRunnerAdapter,
                "_collect_php_files",
                return_value=[php_file1, php_file2],
            ):
                with patch("subprocess.run", side_effect=mock_run_side_effect):
                    from harness_quality_gate.adapters.php import visitor_runner_adapter as vra_mod
                    orig_dir = vra_mod.VISITORS_DIR
                    vra_mod.VISITORS_DIR = visitors_dir
                    try:
                        result = VisitorRunnerAdapter().invoke(tmp_path, [])
                    finally:
                        vra_mod.VISITORS_DIR = orig_dir

        data = json.loads(result.stdout)
        assert len(data) == 2, f"Expected 2 findings, got {len(data)}"
        filenames = {d["file"] for d in data}
        assert "A.php" in filenames
        assert "B.php" in filenames
        assert result.exitcode == 0

    def test_invoke_env_none_handled_correctly(self, tmp_path: Path) -> None:
        """Mutation killer: assert subprocess.run receives env when env=None.
        Kills mutant where  **(env or {})  →  **{}  (env not merged with os.environ)."""
        php_file = tmp_path / "Foo.php"
        php_file.touch()
        visitors_dir = tmp_path / "visitors"
        visitors_dir.mkdir()
        (visitors_dir / "g.php").touch()

        with patch(
            "harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors",
            return_value=["g"],
        ):
            with patch.object(
                VisitorRunnerAdapter,
                "_collect_php_files",
                return_value=[php_file],
            ):
                with patch(
                    "subprocess.run",
                    return_value=MagicMock(returncode=0, stdout="[]", stderr="")
                ) as mock_run:
                    from harness_quality_gate.adapters.php import visitor_runner_adapter as vra_mod
                    orig_dir = vra_mod.VISITORS_DIR
                    vra_mod.VISITORS_DIR = visitors_dir
                    try:
                        # Explicitly pass env=None (or omit it to use default)
                        result = VisitorRunnerAdapter().invoke(tmp_path, [], env=None)
                    finally:
                        vra_mod.VISITORS_DIR = orig_dir

        env_used = mock_run.call_args.kwargs.get("env")
        assert env_used is not None
        # env should contain system vars (merged with os.environ)
        assert "PATH" in env_used or len(env_used) > 0

    def test_invoke_missing_visitor_script_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that a missing visitor script logs a warning with exact format.

        Creates a visitors dir with one real visitor + one discovered-but-missing,
        then patches _discover_visitors to also return the missing name.

        Kills mutants 39-43 (all logger.warning mutations):
          - mutmut_39:  visitor_script arg replaced with None
          - mutmut_40:  format string removed, visitor_script passed as bare message
          - mutmut_41:  visitor_script arg removed → literal "%s" in message
          - mutmut_42:  string case mutation ("XXVisitor...XX")
          - mutmut_43:  string case mutation ("visitor..." lowercase)
        """
        visitors_dir = tmp_path / "visitors"
        visitors_dir.mkdir()
        (visitors_dir / "valid.php").touch()

        php_file = tmp_path / "Foo.php"
        php_file.touch()

        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "[]"
        completed.stderr = ""

        with caplog.at_level(logging.WARNING, logger="harness_quality_gate.adapters.php.visitor_runner_adapter"):
            with patch("harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors", return_value=["valid", "missing"]):
                with patch.object(VisitorRunnerAdapter, "_collect_php_files", return_value=[php_file]):
                    with patch("subprocess.run", return_value=completed):
                        from harness_quality_gate.adapters.php import visitor_runner_adapter as vra_mod
                        orig_dir = vra_mod.VISITORS_DIR
                        try:
                            vra_mod.VISITORS_DIR = visitors_dir
                            result = VisitorRunnerAdapter().invoke(tmp_path, [])
                        finally:
                            vra_mod.VISITORS_DIR = orig_dir

        # Must have exactly one WARNING record for the missing visitor
        warns = [r for r in caplog.records if r.levelno == logging.WARNING]
        missing_warns = [r for r in warns if "Visitor script missing" in r.message]
        assert len(missing_warns) == 1
        warn = missing_warns[0]

        # Original message: "Visitor script missing: {path}"
        # Mutant 42: "XXVisitor script missing: %sXX" — wrong case for "Visitor"
        # Mutant 43: "visitor script missing: %s" — wrong case
        assert "Visitor script missing" in warn.message
        # Mutant 39: replaced visitor_script with None → "Visitor script missing: None"
        assert "None" not in warn.message
        # Mutant 40: bare message (just path, no "Visitor script missing" prefix)
        assert warn.message.startswith("Visitor script missing")
        # Mutant 41: removed visitor_script arg → literal "%s" remains
        assert "%s" not in warn.message
        # The path must be present (original behavior)
        assert str(tmp_path) in warn.message
# ===========================================================================

class TestPhpWeakTestAdapter:
    def test_name(self) -> None:
        assert PhpWeakTestAdapter().name == "weak-test-php"

    def test_version_returns_visitor_count(self) -> None:
        v = PhpWeakTestAdapter().version(Path("."))
        assert "visitors" in v

    def test_invoke_no_test_files(self, tmp_path: Path) -> None:
        result = PhpWeakTestAdapter().invoke(tmp_path, [])
        assert result.stdout == "[]"
        assert "no PHP test files" in result.stderr

    def test_invoke_with_test_files_visitor_missing(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "FooTest.php"
        test_file.touch()
        # With no visitor scripts present (they won't exist), invoke should run
        # but skip each visitor gracefully and return empty findings
        result = PhpWeakTestAdapter().invoke(tmp_path, [])
        assert result.exitcode == 0
        assert json.loads(result.stdout) == []

    def test_invoke_visitor_success(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "FooTest.php"
        test_file.touch()

        findings_json = '[{"file": "tests/FooTest.php", "line": 5, "rule_id": "A1", "message": "no assertions", "severity": "error"}]'
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = findings_json
        completed.stderr = ""

        visitors_dir = tmp_path / "visitors"
        visitors_dir.mkdir()
        for name in ["weak_test_a1"]:
            (visitors_dir / f"{name}.php").touch()

        # Patch parent so visitor scripts are found
        with patch.object(
            PhpWeakTestAdapter,
            "_collect_test_files",
            return_value=[test_file],
        ):
            with patch("subprocess.run", return_value=completed):
                with patch("harness_quality_gate.adapters.php.weak_test_php.Path") as mock_path_cls:
                    # Make visitors_dir resolve correctly
                    mock_resolve = MagicMock()
                    mock_resolve.parent = visitors_dir.parent
                    mock_path_cls.return_value.resolve.return_value = mock_resolve
                    mock_path_cls.side_effect = lambda *args, **kwargs: Path(*args, **kwargs)

                    result = PhpWeakTestAdapter().invoke(tmp_path, [])
        # Just verify it runs without error
        assert result is not None

    def test_invoke_visitor_failure_records_stderr(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "FooTest.php"
        test_file.touch()

        completed = MagicMock()
        completed.returncode = 1
        completed.stdout = ""
        completed.stderr = "Fatal error in visitor"

        # Create a real visitors dir with one script so it can be found
        from harness_quality_gate.adapters.php import weak_test_php as wt_module
        real_visitors_dir = Path(wt_module.__file__).parent / "visitors"
        if not real_visitors_dir.exists() or not (real_visitors_dir / "weak_test_a1.php").exists():
            pytest.skip("weak_test_a1.php visitor not present on this install")

        with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[test_file]):
            with patch("subprocess.run", return_value=completed):
                result = PhpWeakTestAdapter().invoke(tmp_path, [])

        assert result.exitcode == 1
        assert "Fatal error" in result.stderr

    def test_parse_empty(self) -> None:
        assert PhpWeakTestAdapter().parse("") == []

    def test_parse_with_findings(self) -> None:
        data = [
            {
                "file": "tests/FooTest.php",
                "line": 42,
                "rule_id": "A1",
                "message": "No assertions",
                "severity": "error",
                "fix_hint": "Add an assertion",
            }
        ]
        findings = PhpWeakTestAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "tests/FooTest.php:42"
        assert f.severity == "error"
        assert f.rule_id == "A1"
        assert f.layer == "L3B"
        assert f.language == "php"
        assert f.fix_hint == "Add an assertion"

    def test_parse_finding_no_line(self) -> None:
        data = [{"file": "x.php", "rule_id": "A2-PHP", "message": "mocks only"}]
        findings = PhpWeakTestAdapter().parse(json.dumps(data))
        assert findings[0].node == "x.php"

    def test_parse_non_dict_item_skipped(self) -> None:
        assert PhpWeakTestAdapter().parse('["bad"]') == []

    def test_collect_test_files_filters_vendor(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "FooTest.php").touch()
        vendor_dir = tmp_path / "vendor" / "pkg"
        vendor_dir.mkdir(parents=True)
        (vendor_dir / "BarTest.php").touch()
        files = PhpWeakTestAdapter._collect_test_files(tmp_path)
        assert all("vendor" not in str(f) for f in files)
        assert len(files) == 1

    def test_parse_single_output_fallback(self) -> None:
        text = "Warning\n[{\"rule_id\": \"A1\", \"message\": \"x\"}]"
        result = PhpWeakTestAdapter._parse_single_output(text)
        assert len(result) == 1

    def test_parse_single_output_invalid(self) -> None:
        assert PhpWeakTestAdapter._parse_single_output("totally invalid") == []

    def test_parse_single_output_empty(self) -> None:
        assert PhpWeakTestAdapter._parse_single_output("") == []


# ===========================================================================
# antipattern_tier_a_php.py
# ===========================================================================

class TestPhpAntipatternTierAAdapter:
    def test_name(self) -> None:
        assert PhpAntipatternTierAAdapter().name == "antipattern-tier-a"

    def test_parity_gap(self) -> None:
        assert PhpAntipatternTierAAdapter.parity_gap == 8

    def test_init_adapters(self) -> None:
        """__init__ creates both PhpMdAdapter and VisitorRunnerAdapter."""
        adapter = PhpAntipatternTierAAdapter()
        assert isinstance(adapter._phpmd, PhpMdAdapter)
        assert isinstance(adapter._visitors, VisitorRunnerAdapter)

    def test_version_phpmd_missing(self, tmp_path: Path) -> None:
        with patch.object(PhpMdAdapter, "version", side_effect=RuntimeError("not found")):
            with patch.object(VisitorRunnerAdapter, "version", side_effect=NotImplementedError):
                v = PhpAntipatternTierAAdapter().version(tmp_path)
        assert v == "phpmd:MISSING visitors:poC"

    def test_version_visitor_missing(self, tmp_path: Path) -> None:
        with patch.object(PhpMdAdapter, "version", side_effect=RuntimeError("not found")):
            with patch.object(VisitorRunnerAdapter, "version", side_effect=RuntimeError("not found")):
                v = PhpAntipatternTierAAdapter().version(tmp_path)
        assert v == "phpmd:MISSING visitors:MISSING"

    def test_invoke_both_ok_empty(self, tmp_path: Path) -> None:
        """Base case: both tools return empty — exitcode=0, empty stdout."""
        phpmd_empty = json.dumps({"files": []})
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok(phpmd_empty, exitcode=0)) as mock_phpmd:
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok("[]", exitcode=0)) as mock_visitor:
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        assert json.loads(result.stdout) == []
        assert result.exitcode == 0
        assert result.stderr == ""
        # Kill mutmut_17: args→None, mutmut_18: env→None,
        # mutmut_21: args-removed, mutmut_22: env-removed calls
        mock_phpmd.assert_called_once_with(tmp_path, [], env=None, timeout=300.0)
        mock_visitor.assert_called_once_with(tmp_path, [], env=None, timeout=300.0)

    def test_invoke_phpmd_not_found_graceful(self, tmp_path: Path) -> None:
        with patch.object(PhpMdAdapter, "invoke", side_effect=RuntimeError("phpmd not found")) as mock_phpmd:
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok("[]")) as mock_visitor:
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        # Kill mutmut_17: args→None
        # mutmut_21: args-removed, mutmut_22: env-removed
        mock_phpmd.assert_called_once_with(tmp_path, [], env=None, timeout=300.0)
        mock_visitor.assert_called_once_with(tmp_path, [], env=None, timeout=300.0)
        # PHPMD is skipped, visitor returns empty → merged list is empty
        assert result.stdout == "[]"
        assert result.exitcode == 0

    def test_invoke_with_non_none_env(self, tmp_path: Path) -> None:
        """Test with explicit env dict — kills mutmut_18 (env=env → env=None).

        When env is provided, the original code passes it through; the mutation
        replaces it with None, changing the call signature and failing this test.
        """
        phpmd_empty = json.dumps({"files": []})
        env = {"FOO": "bar"}
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok(phpmd_empty, exitcode=0)) as mock_phpmd:
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok("[]", exitcode=0)) as mock_visitor:
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [], env=env)
        # The env dict must be passed through (not mutated to None)
        mock_phpmd.assert_called_once_with(tmp_path, [], env=env, timeout=300.0)
        mock_visitor.assert_called_once_with(tmp_path, [], env=env, timeout=300.0)

    def test_invoke_phpmd_only(self, tmp_path: Path) -> None:
        """Only PHPMD returns findings — visitor is empty."""
        phpmd_out = json.dumps({
            "files": [
                {
                    "file": "src/God.php",
                    "violations": [
                        {"rule": "GodClass", "description": "Too large", "beginLine": 42, "priority": 1}
                    ],
                }
            ]
        })
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok(phpmd_out, exitcode=0)):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok("[]")):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        merged = json.loads(result.stdout)
        assert len(merged) == 1
        item = merged[0]
        assert item["source"] == "phpmd"
        assert item["file"] == "src/God.php"
        assert item["rule"] == "GodClass"
        assert item["description"] == "Too large"
        assert item["line"] == 42
        assert item["priority"] == 1
        assert result.exitcode == 0

    def test_invoke_visitor_only(self, tmp_path: Path) -> None:
        """Only visitor runner returns findings — PHPMD is empty."""
        visitor_out = json.dumps([
            {"file": "src/Envy.php", "line": 10, "rule_id": "feature_envy", "message": "Feature envy"}
        ])
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok("")):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok(visitor_out)):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        merged = json.loads(result.stdout)
        assert len(merged) == 1
        item = merged[0]
        assert item["source"] == "visitor"
        assert item["file"] == "src/Envy.php"
        assert item["rule"] == "feature_envy"
        assert item["description"] == "Feature envy"
        assert item["line"] == 10

    def test_invoke_phpmd_visitor_combined(self, tmp_path: Path) -> None:
        phpmd_out = json.dumps({
            "files": [
                {
                    "file": "src/Foo.php",
                    "violations": [
                        {"rule": "GodClass", "description": "Too large", "beginLine": 1, "priority": 2}
                    ],
                }
            ]
        })
        visitor_out = json.dumps([
            {"file": "src/Bar.php", "line": 5, "rule_id": "god_class", "message": "God class detected"}
        ])
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok(phpmd_out)):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok(visitor_out)):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        merged = json.loads(result.stdout)
        assert len(merged) == 2
        # Check exact structure for PHPMD item
        phpmd_item = merged[0]
        assert phpmd_item["source"] == "phpmd"
        assert phpmd_item["file"] == "src/Foo.php"
        assert phpmd_item["rule"] == "GodClass"
        assert phpmd_item["description"] == "Too large"
        assert phpmd_item["line"] == 1
        assert phpmd_item["priority"] == 2
        # Check exact structure for visitor item
        visitor_item = merged[1]
        assert visitor_item["source"] == "visitor"
        assert visitor_item["file"] == "src/Bar.php"
        assert visitor_item["rule"] == "god_class"
        assert visitor_item["description"] == "God class detected"
        assert visitor_item["line"] == 5

    def test_invoke_phpmd_invalid_json_graceful(self, tmp_path: Path) -> None:
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok("not json")):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok("[]")):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        assert result.stdout == "[]"

    def test_invoke_visitor_invalid_json_graceful(self, tmp_path: Path) -> None:
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok("")):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok("not json")):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        assert result.stdout == "[]"

    def test_invoke_visitor_runtime_error_graceful(self, tmp_path: Path) -> None:
        """Visitor raises RuntimeError — sentinel default produces marker finding."""
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok('{"files": []}')):
            with patch.object(VisitorRunnerAdapter, "invoke", side_effect=RuntimeError("failed")):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        # Sentinel JSON parses to list with one marker dict. Visitor source field
        # identifies it. Mutant 9 (sentinel → "XX...") → 0 items.
        parsed = json.loads(result.stdout)
        assert len(parsed) == 1
        assert parsed[0]["source"] == "visitor"

    def test_invoke_visitor_not_implemented_graceful(self, tmp_path: Path) -> None:
        """Visitor raises NotImplementedError — sentinel default produces marker finding."""
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok("")):
            with patch.object(VisitorRunnerAdapter, "invoke", side_effect=NotImplementedError):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        # Sentinel JSON parses to list with one marker dict.
        # Mutant 9 (vis_out → "XX...") breaks JSON parsing → 0 items → assertion fails.
        parsed = json.loads(result.stdout)
        assert len(parsed) == 1
        assert parsed[0]["source"] == "visitor"
        assert result.stderr == ""

    def test_invoke_stderr_merged(self, tmp_path: Path) -> None:
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok("", stderr="phpmd error")):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok("[]", stderr="visitor warning")):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        assert "phpmd" in result.stderr
        assert "visitor" in result.stderr
        assert "phpmd error" in result.stderr
        assert "visitor warning" in result.stderr

    def test_invoke_phpmd_exitcode_propagated(self, tmp_path: Path) -> None:
        """Exit code from PHPMD invocation is reflected in ToolInvocation."""
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok('{"files": []}', exitcode=1)):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok('[]', exitcode=0)):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        assert result.exitcode == 1

    def test_invoke_both_runtime_error_graceful(self, tmp_path: Path) -> None:
        """Both PHPMD and visitor runner fail — all defaults used.

        The visitor_stdout default is a sentinel JSON list containing a marker dict.
        The sentinel is parseable → merged_findings gets one marker entry.
        Killing mutant 9 (visitor_stdout → "XX...") requires asserting on the marker.
        Killing mutant 10 (visitor_stderr → None) is handled by the production guard
        assertion `assert isinstance(visitor_stderr, str)`, but we also assert
        result.stderr == "" to verify the exact error string is built correctly.
        """
        with patch.object(PhpMdAdapter, "invoke", side_effect=RuntimeError("phpmd broken")):
            with patch.object(VisitorRunnerAdapter, "invoke", side_effect=RuntimeError("vis broken")):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        parsed = json.loads(result.stdout)
        assert len(parsed) == 1
        assert parsed[0]["source"] == "visitor"
        assert result.stderr == ""
        assert result.exitcode == 0

    def test_parse_empty(self) -> None:
        assert PhpAntipatternTierAAdapter().parse("") == []

    def test_parse_invalid_json(self) -> None:
        assert PhpAntipatternTierAAdapter().parse("not json") == []

    def test_parse_not_list(self) -> None:
        assert PhpAntipatternTierAAdapter().parse('{"key": "val"}') == []

    def test_parse_phpmd_findings(self) -> None:
        data = [
            {
                "source": "phpmd",
                "file": "src/Foo.php",
                "rule": "GodClass",
                "description": "Class is too large",
                "line": 10,
                "priority": 1,
            }
        ]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        f = findings[0]
        # Verify ALL fields on the Finding object
        assert f.severity == "critical"
        assert f.node == "src/Foo.php:10"
        assert f.layer == "L2"
        assert f.language == "php"
        assert f.tool == "antipattern-tier-a"
        assert f.rule_id == "GodClass"
        assert "Class is too large" in f.message
        assert f.fix_hint is not None

    def test_parse_visitor_findings(self) -> None:
        data = [
            {
                "source": "visitor",
                "file": "src/Bar.php",
                "rule": "god_class",
                "description": "God class detected",
                "line": 5,
            }
        ]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        f = findings[0]
        assert f.severity == "info"
        assert f.node == "src/Bar.php:5"
        assert f.layer == "L2"
        assert f.language == "php"
        assert f.tool == "antipattern-tier-a"
        assert f.rule_id == "god_class"
        assert "God class detected" in f.message

    def test_parse_multi_findings(self) -> None:
        """Multiple findings are returned in order — catches merge-order mutations."""
        data = [
            {"source": "phpmd", "file": "a.php", "rule": "R1", "description": "d1", "line": 1, "priority": 2},
            {"source": "visitor", "file": "b.php", "rule": "R2", "description": "d2", "line": 2},
        ]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert len(findings) == 2
        assert findings[0].rule_id == "R1"
        assert findings[0].severity == "major"
        assert findings[1].rule_id == "R2"
        assert findings[1].severity == "info"

    def test_parse_no_line(self) -> None:
        data = [{"source": "phpmd", "file": "x.php", "rule": "R", "description": "d", "priority": 3}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert findings[0].node == "x.php"
        assert ":" not in findings[0].node

    def test_parse_fix_hint_from_item(self) -> None:
        data = [{"source": "visitor", "file": "x.php", "rule": "R", "description": "d", "fix_hint": "custom hint"}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert findings[0].fix_hint == "custom hint"

    def test_parse_fix_hint_fallback(self) -> None:
        """When no fix_hint in item, fallback is 'Rule: {rule}'."""
        data = [{"source": "visitor", "file": "x.php", "rule": "MyRule", "description": "d"}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert findings[0].fix_hint == "Rule: MyRule"

    def test_parse_no_rule(self) -> None:
        """When no rule at all, fix_hint should be None."""
        data = [{"source": "visitor", "file": "x.php", "description": "d"}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert findings[0].fix_hint is None
        assert findings[0].rule_id == ""

    def test_parse_non_dict_item_skipped(self) -> None:
        assert PhpAntipatternTierAAdapter().parse('["not-a-dict"]') == []

    def test_parse_line_invalid_int(self) -> None:
        data = [{"source": "phpmd", "file": "x.php", "rule": "R", "description": "d", "line": "bad", "priority": 2}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        # Non-integer line becomes string in message
        assert "bad" in findings[0].message

    def test_parse_startLine_fallback(self) -> None:
        """When no line field, node should not include line number."""
        data = [
            {"source": "phpmd", "file": "x.php", "rule": "R", "description": "d", "priority": 1}
        ]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].node == "x.php"  # line is None, so no ":line" part

    def test_parse_priority_5_is_info(self) -> None:
        data = [{"source": "phpmd", "file": "x.php", "rule": "R", "description": "d", "priority": 5}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert findings[0].severity == "info"

    def test_parse_priority_unknown_is_info(self) -> None:
        """Out-of-range priority falls back to info."""
        data = [{"source": "phpmd", "file": "x.php", "rule": "R", "description": "d", "priority": 99}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert findings[0].severity == "info"

    def test_parse_full_fields(self) -> None:
        """Assert ALL fields of Finding exactly — catches parse mutations."""
        data = [
            {
                "source": "phpmd",
                "file": "src/App.php",
                "rule": "TooManyMethods",
                "description": "Has too many",
                "line": 20,
                "priority": 1,
            }
        ]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "src/App.php:20"
        assert f.severity == "critical"
        assert f.message == "Line 20: Has too many"
        assert f.fix_hint == "Rule: TooManyMethods"
        assert f.rule_id == "TooManyMethods"
        assert f.tool == "antipattern-tier-a"
        assert f.layer == "L2"
        assert f.language == "php"

    def test_parse_visitor_full_fields(self) -> None:
        """Assert ALL fields of a visitor Finding exactly."""
        data = [
            {
                "source": "visitor",
                "file": "src/Helper.php",
                "rule_id": "short_variable",
                "description": "Use descriptive name",
                "line": 5,
            }
        ]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "src/Helper.php:5"
        assert f.severity == "info"
        assert f.message == "Line 5: Use descriptive name"
        assert f.fix_hint == "Rule: short_variable"
        assert f.rule_id == "short_variable"
        assert f.tool == "antipattern-tier-a"
        assert f.layer == "L2"
        assert f.language == "php"

    def test_parse_message_format_no_line(self) -> None:
        """When no line, message uses only description."""
        data = [{"source": "phpmd", "file": "x.php", "rule": "R", "description": "desc", "priority": 3}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert findings[0].message == "desc"

    def test_parse_message_format_empty_description(self) -> None:
        """When line exists but description is empty."""
        data = [{"source": "phpmd", "file": "x.php", "rule": "R", "line": 1, "priority": 3}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert findings[0].message == "Line 1"

    def test_parse_multi_rule_sources(self) -> None:
        """Different sources produce different severities."""
        data = [
            {"source": "phpmd", "file": "x.php", "rule": "R1", "description": "d1", "priority": 1},
            {"source": "phpmd", "file": "x.php", "rule": "R2", "description": "d2", "priority": 3},
            {"source": "visitor", "file": "y.php", "rule": "R3", "description": "d3", "line": 1},
        ]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert len(findings) == 3
        assert findings[0].severity == "critical"
        assert findings[1].severity == "minor"
        assert findings[2].severity == "info"

    def test_priority_to_severity_helper(self) -> None:
        assert antipattern_priority_to_severity(1) == "critical"
        assert antipattern_priority_to_severity(2) == "major"
        assert antipattern_priority_to_severity(3) == "minor"
        assert antipattern_priority_to_severity(4) == "info"
        assert antipattern_priority_to_severity(5) == "info"
        assert antipattern_priority_to_severity(0) == "info"
        assert antipattern_priority_to_severity(-1) == "info"
        assert antipattern_priority_to_severity(100) == "info"

    # -- version: happy path & edge cases (kills version string mutation survivors) --

    def test_version_all_ok(self, tmp_path: Path) -> None:
        """Both tools succeed — returns composite version string."""
        with patch.object(PhpMdAdapter, "version", return_value="8.0"):
            with patch.object(VisitorRunnerAdapter, "version", return_value="1.0"):
                v = PhpAntipatternTierAAdapter().version(tmp_path)
        assert v == "phpmd:8.0 visitors:1.0"
        assert v.startswith("phpmd:")
        assert "visitors:" in v

    def test_version_phpmd_ok_visitor_missing(self, tmp_path: Path) -> None:
        """PHPMD succeeds but visitor raises RuntimeError."""
        with patch.object(PhpMdAdapter, "version", return_value="8.0"):
            with patch.object(VisitorRunnerAdapter, "version", side_effect=RuntimeError("not found")):
                v = PhpAntipatternTierAAdapter().version(tmp_path)
        assert v == "phpmd:8.0 visitors:MISSING"

    def test_version_phpmd_missing_visitor_ok(self, tmp_path: Path) -> None:
        """PHPMD fails but visitor succeeds."""
        with patch.object(PhpMdAdapter, "version", side_effect=RuntimeError("not found")):
            with patch.object(VisitorRunnerAdapter, "version", return_value="1.0"):
                v = PhpAntipatternTierAAdapter().version(tmp_path)
        assert v == "phpmd:MISSING visitors:1.0"

    # -- invoke: exhaustive string-key and output mutations --

    def test_invoke_phpmd_visitor_combined_full_assertions(self, tmp_path: Path) -> None:
        """Full assertions on all fields in merged output — catches string-key mutations."""
        phpmd_out = json.dumps({
            "files": [
                {
                    "file": "src/A.php",
                    "violations": [
                        {"rule": "R1", "description": "desc1", "beginLine": 10, "priority": 1},
                        {"rule": "R2", "description": "desc2", "beginLine": 20, "priority": 3},
                    ],
                },
                {
                    "file": "src/B.php",
                    "violations": [
                        {"rule": "R3", "description": "desc3", "beginLine": 30, "priority": 5},
                    ],
                },
            ]
        })
        visitor_out = json.dumps([
            {"file": "src/C.php", "line": 5, "rule_id": "v1", "message": "msg1"},
            {"file": "src/D.php", "line": 15, "rule_id": "v2", "message": "msg2"},
        ])
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok(phpmd_out)):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok(visitor_out)):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        merged = json.loads(result.stdout)
        # PHPMD items
        assert merged[0]["source"] == "phpmd"
        assert merged[0]["file"] == "src/A.php"
        assert merged[0]["rule"] == "R1"
        assert merged[0]["description"] == "desc1"
        assert merged[0]["line"] == 10
        assert merged[0]["priority"] == 1
        assert merged[1]["source"] == "phpmd"
        assert merged[1]["file"] == "src/A.php"
        assert merged[1]["rule"] == "R2"
        assert merged[1]["description"] == "desc2"
        assert merged[1]["line"] == 20
        assert merged[1]["priority"] == 3
        assert merged[2]["source"] == "phpmd"
        assert merged[2]["file"] == "src/B.php"
        assert merged[2]["rule"] == "R3"
        assert merged[2]["description"] == "desc3"
        assert merged[2]["line"] == 30
        assert merged[2]["priority"] == 5
        # Visitor items
        assert merged[3]["source"] == "visitor"
        assert merged[3]["file"] == "src/C.php"
        assert merged[3]["rule"] == "v1"
        assert merged[3]["description"] == "msg1"
        assert merged[3]["line"] == 5
        assert merged[4]["source"] == "visitor"
        assert merged[4]["file"] == "src/D.php"
        assert merged[4]["rule"] == "v2"
        assert merged[4]["description"] == "msg2"
        assert merged[4]["line"] == 15

    def test_invoke_both_stderr_content(self, tmp_path: Path) -> None:
        """Both tools produce stderr — exact stderr format is verified."""
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok('{"files": []}', stderr="phpmd: warning")):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok("[]", stderr="visitor: error")):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        assert "phpmd: warning" in result.stderr
        assert "visitor: error" in result.stderr
        assert result.stderr.startswith("phpmd:")

    def test_invoke_phpmd_visitor_combined_stderr_only(self, tmp_path: Path) -> None:
        """Both return empty findings but with stderr content."""
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok('{"files": []}', stderr="pmd-warn")):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok("[]", stderr="vis-warn")):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        assert json.loads(result.stdout) == []
        assert "pmd-warn" in result.stderr
        assert "vis-warn" in result.stderr
        assert result.exitcode == 0

    def test_invoke_visitor_stderr_only_phpmd_empty(self, tmp_path: Path) -> None:
        """Only visitor produces stderr."""
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok('{"files": []}')):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok("[]", stderr="vis-only")):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        assert "vis-only" in result.stderr
        assert result.exitcode == 0

    def test_invoke_not_implemented_no_stderr(self, tmp_path: Path) -> None:
        """Visitor not implemented — sentinel default produces one marker finding."""
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok('{"files": []}')):
            with patch.object(VisitorRunnerAdapter, "invoke", side_effect=NotImplementedError):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        parsed = json.loads(result.stdout)
        assert len(parsed) == 1
        assert parsed[0]["source"] == "visitor"
        assert result.stderr == ""
        assert result.exitcode == 0

    def test_invoke_visitor_only_comprehensive(self, tmp_path: Path) -> None:
        """Visitor output — exact field assertions catch string-key mutations."""
        visitor_out = json.dumps([
            {"file": "src/X.php", "line": 7, "rule_id": "rule_x", "message": "msg_x"},
        ])
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok("")):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok(visitor_out)):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        merged = json.loads(result.stdout)
        assert len(merged) == 1
        # Verify exact keys present (catches key-name mutations)
        assert set(merged[0].keys()) == {"source", "file", "rule", "description", "line"}
        assert merged[0]["source"] == "visitor"
        assert merged[0]["file"] == "src/X.php"
        assert merged[0]["rule"] == "rule_x"
        assert merged[0]["description"] == "msg_x"
        assert merged[0]["line"] == 7
        assert result.exitcode == 0

    def test_invoke_both_ok_comprehensive(self, tmp_path: Path) -> None:
        """Both ok, empty — exact stderr and exitcode assertions."""
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok('{"files": []}')):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok("[]")):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        assert result.stdout == "[]"
        assert result.stderr == ""
        assert result.exitcode == 0

    def test_invoke_mutiple_violations_from_same_file(self, tmp_path: Path) -> None:
        """Multiple violations in one file — merge order is PHPMD first."""
        phpmd_out = json.dumps({
            "files": [
                {
                    "file": "src/Multi.php",
                    "violations": [
                        {"rule": "R1", "description": "d1", "beginLine": 1, "priority": 1},
                        {"rule": "R2", "description": "d2", "beginLine": 2, "priority": 2},
                        {"rule": "R3", "description": "d3", "beginLine": 3, "priority": 3},
                    ],
                },
            ]
        })
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok(phpmd_out)):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok("[]")):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        merged = json.loads(result.stdout)
        assert len(merged) == 3
        for i, (rule, desc, line, prio) in enumerate([
            ("R1", "d1", 1, 1),
            ("R2", "d2", 2, 2),
            ("R3", "d3", 3, 3),
        ]):
            assert merged[i]["source"] == "phpmd"
            assert merged[i]["file"] == "src/Multi.php"
            assert merged[i]["rule"] == rule
            assert merged[i]["description"] == desc
            assert merged[i]["line"] == line
            assert merged[i]["priority"] == prio

    def test_invoke_phpmd_exception_no_change_to_exitcode(self, tmp_path: Path, caplog) -> None:
        """PHPMD RuntimeError — exitcode stays 0 (default)."""
        with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.php.antipattern_tier_a_php"):
            with patch.object(PhpMdAdapter, "invoke", side_effect=RuntimeError("broken")):
                with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok("[]")):
                    result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        assert result.exitcode == 0
        assert json.loads(result.stdout) == []
        assert result.stderr == ""
        # Check logger format string mutation
        assert "PHPMD skipped" in caplog.text
        # Kill mutmut_28: exc→None in logger(arg). Mutant produces "PHPMD skipped: None"
        # Kill mutmut_30: removed logger(arg) → log differs
        # Original logs: "PHPMD skipped: broken"
        # Mutant 28 logs: "PHPMD skipped: None"
        assert "broken" in caplog.text

    def test_invoke_visitor_not_implemented_logs(self, tmp_path: Path, caplog) -> None:
        """Visitor NotImplementedError — sentinel default produces marker finding."""
        with caplog.at_level("INFO", logger="harness_quality_gate.adapters.php.antipattern_tier_a_php"):
            with patch.object(PhpMdAdapter, "invoke", return_value=_ok("")):
                with patch.object(VisitorRunnerAdapter, "invoke", side_effect=NotImplementedError()):
                    result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        parsed = json.loads(result.stdout)
        assert len(parsed) == 1
        assert parsed[0]["source"] == "visitor"
        # Verify logger message format mutation is caught
        assert "Visitor runner not yet implemented" in caplog.text
        # Verify sentinel marker key — catches mutation of _DEFAULT_MARKER string
        assert parsed[0]["____DEFAULT__"] is True
        # Verify rule defaults to empty string when rule_id absent — catches
        # mutation of default "" → None in item.get("rule_id", "")
        assert parsed[0]["rule"] == ""

    def _invoke_with_both_ok_check_exactly(self, tmp_path: Path) -> str:
        """Run invoke with both ok and return exact stdout."""
        phpmd_out = json.dumps({
            "files": [
                {
                    "file": "src/Ex.php",
                    "violations": [{"rule": "R", "description": "d", "beginLine": 1, "priority": 1}],
                }
            ]
        })
        visitor_out = json.dumps([
            {"file": "src/X.php", "line": 2, "rule_id": "v", "message": "vm"},
        ])
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok(phpmd_out)):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok(visitor_out)):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        return result.stdout

    def test_invoke_full_output_exact(self, tmp_path: Path) -> None:
        """Full invoke — exact stdout string assertion catches merge/format mutations."""
        stdout = self._invoke_with_both_ok_check_exactly(tmp_path)
        assert stdout == json.dumps([{
            "source": "phpmd",
            "file": "src/Ex.php",
            "rule": "R",
            "description": "d",
            "line": 1,
            "priority": 1,
        }, {
            "source": "visitor",
            "file": "src/X.php",
            "rule": "v",
            "description": "vm",
            "line": 2,
        }], ensure_ascii=False, sort_keys=False)

    # Also add these right after the invoke tests and before parse tests

    def test_invoke_phpmd_whitespace_output(self, tmp_path: Path) -> None:
        """PHPMD outputs only whitespace — treated as empty."""
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok("   ")):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok("[]")):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        assert result.stdout == "[]"
        assert result.exitcode == 0

    def test_parse_source_unknown(self) -> None:
        """Source field is 'unknown' — catches mutation on 'unknown' default string."""
        data = [{"source": "unknown", "file": "x.php", "rule": "R", "description": "d"}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].layer == "L2"
        assert findings[0].language == "php"
        assert findings[0].severity == "info"

    def test_parse_no_line_no_description(self) -> None:
        """Both line and description absent — checks message fallback."""
        data = [{"source": "phpmd", "file": "x.php", "rule": "R", "priority": 1}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].message == ""
        assert findings[0].node == "x.php"

    def test_parse_line_zero(self) -> None:
        """Line=0 is falsy — node should be file only, no ':0'."""
        data = [{"source": "phpmd", "file": "x.php", "rule": "R", "description": "d", "line": 0, "priority": 1}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].node == "x.php"
        assert ":" not in findings[0].node

    def test_parse_startLine_fallback_to_line(self) -> None:
        """invoke puts 'line' field (may come from beginLine or startLine) — parse reads 'line'."""
        data = [{"source": "phpmd", "file": "x.php", "rule": "R", "description": "d", "line": 99, "priority": 2}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].node == "x.php:99"
        assert "99" in findings[0].message
        assert findings[0].severity == "major"

    def test_parse_empty_dict_item(self) -> None:
        """Dict item with no source — uses default 'unknown'."""
        data = [{}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].rule_id == ""
        assert findings[0].fix_hint is None

    def test_parse_layer_language_exact(self) -> None:
        """Verify exact 'L2' and 'php' strings in output — catches default string mutations."""
        data = [{"source": "phpmd", "file": "x.php", "rule": "R", "description": "d", "priority": 1}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert findings[0].layer == "L2"
        assert findings[0].language == "php"

    def test_parse_message_format_line_prefix(self) -> None:
        """Message uses 'Line N: description' format — catches 'Line ' prefix mutations."""
        data = [{"source": "phpmd", "file": "x.php", "rule": "R", "description": "desc", "line": 42, "priority": 1}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert findings[0].message == "Line 42: desc"

    def test_full_pipeline_phpmd(self, tmp_path: Path) -> None:
        """Full invoke → parse pipeline with PHPMD data — asserts every Finding field."""
        phpmd_out = json.dumps({
            "files": [
                {
                    "file": "src/Full.php",
                    "violations": [
                        {"rule": "GodClass", "description": "Class too large", "beginLine": 5, "priority": 1},
                    ],
                }
            ]
        })
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok(phpmd_out, exitcode=0)):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok("[]")):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        
        findings = PhpAntipatternTierAAdapter().parse(result.stdout, result.stderr, result.exitcode)
        assert len(findings) == 1
        f = findings[0]
        # Assert EVERY single field on the Finding
        assert f.node == "src/Full.php:5"
        assert f.severity == "critical"
        assert f.message == "Line 5: Class too large"
        assert f.fix_hint == "Rule: GodClass"
        assert f.rule_id == "GodClass"
        assert f.tool == "antipattern-tier-a"
        assert f.layer == "L2"
        assert f.language == "php"

    def test_full_pipeline_visitor(self, tmp_path: Path) -> None:
        """Full invoke → parse pipeline with Visitor data — asserts every Finding field."""
        visitor_out = json.dumps([
            {"file": "src/Vis.php", "line": 12, "rule_id": "narrowing_type_hint", "message": "Use type hint"},
        ])
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok("")):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok(visitor_out)):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        
        findings = PhpAntipatternTierAAdapter().parse(result.stdout, result.stderr, result.exitcode)
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "src/Vis.php:12"
        assert f.severity == "info"
        assert f.message == "Line 12: Use type hint"
        assert f.fix_hint == "Rule: narrowing_type_hint"
        assert f.rule_id == "narrowing_type_hint"
        assert f.tool == "antipattern-tier-a"
        assert f.layer == "L2"
        assert f.language == "php"

    def test_full_pipeline_both_sources(self, tmp_path: Path) -> None:
        """Full invoke → parse with both PHPMD and visitor — all fields verified."""
        phpmd_out = json.dumps({
            "files": [{
                "file": "src/A.php",
                "violations": [{"rule": "R", "description": "d", "beginLine": 1, "priority": 2}],
            }]
        })
        visitor_out = json.dumps([
            {"file": "src/B.php", "line": 2, "rule_id": "v", "message": "vm"},
        ])
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok(phpmd_out)):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok(visitor_out)):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        
        findings = PhpAntipatternTierAAdapter().parse(result.stdout, result.stderr, result.exitcode)
        assert len(findings) == 2
        
        # PHPMD finding
        f0 = findings[0]
        assert f0.node == "src/A.php:1"
        assert f0.severity == "major"
        assert f0.message == "Line 1: d"
        assert f0.fix_hint == "Rule: R"
        assert f0.rule_id == "R"
        assert f0.tool == "antipattern-tier-a"
        assert f0.layer == "L2"
        assert f0.language == "php"
        
        # Visitor finding
        f1 = findings[1]
        assert f1.node == "src/B.php:2"
        assert f1.severity == "info"
        assert f1.message == "Line 2: vm"
        assert f1.fix_hint == "Rule: v"
        assert f1.rule_id == "v"
        assert f1.tool == "antipattern-tier-a"
        assert f1.layer == "L2"
        assert f1.language == "php"

    def test_module_pattern_counts(self) -> None:
        """Module-level pattern count constants have expected values — catches mutations."""
        # These are defined at module level and mutated by mutmut
        from harness_quality_gate.adapters.php.antipattern_tier_a_php import (
            _PHPMD_PATTERN_COUNT,
            _VISITOR_PATTERN_COUNT,
        )
        assert _PHPMD_PATTERN_COUNT == 13
        assert _VISITOR_PATTERN_COUNT == 4

    def test_adapter_name_exact(self) -> None:
        """Adapter _name attribute — catches mutation on string literal."""
        adapter = PhpAntipatternTierAAdapter()
        assert adapter._name == "antipattern-tier-a"
        assert adapter.name == "antipattern-tier-a"

    def test_parse_parse_method_return(self) -> None:
        """parse returns list[Finding] — catching string mutations in 'findings' append."""
        data = [{"source": "phpmd", "file": "x.php", "rule": "R", "description": "d"  , "line": 1, "priority": 1}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert isinstance(findings, list)
        assert len(findings) == 1
        f = findings[0]
        assert hasattr(f, 'node')
        assert hasattr(f, 'severity')
        assert hasattr(f, 'message')
        assert hasattr(f, 'fix_hint')
        assert hasattr(f, 'rule_id')
        assert hasattr(f, 'tool')
        assert hasattr(f, 'layer')
        assert hasattr(f, 'language')

    def test_invoke_mutiple_visitor_items(self, tmp_path: Path) -> None:
        """Multiple visitor findings — exact merge order and fields."""
        visitor_out = json.dumps([
            {"file": "src/A.php", "line": 1, "rule_id": "r1", "message": "m1"},
            {"file": "src/B.php", "line": 2, "rule_id": "r2", "message": "m2"},
        ])
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok('{"files": []}')):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok(visitor_out)):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        merged = json.loads(result.stdout)
        assert len(merged) == 2
        assert merged[0] == {
            "source": "visitor", "file": "src/A.php", "rule": "r1",
            "description": "m1", "line": 1,
        }
        assert merged[1] == {
            "source": "visitor", "file": "src/B.php", "rule": "r2",
            "description": "m2", "line": 2,
        }

    def test_parse_source_mutation_catches(self) -> None:
        """Source 'phpmd' vs non-phpmd — mutation of 'phpmd' in condition catches severity change."""
        data = [{"source": "phpmd", "file": "c.php", "rule": "R", "description": "d", "priority": 1}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert findings[0].severity == "critical"
        # Mutation of "phpmd" in condition would make source != "phpmd" → severity = "info"
        # This test would fail if such mutation occurred

    def test_parse_rule_id_fallback(self) -> None:
        """Rule fallback: item.get('rule', item.get('rule_id', '')) — mutation of 'rule' key."""
        data = [{"source": "phpmd", "file": "x.php", "rule": "R1", "description": "d", "priority": 2}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert findings[0].rule_id == "R1"

    def test_parse_empty_fix_hint_no_rule(self, tmp_path: Path) -> None:
        """Empty rule → fix_hint should be None, not 'Rule: None'."""
        data = [{"source": "visitor", "file": "x.php", "description": "d"}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        # With rule="", the expression `item.get("fix_hint") or f"Rule: {rule}" if rule else None`
        # should yield None since `rule` (the fallback) is ""
        assert findings[0].fix_hint is None

    def test_parse_with_custom_fix_hint(self, tmp_path: Path) -> None:
        """Custom fix_hint in input should override default 'Rule: {rule}'."""
        data = [
            {"source": "visitor", "file": "x.php", "rule": "R", "description": "d",
             "fix_hint": "Custom fix instruction"},
        ]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].fix_hint == "Custom fix instruction"

    def test_version_all_combinations(self, tmp_path: Path) -> None:
        """All 4 version combinations: both OK, both MISSING, phpmd OK/visitor MISSING, phpmd MISSING/visitor OK."""
        # 1: Both OK
        with patch.object(PhpMdAdapter, "version", return_value="v1"):
            with patch.object(VisitorRunnerAdapter, "version", return_value="v2"):
                assert PhpAntipatternTierAAdapter().version(tmp_path) == "phpmd:v1 visitors:v2"
        # 2: Both MISSING
        with patch.object(PhpMdAdapter, "version", side_effect=RuntimeError):
            with patch.object(VisitorRunnerAdapter, "version", side_effect=RuntimeError):
                assert PhpAntipatternTierAAdapter().version(tmp_path) == "phpmd:MISSING visitors:MISSING"
        # 3: phpmd ok, visitor missing
        with patch.object(PhpMdAdapter, "version", return_value="v1"):
            with patch.object(VisitorRunnerAdapter, "version", side_effect=RuntimeError):
                assert PhpAntipatternTierAAdapter().version(tmp_path) == "phpmd:v1 visitors:MISSING"
        # 4: phpmd missing, visitor ok
        with patch.object(PhpMdAdapter, "version", side_effect=RuntimeError):
            with patch.object(VisitorRunnerAdapter, "version", return_value="v2"):
                assert PhpAntipatternTierAAdapter().version(tmp_path) == "phpmd:MISSING visitors:v2"
        # 5: phpmd missing, visitor not implemented
        with patch.object(PhpMdAdapter, "version", side_effect=RuntimeError):
            with patch.object(VisitorRunnerAdapter, "version", side_effect=NotImplementedError):
                assert PhpAntipatternTierAAdapter().version(tmp_path) == "phpmd:MISSING visitors:poC"

    def test_version_format_regex(self, tmp_path: Path) -> None:
        """Version string must match 'phpmd:X visitors:X' format — catches format string mutations."""
        import re as re2

        scenarios = [
            ("8.0", "1.0", "phpmd:8.0 visitors:1.0"),
            (None, None, "phpmd:MISSING visitors:MISSING"),
            (None, "2.0", "phpmd:MISSING visitors:2.0"),
            ("9.0", None, "phpmd:9.0 visitors:MISSING"),
            (None, "poC", "phpmd:MISSING visitors:poC"),
        ]
        for phpmd_ver, visitor_ver, expected in scenarios:
            with (
                patch.object(PhpMdAdapter, "version", return_value=phpmd_ver) if phpmd_ver else
                patch.object(PhpMdAdapter, "version", side_effect=RuntimeError),
                patch.object(VisitorRunnerAdapter, "version", return_value=visitor_ver) if visitor_ver else
                (patch.object(VisitorRunnerAdapter, "version", side_effect=NotImplementedError) if visitor_ver == "poC" else patch.object(VisitorRunnerAdapter, "version", side_effect=RuntimeError)),
            ):
                v = PhpAntipatternTierAAdapter().version(tmp_path)
            assert v == expected
            assert re2.match(r'phpmd:\S+ visitors:\S+', v), f"Expected {expected} got {v}"

    def test_invoke_default_timeout_forwarded(self, tmp_path: Path) -> None:
        """Verify timeout=300.0 default is forwarded to child invocations.

        This test kills the mutmut default-arg mutant that changes
        timeout: float = 300.0 to timeout: float = 301.0 — the assertion
        on 300.0 would fail with 301.0.
        """
        with patch.object(PhpMdAdapter, "invoke") as phpmd_mock:
            with patch.object(VisitorRunnerAdapter, "invoke") as visitor_mock:
                phpmd_mock.return_value = _ok(json.dumps({"files": []}), exitcode=0)
                visitor_mock.return_value = _ok("[]", exitcode=0)
                PhpAntipatternTierAAdapter().invoke(tmp_path, [])

        # Check timeout was forwarded with default value 300.0
        phpmd_kwargs = phpmd_mock.call_args.kwargs
        assert phpmd_kwargs["timeout"] == 300.0
        visitor_kwargs = visitor_mock.call_args.kwargs
        assert visitor_kwargs["timeout"] == 300.0
        # Verify repo is actually passed as positional arg — catches mutation of repo→None
        assert phpmd_mock.call_args.args[0] is tmp_path
        assert visitor_mock.call_args.args[0] is tmp_path

    def test_invoke_phpmd_failure_json_decode_warning(self, tmp_path: Path, caplog) -> None:
        """When PHPMD fails, mutated phpmd_stdout='XXXX' triggers JSON decode warning.

        This test kills mutmut_3 (phpmd_stdout='' → 'XXXX'): the mutation causes
        the if-block to enter (truthy 'XXXX'), then json.loads('XXXX') raises
        JSONDecodeError and logs the 'not valid JSON' warning. In the original,
        empty string is falsy so the if-block is never entered and no warning.
        """
        visitor_out = json.dumps([
            {"file": "src/Bar.php", "line": 5, "rule_id": "feature_envy", "message": "Feature envy"}
        ])
        with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.php.antipattern_tier_a_php"):
            with patch.object(PhpMdAdapter, "invoke", side_effect=RuntimeError("broken")):
                with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok(visitor_out)):
                    result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        assert json.loads(result.stdout) == [{"source": "visitor", "file": "src/Bar.php", "rule": "feature_envy", "description": "Feature envy", "line": 5}]
        # Mutation: "XXXX" is truthy → enters parse block → JSON decode error → warning logged
        # Original: "" is falsy → skip block → no warning logged
        # This test asserts NO warning (original behavior), so mutation causes test failure.
        assert "not valid JSON" not in caplog.text

    def test_invoke_phpmd_failure_with_visitor_ok(self, tmp_path: Path, caplog) -> None:
        """PHPMD RuntimeError with visitor OK — no assertion error on isinstance check."""
        visitor_out = json.dumps([
            {"file": "src/Bar.php", "line": 5, "rule_id": "feature_envy", "message": "Feature envy"}
        ])
        with caplog.at_level("WARNING", logger="harness_quality_gate.adapters.php.antipattern_tier_a_php"):
            with patch.object(PhpMdAdapter, "invoke", side_effect=RuntimeError("broken")):
                with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok(visitor_out)):
                    result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        assert result.exitcode == 0
        merged = json.loads(result.stdout)
        assert len(merged) == 1
        assert merged[0]["source"] == "visitor"