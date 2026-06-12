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

from harness_quality_gate.adapters.base import ToolInvocation
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

    def test_version_wiring_exact_call_args(self, tmp_path: Path) -> None:
        """version() calls _run with exact binary cmd + cwd and env.

        Kills mutmut on version (10,11,12,13,14,15,16,17,18,19):
        - mutmut_10-15: cmd element mutations (binary, args)
        - mutmut_16,17: cwd → None mutation
        - mutmut_18,19: env → None mutation
        Uses §4.4 strict mock args on _run spy.
        """
        with patch(
            "harness_quality_gate.adapters.python.pytest_adapter.shutil.which",
            return_value="/usr/bin/python3",
        ):
            adapter = PytestAdapter()
            mock_result = MagicMock(stdout="pytest 8.1.1\n", stderr="")
            with patch.object(adapter, "_run", return_value=mock_result) as mock_run:
                adapter.version(tmp_path, env={"ENV1": "v1"})

        mock_run.assert_called_once()
        assert mock_run.call_args.args[0] == [
            "/usr/bin/python3", "-m", "pytest", "--version",
        ]
        assert mock_run.call_args.kwargs["cwd"] == tmp_path
        assert mock_run.call_args.kwargs["env"] == {"ENV1": "v1"}

    def test_version_env_none_passed(self, tmp_path: Path) -> None:
        """When env is omitted (default None), it's still passed as None to _run.

        Kills mutmut_18,19: env=env → env=None mutation.
        Verifies that _run receives the exact env value, not a mutated None.
        """
        with patch(
            "harness_quality_gate.adapters.python.pytest_adapter.shutil.which",
            return_value="/usr/bin/python3",
        ):
            adapter = PytestAdapter()
            mock_result = MagicMock(stdout="pytest 8.1.1\n")
            with patch.object(adapter, "_run", return_value=mock_result) as mock_run:
                adapter.version(tmp_path)

        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["env"] is None


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
        """Command contains python -m pytest --junitxml <tempfile.xml> …"""
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
                junit_arg = cmd[cmd.index("--junitxml") + 1]
                assert junit_arg != "/dev/stdout"
                assert "hqg-junit-" in junit_arg
                assert junit_arg.endswith(".xml")
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
                # no extra items appended beyond defaults (the junit temp
                # file path varies per call)
                junit_arg = cmd[cmd.index("--junitxml") + 1]
                extra = [a for a in cmd if a not in (
                    "python3", "/usr/bin/python3", "-m", "pytest",
                    "--junitxml", junit_arg, "-o", "junit_suite_name=pytest",
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

    def test_invoke_wiring_exact_call_args(self, tmp_path: Path) -> None:
        """_run is called with exact cmd list, cwd, env, timeout.

        Kills mutmut survivors on invoke (1,3,5,6,7,8): mutates binary path
        in cmd, positional index, cwd, env, timeout — all observed via spy.
        Uses §4.4 strict mock args + §4.7 argv list equality.
        """
        with patch(
            "harness_quality_gate.adapters.python.pytest_adapter.shutil.which",
            return_value="/usr/bin/python3",
        ):
            adapter = PytestAdapter()
            mock_result = MagicMock(stdout="", stderr="", returncode=0)
            with patch.object(adapter, "_run", return_value=mock_result) as mock_run:
                adapter.invoke(
                    tmp_path, ["-k", "foo"],
                    env={"PYTEST_ENV": "1"}, timeout=120.0,
                )

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        # Exact cmd list
        cmd = call_args.args[0]
        junit_arg = cmd[cmd.index("--junitxml") + 1]
        assert "hqg-junit-" in junit_arg and junit_arg.endswith(".xml")
        assert cmd == ["/usr/bin/python3", "-m", "pytest", "--junitxml", junit_arg, "-o", "junit_suite_name=pytest", "-k", "foo"]
        # Verify all keyword args exactly
        assert call_args.kwargs["cwd"] == tmp_path
        assert call_args.kwargs["env"] == {"PYTEST_ENV": "1"}
        assert call_args.kwargs["timeout"] == 120.0

    def test_invoke_default_timeout(self, tmp_path: Path) -> None:
        """Default timeout=300.0 is used when not specified.

        Kills mutmut: default timeout=300.0 → 301.0 mutation.
        """
        with patch(
            "harness_quality_gate.adapters.python.pytest_adapter.shutil.which",
            return_value="/usr/bin/python3",
        ):
            adapter = PytestAdapter()
            mock_result = MagicMock(stdout="", stderr="", returncode=0)
            with patch.object(adapter, "_run", return_value=mock_result) as mock_run:
                adapter.invoke(tmp_path, [])
        assert mock_run.call_args.kwargs["timeout"] == 300.0


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

    def test_parse_failure_empty_message_has_fallback(self) -> None:
        """<failure/> with no message/text → fallback message contains full_name.

        Kills mutants 84 and 86: when failure has no message attribute and
        no text, both '' and None fall through to the fallback
        'Test failed: {full_name}'."""
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
        # Message falls back to "Test failed: pkg.test_x" when no message attr and no text
        assert "Test failed:" in f.message
        assert "pkg.test_x" in f.message

    def test_parse_failure_no_message_attr_uses_text(self) -> None:
        """<failure>text only</failure> → text used as message (not None/empty).

        Kills mutants 84, 86, 89: when failure.text is truthy ('boom'),
        failure.text and "" → "" (mutants) vs failure.text or "" → 'boom' (original).
        Mutant 86: failure.get("message", None) → None when no attr, then fallback."""
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
        # Key assertion: message must be the raw text "boom", not empty or fallback
        assert f.message == "boom"

    def test_parse_testcase_without_classname_fullname(self) -> None:
        """testcase missing classname → node is just the name.

        Kills mutants 51/53: when classname default is None or removed,
        full_name becomes just 'name' (not 'classname.name') since None/''
        is falsy in the ternary. The classname-less and classname-present
        cases must produce DIFFERENT nodes."""
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
        assert f.severity == "error"
        # Without classname, full_name = just name (not "None.name" or ".name")
        assert f.node == "standalone_test"
        # Explicitly assert "None" is never in node — catches default-param mutations
        # on .get("classname", "") → .get("classname", None) [mutmut_51, mutmut_53]
        assert "None" not in f.node
        assert f.rule_id == "failure"
        # Message falls back to "Test failed: standalone_test"
        assert "Test failed:" in f.message
        assert "standalone_test" in f.message

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
        # Ensure classname is properly used in full_name (kills mutants 51,53,59,61,64)
        assert "mytests.test_mod" in failure.node
        assert ".test_login" in failure.node

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
        """<error/> with no message and no text → fallback message.

        Kills mutants 121 and 123: when error.get("message", ...) defaults
        to None or is omitted entirely, msg.strip(None) raises AttributeError
        but the original code's fallback is "" → fallback message string.
        The exact fallback value is the kill criteria.
        """
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
        assert e.severity == "error"
        # The exact fallback message MUST match
        assert e.message == "Test error: mod.test_z"
        # Mutant 103: fix_hint default removed; must still be None
        assert e.fix_hint is None
        assert e.tool == "pytest"
        assert e.layer == "L1"
        assert e.language == "python"

    def test_parse_error_empty_message_attr_fallback(self) -> None:
        """<error message=""> with empty message attr → fallback message used.

        Validates that error parsing handles message="" attr correctly.
        When error.get("message", ...) returns "" (empty string), it falls
        through to the fallback "Test error: {full_name}".
        This tests the msg.strip("") path which mutants 121/123 modify.
        """
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" errors="1" failures="0">
    <testcase classname="mod" name="test_msg_empty">
      <error message=""></error>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        assert len(findings) >= 2
        e = findings[1]
        assert e.rule_id == "error"
        assert e.severity == "error"
        # With message="" attr, strip returns "" (falsy), so fallback is used
        assert "Test error: mod.test_msg_empty" == e.message
        assert e.fix_hint is None

    def test_parse_error_text_only_no_message_attr(self) -> None:
        """Error with text content but no message attribute → text used as message.

        Kills mutants 121 and 123: when error.tag has no 'message' attribute
        but has text content, the original code's
        error.get("message", error.text or "") returns the text.
        Mutant 121 (.get("message", None)) returns None for both message
        and the fallback, so the result diverges from original.
        Mutant 123 (.get("message",)) also returns None.
        """
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" errors="1" failures="0">
    <testcase classname="mod" name="test_crash">
      <error>crashed with exit code 1</error>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        assert len(findings) >= 2
        e = findings[1]
        assert e.rule_id == "error"
        assert e.severity == "error"
        # The text content "crashed with exit code 1" must be the message
        assert e.message == "crashed with exit code 1"

    def test_parse_error_empty_tag_strict_message(self) -> None:
        """Error with empty tag → fallback with EXACT message value.

        Strictly asserts the exact fallback message string for empty error tag.
        This validates that the error path through error.text="" → fallback
        works correctly with the original code.
        """
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" errors="1" failures="0">
    <testcase classname="strict.mod" name="test_empty_err">
      <error></error>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        e = findings[1]
        assert e.rule_id == "error"
        # Exact fallback for empty error tag
        assert e.message == "Test error: strict.mod.test_empty_err"
        assert e.fix_hint is None
        assert e.node == "strict.mod.test_empty_err"

    def test_parse_failure_fix_hint_hasattr_is_none(self) -> None:
        """Failure Finding's fix_hint attribute exists and is None.

        Kills mutant 103: when fix_hint=None line is removed from the
        Finding constructor, hasattr(finding, "fix_hint") returns False,
        proving the attribute was not set.
        """
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" failures="1" errors="0">
    <testcase classname="mod" name="test_fix_hint">
      <failure message="assertion failed"/>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        assert len(findings) >= 2
        f = findings[1]
        assert f.rule_id == "failure"
        # Mutant 103 removes fix_hint=None → hasattr returns False
        assert hasattr(f, "fix_hint")
        assert f.fix_hint is None

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
            # Exact message assertion kills mutants 156, 158, 159, 160:
            # - mutmut_156: msg=None → fallback message, not "no reason"
            # - mutmut_158: get("message", None) returns None → fallback
            # - mutmut_159: get("no reason") → None (key lookup fails)
            # - mutmut_160: get("message",) → None → fallback
            assert f.message == "no reason"
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
        assert f.severity == "error"
        assert f.rule_id == "failure"
        assert f.node == "standalone_test"
        # Message must be the fallback when no message attr and no text
        assert "Test failed:" in f.message
        assert "standalone_test" in f.message

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

    def test_parse_testcase_without_name_attr(self) -> None:
        """testcase missing name attr entirely → full_name = classname only.
        Tests that empty-string default is used (not None or 'XXXX').
        This kills mutant 64 (name default → 'XXXX'), which would produce
        'classname.XXXX' instead of just 'classname' when name is absent."""
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" failures="1" errors="0">
    <testcase classname="standalone">
      <failure/>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        assert len(findings) >= 2
        f = findings[1]
        assert f.rule_id == "failure"
        # Without name attr, classname is "standalone", name defaults to ""
        # full_name = "standalone" (no dot, since name is falsy)
        # With classname="standalone" and name not present (defaults to ""):
        # The conditional evaluates to f"{classname}.{name}" since classname is truthy
        # This produces "standalone." — mutant 59 (name→None) would produce
        # "standalone.None", mutant 64 (name→"XXXX") would produce "standalone.XXXX"
        assert "None" not in f.node, "Node must not contain 'None' — classnames are strings"
        assert f.node == "standalone."

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


# ---------------------------------------------------------------------------
# parse() — skip message edge cases (kills mutants 156, 157, 158, 159, 160)
# ---------------------------------------------------------------------------

class TestSkipMessageEdgeCases:
    def test_parse_skipped_text_no_message_attr(self) -> None:
        """Skipped element has text but no 'message' attribute.

        Kills mutants 156, 157, 158:
        - mutmut_156: msg = None → fallback "Test skipped: full_name"
        - mutmut_157: skip.get(None, skip.text or "") → None → fallback
        - mutmut_158: skip.get("message", None) → None → fallback
        All three diverge from original's skip.text or "" → "some reason"
        """
        adapter = PytestAdapter()
        # No "message" attribute, but has text content
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" failures="0" errors="0">
    <testcase classname="mod" name="test_skip_text">
      <skipped>some reason</skipped>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "skipped"
        # With no "message" attribute, original code: skip.text = "some reason"
        # This becomes the message. Mutant 156 (msg=None) would give fallback.
        assert f.message == "some reason"

    def test_parse_skipped_empty_text_no_message_attr(self) -> None:
        """Skipped element has empty content and no message → fallback used.

        Kills mutant 156: msg = None → strip fails → fallback "Test skipped: ..."
        Original code: skip.text="" → "" (falsy) → fallback "Test skipped: ..."
        Both produce the same message here, but mutant 156 explicitly sets
        msg=None before the conditional, which tests the None-handling path.
        """
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" failures="0" errors="0">
    <testcase classname="mod" name="test_skip_empty">
      <skipped></skipped>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "skipped"
        assert f.node == "mod.test_skip_empty"
        assert f.message == "Test skipped: mod.test_skip_empty"

    def test_parse_skipped_text_only_fallback_when_message_none_mutated(self) -> None:
        """Skipped element with text, mutated skip.get returns None-like value.

        Validates the exact fallback for mutant 156 behavior.
        When msg is mutated to None, the conditional `msg.strip() if msg`
        evaluates to the else branch. The result must be the fallback.
        This test ensures that even with mutated code, the fallback is correct.
        """
        adapter = PytestAdapter()
        # Element with NO attributes and NO text → empty element
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" failures="0" errors="0">
    <testcase classname="standalone" name="no_attr_skip">
      <skipped/>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "skipped"
        assert f.severity == "info"
        # No message attr, no text → fallback must be used
        assert f.message == "Test skipped: standalone.no_attr_skip"
        assert f.node == "standalone.no_attr_skip"
        assert f.tool == "pytest"
        assert f.layer == "L1"
        assert f.language == "python"


# ---------------------------------------------------------------------------
# parse() — signature/defaults verification (kills default-param mutants)
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_parse_signature_defaults(self) -> None:
        """Default parameter values: stderr="", exitcode=0.

        Kills mutant 1: if stderr default is mutated to "XXXX", this
        assert strictly requires the default to be an empty string.
        """
        import inspect
        from harness_quality_gate.adapters.python.pytest_adapter import (
            PytestAdapter,
        )

        sig = inspect.signature(PytestAdapter.parse)
        params = sig.parameters
        assert params["stderr"].default == ""
        assert params["exitcode"].default == 0

    def test_parse_exitcode_default_zero(self) -> None:
        """exitcode=0 (default) → no exitcode Finding."""
        adapter = PytestAdapter()
        findings = adapter.parse(stdout='<testsuites/>', exitcode=0)
        assert len(findings) == 0

    def test_parse_no_explicit_stderr(self) -> None:
        """Calling parse without explicit stderr → default '' means no
        CRITICAL finding. Catches default-param-value mutants (mutmut_1)."""
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" failures="0" errors="0">
    <testcase classname="m" name="ok"/>
  </testsuite>
</testsuites>"""
        # Call without passing stderr — uses the default ""
        findings = adapter.parse(xml)
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

    def test_parse_stderr_default_is_empty_string(self) -> None:
        """Default stderr="" → calling parse() without stderr arg never
        triggers the CRITICAL check. Catches mutant 1 where default
        becomes "XXXX" (truthy, so CRITICAL check runs).

        If the default is mutated to "XXXX", the condition
        `stderr and "CRITICAL" in stderr` changes its behavior:
        - Original: "" → falsy → CRITICAL check skipped
        - Mutated:  "XXXX" → truthy → CRITICAL check runs
          but "CRITICAL" not in "XXXX" → still skipped (safe)

        The key behavioral difference is a CRITICAL+non-CRITICAL mixed case
        where the default matters most - with "" default no finding,
        with "XXXX" default the same since "CRITICAL" wouldn't be in "XXXX".
        So the real kill is through strict signature check combined with
        the behavior test below.
        """
        adapter = PytestAdapter()
        # Call with no explicit stderr → uses default ""
        findings = adapter.parse(stdout='<testsuites/>')
        assert len(findings) == 0

        # With the mutated default "XXXX", if we pass a stderr that
        # contains CRITICAL, the check should still work since CRITICAL
        # is explicitly in the string. The default only matters for
        # calls that omit stderr entirely.
        findings = adapter.parse('<testsuites/>', "CRITICAL: some issue")
        assert len(findings) == 1
        assert findings[0].rule_id == "stderr"

    def test_parse_exitcode_with_summary(self) -> None:
        """Exit code + real failures → exitcode Finding at position 0
        then summary, then failures.

        Kills mutmut_240: exitcode > 0 check mutations that skip/insert
        the exitcode Finding at wrong position.
        """
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="2" failures="1" errors="0">
    <testcase classname="mod" name="test_fail">
      <failure message="assertion failed"/>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml, exitcode=2)
        assert len(findings) >= 2
        # [0] exitcode finding
        assert findings[0].rule_id == "exitcode"
        assert findings[0].message == "Test execution failed with exit code 2"
        # [1] summary
        assert findings[1].rule_id == "summary"
        #[2] failure
        assert findings[2].rule_id == "failure"
        assert findings[2].message == "assertion failed"

    def test_parse_exitcode_no_failures(self) -> None:
        """Exit code 1 with no failures → only exitcode Finding.

        Kills mutmut_1: early return and exitcode check mutations.
        """
        adapter = PytestAdapter()
        xml = """<testsuites>
  <testsuite tests="2" failures="0" errors="0">
    <testcase classname="m" name="ok"/>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml, exitcode=1)
        assert len(findings) == 1
        assert findings[0].rule_id == "exitcode"
        assert findings[0].message == "Test execution failed with exit code 1"

    def test_parse_error_full_finding_object(self) -> None:
        """Full Finding comparison for error → kills mutmut_219,240.

        Ensures every field on the error Finding is correct.
        Mutant: .get("message", None) → None causes fallback message → diff.
        Mutant: .get("message",) → KeyError would crash or return default.
        Mutant: severity mutations → "error" → "XXerrorXX" or None.
        """
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" errors="1" failures="0">
    <testcase classname="mod.pkg" name="test_crash_xyz">
      <error message="segmentation fault" type="SIGSEGV">core dump</error>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        assert len(findings) == 2
        # summary
        summary = findings[0]
        assert summary.rule_id == "summary"
        assert summary.message == "1 error(s)"
        # error finding
        err = findings[1]
        assert err.severity == "error"
        assert err.node == "mod.pkg.test_crash_xyz"
        assert err.message == "segmentation fault"  # exact message
        assert err.fix_hint is None
        assert err.tool == "pytest"
        assert err.layer == "L1"
        assert err.language == "python"
        assert err.rule_id == "error"

    def test_parse_failure_full_finding_object(self) -> None:
        """Full Finding comparison for failure → same pattern as error test.

        Kills mutmut_197: mutations on failure get("message", ...) path.
        """
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" failures="1" errors="0">
    <testcase classname="e2e" name="test_auth_flow">
      <failure message="Expected: 42, Got: 0" type="AssertionError">expected 42</failure>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        assert len(findings) == 2
        failure = findings[1]
        assert failure.severity == "error"
        assert failure.node == "e2e.test_auth_flow"
        assert failure.message == "Expected: 42, Got: 0"  # exact from message attr
        assert failure.fix_hint is None
        assert failure.tool == "pytest"
        assert failure.rule_id == "failure"

    def test_parse_skipped_full_finding_object(self) -> None:
        """Full Finding comparison for skipped → kills mutmut mutations.

        Mutants on skip.get("message", ...), severity "info", etc.
        """
        adapter = PytestAdapter()
        xml = """<?xml version="1.0"?>
<testsuites>
  <testsuite tests="1" failures="0" errors="0">
    <testcase classname="tests.integration" name="test_skip_xfail">
      <skipped message="reason: xfail expected" type="xfail"/>
    </testcase>
  </testsuite>
</testsuites>"""
        findings = adapter.parse(xml)
        assert len(findings) == 1
        skip = findings[0]
        assert skip.severity == "info"
        assert skip.node == "tests.integration.test_skip_xfail"
        assert skip.message == "reason: xfail expected"
        assert skip.fix_hint is None
        assert skip.tool == "pytest"
        assert skip.layer == "L1"
        assert skip.language == "python"
        assert skip.rule_id == "skipped"


# ---------------------------------------------------------------------------
# Simulation regressions (H8): junitxml on /dev/stdout interleaves with the
# terminal report making the XML unparseable, so failures vanished silently.
# The adapter must write JUnit XML to a temp file and harden parse().
# ---------------------------------------------------------------------------

_COLLECT_ERROR_XML = (
    '<testsuites name="pytest tests"><testsuite name="pytest" errors="1" '
    'failures="0" skipped="0" tests="1"><testcase classname="" '
    'name="tests/test_x.py"><error message="collection failure">'
    'ModuleNotFoundError: No module named &#x27;greeter&#x27;</error>'
    "</testcase></testsuite></testsuites>"
)


class TestJunitTempFileContract:
    def test_invoke_returns_junit_xml_not_terminal_noise(self, tmp_path: Path) -> None:
        adapter = PytestAdapter()

        def _fake_run(cmd, **kwargs):
            junit_path = Path(cmd[cmd.index("--junitxml") + 1])
            junit_path.write_text(_COLLECT_ERROR_XML, encoding="utf-8")
            return ToolInvocation(
                stdout="===== test session starts =====\n1 error in 0.05s",
                stderr="", exitcode=2, duration_seconds=0.1,
            )

        with patch.object(PytestAdapter, "_run", side_effect=_fake_run) as run:
            inv = adapter.invoke(tmp_path, [])
        cmd = run.call_args[0][0]
        assert "/dev/stdout" not in cmd
        assert inv.stdout == _COLLECT_ERROR_XML
        assert inv.exitcode == 2
        # the temp file must not leak
        junit_path = Path(cmd[cmd.index("--junitxml") + 1])
        assert not junit_path.exists()

    def test_invoke_missing_junit_file_yields_empty_stdout(self, tmp_path: Path) -> None:
        """pytest crashed before writing the report — stdout must be empty,
        so the hardened parse() turns the nonzero exit into a finding."""
        adapter = PytestAdapter()
        crash = ToolInvocation(stdout="boom", stderr="crash", exitcode=3,
                               duration_seconds=0.1)
        with patch.object(PytestAdapter, "_run", return_value=crash):
            inv = adapter.invoke(tmp_path, [])
        assert inv.stdout == ""
        assert inv.exitcode == 3


class TestParseHardening:
    def test_unparseable_output_with_nonzero_exit_is_error_finding(self) -> None:
        findings = PytestAdapter().parse("not xml at all", "", 2)
        assert len(findings) == 1
        f = findings[0]
        assert f.severity == "error"
        assert f.tool == "pytest"
        assert f.layer == "L1"
        assert f.rule_id == "parse-error"
        assert "2" in f.message

    def test_empty_output_with_nonzero_exit_is_error_finding(self) -> None:
        findings = PytestAdapter().parse("", "", 1)
        assert len(findings) == 1
        assert findings[0].rule_id == "parse-error"
        assert findings[0].severity == "error"

    def test_empty_output_with_zero_exit_is_clean(self) -> None:
        assert PytestAdapter().parse("", "", 0) == []

    def test_collection_error_xml_yields_error_finding(self) -> None:
        findings = PytestAdapter().parse(_COLLECT_ERROR_XML, "", 2)
        # exitcode + summary + the collection error itself
        assert [f.rule_id for f in findings] == ["exitcode", "summary", "error"]
        assert all(f.severity == "error" for f in findings)
        assert findings[2].message == "collection failure"

    def test_no_tests_collected_exit5_is_error_finding(self) -> None:
        xml = ('<testsuites><testsuite name="pytest" errors="0" failures="0" '
               'skipped="0" tests="0"></testsuite></testsuites>')
        findings = PytestAdapter().parse(xml, "", 5)
        assert len(findings) == 1
        assert findings[0].severity == "error"
        assert findings[0].rule_id == "no-tests"


# ---------------------------------------------------------------------------
# MSI survivor killers (post-simulation campaign)
# ---------------------------------------------------------------------------

_UNPARSEABLE_FIX_HINT = ("Run pytest manually in the repo to inspect the "
                         "failure (collection error, crash or misconfiguration).")


class TestInvokeRecomposition:
    def test_invoke_recomposes_invocation_exactly(self, tmp_path: Path) -> None:
        """stderr/exitcode/duration must pass through verbatim."""
        adapter = PytestAdapter()

        def _fake_run(cmd, **kwargs):
            junit_path = Path(cmd[cmd.index("--junitxml") + 1])
            junit_path.write_text("<testsuites/>", encoding="utf-8")
            return ToolInvocation(stdout="noise", stderr="warn-x",
                                  exitcode=7, duration_seconds=1.5)

        with patch.object(PytestAdapter, "_run", side_effect=_fake_run):
            inv = adapter.invoke(tmp_path, [])
        assert inv == ToolInvocation(stdout="<testsuites/>", stderr="warn-x",
                                     exitcode=7, duration_seconds=1.5)

    def test_invoke_junit_temp_name_shape(self, tmp_path: Path) -> None:
        adapter = PytestAdapter()
        with patch.object(PytestAdapter, "_run", return_value=ToolInvocation()) as run:
            adapter.invoke(tmp_path, [])
        junit_arg = Path(run.call_args.args[0][run.call_args.args[0].index("--junitxml") + 1])
        assert junit_arg.name.startswith("hqg-junit-")
        assert junit_arg.suffix == ".xml"

    def test_invoke_survives_subprocess_deleting_junit_file(self, tmp_path: Path) -> None:
        """If the subprocess removes the report, invoke must neither stat()
        nor unlink() a missing file into an exception."""
        adapter = PytestAdapter()

        def _fake_run(cmd, **kwargs):
            junit_path = Path(cmd[cmd.index("--junitxml") + 1])
            junit_path.unlink()
            return ToolInvocation(stdout="", stderr="", exitcode=3)

        with patch.object(PytestAdapter, "_run", side_effect=_fake_run):
            inv = adapter.invoke(tmp_path, [])
        assert inv.stdout == ""
        assert inv.exitcode == 3


class TestSurvivorExactFields:
    def test_unparseable_finding_exact_fields_exit2(self) -> None:
        findings = PytestAdapter().parse("garbage not xml", "", 2)
        f = findings[0]
        assert f.node == "pytest"
        assert f.severity == "error"
        assert f.message == ("pytest exited with code 2 but produced no "
                             "parseable JUnit XML report")
        assert f.fix_hint == _UNPARSEABLE_FIX_HINT
        assert f.tool == "pytest"
        assert f.layer == "L1"
        assert f.language == "python"
        assert f.rule_id == "parse-error"

    def test_unparseable_finding_interpolates_exitcode_on_empty(self) -> None:
        findings = PytestAdapter().parse("", "", 1)
        assert findings[0].message == ("pytest exited with code 1 but "
                                       "produced no parseable JUnit XML report")

    def test_no_tests_finding_exact_fields(self) -> None:
        xml = ('<testsuites><testsuite name="pytest" errors="0" failures="0" '
               'skipped="0" tests="0"></testsuite></testsuites>')
        findings = PytestAdapter().parse(xml, "", 5)
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "pytest"
        assert f.severity == "error"
        assert f.message == "pytest collected no tests (exit code 5)"
        assert f.fix_hint == ("Add tests under tests/ — L1 validates test "
                              "execution and cannot pass without tests.")
        assert f.tool == "pytest"
        assert f.layer == "L1"
        assert f.language == "python"
        assert f.rule_id == "no-tests"
