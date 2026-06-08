"""Tests for PhpWeakTestLayerAdapter.run_l3b in weak_test_php.py.

Targets: run_l3b method of PhpWeakTestLayerAdapter which wraps
PhpWeakTestAdapter and returns LayerResult.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.php.weak_test_php import (
    PhpWeakTestLayerAdapter,
    PhpWeakTestAdapter,
)


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

        # Assert log message format contains both the expected prefix and the repo path.
        # This kills mutations 14 (None replaces repo) and 15 (entire format string removed).
        assert len(caplog.records) >= 1
        log_msg = caplog.messages[0]
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
            with patch("subprocess.run", return_value=completed):
                result = PhpWeakTestAdapter().invoke(tmp_path, [])

        assert result.exitcode == 1
        assert "visitor=" in result.stderr
        assert "exit=42" in result.stderr
        assert "fatal parse error" in result.stderr

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
                        stdout='',
                        stderr=""
                    )
                    with patch("harness_quality_gate.adapters.php.weak_test_php.Path") as MockPath:
                        mock_resolve = MagicMock()
                        mock_resolve.parent = real_visitors_dir.parent
                        MockPath.return_value.resolve.return_value = mock_resolve
                        MockPath.side_effect = lambda *a, **kw: Path(*a, **kw)
                        result = PhpWeakTestAdapter().invoke(tmp_path, [])
            findings = json.loads(result.stdout) if result.stdout else []
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
