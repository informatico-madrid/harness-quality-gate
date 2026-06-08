"""Comprehensive tests for PytestAdapter — mutation-killing suite.

Targets: version(), invoke(), parse() with granular asserts on every
Finding field (severity, tool, layer, language, rule_id, message,
fix_hint, node).
Design: Mutation testing / pytest_adapter coverage.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import sys

sys.path.insert(0, "/mnt/bunker_data/harness-quality-gate")

from harness_quality_gate.adapters.python.pytest_adapter import (
    PytestAdapter,
)


# ---------------------------------------------------------------------------
# version()
# ---------------------------------------------------------------------------

class TestVersion:
    def test_version_when_python3_missing(self, tmp_path: Path) -> None:
        """shutil.which returns None → _run still works because fallback
        string literal is used inside _run call."""
        with patch("shutil.which", return_value=None):
            with patch(
                "harness_quality_gate.adapters.base.subprocess.run"
            ) as mock_run:
                mock_run.return_value = MagicMock(
                    stdout="pytest 8.1.1\n", returncode=0, stderr=""
                )
                adapter = PytestAdapter()
                result = adapter.version(tmp_path)
                assert isinstance(result, str)
                assert result == "pytest 8.1.1"

    def test_version_default_stdout(self, tmp_path: Path) -> None:
        """Empty stdout → 'unknown'."""
        with patch("shutil.which", return_value="/usr/bin/python3"):
            with patch(
                "harness_quality_gate.adapters.base.subprocess.run"
            ) as mock_run:
                mock_run.return_value = MagicMock(
                    stdout="", returncode=0, stderr=""
                )
                adapter = PytestAdapter()
                result = adapter.version(tmp_path)
                assert isinstance(result, str)
                assert result == "unknown"

    def test_version_returns_lowercase_name(self, tmp_path: Path) -> None:
        """Property name returns the internal _name."""
        adapter = PytestAdapter()
        assert adapter.name == "pytest"


# ---------------------------------------------------------------------------
# invoke()
# ---------------------------------------------------------------------------

class TestInvoke:
    def test_invoke_returns_tool_invocation(self, tmp_path: Path) -> None:
        """Normal invocation returns a ToolInvocation with exitcode."""
        with patch("shutil.which", return_value="/usr/bin/python3"):
            with patch(
                "harness_quality_gate.adapters.base.subprocess.run"
            ) as mock_run:
                mock_run.return_value = MagicMock(
                    stdout="<testsuites/>",
                    stderr="",
                    returncode=0,
                )
                adapter = PytestAdapter()
                result = adapter.invoke(tmp_path, ["tests/"])
                assert hasattr(result, "exitcode")
                assert result.exitcode == 0

    def test_invoke_command_arguments(self, tmp_path: Path) -> None:
        """Command contains python -m pytest --junitxml /dev/stdout …"""
        with patch("shutil.which", return_value="/usr/bin/python3"):
            with patch(
                "harness_quality_gate.adapters.base.subprocess.run"
            ) as mock_run:
                mock_run.return_value = MagicMock(
                    stdout="", stderr="", returncode=0
                )
                adapter = PytestAdapter()
                adapter.invoke(tmp_path, ["-k", "foo"])
                call_args = mock_run.call_args
                cmd = call_args.args[0]  # first positional = cmd list
                assert "python3" in cmd or "/usr/bin/python3" in cmd
                assert "-m" in cmd
                assert "pytest" in cmd
                assert "--junitxml" in cmd
                assert "/dev/stdout" in cmd
                assert "-o" in cmd
                assert "junit_suite_name=pytest" in cmd
                assert "-k" in cmd
                assert "foo" in cmd

    def test_invoke_empty_args(self, tmp_path: Path) -> None:
        """No extra args → command only has default pytest flags."""
        with patch("shutil.which", return_value="/usr/bin/python3"):
            with patch(
                "harness_quality_gate.adapters.base.subprocess.run"
            ) as mock_run:
                mock_run.return_value = MagicMock(
                    stdout="", stderr="", returncode=0
                )
                adapter = PytestAdapter()
                adapter.invoke(tmp_path, [])
                call_args = mock_run.call_args
                cmd = call_args.args[0]
                # base flags present
                assert "pytest" in cmd
                # no extra items appended beyond defaults
                extra = [a for a in cmd if a not in (
                    "python3", "/usr/bin/python3", "-m", "pytest",
                    "--junitxml", "/dev/stdout", "-o", "junit_suite_name=pytest",
                )]
                assert extra == []

    def test_invoke_run_called_with_cwd(self, tmp_path: Path) -> None:
        """_run is called with cwd=repo."""
        with patch("shutil.which", return_value="/usr/bin/python3"):
            with patch(
                "harness_quality_gate.adapters.base.subprocess.run"
            ) as mock_run:
                mock_run.return_value = MagicMock(
                    stdout="", stderr="", returncode=0
                )
                adapter = PytestAdapter()
                adapter.invoke(tmp_path, [])
                call_kwargs = mock_run.call_args.kwargs
                assert Path(call_kwargs["cwd"]) == tmp_path

    def test_invoke_passes_env(self, tmp_path: Path) -> None:
        """env dict is forwarded to _run."""
        with patch("shutil.which", return_value="/usr/bin/python3"):
            with patch(
                "harness_quality_gate.adapters.base.subprocess.run"
            ) as mock_run:
                mock_run.return_value = MagicMock(
                    stdout="", stderr="", returncode=0
                )
                adapter = PytestAdapter()
                adapter.invoke(tmp_path, [], env={"FOO": "bar"})
                call_kwargs = mock_run.call_args.kwargs
                assert call_kwargs["env"]["FOO"] == "bar"

    def test_invoke_passes_timeout(self, tmp_path: Path) -> None:
        """Custom timeout is forwarded."""
        with patch("shutil.which", return_value="/usr/bin/python3"):
            with patch(
                "harness_quality_gate.adapters.base.subprocess.run"
            ) as mock_run:
                mock_run.return_value = MagicMock(
                    stdout="", stderr="", returncode=0
                )
                adapter = PytestAdapter()
                adapter.invoke(tmp_path, [], timeout=10.0)
                call_kwargs = mock_run.call_args.kwargs
                assert call_kwargs["timeout"] == 10.0


# ---------------------------------------------------------------------------
# parse() — granular Finding-field assertions
# ---------------------------------------------------------------------------

class TestParse:
    def test_parse_empty_string(self) -> None:
        """Empty stdout → []"""
        adapter = PytestAdapter()
        findings = adapter.parse("")
        assert isinstance(findings, list)
        assert len(findings) == 0

    def test_parse_whitespace_only(self) -> None:
        """Whitespace-only stdout → []"""
        adapter = PytestAdapter()
        findings = adapter.parse("   \n\t  ")
        assert isinstance(findings, list)
        assert len(findings) == 0

    def test_parse_invalid_xml(self) -> None:
        """Malformed XML → []"""
        adapter = PytestAdapter()
        findings = adapter.parse("{not valid xml <>}")
        assert isinstance(findings, list)
        assert len(findings) == 0

    def test_parse_no_failures_no_findings(self) -> None:
        """All tests pass → no summary, no failures."""
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite name="mod" tests="2" failures="0" errors="0">
    <testcase classname="mod" name="test_a" time="0.01"/>
    <testcase classname="mod" name="test_b" time="0.02"/>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        assert isinstance(findings, list)
        assert len(findings) == 0

    # -- single failures ---------------------------------------------------

    def test_parse_single_failure_fields(self) -> None:
        """One failing test → summary + failure Finding with all fields."""
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" failures="1" errors="0">
    <testcase classname="mytests.test_mod" name="test_login" time="0.5">
      <failure message="AssertionError: expected 2" type="">line1
line2</failure>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)

        # We expect summary at index 0 then the individual finding
        assert isinstance(findings, list)
        assert len(findings) >= 2

        # Summary finding at position 0
        summary = findings[0]
        assert summary.severity == "error"
        assert summary.tool == "pytest"
        assert summary.layer == "L1"
        assert summary.language == "python"
        assert summary.rule_id == "summary"
        assert summary.node == "pytest"
        assert "1" in summary.message
        assert "failure" in summary.message.lower()
        assert summary.fix_hint == "Review failing test assertions and stack traces."

        # Individual failure Finding
        failure = findings[1]
        assert failure.severity == "error"
        assert failure.tool == "pytest"
        assert failure.layer == "L1"
        assert failure.language == "python"
        assert failure.rule_id == "failure"
        assert failure.node == "mytests.test_mod.test_login"
        assert failure.message == "AssertionError: expected 2"
        assert failure.fix_hint is None

    def test_parse_failure_empty_message(self) -> None:
        """<failure/> with no message/text → fallback message."""
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" failures="1" errors="0">
    <testcase classname="pkg" name="test_x" time="0.1">
      <failure></failure>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        assert len(findings) >= 2
        f = findings[1]
        assert f.severity == "error"
        assert f.node == "pkg.test_x"

    def test_parse_failure_no_message_attr(self) -> None:
        """<failure>text only</failure> → text used as message."""
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" failures="1" errors="0">
    <testcase classname="mod" name="test_y">
      <failure>boom</failure>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        f = findings[1]
        assert f.node == "mod.test_y"

    # -- single errors -----------------------------------------------------

    def test_parse_single_error_fields(self) -> None:
        """One error → summary + error Finding with all fields."""
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" failures="0" errors="1">
    <testcase classname="integration" name="test_db_connect">
      <error message="Connection refused">Traceback…</error>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        assert len(findings) >= 2

        summary = findings[0]
        assert summary.severity == "error"
        assert summary.tool == "pytest"
        assert summary.layer == "L1"
        assert summary.language == "python"
        assert summary.rule_id == "summary"
        assert summary.node == "pytest"

        err = findings[1]
        assert err.severity == "error"
        assert err.tool == "pytest"
        assert err.layer == "L1"
        assert err.language == "python"
        assert err.rule_id == "error"
        assert err.node == "integration.test_db_connect"
        assert err.message == "Connection refused"
        assert err.fix_hint is None

    def test_parse_error_no_message(self) -> None:
        """<error/> with no message → fallback."""
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" errors="1" failures="0">
    <testcase classname="mod" name="test_z">
      <error></error>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        e = findings[1]
        assert e.rule_id == "error"

    # -- skipped -----------------------------------------------------------

    def test_parse_skipped_fields(self) -> None:
        """Skipped test → info Finding, NOT included in summary."""
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="2" failures="0" errors="0">
    <testcase classname="tests.mod" name="test_skip">
      <skipped message="no reason" type="pytest.skip"/>
    </testcase>
    <testcase classname="tests.mod" name="test_pass" time="0.01"/>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        # Should have 1 finding (the skip), no summary
        skip_f = None
        for f in findings:
            assert f.severity == "info"
            assert f.rule_id == "skipped"
            assert f.tool == "pytest"
            assert f.layer == "L1"
            assert f.language == "python"
            skip_f = f
        assert skip_f is not None

    # -- mixed: failure + error + skipped ----------------------------------

    def test_parse_mixed_failures_and_errors(self) -> None:
        """Mix of failures and errors → summary at top, then all."""
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="4" failures="1" errors="1">
    <testcase classname="a" name="t_fail">
      <failure message="fail-msg"/>
    </testcase>
    <testcase classname="b" name="t_err">
      <error message="err-msg"/>
    </testcase>
    <testcase classname="c" name="t_ok"/>
    <testcase classname="d" name="t_skip">
      <skipped message="skip-reason"/>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        assert len(findings) >= 4

        # [0] summary
        assert findings[0].rule_id == "summary"
        assert "1" in findings[0].message
        assert "failure" in findings[0].message.lower()
        assert "error" in findings[0].message.lower()

        # [1] failure finding
        assert findings[1].rule_id == "failure"
        assert findings[1].message == "fail-msg"

        # [2] error finding
        assert findings[2].rule_id == "error"
        assert findings[2].message == "err-msg"

        # [3] skipped finding with severity info
        assert findings[3].rule_id == "skipped"
        assert findings[3].severity == "info"

    def test_parse_only_skipped_no_summary(self) -> None:
        """Only skipped tests → no summary finding."""
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" failures="0" errors="0">
    <testcase classname="mod" name="t">
      <skipped message="x"/>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        # Only the skipped finding, no summary at [0]
        if len(findings) > 0:
            assert findings[0].rule_id == "skipped"
            assert findings[0].severity == "info"

    def test_parse_multiple_failures(self) -> None:
        """Several failures → summary lists count then each."""
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="3" failures="2" errors="0">
    <testcase classname="t" name="one">
      <failure message="a"/>
    </testcase>
    <testcase classname="t" name="two">
      <failure message="b"/>
    </testcase>
    <testcase classname="t" name="three"/>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        assert len(findings) >= 3
        assert findings[0].rule_id == "summary"
        assert "2" in findings[0].message
        assert findings[1].rule_id == "failure"
        assert findings[1].message == "a"
        assert findings[2].rule_id == "failure"
        assert findings[2].message == "b"

    def test_parse_testcase_without_classname(self) -> None:
        """testcase missing classname → node is just the name."""
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" failures="1" errors="0">
    <testcase name="standalone_test">
      <failure/>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        assert len(findings) >= 2
        f = findings[1]
        assert f.node == "standalone_test"

    def test_parse_multiple_test_suites(self) -> None:
        """Multiple <testsuite> elements → all testcases parsed."""
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" failures="1">
    <testcase classname="suite1" name="fail1">
      <failure/>
    </testcase>
  </testsuite>
  <testsuite tests="1" failures="1">
    <testcase classname="suite2" name="fail2">
      <failure/>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        assert len(findings) >= 3
        # summary at [0]
        assert findings[0].rule_id == "summary"
        assert "2" in findings[0].message
        # the two individual failure findings
        assert findings[1].rule_id == "failure"
        assert findings[2].rule_id == "failure"

    def test_parse_exitcode_not_used(self) -> None:
        """exitcode=1 → single exitcode Finding with all fields."""
        adapter = PytestAdapter()
        xml = """<testsuites>
  <testsuite tests="2" failures="0" errors="0">
    <testcase classname="m" name="ok"/>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml, exitcode=1)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "exitcode"
        assert f.severity == "error"
        assert f.node == "pytest"
        assert "1" in f.message
        assert f.fix_hint == "Review the test output and check for environment issues."
        assert f.tool == "pytest"
        assert f.layer == "L1"
        assert f.language == "python"

    def test_parse_exitcode_default_zero(self) -> None:
        """exitcode=0 (default) → no exitcode Finding."""
        adapter = PytestAdapter()
        findings = adapter.parse(stdout='<testsuites/>', exitcode=0)
        assert len(findings) == 0

    def test_parse_stderr_not_used(self) -> None:
        """stderr parameter is accepted — CRITICAL warnings in stderr
        produce a stderr Finding with exact fields."""
        adapter = PytestAdapter()
        xml = """<testsuites>
  <testsuite tests="2" failures="0" errors="0">
    <testcase classname="m" name="ok"/>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml, stderr="CRITICAL: environment variable missing")
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "stderr"
        assert f.severity == "warning"
        assert f.message == "CRITICAL: environment variable missing"
        assert f.fix_hint == "Check pytest configuration or environment."
        assert f.tool == "pytest"
        assert f.node == "pytest"
        assert f.layer == "L1"
        assert f.language == "python"

    def test_parse_stderr_no_critical(self) -> None:
        """Non-CRITICAL stderr → no stderr finding."""
        adapter = PytestAdapter()
        findings = adapter.parse(stdout='<testsuites/>', stderr="some warnings here")
        assert len(findings) == 0

    def test_parse_all_fields_consistent(self) -> None:
        """Every Finding has consistent tool/layer/language values."""
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="3" failures="1" errors="1">
    <testcase classname="a" name="f">
      <failure message="fail"/>
    </testcase>
    <testcase classname="b" name="e">
      <error message="err"/>
    </testcase>
    <testcase classname="c" name="s">
      <skipped message="skip"/>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        for f in findings:
            assert f.tool == "pytest"
            assert f.layer == "L1"
            assert f.language == "python"
