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
