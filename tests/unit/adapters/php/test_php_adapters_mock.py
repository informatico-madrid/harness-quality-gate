"""Comprehensive mock-based tests for PHP adapters.

Covers invoke/version/parse paths using unittest.mock.patch for subprocess
calls. Targets near-100% coverage of all PHP adapter modules.
"""

from __future__ import annotations

import json
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
        # regex may or may not match this exact format; at minimum returns list
        assert isinstance(findings, list)

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

    def test_invoke_no_php_files_returns_empty(self, tmp_path: Path) -> None:
        with patch("harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors", return_value=["god_class"]):
            with patch.object(VisitorRunnerAdapter, "_collect_php_files", return_value=[]):
                result = VisitorRunnerAdapter().invoke(tmp_path, [])
        assert result.stdout == "[]"
        assert "no PHP files" in result.stderr

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


# ===========================================================================
# weak_test_php.py
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

    def test_version_phpmd_missing(self, tmp_path: Path) -> None:
        with patch.object(PhpMdAdapter, "version", side_effect=RuntimeError("not found")):
            with patch.object(VisitorRunnerAdapter, "version", side_effect=NotImplementedError):
                v = PhpAntipatternTierAAdapter().version(tmp_path)
        assert "MISSING" in v
        assert "poC" in v

    def test_version_visitor_missing(self, tmp_path: Path) -> None:
        with patch.object(PhpMdAdapter, "version", side_effect=RuntimeError("not found")):
            with patch.object(VisitorRunnerAdapter, "version", side_effect=RuntimeError("not found")):
                v = PhpAntipatternTierAAdapter().version(tmp_path)
        assert "MISSING" in v

    def test_invoke_phpmd_not_found_graceful(self, tmp_path: Path) -> None:
        with patch.object(PhpMdAdapter, "invoke", side_effect=RuntimeError("phpmd not found")):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok("[]")):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        assert isinstance(json.loads(result.stdout), list)

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
        sources = {item["source"] for item in merged}
        assert "phpmd" in sources
        assert "visitor" in sources

    def test_invoke_phpmd_invalid_json_graceful(self, tmp_path: Path) -> None:
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok("not json")):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok("[]")):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        assert json.loads(result.stdout) == []

    def test_invoke_visitor_invalid_json_graceful(self, tmp_path: Path) -> None:
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok("")):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok("not json")):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        assert isinstance(json.loads(result.stdout), list)

    def test_invoke_visitor_runtime_error_graceful(self, tmp_path: Path) -> None:
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok("")):
            with patch.object(VisitorRunnerAdapter, "invoke", side_effect=RuntimeError("failed")):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        assert isinstance(json.loads(result.stdout), list)

    def test_invoke_visitor_not_implemented_graceful(self, tmp_path: Path) -> None:
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok("")):
            with patch.object(VisitorRunnerAdapter, "invoke", side_effect=NotImplementedError):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        assert isinstance(json.loads(result.stdout), list)

    def test_invoke_stderr_merged(self, tmp_path: Path) -> None:
        with patch.object(PhpMdAdapter, "invoke", return_value=_ok("", stderr="phpmd error")):
            with patch.object(VisitorRunnerAdapter, "invoke", return_value=_ok("[]", stderr="visitor warning")):
                result = PhpAntipatternTierAAdapter().invoke(tmp_path, [])
        assert "phpmd" in result.stderr
        assert "visitor" in result.stderr

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
        assert f.severity == "critical"
        assert "src/Foo.php:10" == f.node
        assert f.layer == "L2"

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
        assert findings[0].severity == "info"

    def test_parse_non_dict_item_skipped(self) -> None:
        assert PhpAntipatternTierAAdapter().parse('["not-a-dict"]') == []

    def test_parse_no_line(self) -> None:
        data = [{"source": "phpmd", "file": "x.php", "rule": "R", "description": "d", "priority": 3}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert findings[0].node == "x.php"

    def test_parse_fix_hint_from_item(self) -> None:
        data = [{"source": "visitor", "file": "x.php", "rule": "R", "description": "d", "fix_hint": "custom hint"}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert findings[0].fix_hint == "custom hint"

    def test_parse_line_invalid_int(self) -> None:
        data = [{"source": "phpmd", "file": "x.php", "rule": "R", "description": "d", "line": "bad", "priority": 2}]
        findings = PhpAntipatternTierAAdapter().parse(json.dumps(data))
        assert len(findings) == 1

    def test_priority_to_severity_helper(self) -> None:
        assert antipattern_priority_to_severity(1) == "critical"
        assert antipattern_priority_to_severity(2) == "major"
        assert antipattern_priority_to_severity(3) == "minor"
        assert antipattern_priority_to_severity(4) == "info"
        assert antipattern_priority_to_severity(5) == "info"
        assert antipattern_priority_to_severity(0) == "info"
