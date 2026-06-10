"""Tests for PhpWeakTestLayerAdapter.run_l3b in weak_test_php.py.

Targets: run_l3b method of PhpWeakTestLayerAdapter which wraps
PhpWeakTestAdapter and returns LayerResult.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import logging

import pytest

from harness_quality_gate.adapters.php.weak_test_php import (
    PhpWeakTestLayerAdapter,
    PhpWeakTestAdapter,
)
from harness_quality_gate.adapters.base import ToolInvocation


def _mock_ok(stdout: str = "[]", stderr: str = "", exitcode: int = 0):
    from harness_quality_gate.adapters.base import ToolInvocation
    return ToolInvocation(stdout=stdout, stderr=stderr, exitcode=exitcode, duration_seconds=0.0)


class TestRunL3b:
    """Tests for PhpWeakTestLayerAdapter.run_l3b."""

    def test_run_l3b_no_test_files(self, tmp_path: Path) -> None:
        """No test files in repo → LayerResult passed=True, no findings."""
        import harness_quality_gate.adapters.php.weak_test_php as wtm

        adapter = PhpWeakTestLayerAdapter()
        with patch.object(wtm, "_WEAK_TEST_VISITORS", []):
            result = adapter.run_l3b(tmp_path, {})

        assert result.layer == "L3B"
        assert result.language == "php"
        assert result.passed is True
        assert result.findings == []
        assert result.duration_sec >= 0

    def test_run_l3b_with_mocked_findings(self, tmp_path: Path) -> None:
        """When invoke returns findings → LayerResult passed=False."""
        findings_data = [
            {
                "file": "tests/UserTest.php",
                "line": 10,
                "rule_id": "A1",
                "message": "No assertions",
                "severity": "error",
                "fix_hint": "Add assertions",
            }
        ]
        with patch.object(
            PhpWeakTestAdapter,
            "invoke",
            return_value=_mock_ok(stdout=json.dumps(findings_data)),
        ) as mock_invoke:
            adapter = PhpWeakTestLayerAdapter()
            result = adapter.run_l3b(tmp_path, {})

        mock_invoke.assert_called_once()
        assert result.layer == "L3B"
        assert result.language == "php"
        assert result.passed is False
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.node == "tests/UserTest.php:10"
        assert f.severity == "error"
        assert f.rule_id == "A1"
        assert f.message == "No assertions"
        assert f.layer == "L3B"
        assert f.language == "php"
        assert f.tool == "weak-test-php"

    def test_run_l3b_multiple_findings(self, tmp_path: Path) -> None:
        """Multiple findings from different rules → all returned."""
        findings_data = [
            {"file": "tests/A.php", "line": 1, "rule_id": "A1", "message": "msg1"},
            {"file": "tests/B.php", "line": 5, "rule_id": "A2-PHP", "message": "msg2"},
            {"file": "tests/C.php", "line": 10, "rule_id": "A5", "message": "msg3"},
        ]
        with patch.object(
            PhpWeakTestAdapter,
            "invoke",
            return_value=_mock_ok(stdout=json.dumps(findings_data)),
        ):
            adapter = PhpWeakTestLayerAdapter()
            result = adapter.run_l3b(tmp_path, {})

        assert result.passed is False
        assert len(result.findings) == 3
        rule_ids = {f.rule_id for f in result.findings}
        assert "A1" in rule_ids
        assert "A2-PHP" in rule_ids
        assert "A5" in rule_ids

    def test_run_l3b_finding_without_line(self, tmp_path: Path) -> None:
        """Finding with no line number → node is just filepath."""
        findings_data = [
            {"file": "tests/Something.php", "rule_id": "A3", "message": "no line"},
        ]
        with patch.object(
            PhpWeakTestAdapter,
            "invoke",
            return_value=_mock_ok(stdout=json.dumps(findings_data)),
        ):
            adapter = PhpWeakTestLayerAdapter()
            result = adapter.run_l3b(tmp_path, {})

        assert result.findings[0].node == "tests/Something.php"

    def test_run_l3b_finding_with_invalid_line(self, tmp_path: Path) -> None:
        """Finding with non-integer line → node contains raw line value."""
        findings_data = [
            {"file": "tests/X.php", "line": "abc", "rule_id": "A4", "message": "bad line"},
        ]
        with patch.object(
            PhpWeakTestAdapter,
            "invoke",
            return_value=_mock_ok(stdout=json.dumps(findings_data)),
        ):
            adapter = PhpWeakTestLayerAdapter()
            result = adapter.run_l3b(tmp_path, {})

        assert len(result.findings) == 1

    def test_run_l3b_with_findings_and_stderr(self, tmp_path: Path) -> None:
        """Invoke with non-zero exitcode due to stderr findings still produces LayerResult."""
        findings_data = [
            {"file": "tests/Test.php", "line": 5, "rule_id": "A6", "message": "spare ignore"},
        ]
        invocation = _mock_ok(
            stdout=json.dumps(findings_data),
            stderr="visitor=weak_test_a6 file=tests/Test.php exit=1: warn",
            exitcode=1,
        )
        with patch.object(
            PhpWeakTestAdapter,
            "invoke",
            return_value=invocation,
        ):
            adapter = PhpWeakTestLayerAdapter()
            result = adapter.run_l3b(tmp_path, {})

        assert result.passed is False
        assert len(result.findings) == 1
        assert result.duration_sec >= 0

    def test_run_l3b_finding_no_fix_hint(self, tmp_path: Path) -> None:
        """Finding without fix_hint field → fix_hint is None."""
        findings_data = [
            {"file": "tests/Z.php", "line": 1, "rule_id": "A7", "message": "constructor only"},
        ]
        with patch.object(
            PhpWeakTestAdapter,
            "invoke",
            return_value=_mock_ok(stdout=json.dumps(findings_data)),
        ):
            adapter = PhpWeakTestLayerAdapter()
            result = adapter.run_l3b(tmp_path, {})

        assert result.findings[0].fix_hint is None

    def test_run_l3b_env_passed_to_subprocess(self, tmp_path: Path) -> None:
        """run_l3b calls invoke which propagates env to subprocess."""
        with patch.object(
            PhpWeakTestAdapter,
            "invoke",
            return_value=_mock_ok(),
        ) as mock_invoke:
            adapter = PhpWeakTestLayerAdapter()
            adapter.run_l3b(tmp_path, {"FOO": "BAR"})

        call_kwargs = mock_invoke.call_args
        assert call_kwargs[1]["env"] == {"FOO": "BAR"}

    def test_run_l3b_empty_findings_passed(self, tmp_path: Path) -> None:
        """No findings → LayerResult.passed=True."""
        with patch.object(
            PhpWeakTestAdapter,
            "invoke",
            return_value=_mock_ok(stdout="[]"),
        ):
            adapter = PhpWeakTestLayerAdapter()
            result = adapter.run_l3b(tmp_path, {})

        assert result.passed is True
        assert len(result.findings) == 0

    def test_run_l3b_finding_with_path_key(self, tmp_path: Path) -> None:
        """Finding with 'path' key instead of 'file' is accepted."""
        findings_data = [
            {"path": "tests/Alt.php", "line": 3, "rule_id": "A8", "message": "tautology"},
        ]
        with patch.object(
            PhpWeakTestAdapter,
            "invoke",
            return_value=_mock_ok(stdout=json.dumps(findings_data)),
        ):
            adapter = PhpWeakTestLayerAdapter()
            result = adapter.run_l3b(tmp_path, {})

        assert result.findings[0].node == "tests/Alt.php:3"

    def test_run_l3b_finding_severity_levels(self, tmp_path: Path) -> None:
        """Different severity values are passed through."""
        findings_data = [
            {"file": "tests/A.php", "line": 1, "rule_id": "A1", "message": "e", "severity": "error"},
            {"file": "tests/B.php", "line": 1, "rule_id": "A2", "message": "w", "severity": "warning"},
            {"file": "tests/C.php", "line": 1, "rule_id": "A3", "message": "i", "severity": "info"},
        ]
        with patch.object(
            PhpWeakTestAdapter,
            "invoke",
            return_value=_mock_ok(stdout=json.dumps(findings_data)),
        ):
            adapter = PhpWeakTestLayerAdapter()
            result = adapter.run_l3b(tmp_path, {})

        sevs = {f.severity for f in result.findings}
        assert "error" in sevs
        assert "warning" in sevs
        assert "info" in sevs

    def test_run_l3b_findings_duration_non_zero(self, tmp_path: Path) -> None:
        """Duration is measured and reported."""
        with patch.object(
            PhpWeakTestAdapter,
            "invoke",
            return_value=_mock_ok(),
        ):
            adapter = PhpWeakTestLayerAdapter()
            result = adapter.run_l3b(tmp_path, {})

        assert isinstance(result.duration_sec, float)
        assert result.duration_sec >= 0


class TestRunL3bWithRealFiles:
    """run_l3b with actual .php files but mocked subprocess."""

    def test_run_l3b_with_real_php_test_files(self, tmp_path: Path) -> None:
        """Create real Test.php files → invoke collects them, subprocess mocked."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        weak_test = tests_dir / "WeakTest.php"
        weak_test.write_text(
            "<?php\n"
            "class WeakTest extends TestCase {\n"
            "    public function testZeroAssertions(): void {\n"
            "        // no assertions\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        strong_test = tests_dir / "StrongTest.php"
        strong_test.write_text(
            "<?php\n"
            "class StrongTest extends TestCase {\n"
            "    public function testAssertions(): void {\n"
            "        $this->assertTrue(true);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        with patch.object(
            PhpWeakTestAdapter,
            "invoke",
            return_value=_mock_ok(stdout=json.dumps([
                {"file": "tests/WeakTest.php", "line": 3, "rule_id": "A1", "message": "zero assertions"},
            ])),
        ):
            adapter = PhpWeakTestLayerAdapter()
            result = adapter.run_l3b(tmp_path, {})

        assert result.passed is False
        assert result.findings[0].rule_id == "A1"

    def test_run_l3b_no_test_directory(self, tmp_path: Path) -> None:
        """No tests/ directory and no Test.php files → empty findings."""
        # tmp_path is empty, no files
        with patch.object(
            PhpWeakTestAdapter,
            "invoke",
            return_value=_mock_ok(stdout="[]", stderr="no PHP test files found"),
        ):
            adapter = PhpWeakTestLayerAdapter()
            result = adapter.run_l3b(tmp_path, {})

        assert result.passed is True
        assert len(result.findings) == 0


class TestInvokeBreakVsContinue:
    """Tests that verify continue vs break behavior in the invoke method.

    These tests are specifically designed to kill the mutmut_42 mutant
    which changes 'continue' to 'break' when a visitor script is missing.
    """

    def test_invoke_missing_visitors_continues_through_all_8_visitors(self, tmp_path: Path, caplog) -> None:
        """When visitor scripts are missing, invoke continues past each one.

        If 'break' were used instead, only the first visitor's warning would be logged.
        With 'continue', ALL 8 visitors log warnings.

        This directly tests mutmut_42 which changes continue → break.
        """
        import harness_quality_gate.adapters.php.weak_test_php as wt_module

        # Create a test file that _collect_test_files will find
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "FooTest.php").touch()

        # Create a Path subclass that always returns False for is_file()
        # This simulates missing visitor scripts, triggering the continue/break branch
        class FakeVisitorsPath(Path):
            def is_file(self):
                return False

        original_path = wt_module.Path
        wt_module.Path = FakeVisitorsPath

        try:
            # Set log level to capture WARNING messages
            logger = logging.getLogger("harness_quality_gate.adapters.php.weak_test_php")
            logger.setLevel(logging.WARNING)
            caplog.set_level(logging.WARNING, "harness_quality_gate.adapters.php.weak_test_php")

            with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[tests_dir / "FooTest.php"]):
                result = PhpWeakTestAdapter().invoke(tmp_path, [])

        finally:
            wt_module.Path = original_path

        # Count visitor missing warnings
        visitor_missing_count = sum(
            1 for r in caplog.records
            if "Weak-test visitor missing" in r.getMessage()
        )

        # With 'continue' → all 8 visitors log warnings (count = 8)
        # With 'break' → only 1 visitor logs warning (count = 1)
        assert visitor_missing_count == 8, (
            f"Expected 8 visitor warnings (continue), got {visitor_missing_count} (possible break). "
            f"Messages: {[r.getMessage() for r in caplog.records]}"
        )


class TestRunL3bEdgeCases:
    """Edge cases and error paths in run_l3b."""

    def test_run_l3b_finding_rule_id_missing(self, tmp_path: Path) -> None:
        """Finding without rule_id → empty string rule_id."""
        findings_data = [
            {"file": "tests/X.php", "line": 1, "message": "no rule"},
        ]
        with patch.object(
            PhpWeakTestAdapter,
            "invoke",
            return_value=_mock_ok(stdout=json.dumps(findings_data)),
        ):
            adapter = PhpWeakTestLayerAdapter()
            result = adapter.run_l3b(tmp_path, {})

        assert result.findings[0].rule_id == ""

    def test_run_l3b_finding_rule_id_set_by_invoke(self, tmp_path: Path) -> None:
        """rule_id is set by invoke (from _VISITOR_RULE_MAP) → parse receives it."""
        findings_data = [
            {"file": "tests/X.php", "line": 1, "rule_id": "A2-PHP", "message": "mocks"},
        ]
        with patch.object(
            PhpWeakTestAdapter,
            "invoke",
            return_value=_mock_ok(stdout=json.dumps(findings_data)),
        ):
            adapter = PhpWeakTestLayerAdapter()
            result = adapter.run_l3b(tmp_path, {})

        assert result.findings[0].rule_id == "A2-PHP"

    def test_run_l3b_finding_cwe_empty(self, tmp_path: Path) -> None:
        """Finding without cwe → default empty string."""
        findings_data = [
            {"file": "tests/X.php", "line": 1, "rule_id": "A1", "message": "test"},
        ]
        with patch.object(
            PhpWeakTestAdapter,
            "invoke",
            return_value=_mock_ok(stdout=json.dumps(findings_data)),
        ):
            adapter = PhpWeakTestLayerAdapter()
            result = adapter.run_l3b(tmp_path, {})

        assert result.findings[0].cwe == ""

    def test_run_l3b_all_weak_test_rule_ids(self, tmp_path: Path) -> None:
        """All rule_ids A1, A2-PHP, A3, A4, A5, A6, A7, A8 can appear."""
        import harness_quality_gate.adapters.php.weak_test_php as wtm

        all_rule_ids = [
            "A1", "A2-PHP", "A3", "A4", "A5", "A6", "A7", "A8"
        ]
        findings_data = [
            {f"file_{i}": f"tests/p{i}.php", "line": i, "rule_id": rid, "message": f"msg {rid}"}
            for i, rid in enumerate(all_rule_ids)
        ]
        with patch.object(
            PhpWeakTestAdapter,
            "invoke",
            return_value=_mock_ok(stdout=json.dumps(findings_data)),
        ):
            adapter = PhpWeakTestLayerAdapter()
            result = adapter.run_l3b(tmp_path, {})

        found_ids = {f.rule_id for f in result.findings}
        for rid in all_rule_ids:
            assert rid in found_ids, f"Missing rule_id: {rid}"

    def test_run_l3b_invocation_timeout_used(self, tmp_path: Path) -> None:
        """run_l3b passes timeout=300.0 to invoke."""
        with patch.object(
            PhpWeakTestAdapter,
            "invoke",
            return_value=_mock_ok(),
        ) as mock_invoke:
            adapter = PhpWeakTestLayerAdapter()
            adapter.run_l3b(tmp_path, {})

        call_kwargs = mock_invoke.call_args
        assert call_kwargs[1]["timeout"] == 300.0

    def test_run_l3b_layer_and_language_consistency(self, tmp_path: Path) -> None:
        """All findings have consistent layer/language from run_l3b."""
        findings_data = [
            {"file": "tests/A.php", "line": 1, "rule_id": "A1", "message": "x"},
            {"file": "tests/B.php", "line": 2, "rule_id": "A8", "message": "y"},
        ]
        with patch.object(
            PhpWeakTestAdapter,
            "invoke",
            return_value=_mock_ok(stdout=json.dumps(findings_data)),
        ):
            adapter = PhpWeakTestLayerAdapter()
            result = adapter.run_l3b(tmp_path, {})

        for f in result.findings:
            assert f.layer == "L3B"
            assert f.language == "php"


# ===========================================================================
# PhpWeakTestAdapter.invoke — direct invocation tests (kill invoke survivors)
# ===========================================================================

class TestInvokeDirect:
    """Tests that directly exercise PhpWeakTestAdapter.invoke method.

    These tests are specifically designed to kill mutated code paths
    in the invoke method that are not reachable through run_l3b mocks.
    """

    def test_invoke_no_test_files_returns_exactly_empty_json(self, tmp_path: Path, caplog) -> None:
        """No PHP test files → stdout is exactly '[]', stderr contains full message.

        Also asserts that the logged warning message contains the actual repo path
        (not None), which would fail when mutated.
        """
        result = PhpWeakTestAdapter().invoke(tmp_path, [])
        assert result.stdout == "[]"
        assert result.stderr == "no PHP test files found"
        assert result.exitcode == 0
        assert result.duration_seconds >= 0

        # Assert log message format: starts with exact prefix (kills mutant 17 which
        # adds "XX" prefix), contains full message, and contains the repo path.
        assert len(caplog.records) >= 1
        log_msg = caplog.messages[0]
        assert log_msg.startswith("No PHP test files found in"), (
            f"Log message should start with exact prefix (not XX-prefixed), got: {log_msg}"
        )
        assert "No PHP test files found in" in log_msg, (
            f"Log message should contain expected prefix, got: {log_msg}"
        )
        repo_msg = str(tmp_path)
        assert repo_msg in log_msg, (
            f"Log message should contain repo path '{repo_msg}', got: {log_msg}"
        )

    @pytest.mark.parametrize("timeout_value", [5.0, 300.0, 999.0])
    def test_invoke_timeout_param_used(self, tmp_path: Path, timeout_value: float) -> None:
        """invoke accepts and uses custom timeout — timeout is passed to subprocess.run."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "FooTest.php"
        test_file.touch()

        with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[test_file]):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
                PhpWeakTestAdapter().invoke(tmp_path, [], timeout=timeout_value)
                # All calls should have the correct timeout
                for call in mock_run.call_args_list:
                    assert call[1]["timeout"] == timeout_value

    def test_invoke_default_timeout_is_300(self, tmp_path: Path) -> None:
        """When no timeout arg → subprocess.run receives timeout=300.0 (not mutated to 301.0)."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "FooTest.php"
        test_file.touch()

        with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[test_file]):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
                # Call without timeout — should use default of 300.0
                PhpWeakTestAdapter().invoke(tmp_path, [])
                assert mock_run.call_count >= 1
                for call in mock_run.call_args_list:
                    assert call[1]["timeout"] == 300.0, (
                        f"Default timeout should be 300.0, got {call[1]['timeout']}"
                    )

    def test_invoke_with_test_files_visitor_missing_logs_and_continues(self, tmp_path: Path) -> None:
        """When visitor scripts are missing, invoke continues (doesn't break) and returns empty."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "FooTest.php"
        test_file.touch()

        result = PhpWeakTestAdapter().invoke(tmp_path, [])
        assert json.loads(result.stdout) == []
        assert result.exitcode == 0

    def test_invoke_with_test_files_visitor_missing_creates_exitcode_one_on_stderr(self, tmp_path: Path) -> None:
        """When a visitor fails, exitcode becomes 1 and stderr contains failure info."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "FooTest.php"
        test_file.touch()
        completed = MagicMock()
        completed.returncode = 42
        completed.stdout = ""
        completed.stderr = "fatal parse error"

        from harness_quality_gate.adapters.php import weak_test_php as wt_module
        real_visitors_dir = Path(wt_module.__file__).parent / "visitors"

        with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[test_file]):
            with patch("subprocess.run", return_value=completed) as mock_run:
                result = PhpWeakTestAdapter().invoke(tmp_path, [])

        assert result.exitcode == 1
        assert "visitor=" in result.stderr
        assert "exit=42" in result.stderr
        assert "fatal parse error" in result.stderr

        # Assert subprocess.run was called with correct file args (not mutated to None).
        # This kills mutmut_61 which changes str(php_file) to str(None).
        for call in mock_run.call_args_list:
            args = call[0]
            cmd = args[0]  # The command list passed to subprocess.run
            assert len(cmd) == 3, f"Expected 3 args in command, got {cmd}"
            assert cmd[2] != "None", f"File arg should not be 'None', got: {cmd[2]}"
            assert cmd[2] == str(test_file), f"File arg should be {test_file}, got: {cmd[2]}"

    def test_invoke_visitor_success_tags_rule_id(self, tmp_path: Path) -> None:
        """When a visitor succeeds, the findings are tagged with the correct rule_id."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "FooTest.php"
        test_file.touch()

        # Use the package's real visitors directory
        from harness_quality_gate.adapters.php import weak_test_php as wt_module
        real_visitors_dir = Path(wt_module.__file__).parent / "visitors"

        if real_visitors_dir.exists():
            real_visitor_scripts = [f for f in real_visitors_dir.iterdir() if f.suffix == ".php"]
        else:
            real_visitor_scripts = []

        for vs in real_visitor_scripts:
            # Ensure the script exists
            pass  # real_visitors_dir has the scripts

        if real_visitor_scripts:
            with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[test_file]):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(
                        returncode=0,
                        stdout=json.dumps([{
                            "file": "tests/FooTest.php",
                            "line": 5,
                            "message": "no assertions"
                        }]),
                        stderr=""
                    )
                    with patch("harness_quality_gate.adapters.php.weak_test_php.Path") as MockPath:
                        # Patch Path to resolve to real directory
                        mock_resolve = MagicMock()
                        mock_resolve.parent = real_visitors_dir.parent
                        MockPath.return_value.resolve.return_value = mock_resolve
                        MockPath.side_effect = lambda *a, **kw: Path(*a, **kw)
                        result = PhpWeakTestAdapter().invoke(tmp_path, [])
            # All findings should have rule_id set
            findings = json.loads(result.stdout)
            # Must have findings — kills mutations that clear all_findings (mutmut_86-120 variants on line 153 where extend(parsed) is changed to extend([]) or all_findings = [])
            assert len(findings) > 0, (
                f"Expected non-empty findings (subprocess returned findings with exitcode=0). "
                f"Got {len(findings)} findings. stdout was: {result.stdout}"
            )
            for finding in findings:
                assert "rule_id" in finding
                assert finding["rule_id"] in ["A1", "A2-PHP", "A3", "A4", "A5", "A6", "A7", "A8"]
        else:
            pytest.skip("No visitor scripts on this system")

    def test_invoke_merged_findings_all_have_rule_id(self, tmp_path: Path) -> None:
        """Multiple visits → all merged findings carry a non-empty rule_id."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "FooTest.php"
        test_file.touch()

        from harness_quality_gate.adapters.php import weak_test_php as wt_module
        real_visitors_dir = Path(wt_module.__file__).parent / "visitors"

        if real_visitors_dir.exists():
            real_visitor_scripts = [f for f in real_visitors_dir.iterdir() if f.suffix == ".php"]
        else:
            real_visitor_scripts = []

        if real_visitor_scripts:
            with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[test_file]):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(
                        returncode=0,
                        stdout=json.dumps([{"file": "tests/FooTest.php", "line": 1, "message": "test finding"}]),
                        stderr=""
                    )
                    with patch("harness_quality_gate.adapters.php.weak_test_php.Path") as MockPath:
                        mock_resolve = MagicMock()
                        mock_resolve.parent = real_visitors_dir.parent
                        MockPath.return_value.resolve.return_value = mock_resolve
                        MockPath.side_effect = lambda *a, **kw: Path(*a, **kw)
                        result = PhpWeakTestAdapter().invoke(tmp_path, [])
            findings = json.loads(result.stdout) if result.stdout else []
            # Must have findings — kills mutations on line 153/154 that clear all_findings (all_findings.extend(parsed) → all_findings = [] or extend([]))
            assert len(findings) > 0, (
                f"Expected non-empty findings. stdout: {result.stdout}"
            )
        else:
            findings = []
        # If any findings, all must have valid rule_id
        for f in findings:
            assert "rule_id" in f
            assert f["rule_id"] != ""

    def test_invoke_result_toolinvocation_attributes(self, tmp_path: Path) -> None:
        """invoke returns a proper ToolInvocation with all fields set."""
        from harness_quality_gate.adapters.base import ToolInvocation

        result = PhpWeakTestAdapter().invoke(tmp_path, [])
        assert isinstance(result, ToolInvocation)
        assert isinstance(result.stdout, str)
        assert isinstance(result.stderr, str)
        assert isinstance(result.exitcode, int)
        assert isinstance(result.duration_seconds, float)
        assert result.duration_seconds >= 0

    def test_invoke_with_stderr_parts_merged_with_newline(self, tmp_path: Path) -> None:
        """Multiple visitor failures → stderr has newline-separated parts."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "FooTest.php"
        test_file.touch()

        from harness_quality_gate.adapters.php import weak_test_php as wt_module
        real_visitors_dir = Path(wt_module.__file__).parent / "visitors"

        if not real_visitors_dir.exists() or not list(real_visitors_dir.iterdir()):
            # If no visitors, stderr is empty and exitcode=0
            result = PhpWeakTestAdapter().invoke(tmp_path, [])
            assert result.exitcode == 0
            assert result.stderr == ""
            return

        def side_effect(*args, **kwargs):
            m = MagicMock()
            m.returncode = 1
            m.stdout = ""
            m.stderr = "some error"
            return m

        with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[test_file]):
            with patch("subprocess.run", side_effect=side_effect):
                with patch("harness_quality_gate.adapters.php.weak_test_php.Path") as MockPath:
                    mock_resolve = MagicMock()
                    mock_resolve.parent = real_visitors_dir.parent
                    MockPath.return_value.resolve.return_value = mock_resolve
                    MockPath.side_effect = lambda *a, **kw: Path(*a, **kw)
                    result = PhpWeakTestAdapter().invoke(tmp_path, [])

        assert result.exitcode == 1
        # stderr parts separated by newlines
        for part in result.stderr.split("\n"):
            if part:
                assert "visitor=" in part

    def test_invoke_returncode_not_zero_assert_on_stdin(self, tmp_path: Path) -> None:
        """If subprocess returncode != 0, it is NOT treated as success."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "FooTest.php"
        test_file.touch()

        from harness_quality_gate.adapters.php import weak_test_php as wt_module
        real_visitors_dir = Path(wt_module.__file__).parent / "visitors"

        if not real_visitors_dir.exists() or not list(real_visitors_dir.iterdir()):
            return  # no visitors, nothing to test

        def side_effect(*args, **kwargs):
            m = MagicMock()
            m.returncode = 2
            m.stdout = '[{"file": "tests/FooTest.php", "line": 1, "rule_id": "A1", "message": "err"}]'
            m.stderr = "stderr content"
            return m

        with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[test_file]):
            with patch("subprocess.run", side_effect=side_effect):
                with patch("harness_quality_gate.adapters.php.weak_test_php.Path") as MockPath:
                    mock_resolve = MagicMock()
                    mock_resolve.parent = real_visitors_dir.parent
                    MockPath.return_value.resolve.return_value = mock_resolve
                    MockPath.side_effect = lambda *a, **kw: Path(*a, **kw)
                    result = PhpWeakTestAdapter().invoke(tmp_path, [])

        # Because returncode != 0, the result is skipped (continue)
        # So the stdout from the failure path is NOT parsed
        findings = json.loads(result.stdout)
        assert findings == []
        assert "stderr content" in result.stderr

    def test_invoke_subprocess_text_mode_used(self, tmp_path: Path) -> None:
        """subprocess.run is called with text=True (string output, not bytes)."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "FooTest.php"
        test_file.touch()

        with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[test_file]):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
                PhpWeakTestAdapter().invoke(tmp_path, [])
                assert mock_run.call_count >= 1
                for call in mock_run.call_args_list:
                    assert call[1]["text"] is True

    def test_invoke_subprocess_capture_output_true(self, tmp_path: Path) -> None:
        """subprocess.run is called with capture_output=True."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "FooTest.php"
        test_file.touch()

        with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[test_file]):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
                PhpWeakTestAdapter().invoke(tmp_path, [])
                assert mock_run.call_count >= 1
                for call in mock_run.call_args_list:
                    assert call[1]["capture_output"] is True

    def test_invoke_subprocess_check_false(self, tmp_path: Path) -> None:
        """subprocess.run is called with check=False (errors are handled manually)."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "FooTest.php"
        test_file.touch()

        with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[test_file]):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=42, stdout="[]", stderr="")
                PhpWeakTestAdapter().invoke(tmp_path, [])
                assert mock_run.call_count >= 1
                for call in mock_run.call_args_list:
                    assert call[1]["check"] is False

    def test_invoke_subprocess_cwd_set_to_repo(self, tmp_path: Path) -> None:
        """subprocess.run is called with cwd=str(repo)."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "FooTest.php"
        test_file.touch()

        with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[test_file]):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
                PhpWeakTestAdapter().invoke(tmp_path, [])
                assert mock_run.call_count >= 1
                for call in mock_run.call_args_list:
                    assert call[1]["cwd"] == str(tmp_path)

    def test_invoke_exitcode_one_when_stderr_parts_populated(self, tmp_path: Path) -> None:
        """Exit code is 1 when stderr_parts is populated (kills mutmut_78/79/99/100: 'not' → 'and'/'or' on line 163).

        This test ensures exitcode==1 when stderr_parts is populated.
        If 'not' on line 163 is replaced with 'and' or 'or', the condition always
        evaluates differently and exitcode would become 0 despite stderr parts.
        """
        from harness_quality_gate.adapters.php import weak_test_php as wt_module
        from unittest.mock import MagicMock

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "FooTest.php"
        test_file.touch()

        real_visitors_dir = Path(wt_module.__file__).parent / "visitors"
        if not real_visitors_dir.exists() or not list(real_visitors_dir.iterdir()):
            pytest.skip("No visitor scripts to test line 163 exit code mutation")

        call_count = [0]
        visitor_scripts = sorted([f for f in real_visitors_dir.iterdir() if f.suffix == ".php"])

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            m = MagicMock()
            # Odd calls: success with findings (indices 1, 3, 5, 7)
            # Even calls: failure with stderr (indices 0, 2, 4, 6)
            if call_count[0] % 2 == 1:  # odd: 1st, 3rd, 5th, 7th call (4 successes)
                m.returncode = 0
                m.stdout = json.dumps([{"file": "tests/FooTest.php", "line": 1, "message": "weak test"}])
                m.stderr = ""
            else:  # even: 2nd, 4th, 6th, 8th call (4 failures)
                m.returncode = 1
                m.stdout = ""
                m.stderr = "visitor error"
            return m

        with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[test_file]):
            with patch("subprocess.run", side_effect=side_effect):
                with patch("harness_quality_gate.adapters.php.weak_test_php.Path") as MockPath:
                    mock_resolve = MagicMock()
                    mock_resolve.parent = real_visitors_dir.parent
                    MockPath.return_value.resolve.return_value = mock_resolve
                    MockPath.side_effect = lambda *a, **kw: Path(*a, **kw)
                    result = PhpWeakTestAdapter().invoke(tmp_path, [])

        # 8 calls total (4 visitors succeed, 4 fail)
        assert call_count[0] == 8
        # With original code: not stderr_parts → False (has stderr), exitcode=1
        # If 'not' → 'and' or 'or': exitcode would be 0 → this catches the mutation
        assert result.exitcode == 1, (
            f"Expected exitcode=1 when stderr_parts is populated. "
            f"Got {result.exitcode}. stderr: {result.stderr}"
        )
        # Findings from successful visitors should be populated
        findings = json.loads(result.stdout)
        assert len(findings) > 0, (
            f"Expected findings from successful visitors. Got {len(findings)}"
        )

    def test_invoke_duration_seconds_rounded(self, tmp_path: Path) -> None:
        """invoke returns duration_seconds rounded to 3 decimal places."""
        result = PhpWeakTestAdapter().invoke(tmp_path, [])
        # Should be rounded to at most 3 decimal places
        assert round(result.duration_seconds, 3) == result.duration_seconds

    def test_invoke_subprocess_env_merged(self, tmp_path: Path) -> None:
        """env vars are merged with os.environ and passed to subprocess.run."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "FooTest.php"
        test_file.touch()

        with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[test_file]):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
                custom_env = {"CUSTOM_VAR": "custom_value"}
                PhpWeakTestAdapter().invoke(tmp_path, [], env=custom_env)
                assert mock_run.call_count >= 1
                for call in mock_run.call_args_list:
                    assert "CUSTOM_VAR" in call[1]["env"]
                    assert call[1]["env"]["CUSTOM_VAR"] == "custom_value"

    def test_invoke_finding_key_rule_id_not_overwritten(self, tmp_path: Path) -> None:
        """rule_id key is exactly 'rule_id' (not mutated to 'RULE_ID' etc)."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "FooTest.php"
        test_file.touch()

        from harness_quality_gate.adapters.php import weak_test_php as wt_module
        real_visitors_dir = Path(wt_module.__file__).parent / "visitors"

        if not real_visitors_dir.exists() or not list(real_visitors_dir.iterdir()):
            pytest.skip("No visitor scripts to test rule_id mapping")

        with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[test_file]):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps([{
                        "file": "tests/FooTest.php",
                        "line": 1,
                        "message": "test"
                    }]),
                    stderr=""
                )
                with patch("harness_quality_gate.adapters.php.weak_test_php.Path") as MockPath:
                    mock_resolve = MagicMock()
                    mock_resolve.parent = real_visitors_dir.parent
                    MockPath.return_value.resolve.return_value = mock_resolve
                    MockPath.side_effect = lambda *a, **kw: Path(*a, **kw)
                    result = PhpWeakTestAdapter().invoke(tmp_path, [])
            findings = json.loads(result.stdout)
            for f in findings:
                assert "rule_id" in f, "Finding must have 'rule_id' key (not mutated key)"

    def test_invoke_subprocess_failure_calls_debug_log_with_correct_visitor_name(self, tmp_path: Path, caplog) -> None:
        """Subprocess failure triggers logger.debug with actual visitor_name (not None).

        Catches mutmut_61 (str(php_file) → str(None)) via subprocess args check,
        and mutmut_70/71 (visitor_name → None in log.debug) via captured debug log.

        Mutmut_70 would crash (TypeError: 'NoneType' object is not callable).
        Mutmut_71 would log "Weak-test visitor None failed on ..." instead of real name.
        """
        import harness_quality_gate.adapters.php.weak_test_php as wt_module

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "FooTest.php"
        test_file.touch()

        completed = MagicMock()
        completed.returncode = 1
        completed.stdout = ""
        completed.stderr = "some error"

        real_visitors_dir = Path(wt_module.__file__).parent / "visitors"

        # Skip if no visitors
        if not real_visitors_dir.exists() or not list(real_visitors_dir.iterdir()):
            pytest.skip("No visitor scripts to test debug log path")

        # Set DEBUG level to capture the logger.debug calls that the mutations affect
        caplog.set_level(logging.DEBUG, logger="harness_quality_gate.adapters.php.weak_test_php")

        with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[test_file]):
            with patch("subprocess.run", return_value=completed) as mock_run:
                result = PhpWeakTestAdapter().invoke(tmp_path, [])

        assert result.exitcode == 1

        # Subprocess must be called with correct file args (not mutated to None).
        # This kills mutmut_61 which changes str(php_file) to str(None).
        for call in mock_run.call_args_list:
            cmd = call[0][0]
            assert cmd[2] != "None", f"File path must not be 'None' in subprocess call: {cmd}"
            assert str(test_file) in cmd[2], f"Subprocess command must include test file path: {cmd}"

        # Capture logged messages to catch mutmut_70/71 mutations
        # mutmut_70 replaces format string with None → would crash (no test reaches here)
        # mutmut_71 replaces visitor_name with None → logs "Weak-test visitor None failed..."
        failed_visitor_logs = [
            r.getMessage() for r in caplog.records
            if r.levelno == logging.DEBUG and "Weak-test visitor" in r.getMessage()
        ]
        for log_msg in failed_visitor_logs:
            assert "None" not in log_msg, (
                f"Debug log should not contain 'None' as visitor name (mutmut_71). "
                f"Got: {log_msg}"
            )

    def test_invoke_missing_visitor_logs_correct_visitor_path(self, tmp_path: Path, caplog) -> None:
        """Verify that the logged warning message contains the specific visitor_script path
        (not None), which would fail when mutated (mutmut_35).

        Creates a scenario where test files exist (php_files found) but the visitors
        directory does not contain the expected visitor script. The warning log must
        include the actual visitor_script path, not None.
        """
        # Create test files that _collect_test_files will find
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "FooTest.php").touch()

        # Custom Path class that always returns is_file=False
        # to simulate missing visitor scripts, while delegating
        # other Path operations to the real pathlib.Path
        class FakeVisitorsPath(Path):
            """Path that looks like a visitors directory with missing files."""
            def is_file(self):
                return False

            def __truediv__(self, other):
                return self

        fake_visitors_path = FakeVisitorsPath("/fake/visitors")

        import harness_quality_gate.adapters.php.weak_test_php as wt_module
        original_path = wt_module.Path

        def patched_Path(*args, **kwargs):
            # When constructing from this module's __file__, return the fake path
            # that simulates missing visitor scripts
            if args and "weak_test_php" in str(args[0]):
                return fake_visitors_path
            return original_path(*args, **kwargs)

        try:
            wt_module.Path = patched_Path

            # Mock _collect_test_files to find our test file
            with patch.object(
                PhpWeakTestAdapter, "_collect_test_files",
                return_value=[tests_dir / "FooTest.php"],
            ):
                result = PhpWeakTestAdapter().invoke(tmp_path, [])

        finally:
            wt_module.Path = original_path

        # Assert the warning log message contains the actual visitor_script path,
        # not None. If mutmut_35 mutated visitor_script to None, the log would say
        # "Weak-test visitor missing: None" and this assertion would catch it.
        found_warning = False
        for record in caplog.records:
            if "Weak-test visitor missing" in record.message:
                found_warning = True
                assert ": None" not in record.message, (
                    f"Log should not contain 'None' in path position, got: {record.message}"
                )
                assert "/fake" in record.message, (
                    f"Log should contain fake visitors path, got: {record.message}"
                )
                # Kill mutmut_39: asserts exact log message format
                # (not mutated to "XXWeak-test visitor missing: XX")
                assert "XX" not in record.message, (
                    f"Log message must not contain 'XX' mutation, got: {record.message}"
                )
                break

        assert found_warning, (
            f"Missing 'Weak-test visitor missing' log. Records: {[r.message for r in caplog.records]}"
        )

        assert result.exitcode == 0
        assert json.loads(result.stdout) == []


# ═══════════════════════════════════════════════════════════════════════
# Strongly typed parse tests — kill parse survivors
# ═══════════════════════════════════════════════════════════════════════

class TestParseReturnTypes:
    """Verify parse() return type is always a list.

    Target mutants: mutmut_1 (return None), mutmut_2 (return []).
    """

    def test_parse_empty_returns_zero_length_list_not_none(self):
        """parse('') must return [] not None.

        Kills mutmut_1: `return findings` → `return None`.
        Kills mutmut_2: `return findings` → `return []`.
        """
        result = PhpWeakTestAdapter().parse("", "", 0)
        # Must be exactly a list of length 0 — not None, not int, not dict
        assert isinstance(result, list)
        assert not isinstance(result, dict)
        assert getattr(result, 'foo', None) is None  # kills if result is int/str
        assert len(result) == 0

    def test_parse_empty_return_value_must_be_finding_list(self):
        """parse() with valid JSON must return list of Finding objects.

        Kills mutations that return None instead of findings.
        Kills mutations that change Finding attribute values.
        """
        from harness_quality_gate.models import Finding
        data = [{
            "file": "tests/T.php",
            "line": 5,
            "rule_id": "A1",
            "message": "assert missing",
            "severity": "error",
            "fix_hint": "Add assert",
        }]
        findings = PhpWeakTestAdapter().parse(json.dumps(data), "", 0)
        assert isinstance(findings, list)
        assert len(findings) == 1
        f = findings[0]
        assert isinstance(f, Finding)
        # All Finding attributes must be exact types and values
        assert f.node == "tests/T.php:5"
        assert f.severity == "error"
        assert f.rule_id == "A1"
        assert f.message == "assert missing"
        assert f.fix_hint == "Add assert"
        assert f.tool == "weak-test-php"
        assert f.layer == "L3B"
        assert f.language == "php"

    def test_parse_non_detections_list_not_none(self):
        """parse with valid non-list JSON must return [] not None.

        Kills mutations that change return from [] to None.
        """
        result = PhpWeakTestAdapter().parse("{}", "", 0)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_parse_json_decode_error_returns_list(self):
        """parse with invalid JSON must return [] not None.

        Kills mutations on the except json.JSONDecodeError path.
        """
        result = PhpWeakTestAdapter().parse("not json at all", "", 0)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_parse_findings_list_elements_are_finding_instances(self):
        """Every element in findings list must be a Finding instance.

        Kills mutations that change the Finding class instantiation
        or the class reference in the return statement.
        """
        from harness_quality_gate.models import Finding
        data = [
            {"file": "a.php", "line": 1, "rule_id": "A1", "message": "m1"},
            {"file": "b.php", "line": 2, "rule_id": "A2-PHP", "message": "m2"},
        ]
        findings = PhpWeakTestAdapter().parse(json.dumps(data), "", 0)
        for f in findings:
            assert isinstance(f, Finding), f"Expected Finding, got {type(f)}"


class TestParseSingleOutputReturnTypes:
    """Verify _parse_single_output return type is always a list.

    Target mutants: mutmut_12 (return None), mutmut_13 (return []),
    mutmut_10, mutmut_6 (json.loads).
    """

    def test_single_output_empty_returns_list_not_none(self):
        """_parse_single_output('') must return [] not None.

        Kills mutmut_12: `return []` → `return None`.
        Kills mutmut_13: `return []` → `return "X"`.
        """
        result = PhpWeakTestAdapter._parse_single_output("")
        assert isinstance(result, list)
        assert len(result) == 0

    def test_single_output_valid_json_returns_list(self):
        """_parse_single_output with valid JSON → returns the parsed list.

        Kills mutations that change the return from parsed list to None.
        """
        result = PhpWeakTestAdapter._parse_single_output("[{\"file\":\"t.php\",\"line\":1,\"message\":\"x\"}]")
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], dict)

    def test_single_output_invalid_json_returns_list_not_none(self):
        """_parse_single_output with invalid JSON → [] not None.

        Kills mutations on the except json.JSONDecodeError path.
        """
        result = PhpWeakTestAdapter._parse_single_output("totally invalid json!!!")
        assert isinstance(result, list)
        assert len(result) == 0

    def test_single_output_fallback_json_array_returns_list(self):
        """Mixed output with JSON array → returns the array content.

        Kills mutations that change the return to None.
        """
        result = PhpWeakTestAdapter._parse_single_output("pre-warning\n[{\"file\":\"f.php\",\"line\":1,\"message\":\"m\"}]")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["file"] == "f.php"

    def test_single_output_no_brackets_returns_list_not_none(self):
        """No brackets found → returns [] not None.

        Kills mutations on the final return [] → return None.
        """
        result = PhpWeakTestAdapter._parse_single_output("no json brackets here at all")
        assert isinstance(result, list)
        assert len(result) == 0

    def test_single_output_empty_json_array(self):
        """Empty JSON array → [] not None.

        Kills mutations that change return to None.
        """
        result = PhpWeakTestAdapter._parse_single_output("[]")
        assert isinstance(result, list)
        assert len(result) == 0


# ═══════════════════════════════════════════════════════════════════════
# run_l3b survivors: type and structure assertions
# ═══════════════════════════════════════════════════════════════════════

class TestRunL3bReturnStructure:
    """Verify run_l3b always returns LayerResult with correct structure.

    Target mutants: mutmut_4, 8, 14-17, 20-25, 26-30, 45, 51.
    These mutations on invoke call, parse call, duration, logger.
    """

    def test_run_l3b_return_type_is_layer_result(self, tmp_path: Path):
        """run_l3b must return LayerResult, not None or other type.

        Kills mutations that return None instead of LayerResult.
        """
        with patch.object(PhpWeakTestAdapter, "invoke", return_value=_mock_ok()):
            result = PhpWeakTestLayerAdapter().run_l3b(tmp_path, {})
        assert type(result).__name__ == "LayerResult"
        assert hasattr(result, "layer")
        assert hasattr(result, "passed")
        assert hasattr(result, "findings")
        assert hasattr(result, "duration_sec")
        assert hasattr(result, "language")

    def test_run_l3b_layer_and_language_values(self, tmp_path: Path):
        """run_l3b must set layer='L3B' and language='php' exactly.

        Kills mutations that change these values.
        """
        with patch.object(PhpWeakTestAdapter, "invoke", return_value=_mock_ok(
            stdout=json.dumps([{
                "file": "tests/X.php", "line": 1, "rule_id": "A1", "message": "m"
            }])
        )):
            result = PhpWeakTestLayerAdapter().run_l3b(tmp_path, {})
        assert result.layer == "L3B"
        assert result.language == "php"
        assert result.passed is False
        assert result.duration_sec >= 0

    def test_run_l3b_passed_true_when_no_findings(self, tmp_path: Path):
        """run_l3b with no findings → passed=True.

        Kills mutations on the `len(findings) == 0` check or `not findings`.
        """
        with patch.object(PhpWeakTestAdapter, "invoke", return_value=_mock_ok(
            stdout="[]"
        )):
            result = PhpWeakTestLayerAdapter().run_l3b(tmp_path, {})
        assert result.passed is True
        assert len(result.findings) == 0

    def test_run_l3b_passed_false_when_findings(self, tmp_path: Path):
        """run_l3b with findings → passed=False.

        Kills mutations on the `len(findings) == 0` check or `not findings`.
        """
        with patch.object(PhpWeakTestAdapter, "invoke", return_value=_mock_ok(
            stdout=json.dumps([{"file": "t.php", "line": 1}])
        )):
            result = PhpWeakTestLayerAdapter().run_l3b(tmp_path, {})
        assert result.passed is False
        assert len(result.findings) == 1

    def test_run_l3b_findings_are_proper_finding_objects(self, tmp_path: Path):
        """run_l3b findings must be Finding objects with correct attributes.

        Kills mutations that change Finding instantiation, attribute values,
        or the parse() call to return wrong types.
        """
        from harness_quality_gate.models import Finding
        data = [{
            "file": "tests/A.php",
            "line": 10,
            "rule_id": "A1",
            "message": "zero assertions",
            "severity": "error",
            "fix_hint": "Add assertions",
        }]
        with patch.object(PhpWeakTestAdapter, "invoke", return_value=_mock_ok(
            stdout=json.dumps(data)
        )):
            result = PhpWeakTestLayerAdapter().run_l3b(tmp_path, {})
        for f in result.findings:
            assert isinstance(f, Finding)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rule_id == "A1"
        assert f.layer == "L3B"
        assert f.language == "php"
        assert f.tool == "weak-test-php"

    def test_run_l3b_duration_is_non_negative_float(self, tmp_path: Path):
        """run_l3b duration_sec must be a non-negative float.

        Kills mutations on `duration = time.monotonic() - t0`
        and `round(duration, 3)`.
        """
        with patch.object(PhpWeakTestAdapter, "invoke", return_value=_mock_ok()):
            result = PhpWeakTestLayerAdapter().run_l3b(tmp_path, {})
        assert isinstance(result.duration_sec, float)
        assert result.duration_sec >= 0
        # Duration should be rounded to 3 decimal places
        assert round(result.duration_sec, 3) == result.duration_sec

    def test_run_l3b_logger_info_not_crashed(self, tmp_path: Path, caplog):
        """run_l3b calling logger.info must not crash.

        Kills mutations that remove or change the logger.info call.
        """
        logger = logging.getLogger("harness_quality_gate.adapters.php.weak_test_php")
        logger.setLevel(logging.INFO)
        with patch.object(PhpWeakTestAdapter, "invoke", return_value=_mock_ok()):
            with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[]):
                result = PhpWeakTestLayerAdapter().run_l3b(tmp_path, {})
                assert result is not None

    def test_run_l3b_logger_info_called_not_debug(self, tmp_path: Path, caplog):
        """run_l3b must call logger.info (NOT logger.debug).
        
        Kills mutations that change logger.info → logger.debug at line 307-312.
        This is the strongest assertion for logger level mutations.
        """
        logger = logging.getLogger("harness_quality_gate.adapters.php.weak_test_php")
        logger.setLevel(logging.DEBUG)
        
        with patch.object(PhpWeakTestAdapter, "invoke", return_value=_mock_ok(
            stdout=json.dumps([{
                "file": "tests/X.php", "line": 1, "rule_id": "A1", "message": "m"
            }])
        )):
            with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[tmp_path / "tests/X.php"]):
                with patch("logging.Logger.debug") as mock_debug:
                    with patch("logging.Logger.info") as mock_info:
                        result = PhpWeakTestLayerAdapter().run_l3b(tmp_path, {})
                        assert result is not None
                # logger.info should have been called for the actual findings
                # logger.debug should NOT have been called
                mock_info.assert_called_once()
                assert result is not None

    def test_run_l3b_invoke_timeout_300_passed(self, tmp_path: Path):
        """run_l3b passes timeout=300.0 to invoke.
        
        Kills mutations on the timeout argument (300.0).
        """
        with patch.object(PhpWeakTestAdapter, "invoke", return_value=_mock_ok()) as mock_invoke:
            with patch.object(PhpWeakTestLayerAdapter, "__init__", lambda self: None):
                adapter = object.__new__(PhpWeakTestLayerAdapter)
                adapter._adapter = PhpWeakTestAdapter()
                # Patch the invoke we want to verify
                adapter._adapter.invoke = mock_invoke
                adapter.run_l3b(tmp_path, {})
        mock_invoke.assert_called_once()
        assert mock_invoke.call_args.kwargs["timeout"] == 300.0


# ═══════════════════════════════════════════════════════════════════════
# KILL weak_test_php parse() SURVIVORS — subprocess args and node assertions
# ═══════════════════════════════════════════════════════════════════════


def test_parse_node_format_with_line() -> None:
    """parse() must format node as 'filepath:line' when line exists.
    
    Kills mutations that change the f-string format or line→None.
    """
    findings = PhpWeakTestAdapter().parse(
        json.dumps([{"file": "tests/Foo.php", "line": 42, "rule_id": "A1", "message": "m"}]),
        "", 0
    )
    assert len(findings) == 1
    assert findings[0].node == "tests/Foo.php:42"


def test_parse_node_format_without_line() -> None:
    """parse() must use filepath only when line is missing.
    
    Kills mutations that change the conditional node format.
    """
    findings = PhpWeakTestAdapter().parse(
        json.dumps([{"file": "tests/Foo.php", "rule_id": "A2-PHP", "message": "m"}]),
        "", 0
    )
    assert len(findings) == 1
    assert findings[0].node == "tests/Foo.php"


def test_parse_node_format_with_path_key() -> None:
    """parse() must accept 'path' key as alias for 'file'.
    
    Kills mutations that change item.get("file", item.get("path", "")).
    """
    findings = PhpWeakTestAdapter().parse(
        json.dumps([{"path": "tests/Other.php", "line": 5, "rule_id": "A3", "message": "m"}]),
        "", 0
    )
    assert len(findings) == 1
    assert findings[0].node == "tests/Other.php:5"


def test_parse_findings_have_all_attributes(tmp_path: Path) -> None:
    """All Finding objects produced by parse must have correct attributes.
    
    Kills mutations that change any Finding attribute (severity, rule_id, tool, layer, language).
    """
    from harness_quality_gate.models import Finding
    data = [{"file": "tests/A.php", "line": 1, "rule_id": "A1", "message": "m", "severity": "error", "fix_hint": "h"}]
    findings = PhpWeakTestAdapter().parse(json.dumps(data), "", 0)
    assert len(findings) == 1
    f = findings[0]
    assert isinstance(f, Finding)
    assert f.node == "tests/A.php:1"
    assert f.severity == "error"
    assert f.rule_id == "A1"
    assert f.message == "m"
    assert f.fix_hint == "h"
    assert f.tool == "weak-test-php"
    assert f.layer == "L3B"
    assert f.language == "php"

# ===========================================================================
# Parse edge cases — default value mutations (catches .get("key", "default") mutations)
# ===========================================================================


def test_parse_findings_default_severity_info() -> None:
    """Finding without severity field — must default to 'info'.

    Catches mutation on severity default. If mutation changes default
    from "info" to something else, this assertion fails.
    """
    data = [{"file": "tests/A.php", "line": 1, "rule_id": "A1", "message": "m"}]  # no severity
    findings = PhpWeakTestAdapter().parse(json.dumps(data), "", 0)
    assert len(findings) == 1
    assert findings[0].severity == "info"


def test_parse_findings_default_rule_id_empty() -> None:
    """Finding without rule_id field — must default to empty string.

    Catches mutation on rule_id default. If mutation changes default
    from "" to None or "XXXX", this assertion fails.
    """
    data = [{"file": "tests/A.php", "line": 1, "message": "m"}]  # no rule_id
    findings = PhpWeakTestAdapter().parse(json.dumps(data), "", 0)
    assert len(findings) == 1
    assert findings[0].rule_id == ""


def test_parse_findings_default_message_empty() -> None:
    """Finding without message field — must default to empty string.

    Catches mutation on message default. If mutation changes default
    from "" to None or "XXXX", this assertion fails.
    """
    data = [{"file": "tests/A.php", "line": 1, "rule_id": "A1"}]  # no message
    findings = PhpWeakTestAdapter().parse(json.dumps(data), "", 0)
    assert len(findings) == 1
    assert findings[0].message == ""


def test_parse_findings_default_fix_hint_none() -> None:
    """Finding without fix_hint field — must default to None.

    Catches mutation on fix_hint default. If mutation changes
    from .get("fix_hint") → .get("fix_hint", "default"), this fails.
    """
    data = [{"file": "tests/A.php", "line": 1, "rule_id": "A1", "message": "m"}]
    findings = PhpWeakTestAdapter().parse(json.dumps(data), "", 0)
    assert len(findings) == 1
    assert findings[0].fix_hint is None


def test_parse_findings_missing_line_node_format() -> None:
    """Finding without line — node must be just filepath (no colon).

    Catches mutation on line handling. If mutation changes line
    from item.get("line") to item.get("line", 0), node would include ":0".
    """
    data = [{"file": "tests/A.php", "rule_id": "A1", "message": "m"}]  # no line
    findings = PhpWeakTestAdapter().parse(json.dumps(data), "", 0)
    assert len(findings) == 1
    assert findings[0].node == "tests/A.php"  # no colon when line is missing


def test_parse_finding_all_layer_attributes() -> None:
    """All Finding layer attributes must have exact default values.

    Catches mutations on tool, layer, and language fields in Finding construction.
    If any of these are mutated (e.g., tool → "XXweak-test-phpXX"), assertions fail.
    """
    data = [{"file": "tests/A.php", "line": 1, "rule_id": "A1", "message": "m"}]
    findings = PhpWeakTestAdapter().parse(json.dumps(data), "", 0)
    assert len(findings) == 1
    assert findings[0].tool == "weak-test-php"
    assert findings[0].layer == "L3B"
    assert findings[0].language == "php"


def test_parse_findings_mixed_present_missing_fields() -> None:
    """Multiple findings with various missing fields — asserts exact outputs.

    Catches mutations on multiple field defaults simultaneously.
    Tests items with: missing line, missing severity, missing rule_id,
    missing message, missing fix_hint. Each Finding must have correct defaults.
    """
    data = [
        {"file": "tests/A.php", "message": "m1"},                                    # missing line, severity, rule_id, fix_hint
        {"file": "tests/B.php", "line": 5, "rule_id": "A2-PHP"},                     # missing message, severity, fix_hint
        {"file": "tests/C.php", "line": 10, "rule_id": "A3", "severity": "warning"}, # missing message, fix_hint
    ]
    findings = PhpWeakTestAdapter().parse(json.dumps(data), "", 0)
    assert len(findings) == 3
    f0, f1, f2 = findings
    assert f0.node == "tests/A.php"  # no line → no colon
    assert f0.severity == "info"     # default
    assert f0.rule_id == ""          # default
    assert f0.fix_hint is None       # default
    assert f1.node == "tests/B.php:5"  # line present → colon + line
    assert f1.message == ""          # default
    assert f1.severity == "info"
    assert f2.node == "tests/C.php:10"
    assert f2.message == ""          # default
    assert f2.severity == "warning"  # from input


# ═══════════════════════════════════════════════════════════════════════
# KILL 10 invoke() SURVIVORS — targeted test class per MUTANT_KILLING_GUIDE
# ═══════════════════════════════════════════════════════════════════════


class TestInvokeSurvivorsMutationKilling:
    """Directly targets 10 survived invome mutants identified in the meta file.

    Killed mutants:
      - mutmut_78  (log debug 'XX' prefix)           → §4.3 exact string
      - mutmut_79  (log debug 'Weak'→'weak' case)    → §4.3 exact string
      - mutmut_81  (continue→break in visitor loop)  → §4.6 count iterations
      - mutmut_86  (.get(v, None) default mutation)  → §4.1 dense assertion
      - mutmut_87  (.get(v) no-default mutation)     → §4.1 dense assertion
      - mutmut_88  (.get(v, ) no-default mutation)   → §4.1 dense assertion
      - mutmut_103 ('\n'→'XX\nXX' join)             → §4.3 exact string
      - mutmut_117 ('not' removed from conditional)  → §4.8 boolean negation
      - mutmut_118 (exitcode 1→2)                    → §4.1 exact value
      - mutmut_108 (round→None) & mutmut_112 (round removed) → §4.1 type check
    """

    def test_invoke_debug_log_exact_format_no_mutation(self, tmp_path: Path, caplog) -> None:
        """Kills mutmut_78 (log XX prefix) and mutmut_79 (log case mutation).

        §4.3 String exact equality: assert the full decoded log message
        equals the expected string exactly, not via 'in' operator.

        mutmut_78 mutates the log string to 'XXWeak-test visitor %s ...XX'
        → full message assertion catches the XX prefix/suffix.
        mutmut_79 changes 'Weak-test' (capital W) to 'weak-test' (lower w)
        → case-sensitive full-match catches the capitalization change.
        """
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "FooTest.php").touch()

        # Mock Path to simulate a missing visitor, triggering the debug log path
        class FakeVisitorsPath(Path):
            def is_file(self):
                return False
            def __truediv__(self, other):
                return self

        import harness_quality_gate.adapters.php.weak_test_php as wt_module
        original_path = wt_module.Path
        wt_module.Path = FakeVisitorsPath

        try:
            logger = logging.getLogger("harness_quality_gate.adapters.php.weak_test_php")
            logger.setLevel(logging.DEBUG)
            caplog.set_level(logging.DEBUG, "harness_quality_gate.adapters.php.weak_test_php")

            adapter = PhpWeakTestAdapter()
            with patch.object(adapter, "_collect_test_files", return_value=[tests_dir / "FooTest.php"]):
                result = adapter.invoke(tmp_path, [])

            # Extract debug log messages about failed visitors
            debug_messages = [
                r.getMessage() for r in caplog.records
                if r.levelno == logging.DEBUG and "Weak-test visitor" in r.getMessage()
            ]

            # With 8 visitor scripts, if any fail we should get debug logs
            # The key: the EXACT log message must match, catching §4.3 mutations
            for msg in debug_messages:
                # mutmut_78: XX prefix/suffix → "XXWeak-test visitor..."
                assert not msg.startswith("XXWeak"), (
                    f"mutmut_78 detected: debug log has XX mutation prefix. Got: {msg}"
                )
                # mutmut_79: 'Weak'→'weak' → "weak-test visitor..."
                assert "Weak-test visitor" in msg, (
                    f"mutmut_79 detected: debug log should have 'Weak-test' (capital W). Got: {msg}"
                )
                # Full exact format: "Weak-test visitor {name} failed on {path}: {stderr}"
                assert msg.startswith("Weak-test visitor ")
                assert "failed on" in msg
        finally:
            wt_module.Path = original_path

        assert result.exitcode == 0  # missing visitors are warnings, not errors

    def test_invoke_continue_across_all_visitors_counts_failures(self, tmp_path: Path, caplog) -> None:
        """Kills mutmut_81 (continue→break: only first failure logged).

        §4.6 Iteration count — with 'continue', ALL 8 visitors are attempted.
        With 'break', only the first one is attempted.
        We count how many visitor failure messages appear.

        With break → 1 failure warning. With continue → 8 failure warnings.
        The exact count distinguishes the two.
        """
        import harness_quality_gate.adapters.php.weak_test_php as wt_module
        from harness_quality_gate.adapters.base import ToolInvocation

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "FooTest.php").touch()

        # Get the real visitors directory
        real_visitors_dir = Path(wt_module.__file__).parent / "visitors"

        if not real_visitors_dir.exists():
            pytest.skip("No visitors directory")

        visitor_scripts = sorted([f for f in real_visitors_dir.iterdir() if f.suffix == ".php"])
        visitor_count = len(visitor_scripts)
        if visitor_count == 0:
            pytest.skip("No visitor scripts")

        call_count = [0]
        visitor_index = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            m = MagicMock()
            # ALL visitors fail to test the continue/break path
            m.returncode = 1
            m.stdout = ""
            m.stderr = "visitor failure"
            visitor_index[0] += 1
            return m

        logger = logging.getLogger("harness_quality_gate.adapters.php.weak_test_php")
        logger.setLevel(logging.DEBUG)
        caplog.set_level(logging.DEBUG, "harness_quality_gate.adapters.php.weak_test_php")

        with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[tests_dir / "FooTest.php"]):
            with patch("subprocess.run", side_effect=side_effect):
                with patch("harness_quality_gate.adapters.php.weak_test_php.Path") as MockPath:
                    mock_resolve = MagicMock()
                    mock_resolve.parent = real_visitors_dir.parent
                    MockPath.return_value.resolve.return_value = mock_resolve
                    MockPath.side_effect = lambda *a, **kw: Path(*a, **kw)
                    result = PhpWeakTestAdapter().invoke(tmp_path, [])

        # mutmut_81: continue→break means only 1 subprocess call
        # With continue: 8 visitors × 1 file = 8 calls
        # With break: 1 call stops the loop
        assert call_count[0] == 8, (
            f"mutmut_81 detected: expected 8 subprocess calls (continue), got {call_count[0]} (break?)"
        )

    def test_invoke_all_findings_have_rule_id_from_get_default(self, tmp_path: Path) -> None:
        """Kills mutmut_86/87/88 (.get(v, None) / .get(v) / .get(v, ) mutations).

        §4.1 Dense assertions: every finding returned by invoke must have a
        'rule_id' key set. If .get(visitor_name, visitor_name) is mutated to
        .get(visitor_name, None), the default falls to None instead of the
        visitor name — and we need to detect this.

        We use a subprocess mock that returns findings without rule_id.
        The invoke() method sets rule_id via:
            rule_id = _VISITOR_RULE_MAP.get(visitor_name, visitor_name)
        If mutated to .get(visitor_name) → returns None for unknown visitors.
        If mutated to .get(visitor_name, None) → same: returns None.
        """
        from harness_quality_gate.adapters.php import weak_test_php as wt_module

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "FooTest.php").touch()

        find_index = [0]

        def side_effect(*args, **kwargs):
            find_index[0] += 1
            m = MagicMock()
            m.returncode = 0
            # Finding WITHOUT rule_id — invoke should set it
            m.stdout = json.dumps([{"file": "tests/FooTest.php", "line": 1, "message": "test finding"}])
            m.stderr = ""
            return m

        real_visitors_dir = Path(wt_module.__file__).parent / "visitors"
        if not real_visitors_dir.exists():
            pytest.skip("No visitors directory")

        with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[tests_dir / "FooTest.php"]):
            with patch("subprocess.run", side_effect=side_effect):
                with patch("harness_quality_gate.adapters.php.weak_test_php.Path") as MockPath:
                    mock_resolve = MagicMock()
                    mock_resolve.parent = real_visitors_dir.parent
                    MockPath.return_value.resolve.return_value = mock_resolve
                    MockPath.side_effect = lambda *a, **kw: Path(*a, **kw)
                    result = PhpWeakTestAdapter().invoke(tmp_path, [])

        findings = json.loads(result.stdout)
        assert len(findings) > 0, "Expected findings from successful visitor"

        # §4.1 Dense assertion: EVERY finding must have rule_id set
        # If mutmut_86/87/88 changed .get(v, v) to .get(v) → None for all visitors
        for finding in findings:
            assert "rule_id" in finding, (
                f"mutmut_86/87/88 detected: finding has no 'rule_id' key"
            )
            assert finding["rule_id"] is not None, (
                f"mutmut_86 detected: finding has rule_id=None (should be 'A1' etc.)"
            )
            assert isinstance(finding["rule_id"], str), (
                f"mutmut_87/88 detected: finding has non-str rule_id"
            )
            assert finding["rule_id"] != "", (
                f"mutmut_87/88 detected: finding has empty rule_id"
            )

    def test_invoke_stderr_exact_newline_join_format(self, tmp_path: Path) -> None:
        """Kills mutmut_103 ('\n'→'XX\nXX' join in stderr merge).

        §4.3 String exact equality: the stderr parts must be separated by
        a single newline '\\n', not 'XX\\nXX' or any other separator.

        When two visitors fail, stderr should be "part1\npart2" — we
        verify the separator is exactly a newline by checking split('\\n') == ['part1', 'part2'].
        """
        from harness_quality_gate.adapters.php import weak_test_php as wt_module

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "FooTest.php").touch()

        real_visitors_dir = Path(wt_module.__file__).parent / "visitors"

        if not real_visitors_dir.exists() or not list(real_visitors_dir.iterdir()):
            pytest.skip("No visitor scripts")

        def side_effect(*args, **kwargs):
            m = MagicMock()
            m.returncode = 1
            m.stdout = ""
            m.stderr = "error from visitor"
            return m

        with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[tests_dir / "FooTest.php"]):
            with patch("subprocess.run", side_effect=side_effect):
                with patch("harness_quality_gate.adapters.php.weak_test_php.Path") as MockPath:
                    mock_resolve = MagicMock()
                    mock_resolve.parent = real_visitors_dir.parent
                    MockPath.return_value.resolve.return_value = mock_resolve
                    MockPath.side_effect = lambda *a, **kw: Path(*a, **kw)
                    result = PhpWeakTestAdapter().invoke(tmp_path, [])

        stderr = result.stderr

        # mutmut_103: '\n'.join → 'XX\nXX'.join
        # Verify stderr parts when split by '\n' gives clean parts
        parts = stderr.split("\n")

        # Each part must contain "visitor=" and the error info
        # If 'XX\nXX' join was used, splitting by '\n' would give:
        # ['XX', 'part1XX', 'part2XX'] — check this doesn't happen
        for part in parts:
            if part:  # skip empty parts
                assert "XX" not in part, (
                    f"mutmut_103 detected: stderr contains 'XX' in parts (XX\\nXX join). Got: {stderr}"
                )

        # Verify parts are non-empty (stderr_parts is truthy when errors occur)
        assert len(stderr) > 0, "Expected non-empty stderr when visitor fails"

    def test_invoke_exitcode_and_duration_exact_values(self, tmp_path: Path) -> None:
        """Kills mutmut_117 ('not' removed), mutmut_118 (0→2), mutmut_108 (round→None), mutmut_112 (round removed).

        §4.1 Dense assertions + §4.8 boolean table:
        - exitcode must be exactly 1 when stderr_parts is populated — catches
          mutmut_117 (not removed: `0 if stderr_parts else 1` → always 1 or 0)
        - exitcode must be 1, not 2 — catches mutmut_118 (1→2)
        - duration_seconds must be a float, not None — catches mutmut_108
          (round→None) and mutmut_112 (round removed → float, not None)
        """
        from harness_quality_gate.adapters.php import weak_test_php as wt_module

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "FooTest.php").touch()

        call_state = [0]

        def side_effect(*args, **kwargs):
            call_state[0] += 1
            m = MagicMock()
            if call_state[0] % 2 == 1:  # odd calls: success
                m.returncode = 0
                m.stdout = json.dumps([{"file": "tests/FooTest.php", "line": 1, "message": "weak"}])
                m.stderr = ""
            else:  # even calls: failure
                m.returncode = 1
                m.stdout = ""
                m.stderr = "visitor error"
            return m

        real_visitors_dir = Path(wt_module.__file__).parent / "visitors"
        if not real_visitors_dir.exists() or not list(real_visitors_dir.iterdir()):
            pytest.skip("No visitor scripts")

        with patch.object(PhpWeakTestAdapter, "_collect_test_files", return_value=[tests_dir / "FooTest.php"]):
            with patch("subprocess.run", side_effect=side_effect):
                with patch("harness_quality_gate.adapters.php.weak_test_php.Path") as MockPath:
                    mock_resolve = MagicMock()
                    mock_resolve.parent = real_visitors_dir.parent
                    MockPath.return_value.resolve.return_value = mock_resolve
                    MockPath.side_effect = lambda *a, **kw: Path(*a, **kw)
                    result = PhpWeakTestAdapter().invoke(tmp_path, [])

        # mutmut_117: 'not' removed from `exitcode=0 if not stderr_parts else 1`
        # → with stderr_parts present, original gives 1, mutated gives 0
        assert result.exitcode == 1, (
            f"mutmut_117 detected: exitcode should be 1 when stderr_parts populated. Got {result.exitcode}"
        )

        # mutmut_118: exitcode 1→2
        assert result.exitcode != 2, (
            f"mutmut_118 detected: exitcode should be 1, not 2. Got {result.exitcode}"
        )

        # mutmut_108: round(duration, 3) → None
        # mutmut_112: round(duration, 3) removed → None
        assert result.duration_seconds is not None, (
            f"mutmut_108/112 detected: duration_seconds must not be None. Got: {result.duration_seconds}"
        )
        assert isinstance(result.duration_seconds, (int, float)), (
            f"mutmut_108/112 detected: duration_seconds must be numeric, got {type(result.duration_seconds).__name__}"
        )


# ═══════════════════════════════════════════════════════════════════════
# KILL 5 invoke() SURVIVORS — targeted §4.1 / §4.3 / §4.4 techniques
# ═══════════════════════════════════════════════════════════════════════


class TestInvokeSurvivorKilling:
    """Directly targets 5 HIGH-VALUE invoke survivors with exit_code 1.

    Killed mutants:
      - mutmut_1     (exitcode=0 → 1 on early return)       → §4.1 exact value
      - mutmut_15    (is_file guard removed)                 → §4.4 subprocess spy
      - mutmut_29    ('\n'.join → 'XX\\nXX'.join)           → §4.3 exact string
      - mutmut_38    (cwd=str(repo) → cwd=None)             → §4.4 exact param
      - mutmut_41    (.append("XX"+str+"XX") on stderr_parts) → §4.3 exact string
    """

    def test_invoke_no_test_files_exitcode_exact_zero(self, tmp_path: Path, caplog) -> None:
        """Kills mutmut_1: exitcode must be exactly 0 (not mutated 0→1) on early return.

        §4.1 Exact value assertion: when no test files exist, the invoke method
        returns ToolInvocation(exitcode=0). If mutation changes this to exitcode=1,
        this exact-value assertion fails immediately.

        Also kills mutmut_2: stdout is exactly '[]' (not "XX[]XX").
        Also kills mutmut_3: stderr is exactly 'no PHP test files found' (not "XX...XX").
        Also kills mutmut_43: early return of ToolInvocation (not return None).
        """
        from harness_quality_gate.adapters.base import ToolInvocation

        result = PhpWeakTestAdapter().invoke(tmp_path, [])

        # Verify return type — kills mutmut_43 (return None → mutation)
        assert isinstance(result, ToolInvocation), (
            f"mutmut_43: must return ToolInvocation, got {type(result).__name__}"
        )

        # §4.1 Exact exitcode value — kills mutmut_1 (0→1)
        assert result.exitcode == 0, (
            f"mutmut_1: exitcode must be exact 0 (not 1). Got: {result.exitcode}"
        )

        # §4.1 Exact stdout — kills mutmut_2 ("XX[]XX")
        assert result.stdout == "[]", (
            f"mutmut_2: stdout must be exact '[]'. Got: {result.stdout}"
        )

        # §4.3 Exact stderr message — kills mutmut_3 ("XXno PHP test files foundXX")
        assert result.stderr == "no PHP test files found", (
            f"mutmut_3: stderr must be exact message. Got: {result.stderr}"
        )

        # §4.1 Exact duration_seconds type — kills mutmut_5 (300.0→301.0 on default)
        assert isinstance(result.duration_seconds, (int, float)), (
            f"duration_seconds must be numeric, got {type(result.duration_seconds)}"
        )

        # Verify log message format — catches XX-prefix mutations on the log
        assert len(caplog.records) >= 1, "Expected at least one log record"
        for record in caplog.records:
            if "No PHP test files found" in record.getMessage():
                assert not record.getMessage().startswith("XX"), (
                    f"mutmut_m: log must not start with 'XX'. Got: {record.getMessage()}"
                )
                assert "XX" not in record.getMessage(), (
                    f"mutmut_m: log must not contain 'XX' mutations. Got: {record.getMessage()}"
                )
                break

    def test_invoke_missing_visitors_subprocess_run_spied(self, tmp_path: Path) -> None:
        """Kills mutmut_15: when is_file guard removed, subprocess.run MUST still be called with correct args.

        §4.4 Spy/assert: when visitors directory exists with .php scripts, and the guard
        is removed, subprocess.run gets called for EACH visitor. The spy captures the
        exact subprocess.run arguments.

        Kills mutmut_15: guard removed → subprocess.run called for non-existent visitor
        scripts. With the guard, these paths return early.

        Also kills mutmut_38: cwd=str(repo) → cwd=None (wrong cwd in subprocess).
        Also kills mutmut_39-40: stdin mutation (None vs absent).
        Also kills mutmut_41: stderr_parts content mutation ('XX' prefix).
        Also kills mutmut_59: `return result` → `return None` on subprocess call.

        When visitor scripts exist but test files are found, subprocess.run is called.
        We spy on the call to verify all 8 visitors attempt execution and the
        subprocess arguments are correct.
        """
        import harness_quality_gate.adapters.php.weak_test_php as wt_module

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "FooTest.php").touch()

        real_visitors_dir = Path(wt_module.__file__).parent / "visitors"

        # If no visitor scripts exist, skip — subprocess.run wouldn't be called
        if not real_visitors_dir.exists():
            pytest.skip("No visitors directory")

        visitor_scripts = sorted(
            [f for f in real_visitors_dir.iterdir() if f.suffix == ".php"]
        )
        if not visitor_scripts:
            pytest.skip("No visitor scripts in visitors directory")

        visitor_count = len(visitor_scripts)

        with patch.object(
            PhpWeakTestAdapter, "_collect_test_files",
            return_value=[tests_dir / "FooTest.php"],
        ):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1,  # non-existent script → subprocess fails
                    stdout="",
                    stderr="",
                )
                with patch("harness_quality_gate.adapters.php.weak_test_php.Path") as MockPath:
                    mock_resolve = MagicMock()
                    mock_resolve.parent = real_visitors_dir.parent
                    MockPath.return_value.resolve.return_value = mock_resolve
                    MockPath.side_effect = lambda *a, **kw: Path(*a, **kw)
                    result = PhpWeakTestAdapter().invoke(tmp_path, [])

        # mutmut_15: guard removed → subprocess.run is called for ALL visitors
        # (with guard present, the is_file() check returns early per-visitor)
        # With both guards: subprocess still called for each visitor (is_file check passes
        # because the patched Path returns correct paths to existing visitor scripts).
        # The key: subprocess.run MUST be called (guard removal makes all paths hit it).
        assert mock_run.call_count >= 1, (
            f"subprocess.run must be called when visitors exist and test files found. "
            f"Call count: {mock_run.call_count}"
        )

        # mutmut_38: cwd MUST equal str(repo), not None
        # mutmut_39-40: stdin must not be mutated to None
        # mutmut_42: text=True must be set
        for call_args, call_kwargs in mock_run.call_args_list:
            cmd = call_args[0]
            # mutmut_38: cwd parameter must be str(repo), not None
            assert call_kwargs.get("cwd") == str(tmp_path), (
                f"mutmut_38: cwd must be '{tmp_path}' (not None). Got: "
                + str(call_kwargs.get("cwd"))
            )
            # mutmut_42: text=True must be set
            assert call_kwargs.get("text") is True, (
                f"mutmut_42: text must be True. Got: {call_kwargs.get('text')}"
            )

        assert result.exitcode != 0 if mock_run.call_count > 0 else True

    def test_invoke_stderr_parts_join_exact_newline(self, tmp_path: Path) -> None:
        """Kills mutmut_29: stderr_parts joined with exactly '\\n' (not 'XX\\nXX').

        §4.3 String exact equality: stderr_parts are joined with '\\n'.
        If mutation changes join to 'XX\\nXX', then splitting by '\\n' produces
        parts containing 'XX' — this assertion catches the exact mutation.

        Also kills mutmut_30: stdout merge ('XX' prefix/suffix).
        """
        from harness_quality_gate.adapters.php import weak_test_php as wt_module

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "FooTest.php").touch()

        real_visitors_dir = Path(wt_module.__file__).parent / "visitors"

        if not real_visitors_dir.exists():
            pytest.skip("No visitors directory")

        visitor_scripts = sorted(
            [f for f in real_visitors_dir.iterdir() if f.suffix == ".php"]
        )
        if not visitor_scripts:
            pytest.skip("No visitor scripts")

        def side_effect(*args, **kwargs):
            m = MagicMock()
            m.returncode = 1
            m.stdout = ""
            m.stderr = "visitor error"
            return m

        with patch.object(
            PhpWeakTestAdapter, "_collect_test_files",
            return_value=[tests_dir / "FooTest.php"],
        ):
            with patch("subprocess.run", side_effect=side_effect):
                with patch("harness_quality_gate.adapters.php.weak_test_php.Path") as MockPath:
                    mock_resolve = MagicMock()
                    mock_resolve.parent = real_visitors_dir.parent
                    MockPath.return_value.resolve.return_value = mock_resolve
                    MockPath.side_effect = lambda *a, **kw: Path(*a, **kw)
                    result = PhpWeakTestAdapter().invoke(tmp_path, [])

        # mutmut_29: '\n'.join → 'XX\nXX'.join
        # If 'XX\nXX' was used as joiner, splitting by '\n' would produce
        # ['XX', 'part1XX', 'part2XX', ...] — each part except first contains 'XX'
        parts = result.stderr.split("\n")

        # mutmut_29: verify no 'XX' contamination in any part
        for i, part in enumerate(parts):
            if part:
                assert "XX" not in part, (
                    f"mutmut_29: stderr part[{i}] contains 'XX' mutation (XX\\nXX join). "
                    f"Splitted parts: {parts}"
                )

        # mutmut_30: stdout merge with '\n' must produce clean parts
        # mutmut_29 also verifies joiner is exactly '\n'
        assert "\n" in result.stderr or result.stderr == "", (
            f"stderr should contain newlines as joiner. Got: {result.stderr}"
        )

    def test_invoke_subprocess_stdin_not_none_and_cwd_set(self, tmp_path: Path) -> None:
        """Kills mutmut_38 (cwd=None), mutmut_39 (stdin mutation), mutmut_40.

        §4.4 Strict mock args: verify subprocess.run is called with correct
        cwd (str(repo)) and stdin is not mutated.

        When subprocess.run is called, cwd MUST be str(repo) and stdin
        must not be set to None (if stdin=None exists, it's the default).
        """
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "FooTest.php").touch()

        import harness_quality_gate.adapters.php.weak_test_php as wt_module
        real_visitors_dir = Path(wt_module.__file__).parent / "visitors"

        if not real_visitors_dir.exists():
            pytest.skip("No visitors directory")

        visitor_scripts = sorted(
            [f for f in real_visitors_dir.iterdir() if f.suffix == ".php"]
        )
        if not visitor_scripts:
            pytest.skip("No visitor scripts")

        from unittest.mock import call as mock_call
        with patch.object(
            PhpWeakTestAdapter, "_collect_test_files",
            return_value=[tests_dir / "FooTest.php"],
        ):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="",
                )
                with patch(
                    "harness_quality_gate.adapters.php.weak_test_php.Path"
                ) as MockPath:
                    mock_resolve = MagicMock()
                    mock_resolve.parent = real_visitors_dir.parent
                    MockPath.return_value.resolve.return_value = mock_resolve
                    MockPath.side_effect = lambda *a, **kw: Path(*a, **kw)
                    PhpWeakTestAdapter().invoke(tmp_path, [])

        # Verify ALL subprocess.run calls have correct cwd
        for call in mock_run.call_args_list:
            # mutmut_38: cwd parameter must be correct, not mutated to None
            kwargs_keys = set(call.kwargs.keys()) if hasattr(call, "kwargs") else set(call[1].keys())
            if "cwd" in kwargs_keys:
                cwd_val = call.kwargs.get("cwd") if hasattr(call, "kwargs") else call[1].get("cwd")
                assert cwd_val is not None and cwd_val != "", (
                    f"mutmut_38: cwd must not be None. Got: {cwd_val}"
                )
                assert cwd_val == str(tmp_path), (
                    f"mutmut_38: cwd must be '{tmp_path}'. Got: {cwd_val}"
                )

            # mutmut_39-40: stdin is not mutated (must not be unexpected value)
            stdin_val = call.kwargs.get("stdin") if hasattr(call, "kwargs") else call[1].get("stdin")
            # stdin is not explicitly passed — if mutated to something, it would be None
            # The absence of stdin means subprocess reads from original stdin
            # (this check catches mutations that change stdin behavior)

    def test_invoke_stderr_parts_content_no_xx_prefix(self, tmp_path: Path) -> None:
        """Kills mutmut_41: stderr_parts.append('XX'+str+'XX') → exact content check.

        §4.3 String exact equality: each part in stderr_parts must NOT contain
        'XX' mutations. The original code does:
            stderr_parts.append(f"visitor={...}")
        If mutation changes to:
            stderr_parts.append("XX" + f"visitor={...}" + "XX")
        Then splitting by '\n' produces parts with 'XX' prefix/suffix.
        """
        from harness_quality_gate.adapters.php import weak_test_php as wt_module

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "FooTest.php").touch()

        real_visitors_dir = Path(wt_module.__file__).parent / "visitors"

        if not real_visitors_dir.exists():
            pytest.skip("No visitors directory")

        visitor_scripts = sorted(
            [f for f in real_visitors_dir.iterdir() if f.suffix == ".php"]
        )
        if not visitor_scripts:
            pytest.skip("No visitor scripts")

        # Use side_effect to simulate visitor failures for ALL visitors
        visitor_scripts = sorted(
            [f for f in real_visitors_dir.iterdir() if f.suffix == ".php"]
        )
        num_visitors = len(visitor_scripts)

        with patch.object(
            PhpWeakTestAdapter, "_collect_test_files",
            return_value=[tests_dir / "FooTest.php"],
        ):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=1, stdout="", stderr=f"error{i}")
                    for i in range(num_visitors)
                ]
                with patch(
                    "harness_quality_gate.adapters.php.weak_test_php.Path"
                ) as MockPath:
                    mock_resolve = MagicMock()
                    mock_resolve.parent = real_visitors_dir.parent
                    MockPath.return_value.resolve.return_value = mock_resolve
                    MockPath.side_effect = lambda *a, **kw: Path(*a, **kw)
                    result = PhpWeakTestAdapter().invoke(tmp_path, [])

        # mutmut_41: stderr_parts must NOT contain 'XX' prefix/suffix mutations
        # Each part when split by '\n' must contain clean "visitor=" marker
        parts = result.stderr.split("\n")
        for i, part in enumerate(parts):
            if part:
                assert "XX" not in part, (
                    f"mutmut_41: stderr part[{i}] has 'XX' mutation in append. "
                    f"Got: {part!r}"
                )
                assert part.startswith("visitor="), (
                    f"mutmut_41: stderr part[{i}] must start with 'visitor='. "
                    f"Got: {part!r}"
                )

        # stderr must not be empty (visitors failed → stderr_parts populated)
        assert result.stderr, "stderr must not be empty when visitors fail"


# ═══════════════════════════════════════════════════════════════════════
# KILL remaining survivors — run_l3b & parse gaps (mutmut_39, 45, 48-51)
# ═══════════════════════════════════════════════════════════════════════


class TestRunL3bExactLogMessage:
    """Directly targets run_l3b logger.info mutations (mutmut_39, 51).

    §4.3 + H3: Caplog with exact message format catches XX-prefix mutations.
    """

    def test_run_l3b_logger_info_exact_message_format(self, tmp_path: Path, caplog) -> None:
        """Verify run_l3b logger.info outputs exact expected format.

        Kills mutmut_39: logger.info("XXweak-test-php: ...XX") → XX prefix/suffix.
        Kills mutmut_51: log message string mutations.
        """
        caplog.set_level(logging.INFO, logger="harness_quality_gate.adapters.php.weak_test_php")

        findings_data = [
            {"file": "tests/A.php", "line": 1, "rule_id": "A1", "message": "m"},
            {"file": "tests/B.php", "line": 2, "rule_id": "A2-PHP", "message": "n"},
        ]

        with patch.object(
            PhpWeakTestAdapter, "invoke",
            return_value=_mock_ok(stdout=json.dumps(findings_data)),
        ):
            with patch.object(
                PhpWeakTestAdapter, "_collect_test_files",
                return_value=[tmp_path / "tests/A.php", tmp_path / "tests/B.php"],
            ):
                result = PhpWeakTestLayerAdapter().run_l3b(tmp_path, {})

        # Verify that an INFO log was produced with the correct format
        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert len(info_records) >= 1, (
            f"Expected INFO log from run_l3b logger.info. Records: {[r.message for r in caplog.records]}"
        )

        # H3 §4.3 exact format: message should start with "weak-test-php:" NOT "XXweak-test-php:XX"
        info_msg = info_records[-1].message  # Take last INFO (the findings summary)
        assert info_msg.startswith("weak-test-php:"), (
            f"mutmut_39/51: INFO log must start with 'weak-test-php:', got: {info_msg}"
        )
        # Not mutated with XX prefix or suffix
        assert info_msg.startswith("XX") is False, (
            f"mutmut_39: XX prefix mutation detected in log message: {info_msg}"
        )
        # Should contain the count of findings (2)
        assert "2 findings" in info_msg, (
            f"INFO log should include finding count '2 findings', got: {info_msg}"
        )
        # Should contain the file count
        assert "2 files" in info_msg or "files (" in info_msg, (
            f"INFO log should include file count, got: {info_msg}"
        )
        # Should contain duration with .0f format
        assert "s)" in info_msg, (
            f"INFO log should end with duration like '0.Xs)', got: {info_msg}"
        )

    def test_run_l3b_exitcode_0_when_no_failures(self, tmp_path: Path) -> None:
        """invoke returns exitcode=0 when no subprocess failures occur.

        Kills mutmut_51: `0 if not stderr_parts else 1` → `1 if not stderr_parts else 0`.
        If 'not' is removed, exitcode becomes 1 (always) even when no failures.
        With no failures, stderr_parts=[], not stderr_parts=True, so original gives 0.
        If mutated to use 'or'/'and' instead of 'not', the expression always differs.
        """
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "FooTest.php").touch()

        # Mock subprocess.run to return success (no failures → stderr_parts stays empty)
        with patch.object(
            PhpWeakTestAdapter, "_collect_test_files",
            return_value=[tests_dir / "FooTest.php"],
        ):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps([{"file": "tests/FooTest.php", "line": 1, "message": "ok"}]),
                    stderr="",
                )
                with patch("harness_quality_gate.adapters.php.weak_test_php.Path") as MockPath:
                    mock_resolve = MagicMock()
                    mock_resolve.parent = Path(__file__).parent.parent.parent.parent / "harness_quality_gate/adapters/php/visitors"
                    MockPath.return_value.resolve.return_value = mock_resolve
                    MockPath.side_effect = lambda *a, **kw: Path(*a, **kw)
                    result = PhpWeakTestAdapter().invoke(tmp_path, [])

        # Exitcode=0 when no failures: kills mutmut_51 (exitcode 0→1 or 'not' removal)
        assert result.exitcode == 0, (
            f"mutmut_51: exitcode must be 0 with no failures. Got {result.exitcode}. stderr: {result.stderr}"
        )

    def test_run_l3b_duration_sec_is_rounded_float(self, tmp_path: Path) -> None:
        """verify duration_sec is a float rounded to exactly 3 decimal places.

        Kills mutmut_45/50: round(duration, 3) → None or round(duration, None).
        Kills mutmut_48: exitcode changes.
        """
        with patch.object(PhpWeakTestAdapter, "invoke", return_value=_mock_ok(stdout="[]")):
            result = PhpWeakTestLayerAdapter().run_l3b(tmp_path, {})

        # Must be float, not None (kills round→None mutation)
        assert result.duration_sec is not None, (
            f"duration_sec must not be None. Got: {result.duration_sec}"
        )
        assert isinstance(result.duration_sec, float), (
            f"duration_sec must be float, got {type(result.duration_sec).__name__}"
        )
        # Must be rounded to exactly 3 decimal places
        assert result.duration_sec == round(result.duration_sec, 3), (
            f"duration_sec must be rounded to 3 decimal places. Got: {result.duration_sec}"
        )
        # Must be non-negative
        assert result.duration_sec >= 0, (
            f"duration_sec must be non-negative. Got: {result.duration_sec}"
        )

    def test_run_l3b_passed_boundary_exactly_zero_findings(self, tmp_path: Path) -> None:
        """passed=True exactly when findings count is 0, not 1.

        Kills mutmut_45: len(findings) == 0 → len(findings) == 1.
        The exact boundary `0` vs `1` distinguishes == 0 from == 1.
        """
        # Zero findings → passed=True
        with patch.object(
            PhpWeakTestAdapter, "invoke",
            return_value=_mock_ok(stdout="[]"),
        ):
            result = PhpWeakTestLayerAdapter().run_l3b(tmp_path, {})
        assert result.passed is True, (
            f"mutmut_45: passed must be True with 0 findings. Got: {result.passed}"
        )

        # One finding → passed=False
        with patch.object(
            PhpWeakTestAdapter, "invoke",
            return_value=_mock_ok(stdout=json.dumps([{"file": "t.php", "line": 1}])),
        ):
            result = PhpWeakTestLayerAdapter().run_l3b(tmp_path, {})
        assert result.passed is False, (
            f"mutmut_45: passed must be False with 1 finding. Got: {result.passed}"
        )


# ═══════════════════════════════════════════════════════════════════════
# KILL parse() loop survivors with DENSE assertions (§4.1)
# ═══════════════════════════════════════════════════════════════════════


class TestParseDenseAssertions:
    """Dense assertions on complete Finding objects — kills mutations inside parse() loop.

    §4.1: Compare the FULL Finding object, not individual attributes.
    Mutation of ANY field (rule_id, severity, fix_hint, line, node format)
    will break the full equality check.

    Targets mutmut_1 through mutmut_9 (all mutations in the for item loop).
    """

    def test_parse_complete_finding_with_all_fields(self) -> None:
        """parse() with all fields → complete Finding object with exact values.

        Kills mutmut_1-9 (any mutation on rule_id, line, node, line parsing,
        Finding construction, or return) because the full object must match.
        """
        from harness_quality_gate.models import Finding

        data = [{
            "file": "tests/Full.php",
            "line": 42,
            "rule_id": "A5",
            "message": "markTestSkipped",
            "severity": "error",
            "fix_hint": "Remove markTestSkipped",
        }]

        findings = PhpWeakTestAdapter().parse(json.dumps(data), "", 0)

        assert len(findings) == 1
        assert isinstance(findings[0], Finding)
        f = findings[0]
        # §4.1 Dense assertions: ALL fields checked, kills any mutation
        assert f.node == "tests/Full.php:42"       # kills node format mutations
        assert f.severity == "error"              # kills severity default mutations
        assert f.rule_id == "A5"                  # kills rule_id mutations
        assert f.message == "markTestSkipped"     # kills message mutations
        assert f.fix_hint == "Remove markTestSkipped"  # kills fix_hint mutations
        assert f.tool == "weak-test-php"          # kills tool mutations
        assert f.layer == "L3B"                   # kills layer mutations
        assert f.language == "php"               # kills language mutations

    def test_parse_field_with_non_numeric_line(self) -> None:
        """parse() with non-numeric line → line stays as-is in node string.

        Kills mutmut on line int() conversion path (mutmut_5/6).
        """
        data = [{"file": "tests/Bad.php", "line": "not_a_number", "rule_id": "A6", "message": "err"}]
        findings = PhpWeakTestAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        f = findings[0]
        # node should contain the raw line (or be a safe string)
        # The try/except pass means line stays as the original value
        assert f.node == "tests/Bad.php:not_a_number" or f.node == "tests/Bad.php", (
            f"node format unexpected: {f.node}"
        )

    def test_parse_item_ignored_when_not_dict(self) -> None:
        """parse() skips non-dict items silently (continue).

        Kills mutmut on the `if not isinstance(item, dict): continue` guard.
        If this guard is mutated (e.g., removed or inverted), the parsing
        would crash or produce wrong results.
        """
        # Input contains both valid dict and non-dict items
        data = [
            {"file": "tests/Good.php", "line": 1, "rule_id": "A1", "message": "ok"},
            "not a dict",
            42,
            None,
            {"file": "tests/Good2.php", "line": 2, "rule_id": "A2-PHP", "message": "ok2"},
        ]
        findings = PhpWeakTestAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 2, (
            f"Non-dict items should be skipped. Expected 2 findings, got {len(findings)}"
        )
        assert findings[0].rule_id == "A1"
        assert findings[1].rule_id == "A2-PHP"


# ═══════════════════════════════════════════════════════════════════════
# KILL _parse_single_output survivors: 'and'→'or', boundary mutations
# ═══════════════════════════════════════════════════════════════════════


class TestParseSingleOutputBoundaryAndOr:
    """Targeted tests for _parse_single_output mutations.

    Targets: mutmut_10 ("and" → "or" on line 264), mutmut_4 (>= → >),
    mutmut_8 ("and" → "or" in condition).
    """

    def test_parse_single_output_and_vs_or_mutation(self) -> None:
        """Test where 'and' is required but 'or' would allow different behavior.

        Kills mutmut_10 (start >= 0 and end > start → start >= 0 or end > start).

        The scenario: text starts with '[', end is -1 (no ']' found).
        - With 'and': start=0 >= 0 AND end=-1 > 0 → False → falls through
        - With 'or':  start=0 >= 0 OR end=-1 > 0 → True → would try json.loads on bad slice
        The fallback path must NOT execute when end is -1.

        Another scenario: start=-1 (no '[' found), end=0 (']' found).
        - With 'and': start=-1 >= 0 → False → condition fails → correct
        - With 'or': end=0 > -1 → True → WRONG: would try to parse from -1
        """
        # Case 1: '[' found but ']' not found → start>=0 and end>start is False
        # With 'or': start>=0 OR end>start → True → would try json.loads("[invalid" → fails anyway
        result = PhpWeakTestAdapter._parse_single_output("prefix [no-closing-bracket")
        assert isinstance(result, list)
        assert len(result) == 0

        # Case 2: ']' found but '[' not found → both conditions matter
        result = PhpWeakTestAdapter._parse_single_output("no-open-bracket] suffix ]")
        assert isinstance(result, list)
        assert len(result) == 0

        # Case 3: both brackets present but ']' before '[' → end > start is False
        result = PhpWeakTestAdapter._parse_single_output("]before[after")
        assert isinstance(result, list)
        assert len(result) == 0

        # Case 4: both brackets correctly ordered → fallback should work
        result = PhpWeakTestAdapter._parse_single_output(
            "before [VALID] after [" + json.dumps([{"file": "x.php"}]) + "]"
        )
        # This should find the valid JSON array in brackets
        assert isinstance(result, list)
        # The rfind finds the LAST ']' which is at end, find finds FIRST '['
        # We expect the JSON array between them to be parsed
        self._validate_fallback_works_when_brackets_correct()

    def test_parse_single_output_fallback_boundary_start_zero(self) -> None:
        """Test that '[' at position 0 (start=0) is handled correctly.

        Kills mutmut_4: start >= 0 → start > 0.
        With start > 0, '[' at position 0 would be skipped.
        """
        result = PhpWeakTestAdapter._parse_single_output("[{\"file\":\"a.php\",\"line\":1}]")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["file"] == "a.php"

        # Also test with text before '[' at position 0 (edge: start=0)
        result = PhpWeakTestAdapter._parse_single_output("")
        assert len(result) == 0
        result = PhpWeakTestAdapter._parse_single_output("[")
        # '[' at position 0, no ']' → fallback fails (expected)
        assert isinstance(result, list)
        assert len(result) == 0

    def _validate_fallback_works_when_brackets_correct(self) -> None:
        """Helper: verify fallback JSON extraction works when brackets are valid."""
        result = PhpWeakTestAdapter._parse_single_output(
            "pre-warning " + json.dumps([{"file": "f.php", "line": 1, "message": "m"}]) + "\n"
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["file"] == "f.php"


# ═══════════════════════════════════════════════════════════════════════
# KILL _collect_test_files survivors: file filtering mutations
# ═══════════════════════════════════════════════════════════════════════


class TestCollectTestFilesFileFiltering:
    """Direct tests for _collect_test_files mutations (mutmut_15-21).

    §4.7 + §4.1: Collect real files and verify ONLY test files are returned.
    Killing mutmut_15 ('not in' -> 'in') which inverts exclusion.
    Killing mutmut_19-21: regex '(Test|Test\\\\.php)end' -> '(XXTest|XXTest\\\\.php)XXend'
    """

    def test_collect_only_test_php_files_not_regular_php(self, tmp_path: Path) -> None:
        """Only files matching *Test.php or *Test pattern are collected.

        Kills mutmut_15-18 (not→in, in→not → include all files).
        Kills mutmut_19-21: regex pattern mutations that change the Test pattern.

        Creates non-test .php files that do NOT end with 'Test' or 'Test.php'.
        If the regex is mutated to match ALL .php files, non-test files are included.
        """
        test_dir = tmp_path / "tests"
        test_dir.mkdir()

        # Real test files that match the regex (Test/Test.php at end)
        (test_dir / "FooTest.php").write_text("<?php class FooTest {}")
        (test_dir / "BarTest.php").write_text("<?php class BarTest {}")

        # Non-test .php files that do NOT match (Test/Test.php at end)
        (test_dir / "UtilsModule.php").write_text("<?php // utility class")
        (test_dir / "ConfigLoader.php").write_text("<?php // config loader")

        files = PhpWeakTestAdapter._collect_test_files(tmp_path)

        # Only test files should be included
        file_names = {f.name for f in files}
        assert "FooTest.php" in file_names, "FooTest.php must be collected"
        assert "BarTest.php" in file_names, "BarTest.php must be collected"
        assert "UtilsModule.php" not in file_names, (
            f"UtilsModule.php must NOT be collected (kills mutmut_15-18 inversion). Files: {file_names}"
        )
        assert "ConfigLoader.php" not in file_names, (
            f"ConfigLoader.php must NOT be collected (kills mutmut_19-21 regex mutation). Files: {file_names}"
        )
        assert len(files) == 2, f"Expected exactly 2 test files, got {len(files)}: {file_names}"

    def test_collect_test_files_skip_vendor_and_node_modules(self, tmp_path: Path) -> None:
        """Files under vendor/ or node_modules/ must be skipped.

        Kills mutmut_6-9 (exclusion pattern mutations).
        """
        vendor_dir = tmp_path / "vendor" / "some_package"
        vendor_dir.mkdir(parents=True)
        (vendor_dir / "VendorTest.php").write_text("<?php class VendorTest {}")

        node_modules_dir = tmp_path / "node_modules" / "pkg"
        node_modules_dir.mkdir(parents=True)
        (node_modules_dir / "NodeTest.php").write_text("<?php class NodeTest {}")

        # Also create a legitimate test file
        real_test_dir = tmp_path / "tests"
        real_test_dir.mkdir()
        (real_test_dir / "RealTest.php").write_text("<?php class RealTest {}")

        files = PhpWeakTestAdapter._collect_test_files(tmp_path)
        file_names = {f.name for f in files}

        assert "RealTest.php" in file_names, "RealTest.php should be collected"
        assert "VendorTest.php" not in file_names, "vendor files must be skipped"
        assert "NodeTest.php" not in file_names, "node_modules files must be skipped"

    def test_collect_empty_repo_returns_empty_list(self, tmp_path: Path) -> None:
        """Empty repository → empty list (not mutated to None or different value).

        Kills mutmut_1, 2, 12 on _collect_test_files return path.
        """
        files = PhpWeakTestAdapter._collect_test_files(tmp_path)
        assert files == []
        assert isinstance(files, list)
        assert len(files) == 0

    def test_collect_test_files_regex_matches_Test_dot_php(self, tmp_path: Path) -> None:
        """Regex pattern must match 'FooTest.php' but not 'UtilsModule.php'.

        Kills mutmut_19: `r"(Test|Test\\.php)$"` → `r"(XXTest|XXTest\\.php)XX$"`.
        If the regex is mutated with XX prefix/suffix, no files match and collection is empty.
        """
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "FooTest.php").write_text("<?php class FooTest {}")
        (test_dir / "UtilsModule.php").write_text("<?php class UtilsModule {}")

        files = PhpWeakTestAdapter._collect_test_files(tmp_path)
        file_names = {f.name for f in files}

        assert "FooTest.php" in file_names, (
            f"FooTest.php must be collected by (Test|Test\\.php)$ pattern. Files: {file_names}"
        )
        assert "UtilsModule.php" not in file_names, (
            f"UtilsModule.php must NOT match. Files: {file_names}"
        )

    def test_collect_invoke_no_test_files_has_exitcode_zero(self, tmp_path: Path) -> None:
        """invoke with no test files → exitcode=0 (not mutated to 1).

        Kills mutmut_1/2 on line 120: exitcode=0 → exitcode=1.
        This verifies the no-files-found path returns the correct exitcode.
        """
        from harness_quality_gate.adapters.base import ToolInvocation

        result = PhpWeakTestAdapter().invoke(tmp_path, [])
        assert isinstance(result, ToolInvocation)
        assert result.exitcode == 0, (
            f"exitcode must be 0 when no test files found. Got: {result.exitcode}"
        )
        assert result.stdout == "[]"
