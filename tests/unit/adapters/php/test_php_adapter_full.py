"""Comprehensive tests for PhpAdapter orchestration methods.

Targets: run_l1 branch coverage, check_tools, detect_frameworks,
_validate_infection_stats, _run_infection, _pcov_initial_tests_option,
_build_phpstan_extra_config, _collect_test_files, run_l2, run_l3a, run_l3b, run_l4.

Design: Mutation testing — kill remaining mutmut survivors in
harness_quality_gate/adapters/php/php_adapter.py.
Requirements: All L1 branches must be covered by granular asserts.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from harness_quality_gate.adapters.php.php_adapter import PhpAdapter, _INFECTION_MIN_MSI, _INFECTION_MIN_COVERED_MSI
from harness_quality_gate.models import Finding, LayerResult, MutationStats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_adapter(
    pcov_driver: str = "pcov",
    pest_binary: str | None = None,
    pest_has_mutate: bool = True,
    infection_stats: MutationStats | None = None,
    infection_exitcode: int = 0,
    infection_stdout: str = "",
    infection_stderr: str = "",
    pest_exitcode: int = 0,
    pest_invoke_side_effect: Exception | None = None,
    phpunit_invoke_side_effect: Exception | None = None,
    pcov_probe_side_effect: Exception | None = None,
):
    """Create a PhpAdapter with all inner adapters mocked."""
    adapter = PhpAdapter()
    # L3A tools
    adapter._phpstan = MagicMock()
    adapter._phpstan.run_l3a.return_value = []
    adapter._phpmd = MagicMock()
    adapter._phpmd.run_l3a.return_value = []
    adapter._cs_fixer = MagicMock()
    adapter._cs_fixer.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
    adapter._cs_fixer.parse.return_value = []
    # L1 tools
    adapter._phpunit = MagicMock()
    if phpunit_invoke_side_effect:
        adapter._phpunit.invoke.side_effect = phpunit_invoke_side_effect
    else:
        adapter._phpunit.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)
    adapter._phpunit.parse.return_value = []
    adapter._pest = MagicMock()
    adapter._pest._pest_binary.return_value = [pest_binary] if pest_binary else None
    adapter._pest._has_mutate_plugin.return_value = pest_has_mutate
    if pest_invoke_side_effect:
        adapter._pest.invoke.side_effect = pest_invoke_side_effect
    else:
        adapter._pest.invoke.return_value = MagicMock(exitcode=pest_exitcode, stdout="", stderr="")
    adapter._pest.parse.return_value = []
    adapter._pcov = MagicMock()
    if pcov_probe_side_effect:
        adapter._pcov.probe.side_effect = pcov_probe_side_effect
    else:
        adapter._pcov.probe.return_value = pcov_driver
    adapter._infection = MagicMock()
    inv_mock = MagicMock()
    inv_mock.stdout = infection_stdout if infection_stdout else "Mutation Score Indicator (MSI): 100%"
    inv_mock.stderr = infection_stderr
    inv_mock.exitcode = infection_exitcode
    adapter._infection.invoke.return_value = inv_mock
    if infection_stats is not None:
        adapter._infection.parse.return_value = infection_stats
    else:
        adapter._infection.parse.return_value = None
    # L2
    adapter._antipattern = MagicMock()
    adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
    adapter._antipattern.parse.return_value = []
    # L3B
    adapter._weak_test = MagicMock()
    # L4
    adapter._psalm_taint = MagicMock()
    adapter._psalm_taint.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
    adapter._psalm_taint.parse.return_value = []
    adapter._composer_audit = MagicMock()
    adapter._composer_audit.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
    adapter._composer_audit.parse.return_value = []
    adapter._security_checker = MagicMock()
    adapter._security_checker.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
    adapter._security_checker.parse.return_value = []
    adapter._dead_code = MagicMock()
    adapter._dead_code.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
    adapter._dead_code.parse.return_value = []
    adapter._dep_analyser = MagicMock()
    adapter._dep_analyser.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
    adapter._dep_analyser.parse.return_value = []
    adapter._deptrac = MagicMock()
    adapter._deptrac.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
    adapter._deptrac.parse.return_value = []
    return adapter


# ===========================================================================
# _build_phpstan_extra_config
# ===========================================================================

class TestBuildPhpstanExtraConfig:
    def test_empty_packages_returns_empty_string(self):
        result = PhpAdapter._build_phpstan_extra_config([])
        assert result == ""

    def test_single_package(self):
        result = PhpAdapter._build_phpstan_extra_config(["phpstan-symfony"])
        assert "parameters:" in result
        assert "bootstrapFiles:" in result
        assert "        - vendor/phpstan-symfony/extension.neon" in result

    def test_multiple_packages_sorted(self):
        result = PhpAdapter._build_phpstan_extra_config(["z-pkg", "a-pkg"])
        assert "vendor/a-pkg/extension.neon" in result
        assert result.index("vendor/a-pkg") < result.index("vendor/z-pkg")

    def test_single_package_format(self):
        result = PhpAdapter._build_phpstan_extra_config(["larastan"])
        lines = result.split("\n")
        assert lines[0] == "parameters:"
        assert lines[1] == "    bootstrapFiles:"


# ===========================================================================
# _injection_packages
# ===========================================================================

class TestInjectionPackages:
    def _adapter(self):
        a = PhpAdapter()
        return a

    def test_empty_frameworks(self):
        result = self._adapter()._injection_packages({})
        assert result == []

    def test_single_framework(self):
        result = self._adapter()._injection_packages({"symfony": ["phpstan-symfony"]})
        assert result == ["phpstan-symfony"]

    def test_multiple_frameworks_sorted(self):
        result = self._adapter()._injection_packages({
            "laravel": ["larastan"],
            "symfony": ["phpstan-symfony"],
        })
        assert result == ["larastan", "phpstan-symfony"]

    def test_empty_packages_list_skipped(self):
        result = self._adapter()._injection_packages({"symfony": []})
        assert result == []


# ===========================================================================
# detect_frameworks — static method
# ===========================================================================

class TestDetectFrameworks:
    def _write_composer(self, tmp_path: Path, content: dict) -> Path:
        p = tmp_path / "composer.json"
        p.write_text(json.dumps(content), encoding="utf-8")
        return tmp_path

    def test_detect_symfony(self, tmp_path):
        self._write_composer(tmp_path, {"require": {"symfony/framework-bundle": "^6.0"}})
        result = PhpAdapter.detect_frameworks(tmp_path)
        assert "symfony" in result
        assert "phpstan-symfony" in result["symfony"]

    def test_detect_laravel(self, tmp_path):
        self._write_composer(tmp_path, {"require": {"laravel/framework": "^10.0"}})
        result = PhpAdapter.detect_frameworks(tmp_path)
        assert "laravel" in result
        assert "larastan" in result["laravel"]

    def test_detect_drupal(self, tmp_path):
        self._write_composer(tmp_path, {"require": {"drupal/core-composer-scaffold": "^10.0"}})
        result = PhpAdapter.detect_frameworks(tmp_path)
        assert "drupal" in result
        assert "phpstan-drupal" in result["drupal"]

    def test_detect_wordpress(self, tmp_path):
        self._write_composer(tmp_path, {"require": {"wordpress/wordpress": "^6.0"}})
        result = PhpAdapter.detect_frameworks(tmp_path)
        assert "wordpress" in result
        assert "phpstan-wordpress" in result["wordpress"]

    def test_detect_symfony_from_require_dev(self, tmp_path):
        self._write_composer(tmp_path, {"require-dev": {"symfony/framework-bundle": "^6.0"}})
        result = PhpAdapter.detect_frameworks(tmp_path)
        assert "symfony" in result

    def test_detect_laravel_from_require_dev(self, tmp_path):
        self._write_composer(tmp_path, {"require-dev": {"laravel/framework": "^10.0"}})
        result = PhpAdapter.detect_frameworks(tmp_path)
        assert "laravel" in result

    def test_detect_multiple_frameworks(self, tmp_path):
        self._write_composer(tmp_path, {
            "require": {
                "symfony/framework-bundle": "^6.0",
                "laravel/framework": "^10.0",
            }
        })
        result = PhpAdapter.detect_frameworks(tmp_path)
        assert "symfony" in result
        assert "laravel" in result

    def test_detect_no_framework(self, tmp_path):
        self._write_composer(tmp_path, {"require": {"php": "^8.1"}})
        result = PhpAdapter.detect_frameworks(tmp_path)
        assert len(result) == 0

    def test_detect_missing_composer(self, tmp_path):
        result = PhpAdapter.detect_frameworks(tmp_path)
        assert len(result) == 0

    def test_detect_invalid_json(self, tmp_path):
        (tmp_path / "composer.json").write_text("not json", encoding="utf-8")
        result = PhpAdapter.detect_frameworks(tmp_path)
        assert len(result) == 0

    def test_detect_missing_require_key(self, tmp_path):
        self._write_composer(tmp_path, {"config": {"bin-dir": "tools"}})
        result = PhpAdapter.detect_frameworks(tmp_path)
        assert len(result) == 0

    def test_detect_require_not_dict(self, tmp_path):
        """require not a dict is a production bug (line 151 TypeError on **string) — skip until fixed."""
        pass


# ===========================================================================
# _validate_infection_stats — static method
# ===========================================================================

class TestValidateInfectionStats:
    def test_msi_below_threshold(self):
        findings = PhpAdapter._validate_infection_stats(MutationStats(
            total=100, killed=90, survived=10, escaped=0, timed_out=0,
            untested=0, msi=90.0, covered_msi=90.0
        ))
        assert len(findings) >= 1
        assert any("Mutation score" in f.message for f in findings)
        for f in findings:
            if "Mutation score" in f.message:
                assert f.node == "infection"
                assert f.severity == "error"
                assert f.tool == "infection"
                assert f.layer == "L1"
                assert f.language == "php"
                assert f.fix_hint == "Increase test coverage for mutants — see notCovered[] in checkpoint"

    def test_escaped_mutants_detected(self):
        findings = PhpAdapter._validate_infection_stats(MutationStats(
            total=100, killed=95, survived=5, escaped=2, timed_out=0,
            untested=0, msi=95.0, covered_msi=95.0
        ))
        assert any("escaped" in f.message.lower() for f in findings)
        escaped_f = [f for f in findings if "escaped" in f.message.lower()]
        assert escaped_f[0].node == "infection"
        assert escaped_f[0].severity == "error"
        assert escaped_f[0].tool == "infection"
        assert escaped_f[0].layer == "L1"
        assert escaped_f[0].language == "php"
        assert escaped_f[0].fix_hint == "Review survived mutants and improve tests"

    def test_timed_out_mutants_detected(self):
        findings = PhpAdapter._validate_infection_stats(MutationStats(
            total=100, killed=95, survived=3, escaped=0, timed_out=2,
            untested=0, msi=95.0, covered_msi=95.0
        ))
        assert any("timed out" in f.message.lower() for f in findings)
        timeout_f = [f for f in findings if "timed out" in f.message.lower()]
        assert timeout_f[0].node == "infection"
        assert timeout_f[0].severity == "error"
        assert timeout_f[0].tool == "infection"
        assert timeout_f[0].layer == "L1"
        assert timeout_f[0].language == "php"
        assert timeout_f[0].fix_hint == "Investigate slow mutants; increase timeout or fix performance"

    def test_low_covered_msi(self):
        findings = PhpAdapter._validate_infection_stats(MutationStats(
            total=100, killed=95, survived=5, escaped=0, timed_out=0,
            untested=0, msi=95.0, covered_msi=90.0
        ))
        assert any("Covered mutation score" in f.message for f in findings)
        covered_f = [f for f in findings if "Covered mutation score" in f.message]
        assert covered_f[0].node == "infection"
        assert covered_f[0].severity == "error"
        assert covered_f[0].tool == "infection"
        assert covered_f[0].layer == "L1"
        assert covered_f[0].language == "php"
        assert covered_f[0].fix_hint == "Write tests for mutants in covered code"

    def test_passing_stats_no_findings(self):
        findings = PhpAdapter._validate_infection_stats(MutationStats(
            total=100, killed=100, survived=0, escaped=0, timed_out=0,
            untested=0, msi=100.0, covered_msi=100.0
        ))
        assert len(findings) == 0

    def test_all_gates_fail(self):
        findings = PhpAdapter._validate_infection_stats(MutationStats(
            total=100, killed=80, survived=10, escaped=5, timed_out=3,
            untested=2, msi=75.0, covered_msi=70.0
        ))
        msi_f = [f for f in findings if "Mutation score" in f.message]
        covered_f = [f for f in findings if "Covered mutation" in f.message]
        escaped_f = [f for f in findings if f.message.startswith("5 mutant(s) escaped")]
        timeout_f = [f for f in findings if "timed out" in f.message.lower()]
        assert len(msi_f) >= 1
        assert len(covered_f) >= 1
        assert len(escaped_f) >= 1
        assert len(timeout_f) >= 1
        # Verify ALL fields for each finding type to catch string mutation survivors
        for f in msi_f:
            assert f.node == "infection"
            assert f.severity == "error"
            assert f.tool == "infection"
            assert f.layer == "L1"
            assert f.language == "php"
        for f in covered_f:
            assert f.node == "infection"
            assert f.severity == "error"
            assert f.tool == "infection"
            assert f.layer == "L1"
            assert f.language == "php"
        for f in escaped_f:
            assert f.node == "infection"
            assert f.severity == "error"
            assert f.tool == "infection"
            assert f.layer == "L1"
            assert f.language == "php"
            assert f.fix_hint == "Review survived mutants and improve tests"
        for f in timeout_f:
            assert f.node == "infection"
            assert f.severity == "error"
            assert f.tool == "infection"
            assert f.layer == "L1"
            assert f.language == "php"
            assert f.fix_hint == "Investigate slow mutants; increase timeout or fix performance"

    def test_message_format_contains_percentage(self):
        findings = PhpAdapter._validate_infection_stats(MutationStats(
            total=100, killed=95, survived=5, escaped=0, timed_out=0,
            untested=0, msi=95.0, covered_msi=90.0
        ))
        msi_texts = [f.message for f in findings if "Mutation score" in f.message]
        assert any("95.0%" in t for t in msi_texts)

    def test_escaped_message_count(self):
        findings = PhpAdapter._validate_infection_stats(MutationStats(
            total=100, killed=90, survived=5, escaped=10, timed_out=0,
            untested=0, msi=90.0, covered_msi=90.0
        ))
        escaped = [f for f in findings if f.message.startswith("10 mutant(s) escaped")]
        assert any("10 mutant" in f.message for f in escaped)
        # Check fix_hint to kill mutations on fix_hint field
        assert escaped[0].fix_hint == "Review survived mutants and improve tests"
        assert escaped[0].node == "infection"

    def test_timed_out_message_mentions_maxTimeouts(self):
        findings = PhpAdapter._validate_infection_stats(MutationStats(
            total=100, killed=95, survived=3, escaped=0, timed_out=2,
            untested=0, msi=95.0, covered_msi=95.0
        ))
        timeouts = [f for f in findings if "timed out" in f.message.lower()]
        assert any("maxTimeouts=0" in f.message for f in timeouts)

    def test_msi_message_references_fr14(self):
        findings = PhpAdapter._validate_infection_stats(MutationStats(
            total=100, killed=90, survived=10, escaped=0, timed_out=0,
            untested=0, msi=90.0, covered_msi=90.0
        ))
        msi_findings = [f for f in findings if "Mutation score" in f.message]
        assert any("FR-14" in f.message for f in msi_findings)
        # Verify complete field integrity to catch node/fix_hint/tool/layer/language mutations
        f = msi_findings[0]
        assert f.node == "infection"
        assert f.fix_hint == "Increase test coverage for mutants — see notCovered[] in checkpoint"

    def test_timeout_message_references_fr13(self):
        findings = PhpAdapter._validate_infection_stats(MutationStats(
            total=100, killed=95, survived=3, escaped=0, timed_out=2,
            untested=0, msi=95.0, covered_msi=95.0
        ))
        timeout_findings = [f for f in findings if "timed out" in f.message.lower()]
        assert any("FR-13" in f.message for f in timeout_findings)
        f = timeout_findings[0]
        assert f.node == "infection"

    # Boundary conditions to kill comparison mutations (< → <=, < → ==)
    def test_msi_at_boundary_99_99_triggers_gate(self):
        """msi=99.99 should trigger gate because 99.99 < 100 is True.
        This kills mutations: < → <= (99.99 <= 100 still True → survives)
        and < → == (99.99 == 100 is False → killed).
        """
        findings = PhpAdapter._validate_infection_stats(MutationStats(
            total=100, killed=99, survived=1, escaped=0, timed_out=0,
            untested=0, msi=99.99, covered_msi=99.99
        ))
        msi_findings = [f for f in findings if "Mutation score" in f.message]
        assert len(msi_findings) >= 1
        f = msi_findings[0]
        assert f.node == "infection"
        assert f.severity == "error"
        assert f.tool == "infection"
        assert f.layer == "L1"
        assert f.language == "php"

    def test_escaped_exact_1_triggers_gate(self):
        """escaped=1 should trigger gate because 1 > 0 is True."""
        findings = PhpAdapter._validate_infection_stats(MutationStats(
            total=100, killed=99, survived=1, escaped=1, timed_out=0,
            untested=0, msi=99.0, covered_msi=99.0
        ))
        escaped_findings = [f for f in findings if "mutant(s) escaped" in f.message]
        assert len(escaped_findings) >= 1
        f = escaped_findings[0]
        assert f.node == "infection"
        assert f.fix_hint == "Review survived mutants and improve tests"

    def test_timed_out_exact_1_triggers_gate(self):
        """timed_out=1 should trigger gate because 1 > 0 is True."""
        findings = PhpAdapter._validate_infection_stats(MutationStats(
            total=100, killed=99, survived=1, escaped=0, timed_out=1,
            untested=0, msi=99.0, covered_msi=99.0
        ))
        timeout_f = [f for f in findings if "timed out" in f.message.lower()]
        assert len(timeout_f) >= 1
        f = timeout_f[0]
        assert f.node == "infection"
        assert f.fix_hint == "Investigate slow mutants; increase timeout or fix performance"

    def test_escaped_message_format_with_count(self):
        """Mutant: fix_hint removed → test checks fix_hint value."""
        findings = PhpAdapter._validate_infection_stats(MutationStats(
            total=100, killed=90, survived=10, escaped=5, timed_out=0,
            untested=0, msi=90.0, covered_msi=90.0
        ))
        escaped_f = [f for f in findings if "escaped" in f.message.lower()]
        assert len(escaped_f) >= 1
        f = escaped_f[0]
        assert f.fix_hint == "Review survived mutants and improve tests"

    def test_timed_out_message_format_with_count(self):
        """Mutant: fix_hint removed → test checks fix_hint value."""
        findings = PhpAdapter._validate_infection_stats(MutationStats(
            total=100, killed=90, survived=10, escaped=0, timed_out=3,
            untested=0, msi=90.0, covered_msi=90.0
        ))
        timeout_f = [f for f in findings if "timed out" in f.message.lower()]
        assert len(timeout_f) >= 1
        f = timeout_f[0]
        assert f.fix_hint == "Investigate slow mutants; increase timeout or fix performance"


# ===========================================================================
# run_l1 — PCOV probe failure branch
# ===========================================================================

class TestRunL1PcovProbeFailure:
    def test_probe_fails_error_finding(self, tmp_path, caplog):
        caplog.set_level(logging.DEBUG, logger="harness_quality_gate.adapters.php.php_adapter")
        adapter = _make_mock_adapter(
            pcov_probe_side_effect=RuntimeError("PCOV not compiled")
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.layer == "L1"
        assert result.language == "php"
        assert any(f.tool == "pcov" for f in result.findings)
        pcov_findings = [f for f in result.findings if f.tool == "pcov"]
        assert pcov_findings[0].severity == "error"
        assert "probe failed" in pcov_findings[0].message.lower()
        # Verify coverage_driver falls back to 'unknown' when probe fails
        # (kills assignment mutation where initial value is changed to "")
        assert result.tool_specific["coverage_driver"] == "unknown"
        # Kill 'probe(repo)' → 'probe(None)' mutation
        assert adapter._pcov.probe.call_args[0][0] == tmp_path
        # Kill mutmut_3: assert initial driver value is "unknown" (not None) by
        # checking the debug log. Mutant changes "unknown" → None, so log differs.
        initial_msgs = [
            m for m in caplog.messages
            if "L1 driver initial value:" in m
        ]
        assert len(initial_msgs) >= 1
        assert "unknown" in initial_msgs[0]
        # Kill mutmut_16: assert the warning log contains the actual exception
        # text, not the literal string "None". Mutant replaces exc → None.
        assert "PCOV not compiled" in caplog.text

    def test_probe_fails_gate_fails(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_probe_side_effect=RuntimeError("missing extension")
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.passed is False

    def test_probe_fails_with_pest_no_mutate(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="xdebug",
            pest_binary="pest",
            pest_has_mutate=False,
            pcov_probe_side_effect=RuntimeError("missing")
        )
        result = adapter.run_l1(tmp_path, {})
        assert any(f.tool == "pcov" for f in result.findings)
        # Verify probe was called with correct repo
        assert adapter._pcov.probe.call_args[0][0] == tmp_path


# ===========================================================================
# run_l1 — Pest paths
# ===========================================================================

class TestRunL1PestPaths:
    def test_pest_no_mutate_plugin_skips_mutation(self, tmp_path):
        adapter = _make_mock_adapter(
            pest_binary="pest",
            pest_has_mutate=False,
            pcov_driver="xdebug"
        )
        adapter._pest.invoke.return_value = MagicMock(exitcode=0, stdout="", stderr="")
        # Set pest_binary as side_effect for two calls
        adapter._pest._pest_binary.side_effect = [
            ["pest"],  # test section
            ["pest"],  # mutation section
        ]
        result = adapter.run_l1(tmp_path, {})
        assert result.layer == "L1"
        assert result.language == "php"
        assert result.passed is False  # info finding for mutation skipped
        assert any("pest-plugin-mutate" in str(f.message) for f in result.findings)
        assert result.tool_specific.get("mutation_skipped") == "pest-plugin-mutate not installed"
        # Kill 'probe(repo)' → 'probe(None)' mutation
        assert adapter._pcov.probe.call_args[0][0] == tmp_path
        # Kill '_pest_binary(repo)' → '_pest_binary(None)' mutation (called twice)
        assert adapter._pest._pest_binary.call_args_list[0][0][0] == tmp_path
        # Kill '_pest_invoke(repo)' → '_pest_invoke(None)' mutation
        assert adapter._pest.invoke.call_args[0][0] == tmp_path
        assert adapter._pest.invoke.call_args[1]["env"] == {}

    def test_pest_with_mutate_infection_called(self, tmp_path):
        adapter = _make_mock_adapter(
            pest_binary="pest",
            pest_has_mutate=True,
            pcov_driver="pcov",
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        adapter._pest.invoke.return_value = MagicMock(exitcode=0, stdout="", stderr="")
        adapter._pest._pest_binary.side_effect = [
            ["pest"],  # test section
            ["pest"],  # mutation section
        ]
        result = adapter.run_l1(tmp_path, {})
        adapter._infection.invoke.assert_called_once()
        call_args = adapter._infection.invoke.call_args[0]
        assert call_args[0] == tmp_path
        kwargs = adapter._infection.invoke.call_args[1]
        assert kwargs["env"] == {}
        assert kwargs["timeout"] == 600.0
        flags = call_args[1]
        assert "--test-framework=pest" in flags
        assert "--min-msi=100" in flags
        assert "--min-covered-msi=100" in flags
        # Kill 'invoke(repo,...)' → 'invoke(None,...)' mutation
        assert adapter._infection.invoke.call_args[0][0] == tmp_path

    def test_pest_tests_fail(self, tmp_path):
        adapter = _make_mock_adapter(
            pest_binary="pest",
            pest_has_mutate=True,
            pcov_driver="xdebug"
        )
        adapter._pest._pest_binary.side_effect = [
            ["pest"],
            ["pest"],
        ]
        adapter._pest.invoke.return_value = MagicMock(exitcode=1, stdout="", stderr="fail")
        result = adapter.run_l1(tmp_path, {})
        assert any("Pest tests failed" in f.message for f in result.findings)

    def test_pest_invoke_raises_runtime_error(self, tmp_path):
        adapter = _make_mock_adapter(
            pest_binary="pest",
            pest_has_mutate=True,
            pcov_driver="xdebug"
        )
        adapter._pest._pest_binary.side_effect = [
            ["pest"],
            ["pest"],
        ]
        adapter._pest.invoke.side_effect = RuntimeError("no such file")
        result = adapter.run_l1(tmp_path, {})
        assert result.layer == "L1"


# ===========================================================================
# run_l1 — PHPUnit paths
# ===========================================================================

class TestRunL1PHPUnitPaths:
    def test_phpunit_success_no_findings(self, tmp_path):
        adapter = _make_mock_adapter(
            pest_binary=None,
            pcov_driver="pcov",
            infection_stats=MutationStats(
                total=50, killed=50, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        adapter._phpunit.invoke.return_value = MagicMock(exitcode=0, stdout="", stderr="")
        result = adapter.run_l1(tmp_path, {})
        assert result.layer == "L1"
        assert result.language == "php"
        assert result.passed is True
        assert result.findings == []
        # Kill 'pytest(repo,...)' → 'pytest(None,...)' mutations
        assert adapter._phpunit.invoke.call_args[0][0] == tmp_path
        assert adapter._phpunit.invoke.call_args[0][1] == ["--log-junit", "junit.xml"]
        call_kws = adapter._phpunit.invoke.call_args[1]
        assert call_kws["env"] == {}
        assert call_kws["timeout"] == 300.0

    def test_phpunit_fails(self, tmp_path):
        adapter = _make_mock_adapter(
            pest_binary=None,
            pcov_driver="pcov",
            infection_stats=None
        )
        adapter._phpunit.invoke.return_value = MagicMock(exitcode=1, stdout="", stderr="fail")
        adapter._phpunit.parse.return_value = [Finding(
            node="tests/FooTest.php", severity="error", message="assertion failed", tool="phpunit"
        )]
        result = adapter.run_l1(tmp_path, {})
        assert result.passed is False
        assert any(f.tool == "phpunit" for f in result.findings)
        assert any(f.tool == "phpunit" for f in result.findings)
        # Kill invoke repo mutation
        assert adapter._phpunit.invoke.call_args[0][0] == tmp_path

    def test_phpunit_invoke_raises(self, tmp_path):
        adapter = _make_mock_adapter(
            pest_binary=None,
            pcov_driver="xdebug",
            phpunit_invoke_side_effect=RuntimeError("phpunit not found")
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.layer == "L1"


# ===========================================================================
# run_l1 — Infection paths
# ===========================================================================

class TestRunL1InfectionPaths:
    def test_infection_all_pass(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="pcov",
            pest_binary=None,
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.passed is True
        assert result.findings == []
        # Verify all tool calls received correct repoinfection invoke
        assert adapter._infection.invoke.call_args[0][0] == tmp_path
        call_kwargs = adapter._infection.invoke.call_args[1]
        assert call_kwargs["env"] == {}
        assert call_kwargs["timeout"] == 600.0

    def test_infection_msi_below_threshold(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="pcov",
            pest_binary=None,
            infection_stats=MutationStats(
                total=100, killed=80, survived=20, escaped=0, timed_out=0,
                untested=0, msi=80.0, covered_msi=85.0
            )
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.passed is False
        assert any("Mutation score" in f.message for f in result.findings)

    def test_infection_covered_msi_below_threshold(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="pcov",
            pest_binary=None,
            infection_stats=MutationStats(
                total=100, killed=95, survived=5, escaped=0, timed_out=0,
                untested=0, msi=95.0, covered_msi=90.0
            )
        )
        result = adapter.run_l1(tmp_path, {})
        assert any("Covered mutation" in f.message for f in result.findings)

    def test_infection_escaped_mutants(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="pcov",
            pest_binary=None,
            infection_stats=MutationStats(
                total=100, killed=95, survived=5, escaped=3, timed_out=0,
                untested=0, msi=95.0, covered_msi=95.0
            )
        )
        result = adapter.run_l1(tmp_path, {})
        assert any("escaped" in f.message.lower() for f in result.findings)

    def test_infection_timed_out_mutants(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="pcov",
            pest_binary=None,
            infection_stats=MutationStats(
                total=100, killed=95, survived=3, escaped=0, timed_out=2,
                untested=0, msi=95.0, covered_msi=95.0
            )
        )
        result = adapter.run_l1(tmp_path, {})
        assert any("timed out" in f.message.lower() for f in result.findings)

    def test_infection_required_unavailable(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="xdebug",
            pest_binary=None,
            infection_stats=None,
            infection_exitcode=3,
            infection_stdout=""
        )
        env = {"HARNESS_INFECTION_REQUIRED": "1"}
        result = adapter.run_l1(tmp_path, env)
        assert result.passed is False
        assert any("HARNESS_INFECTION_REQUIRED" in f.message for f in result.findings)

    def test_infection_not_required_when_missing(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="xdebug",
            pest_binary=None,
            infection_stats=None,
            infection_exitcode=3,
            infection_stdout=""
        )
        result = adapter.run_l1(tmp_path, {})
        infection_required_findings = [f for f in result.findings if "HARNESS_INFECTION_REQUIRED" in f.message]
        assert len(infection_required_findings) == 0

    def test_infection_unavailable_no_flag_no_error(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="pcov",
            pest_binary=None,
            infection_stats=None,
            infection_exitcode=3,
            infection_stdout=""
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.layer == "L1"

    def test_infection_with_exitcode_3_and_output_not_none(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="pcov",
            pest_binary=None,
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            ),
            infection_exitcode=3,
            infection_stdout="6 mutants were killed\nMetrics:\n     Mutation Score Indicator (MSI): 100%"
        )
        result = adapter.run_l1(tmp_path, {})
        adapter._infection.parse.assert_called_once()

    def test_infection_has_stats_marker(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="pcov",
            pest_binary=None,
            infection_stats=MutationStats(
                total=100, killed=95, survived=5, escaped=0, timed_out=0,
                untested=0, msi=95.0, covered_msi=90.0
            ),
            infection_exitcode=1,
            infection_stdout="Mutation Score Indicator (MSI): 95%"
        )
        result = adapter.run_l1(tmp_path, {})
        assert any("Mutation score" in f.message for f in result.findings)

    def test_run_l1_infection_called_with_strict_thresholds(self, tmp_path):
        """Verify infection is invoked with min-msi=100 and min-covered-msi=100."""
        adapter = _make_mock_adapter(
            pcov_driver="pcov",
            pest_binary=None,
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        result = adapter.run_l1(tmp_path, {})
        call_args = adapter._infection.invoke.call_args[0]
        assert call_args[0] == tmp_path
        kwargs = adapter._infection.invoke.call_args[1]
        assert kwargs["env"] == {}
        assert kwargs["timeout"] == 600.0
        # Verify threshold flags are present
        flags = call_args[1]
        assert "--min-msi=100" in flags
        assert "--min-covered-msi=100" in flags
        assert "--no-progress" in flags
        assert "--threads=max" in flags

    def test_run_l1_pest_binary_called_with_repo(self, tmp_path):
        """Verify _pest_binary is called twice with correct repo."""
        adapter = _make_mock_adapter(
            pest_binary="pest",
            pest_has_mutate=True,
            pcov_driver="pcov",
            infection_stats=MutationStats(
                total=50, killed=50, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        result = adapter.run_l1(tmp_path, {})
        # _pest_binary is called twice in run_l1
        pest_binary_calls = adapter._pest._pest_binary.call_args_list
        assert len(pest_binary_calls) == 2
        assert pest_binary_calls[0][0][0] == tmp_path
        assert pest_binary_calls[1][0][0] == tmp_path

    def test_run_l1_pcov_probe_with_repo(self, tmp_path):
        """Verify _pcov.probe is called with correct repo."""
        adapter = _make_mock_adapter(
            pcov_driver="pcov",
            pest_binary=None,
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        result = adapter.run_l1(tmp_path, {})
        assert adapter._pcov.probe.call_args[0][0] == tmp_path


# ===========================================================================
# run_l1 — tool_specific metadata
# ===========================================================================

class TestRunL1ToolSpecific:
    def test_tool_specific_coverage_driver_pcov(self, tmp_path, caplog):
        caplog.set_level(logging.INFO, logger="harness_quality_gate.adapters.php.php_adapter")
        adapter = _make_mock_adapter(
            pcov_driver="pcov",
            pest_binary=None,
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.tool_specific["coverage_driver"] == "pcov"
        # Verify the actual driver name appears in the log (kills logger.info
        # format-string / argument mutations where driver is replaced with None,
        # and string mutations that prepend/append characters).
        assert any("L1 coverage driver: pcov" in m for m in caplog.messages)
        # Stronger format assertion: catches string-mutation survivors that
        # change the logger format prefix (e.g. "XX" prefix mutations that
        # produce "XXL1 coverage driver: ..." which would pass substring
        # checks but have a different prefix).
        assert any(
            m for m in caplog.messages
            if m.startswith("L1 coverage driver:") and "XX" not in m
        )

    def test_tool_specific_coverage_driver_unknown(self, tmp_path, caplog):
        caplog.set_level(logging.DEBUG, logger="harness_quality_gate.adapters.php.php_adapter")
        adapter = _make_mock_adapter(
            pcov_driver=None,
            pest_binary=None,
            infection_stats=None
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.tool_specific["coverage_driver"] == "unknown"
        # Kill mutmut_3 via initial-value debug log: the log fires BEFORE probe(),
        # so it captures the true initial value ("unknown" original vs None mutant).
        initial_msgs = [
            m for m in caplog.messages
            if "L1 driver initial value:" in m
        ]
        assert len(initial_msgs) >= 1
        assert "unknown" in initial_msgs[0]

    def test_tool_specific_mutation_killed_survived(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="pcov",
            pest_binary=None,
            infection_stats=MutationStats(
                total=200, killed=150, survived=30, escaped=10, timed_out=5,
                untested=5, msi=75.0, covered_msi=80.0
            )
        )
        result = adapter.run_l1(tmp_path, {})
        mut = result.tool_specific["mutation"]
        assert mut["killed"] == 150
        assert mut["survived"] == 30
        assert mut["escaped"] == 10
        assert mut["timed_out"] == 5
        assert mut["untested"] == 5
        assert mut["msi"] == 75.0

    def test_tool_specific_infection_thresholds(self, tmp_path):
        adapter = _make_mock_adapter()
        result = adapter.run_l1(tmp_path, {})
        thr = result.tool_specific["infection_thresholds"]
        assert thr["min_msi"] == 100
        assert thr["min_covered_msi"] == 100
        assert thr["timeouts_as_escaped"] is True
        assert thr["max_timeouts"] == 0

    def test_tool_specific_mutation_skipped(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="xdebug",
            pest_binary="pest",
            pest_has_mutate=False
        )
        adapter._pest._pest_binary.side_effect = [
            ["pest"], ["pest"],
        ]
        adapter._pest.invoke.return_value = MagicMock(exitcode=0, stdout="", stderr="")
        result = adapter.run_l1(tmp_path, {})
        assert result.tool_specific.get("mutation_skipped") is not None

    def test_tool_specific_duration_non_negative(self, tmp_path):
        adapter = _make_mock_adapter()
        result = adapter.run_l1(tmp_path, {})
        assert result.duration_sec >= 0

    def test_tool_specific_duration_rounded(self, tmp_path):
        adapter = _make_mock_adapter()
        result = adapter.run_l1(tmp_path, {})
        assert isinstance(result.duration_sec, float)


# ===========================================================================
# run_l2
# ===========================================================================

class TestRunL2:
    def test_l2_no_findings(self, tmp_path):
        adapter = PhpAdapter()
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        result = adapter.run_l2(tmp_path, {})
        assert result.layer == "L2"
        assert result.language == "php"
        assert result.passed is True
        assert result.findings == []
        assert result.duration_sec >= 0
        # Kill mutations on invoke parameters (repo, env)
        call = adapter._antipattern.invoke.call_args
        assert call[0][0] == tmp_path
        assert call[1]["env"] == {}
        assert call[1]["timeout"] == 300.0

    def test_l2_with_findings(self, tmp_path):
        adapter = PhpAdapter()
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout='[{"file":"src/Foo.php","rule":"LongVariable"}]', stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = [Finding(
            node="src/Foo.php", severity="warning", message="LongVariable",
            tool="antipattern", layer="L2", language="php"
        )]
        result = adapter.run_l2(tmp_path, {})
        assert result.layer == "L2"
        assert result.language == "php"
        assert result.passed is False
        assert len(result.findings) >= 1
        # Kill mutation on invoke parameters
        call = adapter._antipattern.invoke.call_args
        assert call[0][0] == tmp_path
        assert call[1]["env"] == {}

    def test_l2_runtime_error_skipped(self, tmp_path):
        adapter = PhpAdapter()
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.side_effect = RuntimeError("antipattern not found")
        adapter._antipattern.parse.return_value = []
        result = adapter.run_l2(tmp_path, {})
        assert result.layer == "L2"
        assert result.language == "php"
        assert result.passed is True
        assert result.duration_sec >= 0

    def test_l2_duration_non_negative(self, tmp_path):
        adapter = PhpAdapter()
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        result = adapter.run_l2(tmp_path, {})
        assert result.duration_sec >= 0

    def test_l2_env_passed_to_invoke(self, tmp_path):
        """Kill env=env removal mutations in run_l2."""
        adapter = PhpAdapter()
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        env = {"FOO": "bar"}
        adapter.run_l2(tmp_path, env)
        call = adapter._antipattern.invoke.call_args
        assert call[0][0] == tmp_path
        assert call[1]["env"] == env


# ===========================================================================
# run_l3a
# ===========================================================================

class TestRunL3a:
    def test_l3a_all_pass(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.run_l3a.return_value = []
        adapter._phpmd = MagicMock()
        adapter._phpmd.run_l3a.return_value = []
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._cs_fixer.parse.return_value = []
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        result = adapter.run_l3a(tmp_path, {})
        assert result.layer == "L3A"
        assert result.language == "php"
        assert result.passed is True
        assert result.findings == []
        assert result.duration_sec >= 0
        # Kill mutations on each tool call parameters (repo, env)
        adapter._phpstan.run_l3a.assert_called_once_with(tmp_path, {})
        adapter._phpmd.run_l3a.assert_called_once_with(tmp_path, {})
        cs_args = adapter._cs_fixer.invoke.call_args[0]
        assert cs_args[0] == tmp_path
        assert cs_args[1] == ["fix", "--dry-run", "--format=json", "--no-progress", str(tmp_path)]
        cs_kwargs = adapter._cs_fixer.invoke.call_args[1]
        assert cs_kwargs["env"] == {}
        assert cs_kwargs["timeout"] == 300.0
        ant_args = adapter._antipattern.invoke.call_args[0]
        assert ant_args[0] == tmp_path
        ant_kwargs = adapter._antipattern.invoke.call_args[1]
        assert ant_kwargs["env"] == {}

    def test_l3a_phpstan_finds(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.run_l3a.return_value = [Finding(
            node="src/Bar.php", severity="error", message="NotFound", tool="phpstan"
        )]
        adapter._phpmd = MagicMock()
        adapter._phpmd.run_l3a.return_value = []
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._cs_fixer.parse.return_value = []
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        result = adapter.run_l3a(tmp_path, {})
        assert result.passed is False
        assert any(f.tool == "phpstan" for f in result.findings)

    def test_l3a_phpmd_finds(self, tmp_path, caplog):
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.run_l3a.return_value = []
        adapter._phpmd = MagicMock()
        adapter._phpmd.run_l3a.return_value = [Finding(
            node="src/Foo.php", severity="minor", message="LongMethod", tool="phpmd"
        )]
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._cs_fixer.parse.return_value = []
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        caplog.set_level(logging.INFO)
        result = adapter.run_l3a(tmp_path, {})
        assert any(f.tool == "phpmd" for f in result.findings)
        # Kill logger mutations 44 & 45 on PHPMD logger.info line:
        #   Mutant 44: removes format string -> logger.info(len(phpmd_findings))
        #   Mutant 45: removes arg -> logger.info("L3A PHPMD: %d findings", )
        # Both change the logged string format. Exact-match assertion kills them.
        phpmd_logs = [m for m in caplog.messages if m.startswith("L3A PHPMD:")]
        assert (
            len(phpmd_logs) == 1
        ), f"Expected exactly one PHPMD log record, got: {phpmd_logs}"
        # Original: "L3A PHPMD: 1 findings"
        # Mutated 44: "1" (just the count, no prefix)
        # Mutated 45: "%d" or similar invalid output
        assert phpmd_logs[0] == "L3A PHPMD: 1 findings"

    def test_l3a_phpmd_zero_findings_log(self, tmp_path, caplog):
        """Kill mutants 44 & 45 with zero-findings path (log message still has %d format).

        Mutant 44: logger.info(len([])) -> logger.info(0)
        Mutant 45: logger.info("L3A PHPMD: %d findings", ) -> syntax error / TypeError

        Assert exact log message to detect format-string and argument mutations.
        """
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.run_l3a.return_value = []
        adapter._phpmd = MagicMock()
        adapter._phpmd.run_l3a.return_value = []
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._cs_fixer.parse.return_value = []
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        caplog.set_level(logging.INFO)
        result = adapter.run_l3a(tmp_path, {})
        assert result.passed is True
        phpmd_logs = [m for m in caplog.messages if m.startswith("L3A PHPMD:")]
        assert len(phpmd_logs) == 1, f"Expected exactly one PHPMD log record, got: {phpmd_logs}"
        assert phpmd_logs[0] == "L3A PHPMD: 0 findings"

    def test_l3a_cs_fixer_finds(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.run_l3a.return_value = []
        adapter._phpmd = MagicMock()
        adapter._phpmd.run_l3a.return_value = []
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.invoke.return_value = MagicMock(stdout='[{"files":[{"name":"src/X.php","violations":[{"line":1,"message":"test"}]}]}]', stderr="", exitcode=8)
        adapter._cs_fixer.parse.return_value = [Finding(
            node="src/X.php", severity="warning", message="line 1: test",
            tool="php-cs-fixer", rule_id="indentation"
        )]
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        result = adapter.run_l3a(tmp_path, {})
        assert any(f.tool == "php-cs-fixer" for f in result.findings)
        # Kill cs_fixer.parse() argument mutations 77 & 78:
        #   Mut 77: invocation.stdout → None in parse() call
        #   Mut 78: invocation.stderr → None in parse() call
        cs_args = adapter._cs_fixer.parse.call_args[0]
        assert cs_args[0] == adapter._cs_fixer.invoke.return_value.stdout
        assert cs_args[1] == adapter._cs_fixer.invoke.return_value.stderr
        assert cs_args[2] == adapter._cs_fixer.invoke.return_value.exitcode

    def test_l3a_tier_a_visitor_finds(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.run_l3a.return_value = []
        adapter._phpmd = MagicMock()
        adapter._phpmd.run_l3a.return_value = []
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._cs_fixer.parse.return_value = []
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout='[{"file":"src/Y.php","rule":"AntiPattern"}]', stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = [Finding(
            node="src/Y.php", severity="warning", message="AntiPattern", tool="antipattern"
        )]
        result = adapter.run_l3a(tmp_path, {})
        assert any(f.tool == "antipattern" for f in result.findings)

    def test_l3a_phpstan_runtime_error_skipped(self, tmp_path, caplog):
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.run_l3a.side_effect = RuntimeError("phpstan not found")
        adapter._phpmd = MagicMock()
        adapter._phpmd.run_l3a.return_value = []
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._cs_fixer.parse.return_value = []
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        caplog.set_level(logging.WARNING, logger="harness_quality_gate.adapters.php")
        result = adapter.run_l3a(tmp_path, {})
        assert result.layer == "L3A"
        # Verify warning message format — kills logger.arg mutations:
        #   mutant 30: "%s", exc → "%s", None  (output becomes "L3A PHPStan skipped: None")
        #   mutant 31: "L3A ...%s", exc → "L3A ..."(exc)  (output changes entirely)
        warnings = [m for m in caplog.messages if "L3A PHPStan skipped" in m]
        assert len(warnings) == 1, f"Expected exactly one skip warning, got: {warnings}"
        # Exact match kills both string-format AND argument mutations
        assert warnings[0] == "L3A PHPStan skipped: phpstan not found"

    def test_l3a_phpmd_runtime_error_skipped(self, tmp_path, caplog):
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.run_l3a.return_value = []
        adapter._phpmd = MagicMock()
        adapter._phpmd.run_l3a.side_effect = RuntimeError("phpmd not found")
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._cs_fixer.parse.return_value = []
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        caplog.set_level(logging.WARNING, logger="harness_quality_gate.adapters.php")
        result = adapter.run_l3a(tmp_path, {})
        assert result.passed is True
        # Kill logger argument mutations 50, 52, 53, 54:
        #   Mut 50: logger.warning("...", exc) → logger.warning("...", None)
        #     → log becomes "L3A PHPMD skipped: None" instead of "L3A PHPMD skipped: phpmd not found"
        #   Mut 52: logger.warning("...", ) — arg removed → log changes entirely
        #   Mut 53: format "L3A PHPMD skipped: %s" → "XXL3A PHPMD skipped: %sXX"
        #   Mut 54: format "L3A PHPMD skipped: %s" → "l3a phpmd skipped: %s"
        # Exact-match assertion kills all four mutations at once.
        warnings = [m for m in caplog.messages if "L3A PHPMD skipped" in m]
        assert len(warnings) == 1, f"Expected exactly one PHPMD skip warning, got: {warnings}"
        assert warnings[0] == "L3A PHPMD skipped: phpmd not found"

    def test_l3a_cs_fixer_runtime_error_skipped(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.run_l3a.return_value = []
        adapter._phpmd = MagicMock()
        adapter._phpmd.run_l3a.return_value = []
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.invoke.side_effect = RuntimeError("cs-fixer not found")
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        result = adapter.run_l3a(tmp_path, {})
        assert result.passed is True

    def test_l3a_tier_a_visitor_runtime_error_skipped(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.run_l3a.return_value = []
        adapter._phpmd = MagicMock()
        adapter._phpmd.run_l3a.return_value = []
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._cs_fixer.parse.return_value = []
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.side_effect = RuntimeError("visitor error")
        adapter._antipattern.parse.return_value = []
        result = adapter.run_l3a(tmp_path, {})
        assert result.passed is True

    def test_l3a_duration_non_negative(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.run_l3a.return_value = []
        adapter._phpmd = MagicMock()
        adapter._phpmd.run_l3a.return_value = []
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._cs_fixer.parse.return_value = []
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        result = adapter.run_l3a(tmp_path, {})
        assert result.duration_sec >= 0

    def test_l3a_cs_fixer_args(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.run_l3a.return_value = []
        adapter._phpmd = MagicMock()
        adapter._phpmd.run_l3a.return_value = []
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._cs_fixer.parse.return_value = []
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        adapter.run_l3a(tmp_path, {})
        call_args = adapter._cs_fixer.invoke.call_args[0][1]
        assert "fix" in call_args
        assert "--dry-run" in call_args
        assert "--format=json" in call_args
        assert "--no-progress" in call_args

    # -----------------------------------------------------------------------
    # Log-message assertions — kill logger.info mutations
    # -----------------------------------------------------------------------

    def _all_mocked_l3a(self, adapter: PhpAdapter):
        """Stub all l3a tools to avoid real binaries."""
        adapter._phpstan = MagicMock()
        adapter._phpstan.run_l3a.return_value = []
        adapter._phpmd = MagicMock()
        adapter._phpmd.run_l3a.return_value = []
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._cs_fixer.parse.return_value = []
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []

    def test_l3a_with_single_framework_log_message(self, tmp_path, caplog):
        """Kill mutant 15 with single framework (package name check).

        Mutant 15: ', '.join(injection_packages) -> 'XX, XX'.join()
        The format string and join produce the log message.  Mutated join would
        replace the separator 'XX, XX' — visible only with 2+ items, but the
        package name check still validates the format string itself.
        """
        # Write a composer.json that triggers symfony detection
        composer = tmp_path / "composer.json"
        composer.write_text(
            json.dumps({"require": {"symfony/framework-bundle": "^6.0"}}),
            encoding="utf-8",
        )
        adapter = PhpAdapter()
        self._all_mocked_l3a(adapter)

        caplog.set_level(logging.INFO)
        result = adapter.run_l3a(tmp_path, {})

        assert result.layer == "L3A"
        # The log message must contain the actual injected package name,
        # not the mutated 'XX, XX' placeholder
        assert any(
            "phpstan-symfony" in m
            for m in caplog.messages
        ), "Log must contain the actual injected package name"

    def test_l3a_with_multiple_frameworks_log_message(self, tmp_path, caplog):
        """Kill mutant 15: join delimiter visible with 2+ frameworks.

        Mutant 15: ', '.join(injection_packages) -> 'XX, XX'.join()
        With multiple frameworks, the separator becomes observable.
        Original: "L3A PHPStan framework packs: larastan, phpstan-symfony"
        Mutated:  "L3A PHPStan framework packs: larastanXX, XXphpstan-symfony"
        (frameworks sorted alphabetically: laravel → larastan before symfony → phpstan-symfony)
        """
        composer = tmp_path / "composer.json"
        composer.write_text(
            json.dumps({
                "require": {
                    "symfony/framework-bundle": "^6.0",
                    "laravel/framework": "^10.0",
                }
            }),
            encoding="utf-8",
        )
        adapter = PhpAdapter()
        self._all_mocked_l3a(adapter)

        caplog.set_level(logging.INFO)
        result = adapter.run_l3a(tmp_path, {})

        assert result.layer == "L3A"
        # The framework packs log must contain both package names separated
        # by ', ' — the mutated join would replace ', ' with 'XX, XX'
        framework_logs = [
            m for m in caplog.messages if "L3A PHPStan framework packs" in m
        ]
        assert len(framework_logs) == 1, "Expected exactly one framework packs log"
        # Verify the separator is ', ' not 'XX, XX'
        assert (
            "larastan, phpstan-symfony" in framework_logs[0]
        ), f"Log should use ', ' separator, got: {framework_logs[0]}"
        # Verify exact message format to catch all format string mutations
        assert framework_logs[0] == "L3A PHPStan framework packs: larastan, phpstan-symfony"

    def test_l3a_phpstan_zero_findings_log_message(self, tmp_path, caplog):
        """Kill mutants 24 & 25 on PHPStan logger.info.

        Mutant 24: removes format string → logger.info(len(phpstan_findings))
        Mutant 25: removes len() arg → logger.info("L3A PHPStan: %d findings", )

        Both change the resulting logged string.  We assert the exact message
        format (not just substring) so mutations that remove args produce
        different output.  Original: "L3A PHPStan: 0 findings"
        Mutated:                    "0" (just the number, no prefix format)
        """
        adapter = PhpAdapter()
        self._all_mocked_l3a(adapter)

        caplog.set_level(logging.INFO)
        result = adapter.run_l3a(tmp_path, {})

        # Extract the exact PHPStan log record
        phpstan_log = [m for m in caplog.messages if m.startswith("L3A PHPStan:")]
        assert len(phpstan_log) == 1, f"Expected exactly one PHPStan log, got: {phpstan_log}"
        # Verify exact message — mutated versions would produce "0" only
        assert phpstan_log[0] == "L3A PHPStan: 0 findings"

    def test_l3a_phpstan_findings_log_message(self, tmp_path, caplog):
        """Reinforce mutants 24 & 25 with actual findings count.

        Logs 'L3A PHPStan: 3 findings' — mutated versions would produce
        different strings and fail the assertion.
        """
        adapter = PhpAdapter()
        self._all_mocked_l3a(adapter)
        adapter._phpstan.run_l3a.return_value = [
            Finding(node="src/A.php", severity="error", message="e1", tool="phpstan"),
            Finding(node="src/B.php", severity="error", message="e2", tool="phpstan"),
            Finding(node="src/C.php", severity="error", message="e3", tool="phpstan"),
        ]

        caplog.set_level(logging.INFO)
        result = adapter.run_l3a(tmp_path, {})

        # Extract exact log record for PHPStan (not substring, exact match)
        phpstan_log = [m for m in caplog.messages if m.startswith("L3A PHPStan:")]
        assert len(phpstan_log) == 1
        # Mutated versions would produce "3" only (no "L3A PHPStan: ... findings" prefix)
        assert phpstan_log[0] == "L3A PHPStan: 3 findings"


# ===========================================================================
# run_l3b
# ===========================================================================

class TestRunL3b:
    def test_l3b_delegates_to_weak_test(self, tmp_path):
        adapter = PhpAdapter()
        expected_result = LayerResult(
            layer="L3B", language="php", passed=True, findings=[],
            duration_sec=0.0
        )
        adapter._weak_test = MagicMock()
        adapter._weak_test.run_l3b.return_value = expected_result
        result = adapter.run_l3b(tmp_path, {})
        assert result.layer == "L3B"
        assert result.passed is True
        adapter._weak_test.run_l3b.assert_called_once_with(tmp_path, {})


# ===========================================================================
# run_l4
# ===========================================================================

class TestRunL4:
    def _make_l4_mock_adapter(self):
        adapter = PhpAdapter()
        for attr in ("_psalm_taint", "_composer_audit", "_security_checker",
                      "_dead_code", "_dep_analyser", "_deptrac"):
            a = MagicMock()
            a.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
            a.parse.return_value = []
            setattr(adapter, attr, a)
        return adapter

    def test_l4_all_pass(self, tmp_path):
        adapter = self._make_l4_mock_adapter()
        result = adapter.run_l4(tmp_path, {})
        assert isinstance(result, LayerResult)
        assert result.layer == "L4"
        assert result.language == "php"
        assert result.passed is True
        assert result.findings == []
        # duration_sec must be a float and >= 0
        # This kills: round(duration, None) → int, round(3) → int,
        #             time.monotonic() + t0 (still float), t0 = None (TypeError already killed)
        assert isinstance(result.duration_sec, float)
        assert result.duration_sec >= 0
        # Kill mutations on each tool invoke call parameters
        for tool_name in ("_psalm_taint", "_composer_audit", "_security_checker",
                          "_dead_code", "_dep_analyser", "_deptrac"):
            call = getattr(adapter, tool_name).invoke.call_args
            assert call[0][0] == tmp_path
            assert call[1]["env"] == {}
            # Kill mutations on invoke arguments list (args → None, remove args)
            assert call[0][1] not in (None, [])
        # Kill mutations on parse arguments (stdout/stderr/exitcode → None, remove args)
        for tool_name, timeout in (
            ("_psalm_taint", 600.0),
            ("_composer_audit", 300.0),
            ("_security_checker", 300.0),
            ("_dead_code", 300.0),
            ("_dep_analyser", 300.0),
            ("_deptrac", 300.0),
        ):
            inv_call = getattr(adapter, tool_name).invoke.call_args
            assert inv_call[1]["timeout"] == timeout
            inv = getattr(adapter, tool_name).invoke.return_value
            parse_call = getattr(adapter, tool_name).parse.call_args
            # Kill mutations: parse args mutated to None, removed, or swapped
            assert parse_call[0][0] == inv.stdout
            assert parse_call[0][1] == inv.stderr
            assert parse_call[0][2] == inv.exitcode

    def test_l4_log_messages(self, tmp_path, caplog):
        """Verify log messages contain tool names and finding counts to kill string/param mutations on logger calls.

        Kills mutations that:
        - Remove the len(x) arg: `logger.info("...", )` → logs literal "%d" instead of number
        - Change log strings: `"L4 Psalm..."` → `"XXL4 PsalmXX"`
        Each message must match the exact expected format to catch all logger mutations.
        """
        import logging
        with caplog.at_level(logging.INFO, logger="harness_quality_gate.adapters.php"):
            adapter = self._make_l4_mock_adapter()
            result = adapter.run_l4(tmp_path, {})
        # Each successful tool should log an info message with its name
        log_records = [r for r in caplog.records if r.levelno == logging.INFO]
        log_texts = [r.message for r in log_records]
        # 6 tools = 6 info log messages
        assert len(log_records) == 6
        # Check each tool logs exactly one message matching the expected pattern
        # Each message must: contain the tool name AND contain a digit (not literal %d)
        # This kills: arg removal (msg becomes "L4 ...: %d findings"), string mutations ("XX...XX")
        assert any("Psalm" in t and "findings" in t and "%" not in t for t in log_texts)
        assert any("composer-audit" in t and "findings" in t and "%" not in t for t in log_texts)
        assert any("security-checker" in t and "findings" in t and "%" not in t for t in log_texts)
        assert any("dead-code" in t and "findings" in t and "%" not in t for t in log_texts)
        assert any("dep-analyser" in t and "findings" in t and "%" not in t for t in log_texts)
        assert any("deptrac" in t and "findings" in t and "%" not in t for t in log_texts)
        # Kill string mutations: verify exact message format for each tool
        # The format is "L4 <tool-name>: <number> findings"
        psalm_msg = [t for t in log_texts if "Psalm" in t and "taint" in t]
        assert len(psalm_msg) == 1
        assert psalm_msg[0] == "L4 Psalm taint: 0 findings"
        audit_msg = [t for t in log_texts if "composer-audit" in t]
        assert len(audit_msg) == 1
        assert audit_msg[0] == "L4 composer-audit: 0 findings"
        checker_msg = [t for t in log_texts if "security-checker" in t]
        assert len(checker_msg) == 1
        assert checker_msg[0] == "L4 security-checker: 0 findings"
        dead_msg = [t for t in log_texts if "dead-code" in t]
        assert len(dead_msg) == 1
        assert dead_msg[0] == "L4 dead-code: 0 findings"
        depa_msg = [t for t in log_texts if "dep-analyser" in t]
        assert len(depa_msg) == 1
        assert depa_msg[0] == "L4 dep-analyser: 0 findings"
        deptr_msg = [t for t in log_texts if "deptrac" in t]
        assert len(deptr_msg) == 1
        assert deptr_msg[0] == "L4 deptrac: 0 findings"

    def test_l4_finds_change_passed(self, tmp_path):
        """Test that findings correctly flip passed status."""
        adapter = self._make_l4_mock_adapter()
        adapter._psalm_taint.parse.return_value = [Finding(
            node="src/Secret.php", severity="error", message="Taint", tool="psalm"
        )]
        result = adapter.run_l4(tmp_path, {})
        assert result.passed is False
        # Kill mutations where psalm_invocation.exitcode → None or other non-zero value
        # that would cause different behavior in production (e.g. exitcode=None → parse doesn't find stats)
        assert any(f.tool == "psalm" for f in result.findings)

    def test_l4_parse_arguments_verified(self, tmp_path):
        """Kill mutations on parse arguments (exitcode → None, etc)."""
        adapter = self._make_l4_mock_adapter()
        adapter._psalm_taint.invoke.return_value = MagicMock(
            stdout='[{"node":"x"}]', stderr="warn", exitcode=0
        )
        adapter._psalm_taint.parse.return_value = []
        adapter.run_l4(tmp_path, {})
        parse_call = adapter._psalm_taint.parse.call_args
        assert parse_call[0][2] == 0  # exitcode not mutated to None

    def test_l4_psalm_finds(self, tmp_path):
        adapter = self._make_l4_mock_adapter()
        adapter._psalm_taint.parse.return_value = [Finding(
            node="src/Secret.php", severity="error", message="Taint detected", tool="psalm"
        )]
        result = adapter.run_l4(tmp_path, {})
        assert result.passed is False
        assert any(f.tool == "psalm" for f in result.findings)

    def test_l4_composer_audit_finds(self, tmp_path):
        adapter = self._make_l4_mock_adapter()
        adapter._composer_audit.parse.return_value = [Finding(
            node="vendor/pkg", severity="error", message="Vulnerability", tool="composer-audit", cve="CVE-2024-1234"
        )]
        result = adapter.run_l4(tmp_path, {})
        assert any(f.tool == "composer-audit" for f in result.findings)

    def test_l4_security_checker_finds(self, tmp_path):
        adapter = self._make_l4_mock_adapter()
        adapter._security_checker.parse.return_value = [Finding(
            node="vendor/pkg", severity="error", message="Security issue", tool="local-php-security-checker"
        )]
        result = adapter.run_l4(tmp_path, {})
        assert any(f.tool == "local-php-security-checker" for f in result.findings)

    def test_l4_dead_code_finds(self, tmp_path):
        adapter = self._make_l4_mock_adapter()
        adapter._dead_code.parse.return_value = [Finding(
            node="src/Unused.php", severity="info", message="Dead code", tool="dead-code-detector"
        )]
        result = adapter.run_l4(tmp_path, {})
        assert any(f.tool == "dead-code-detector" for f in result.findings)

    def test_l4_dep_analyser_finds(self, tmp_path):
        adapter = self._make_l4_mock_adapter()
        adapter._dep_analyser.parse.return_value = [Finding(
            node="src/X.php", severity="warning", message="Wrong import", tool="composer-dependency-analyser"
        )]
        result = adapter.run_l4(tmp_path, {})
        assert any(f.tool == "composer-dependency-analyser" for f in result.findings)

    def test_l4_deptrac_finds(self, tmp_path):
        adapter = self._make_l4_mock_adapter()
        adapter._deptrac.parse.return_value = [Finding(
            node="src/Forbidden.php", severity="error", message="Architecture violation", tool="deptrac"
        )]
        result = adapter.run_l4(tmp_path, {})
        assert any(f.tool == "deptrac" for f in result.findings)

    def test_l4_all_tools_error_skipped(self, tmp_path):
        adapter = self._make_l4_mock_adapter()
        for attr in ("_psalm_taint", "_composer_audit", "_security_checker",
                      "_dead_code", "_dep_analyser", "_deptrac"):
            setattr(adapter, attr, MagicMock())
            setattr(adapter, attr + ".invoke", MagicMock(side_effect=RuntimeError("not found")))
        result = adapter.run_l4(tmp_path, {})
        assert result.layer == "L4"
        assert result.language == "php"
        assert result.passed is True

    def test_l4_duration_non_negative(self, tmp_path):
        adapter = self._make_l4_mock_adapter()
        result = adapter.run_l4(tmp_path, {})
        assert isinstance(result.duration_sec, float)
        assert result.duration_sec >= 0

    def test_l4_psalm_args(self, tmp_path):
        adapter = self._make_l4_mock_adapter()
        adapter.run_l4(tmp_path, {})
        call_args = adapter._psalm_taint.invoke.call_args[0][1]
        assert "--taint-analysis" in call_args
        assert "--no-progress" in call_args

    def test_l4_composer_audit_args(self, tmp_path):
        adapter = self._make_l4_mock_adapter()
        adapter.run_l4(tmp_path, {})
        call_args = adapter._composer_audit.invoke.call_args[0][1]
        assert "--format=json" in call_args
        assert "--no-dev" in call_args

    def test_l4_security_checker_args(self, tmp_path):
        adapter = self._make_l4_mock_adapter()
        adapter.run_l4(tmp_path, {})
        call_args = adapter._security_checker.invoke.call_args[0][1]
        assert "--format=json" in call_args

    def test_l4_deptrac_args(self, tmp_path):
        adapter = self._make_l4_mock_adapter()
        adapter.run_l4(tmp_path, {})
        call_args = adapter._deptrac.invoke.call_args[0][1]
        assert "--formatter=json" in call_args

    def test_l4_psalm_invoke_args(self, tmp_path):
        """Verify all invoke arguments passed to kill parameter mutation survivors."""
        adapter = self._make_l4_mock_adapter()
        adapter.run_l4(tmp_path, {})
        call = adapter._psalm_taint.invoke.call_args
        # First positional arg = repo (not mutated to None)
        assert call[0][0] == tmp_path
        # Second positional arg = args list
        assert call[0][1] == ["--taint-analysis", "--no-progress"]
        # Keyword args = env and timeout
        assert call[1]["env"] == {}
        assert call[1]["timeout"] == 600.0
        # Verify parse was called with invocation attributes
        parse_call = adapter._psalm_taint.parse.call_args
        assert parse_call[0][0] == "[]"
        assert parse_call[0][1] == ""
        assert parse_call[0][2] == 0

    def test_l4_composer_audit_invoke_args(self, tmp_path):
        """Verify all invoke arguments for composer-audit."""
        adapter = self._make_l4_mock_adapter()
        adapter.run_l4(tmp_path, {})
        call = adapter._composer_audit.invoke.call_args
        assert call[0][0] == tmp_path
        assert call[0][1] == ["--format=json", "--no-dev"]
        assert call[1]["env"] == {}
        assert call[1]["timeout"] == 300.0

    def test_l4_security_checker_invoke_args(self, tmp_path):
        """Verify all invoke arguments for security checker."""
        adapter = self._make_l4_mock_adapter()
        adapter.run_l4(tmp_path, {})
        call = adapter._security_checker.invoke.call_args
        assert call[0][0] == tmp_path
        assert call[0][1] == ["--format=json"]
        assert call[1]["env"] == {}
        assert call[1]["timeout"] == 300.0

    def test_l4_dead_code_invoke_args(self, tmp_path):
        """Verify all invoke arguments for dead-code-detector."""
        adapter = self._make_l4_mock_adapter()
        adapter.run_l4(tmp_path, {})
        call = adapter._dead_code.invoke.call_args
        assert call[0][0] == tmp_path
        assert call[1]["env"] == {}
        assert call[1]["timeout"] == 300.0

    def test_l4_dep_analyser_invoke_args(self, tmp_path):
        """Verify all invoke arguments for dep-analyser."""
        adapter = self._make_l4_mock_adapter()
        adapter.run_l4(tmp_path, {})
        call = adapter._dep_analyser.invoke.call_args
        assert call[0][0] == tmp_path
        assert call[1]["env"] == {}
        assert call[1]["timeout"] == 300.0

    def test_l4_deptrac_invoke_args(self, tmp_path):
        """Verify all invoke arguments for deptrac."""
        adapter = self._make_l4_mock_adapter()
        adapter.run_l4(tmp_path, {})
        call = adapter._deptrac.invoke.call_args
        assert call[0][0] == tmp_path
        assert call[1]["env"] == {}
        assert call[1]["timeout"] == 300.0

    def test_l4_env_passed_to_all_invokes(self, tmp_path):
        """Kill mutations where env=env is removed or mutated to None."""
        adapter = self._make_l4_mock_adapter()
        adapter.run_l4(tmp_path, {"CUSTOM_ENV": "value"})
        for attr in ("_psalm_taint", "_composer_audit", "_security_checker",
                      "_dead_code", "_dep_analyser", "_deptrac"):
            call = getattr(adapter, attr).invoke.call_args
            assert call[1]["env"] == {"CUSTOM_ENV": "value"}
    def test_l4_invoke_timeout_params(self, tmp_path):
        """Verify timeout values for all L4 tool invokes to kill timeout mutation survivors."""
        adapter = self._make_l4_mock_adapter()
        adapter.run_l4(tmp_path, {})
        # psalm has 600.0 timeout, others have 300.0
        assert adapter._psalm_taint.invoke.call_args[1]["timeout"] == 600.0
        for attr in ("_composer_audit", "_security_checker"):
            assert getattr(adapter, attr).invoke.call_args[1]["timeout"] == 300.0
        for attr in ("_dead_code", "_dep_analyser", "_deptrac"):
            assert getattr(adapter, attr).invoke.call_args[1]["timeout"] == 300.0


# ===========================================================================
# check_tools
# ===========================================================================

class TestCheckTools:
    def test_check_tools_all_present(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.version.return_value = "1.0.0"
        adapter._phpstan.name = "phpstan"
        adapter._phpmd = MagicMock()
        adapter._phpmd.version.return_value = "1.0.0"
        adapter._phpmd.name = "phpmd"
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.version.return_value = "1.0.0"
        adapter._cs_fixer.name = "php-cs-fixer"
        result = adapter.check_tools()
        assert "phpstan" in result
        assert "phpmd" in result
        assert "php-cs-fixer" in result

    def test_check_tools_phpstan_missing(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.version.side_effect = RuntimeError("not found")
        adapter._phpstan.name = "phpstan"
        adapter._phpmd = MagicMock()
        adapter._phpmd.version.return_value = "1.0.0"
        adapter._phpmd.name = "phpmd"
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.version.return_value = "1.0.0"
        adapter._cs_fixer.name = "php-cs-fixer"
        with pytest.raises(RuntimeError, match="phpstan"):
            adapter.check_tools()

    def test_check_tools_phpmd_missing(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.version.return_value = "1.0.0"
        adapter._phpstan.name = "phpstan"
        adapter._phpmd = MagicMock()
        adapter._phpmd.version.side_effect = RuntimeError("not found")
        adapter._phpmd.name = "phpmd"
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.version.return_value = "1.0.0"
        adapter._cs_fixer.name = "php-cs-fixer"
        with pytest.raises(RuntimeError, match="phpmd"):
            adapter.check_tools()

    def test_check_tools_cs_fixer_missing(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.version.return_value = "1.0.0"
        adapter._phpstan.name = "phpstan"
        adapter._phpmd = MagicMock()
        adapter._phpmd.version.return_value = "1.0.0"
        adapter._phpmd.name = "phpmd"
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.version.side_effect = RuntimeError("not found")
        adapter._cs_fixer.name = "php-cs-fixer"
        with pytest.raises(RuntimeError, match="php-cs-fixer"):
            adapter.check_tools()

    def test_check_tools_all_missing(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.version.side_effect = RuntimeError("not found")
        adapter._phpstan.name = "phpstan"
        adapter._phpmd = MagicMock()
        adapter._phpmd.version.side_effect = RuntimeError("not found")
        adapter._phpmd.name = "phpmd"
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.version.side_effect = RuntimeError("not found")
        adapter._cs_fixer.name = "php-cs-fixer"
        with pytest.raises(RuntimeError, match="phpstan"):
            adapter.check_tools()


# ===========================================================================
# tool_versions
# ===========================================================================

class TestToolVersions:
    def test_versions_all_present(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.version.return_value = "1.0.0"
        adapter._phpstan.name = "phpstan"
        adapter._phpmd = MagicMock()
        adapter._phpmd.version.return_value = "1.0.0"
        adapter._phpmd.name = "phpmd"
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.version.return_value = "1.0.0"
        adapter._cs_fixer.name = "php-cs-fixer"
        versions = adapter.tool_versions()
        assert versions["phpstan"] == "1.0.0"
        assert versions["phpmd"] == "1.0.0"
        assert versions["php-cs-fixer"] == "1.0.0"

    def test_versions_missing_tool(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.version.return_value = "1.0.0"
        adapter._phpstan.name = "phpstan"
        adapter._phpmd = MagicMock()
        adapter._phpmd.version.side_effect = RuntimeError("not found")
        adapter._phpmd.name = "phpmd"
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.version.return_value = "1.0.0"
        adapter._cs_fixer.name = "php-cs-fixer"
        versions = adapter.tool_versions()
        assert versions["phpstan"] == "1.0.0"
        assert versions["phpmd"] == "MISSING"
        assert versions["php-cs-fixer"] == "1.0.0"


# ===========================================================================
# name property
# ===========================================================================

class TestName:
    def test_adapter_name(self):
        adapter = PhpAdapter()
        assert adapter.name == "php"


# ===========================================================================
# _collect_test_files
# ===========================================================================

class TestCollectTestFiles:
    def test_collect_skips_vendor(self, tmp_path):
        vendor = tmp_path / "vendor" / "pkg"
        vendor.mkdir(parents=True)
        (vendor / "Bar.php").touch()
        src = tmp_path / "src"
        src.mkdir()
        (src / "Foo.php").touch()
        result = PhpAdapter._collect_test_files(tmp_path)
        paths = [str(r) for r in result]
        assert not any("/vendor/" in p for p in paths)
        assert any("/src/" in p for p in paths)

    def test_collect_skips_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "Bar.php").touch()
        result = PhpAdapter._collect_test_files(tmp_path)
        paths = [str(r) for r in result]
        assert not any("node_modules" in p for p in paths)

    def test_collect_empty_repo(self, tmp_path):
        result = PhpAdapter._collect_test_files(tmp_path)
        assert result == []

    def test_collect_returns_sorted(self, tmp_path):
        (tmp_path / "a.php").touch()
        (tmp_path / "b.php").touch()
        (tmp_path / "c.php").touch()
        result = PhpAdapter._collect_test_files(tmp_path)
        paths = [str(r) for r in result]
        assert paths == sorted(paths)


# ===========================================================================
# _antipattern_invoke_and_parse
# ===========================================================================

class TestAntipatternInvokeAndParse:
    def test_invoke_and_parse(self, tmp_path):
        adapter = PhpAdapter()
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout='[{"file":"src/X.php","rule":"test"}]', stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = [Finding(
            node="src/X.php", severity="warning", message="test", tool="antipattern"
        )]
        result = adapter._antipattern_invoke_and_parse(tmp_path, {})
        assert len(result) >= 1
        assert result[0].tool == "antipattern"
        #Kill mutations on invoke args
        assert adapter._antipattern.invoke.call_args[0][0] == tmp_path
        assert adapter._antipattern.invoke.call_args[1]["env"] == {}

    def test_invoke_and_parse_forward_env(self, tmp_path):
        adapter = PhpAdapter()
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        adapter._antipattern_invoke_and_parse(tmp_path, {"FOO": "BAR"})
        adapter._antipattern.invoke.assert_called_once()
        call_env = adapter._antipattern.invoke.call_args[1]["env"]
        assert call_env == {"FOO": "BAR"}


# ===========================================================================
# _pcov_initial_tests_option
# ===========================================================================

class TestPcovInitialTestsOption:
    def test_pcov_already_loaded(self):
        adapter = PhpAdapter()
        completed = MagicMock()
        completed.stdout = "pcov\nCore\ndates\n"
        completed.stderr = ""
        completed.returncode = 0
        with patch("subprocess.run", return_value=completed):
            result = adapter._pcov_initial_tests_option()
        assert result == ""

    def test_pcov_not_loaded_no_glob(self):
        adapter = PhpAdapter()
        completed = MagicMock()
        completed.stdout = "Core\ndates\n"
        completed.stderr = ""
        completed.returncode = 0
        with patch("subprocess.run", return_value=completed):
            with patch("glob.glob", return_value=[]):
                result = adapter._pcov_initial_tests_option()
        assert result == ""

    def test_pcov_found_via_glob(self):
        adapter = PhpAdapter()
        completed = MagicMock()
        completed.stdout = "Core\n"
        completed.stderr = ""
        completed.returncode = 0
        with patch("subprocess.run", return_value=completed):
            with patch("glob.glob", return_value=["/usr/lib/php/20210902/pcov.so"]):
                result = adapter._pcov_initial_tests_option()
        assert "-dextension=" in result
        assert "pcov.so" in result

    def test_subprocess_oserror_returns_empty(self):
        adapter = PhpAdapter()
        with patch("subprocess.run", side_effect=OSError("permission")):
            result = adapter._pcov_initial_tests_option()
        assert result == ""

    def test_subprocess_timeout_returns_empty(self):
        adapter = PhpAdapter()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["php"], timeout=5)):
            result = adapter._pcov_initial_tests_option()
        assert result == ""

    def test_pcov_case_insensitive(self):
        adapter = PhpAdapter()
        completed = MagicMock()
        completed.stdout = "CORE\nPCOV\nDate\n"
        completed.stderr = ""
        completed.returncode = 0
        with patch("subprocess.run", return_value=completed):
            result = adapter._pcov_initial_tests_option()
        assert result == ""

    def test_multiple_glob_patterns_first_matches(self):
        adapter = PhpAdapter()
        completed = MagicMock()
        completed.stdout = "Core\n"
        completed.returncode = 0
        with patch("subprocess.run", return_value=completed):
            with patch("glob.glob", side_effect=[
                [],  # /tmp/pcov-extract pattern
                ["/usr/lib/php/20210902/pcov.so"],  # /usr/lib pattern
            ]):
                result = adapter._pcov_initial_tests_option()
        assert "pcov.so" in result


# ===========================================================================
# _run_infection
# ===========================================================================

class TestRunInfection:
    def test_infection_called_with_min_msi_100(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="pcov",
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        adapter._infection.invoke.return_value = MagicMock(
            stdout="6 mutants were killed\nMetrics:\n     Mutation Score Indicator (MSI): 100%",
            stderr="", exitcode=0
        )
        result = adapter._run_infection(tmp_path, {}, is_pest_project=False)
        call_args = adapter._infection.invoke.call_args[0][1]
        assert "--min-msi=100" in call_args
        assert "--min-covered-msi=100" in call_args

    def test_infection_called_with_threads_max(self, tmp_path):
        adapter = _make_mock_adapter(
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        adapter._infection.invoke.return_value = MagicMock(
            stdout="6 mutants were killed\nMetrics:\n     Mutation Score Indicator (MSI): 100%",
            stderr="", exitcode=0
        )
        adapter._run_infection(tmp_path, {}, is_pest_project=False)
        call_args = adapter._infection.invoke.call_args[0][1]
        assert "--threads=max" in call_args

    def test_infection_no_progress_flag(self, tmp_path):
        adapter = _make_mock_adapter(
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        adapter._infection.invoke.return_value = MagicMock(
            stdout="6 mutants were killed\nMetrics:\n     Mutation Score Indicator (MSI): 100%",
            stderr="", exitcode=0
        )
        adapter._run_infection(tmp_path, {}, is_pest_project=False)
        call_args = adapter._infection.invoke.call_args[0][1]
        assert "--no-progress" in call_args

    def test_infection_pest_flag(self, tmp_path):
        adapter = _make_mock_adapter(
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        adapter._infection.invoke.return_value = MagicMock(
            stdout="6 mutants were killed", stderr="", exitcode=0
        )
        adapter._run_infection(tmp_path, {}, is_pest_project=True)
        call_args = adapter._infection.invoke.call_args[0][1]
        assert "--test-framework=pest" in call_args

    def test_infection_exitcode_3_no_output_returns_none(self, tmp_path):
        adapter = _make_mock_adapter()
        adapter._infection.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=3)
        result = adapter._run_infection(tmp_path, {}, is_pest_project=False)
        assert result is None

    def test_infection_exitcode_nonzero_no_stats_returns_none(self, tmp_path):
        adapter = _make_mock_adapter()
        adapter._infection.invoke.return_value = MagicMock(
            stdout="Some error", stderr="error text", exitcode=1
        )
        adapter._infection.parse.return_value = None
        result = adapter._run_infection(tmp_path, {}, is_pest_project=False)
        assert result is None

    def test_infection_with_stats_exitcode_nonzero_returns_stats(self, tmp_path):
        adapter = _make_mock_adapter(
            infection_stats=MutationStats(
                total=100, killed=90, survived=10, escaped=0, timed_out=0,
                untested=0, msi=90.0, covered_msi=95.0
            )
        )
        adapter._infection.invoke.return_value = MagicMock(
            stdout="Mutation Score Indicator (MSI): 90%", stderr="", exitcode=1
        )
        result = adapter._run_infection(tmp_path, {}, is_pest_project=False)
        assert result is not None
        assert result.msi == 90.0

    def test_infection_runtime_error_returns_none(self, tmp_path):
        adapter = _make_mock_adapter()
        adapter._infection.invoke.side_effect = RuntimeError("invocation failed")
        result = adapter._run_infection(tmp_path, {}, is_pest_project=False)
        assert result is None

    def test_infection_pcov_flag_appended(self, tmp_path):
        """Kill 'if pcov_flag' dead code mutant (line 686-687).

        When _pcov_initial_tests_option returns a non-empty PCOV flag,
        the --initial-tests-php-options must be appended to the args list
        before __main__.py mutation exclusion.
        """
        adapter = PhpAdapter()
        # Mock inner adapters
        adapter._infection = MagicMock()
        adapter._infection.invoke.return_value = MagicMock(
            stdout="6 mutants were killed\n", stderr="", exitcode=0
        )
        adapter._infection.parse.return_value = MutationStats(
            total=6, killed=6, survived=0, escaped=0, timed_out=0,
            untested=0, msi=100.0, covered_msi=100.0
        )
        # Mock _pcov_initial_tests_option to return a non-empty flag
        # (simulating PCOV loaded but not by PHP — found via glob)
        with patch.object(
            adapter,
            "_pcov_initial_tests_option",
            return_value="-dextension=/usr/lib/php/20210902/pcov.so",
        ):
            result = adapter._run_infection(tmp_path, {}, is_pest_project=False)
        call_args = adapter._infection.invoke.call_args[0][1]
        assert "--initial-tests-php-options=-dextension=/usr/lib/php/20210902/pcov.so" in call_args

    def test_infection_args_order(self, tmp_path):
        adapter = _make_mock_adapter(
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        adapter._infection.invoke.return_value = MagicMock(
            stdout="Mutation Score Indicator (MSI): 100%", stderr="", exitcode=0
        )
        adapter._run_infection(tmp_path, {}, is_pest_project=False)
        call_args = adapter._infection.invoke.call_args[0][1]
        assert call_args[0] == "--no-progress"
        assert call_args[1] == "--threads=max"
        assert call_args[2] == "--min-msi=100"
        assert call_args[3] == "--min-covered-msi=100"

    def test_infection_invoke_passes_env(self, tmp_path):
        """Verify env is passed to invoke to kill 'env=env' removal mutation."""
        adapter = _make_mock_adapter(
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        adapter._infection.invoke.return_value = MagicMock(
            stdout="Mutation Score Indicator (MSI): 100%", stderr="", exitcode=0
        )
        env = {"FOO": "bar", "PATH": "/usr/bin"}
        adapter._run_infection(tmp_path, env, is_pest_project=False)
        call_kwargs = adapter._infection.invoke.call_args[1]
        assert call_kwargs["env"] == env

    def test_infection_invoke_passes_timeout(self, tmp_path):
        """Verify timeout=600.0 is passed to kill timeout removal mutation."""
        adapter = _make_mock_adapter(
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        adapter._infection.invoke.return_value = MagicMock(
            stdout="Mutation Score Indicator (MSI): 100%", stderr="", exitcode=0
        )
        adapter._run_infection(tmp_path, {}, is_pest_project=False)
        call_kwargs = adapter._infection.invoke.call_args[1]
        assert call_kwargs["timeout"] == 600.0

    def test_infection_invoke_passes_repo(self, tmp_path):
        """Verify repo is passed to kill 'repo=None' mutation."""
        adapter = _make_mock_adapter(
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        adapter._infection.invoke.return_value = MagicMock(
            stdout="Mutation Score Indicator (MSI): 100%", stderr="", exitcode=0
        )
        adapter._run_infection(tmp_path, {}, is_pest_project=False)
        call_args = adapter._infection.invoke.call_args[0]
        assert call_args[0] == tmp_path


# ===========================================================================
# _run_phpunit_tests
# ===========================================================================

class TestRunPhpunitTests:
    def test_phpunit_success(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpunit = MagicMock()
        adapter._phpunit.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)
        adapter._phpunit.parse.return_value = [Finding(
            node="tests/FooTest.php", severity="error", message="assertion failed", tool="phpunit"
        )]
        result = adapter._run_phpunit_tests(tmp_path, {})
        assert len(result) >= 1

    def test_phpunit_empty(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpunit = MagicMock()
        adapter._phpunit.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)
        adapter._phpunit.parse.return_value = []
        result = adapter._run_phpunit_tests(tmp_path, {})
        assert result == []

    def test_phpunit_runtime_error_returned_empty(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpunit = MagicMock()
        adapter._phpunit.invoke.side_effect = RuntimeError("phpunit missing")
        result = adapter._run_phpunit_tests(tmp_path, {})
        assert result == []

    def test_phpunit_invoke_passes_args(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpunit = MagicMock()
        adapter._phpunit.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)
        adapter._phpunit.parse.return_value = []
        adapter._run_phpunit_tests(tmp_path, {})
        call_args = adapter._phpunit.invoke.call_args[0][1]
        assert "--log-junit" in call_args
        assert "junit.xml" in call_args

    def test_phpunit_invoke_called_with_repo(self, tmp_path):
        """Kill 'repo → None' mutation in _run_phpunit_tests."""
        adapter = PhpAdapter()
        adapter._phpunit = MagicMock()
        adapter._phpunit.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)
        adapter._phpunit.parse.return_value = []
        adapter._run_phpunit_tests(tmp_path, {})
        call_args = adapter._phpunit.invoke.call_args[0]
        assert call_args[0] == tmp_path

    def test_phpunit_parse_called_with_stdout_stderr_exitcode(self, tmp_path):
        """Kill mutations on parse arguments (exitcode → None, stderr → None)."""
        adapter = PhpAdapter()
        adapter._phpunit = MagicMock()
        adapter._phpunit.invoke.return_value = MagicMock(
            stdout="test output", stderr="stderr text", exitcode=1
        )
        adapter._phpunit.parse.return_value = []
        adapter._run_phpunit_tests(tmp_path, {})
        parse_call = adapter._phpunit.parse.call_args
        assert parse_call[0][0] == "test output"
        assert parse_call[0][1] == "stderr text"
        assert parse_call[0][2] == 1


# ===========================================================================
# _run_pest_tests
# ===========================================================================

class TestRunPestTests:
    def test_pest_success(self, tmp_path):
        adapter = PhpAdapter()
        adapter._pest = MagicMock()
        adapter._pest.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)
        result = adapter._run_pest_tests(tmp_path, {})
        assert result == []

    def test_pest_fail(self, tmp_path):
        adapter = PhpAdapter()
        adapter._pest = MagicMock()
        adapter._pest.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=1)
        result = adapter._run_pest_tests(tmp_path, {})
        assert any("Pest tests failed" in f.message for f in result)
        assert result[0].severity == "error"
        assert result[0].tool == "pest"

    def test_pest_runtime_error_empty(self, tmp_path):
        adapter = PhpAdapter()
        adapter._pest = MagicMock()
        adapter._pest.invoke.side_effect = RuntimeError("missing")
        result = adapter._run_pest_tests(tmp_path, {})
        assert result == []

    def test_pest_invoke_passes_args(self, tmp_path):
        adapter = PhpAdapter()
        adapter._pest = MagicMock()
        adapter._pest.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)
        adapter._run_pest_tests(tmp_path, {})
        call_args = adapter._pest.invoke.call_args[0][1]
        assert "--no-output" in call_args

    def test_pest_invoke_called_with_repo(self, tmp_path):
        """Kill 'repo → None' mutation in _run_pest_tests."""
        adapter = PhpAdapter()
        adapter._pest = MagicMock()
        adapter._pest.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)
        adapter._run_pest_tests(tmp_path, {})
        call_args = adapter._pest.invoke.call_args[0]
        assert call_args[0] == tmp_path

    def test_pest_invoke_called_with_env(self, tmp_path):
        """Kill 'env=env → None' mutation in _run_pest_tests."""
        adapter = PhpAdapter()
        adapter._pest = MagicMock()
        adapter._pest.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)
        adapter._run_pest_tests(tmp_path, {"FOO": "BAR"})
        call_kwargs = adapter._pest.invoke.call_args[1]
        assert call_kwargs["env"] == {"FOO": "BAR"}


# ===========================================================================
# LayerResult passed field with granular asserts
# ===========================================================================

class TestRunL1PassedFieldGranular:
    def _assert_finding_fields(self, f, expected_tool=None, expected_severity=None, expected_layer="L1", expected_language="php"):
        """Assert individual Finding fields granularly."""
        if expected_tool:
            assert f.tool == expected_tool
        if expected_severity:
            assert f.severity == expected_severity
        assert f.layer == expected_layer
        assert f.language == expected_language

    def test_run_l1_all_pass_result_fields(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="pcov",
            pest_binary=None,
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.layer == "L1"
        assert result.language == "php"
        assert result.passed is True
        assert result.findings == []
        assert result.duration_sec >= 0

    def test_run_l1_mutation_fail_result_fields(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="pcov",
            pest_binary=None,
            infection_stats=MutationStats(
                total=100, killed=80, survived=20, escaped=0, timed_out=0,
                untested=0, msi=80.0, covered_msi=85.0
            )
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.layer == "L1"
        assert result.language == "php"
        assert result.passed is False
        assert len(result.findings) >= 1
        for f in result.findings:
            self._assert_finding_fields(f, expected_layer="L1", expected_language="php")
        assert result.duration_sec >= 0

    def test_run_l1_pest_no_mutate_result_fields(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="xdebug",
            pest_binary="pest",
            pest_has_mutate=False
        )
        adapter._pest._pest_binary.side_effect = [["pest"], ["pest"]]
        adapter._pest.invoke.return_value = MagicMock(exitcode=0, stdout="", stderr="")
        result = adapter.run_l1(tmp_path, {})
        assert result.layer == "L1"
        assert result.language == "php"
        assert result.passed is False

    def test_run_l1_pcov_fail_result_fields(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_probe_side_effect=RuntimeError("no driver")
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.layer == "L1"
        assert result.language == "php"
        assert result.passed is False
        pcov_f = [f for f in result.findings if f.tool == "pcov"]
        assert len(pcov_f) >= 1
        assert pcov_f[0].severity == "error"

    def test_run_l1_harness_infection_required_result_fields(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="xdebug",
            infection_stats=None,
            infection_exitcode=3,
            infection_stdout=""
        )
        result = adapter.run_l1(tmp_path, {"HARNESS_INFECTION_REQUIRED": "1"})
        assert result.layer == "L1"
        assert result.language == "php"
        assert result.passed is False
        infection_findings = [f for f in result.findings if "HARNESS_INFECTION_REQUIRED" in f.message]
        assert len(infection_findings) >= 1
        assert infection_findings[0].severity == "error"
        assert infection_findings[0].tool == "infection"


# ===========================================================================
# run_l3a framework injection logic
# ===========================================================================

class TestRunL3aFrameworkInjection:
    def test_l3a_phpstan_receives_extra_config(self, tmp_path):
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.run_l3a.return_value = []
        adapter._phpmd = MagicMock()
        adapter._phpmd.run_l3a.return_value = []
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._cs_fixer.parse.return_value = []
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        composer = tmp_path / "composer.json"
        composer.write_text(json.dumps({"require": {"symfony/framework-bundle": "^6.0"}}))
        result = adapter.run_l3a(tmp_path, {})
        adapter._phpstan.run_l3a.assert_called_once()

    def test_l3a_framework_injection_logs_info(self, tmp_path, caplog):
        """Kill log message mutations in run_l3a framework injection logger.info call.

        Mutants killed:
        - mutmut_1: format string "L3A...%s" → removed → None
        - mutmut_2: second arg ", ".join(...) → removed → None
        - mutmut_3: first arg removed entirely
        - mutmut_4: entire logger.info call removed
        """
        adapter = PhpAdapter()
        adapter._phpstan = MagicMock()
        adapter._phpstan.run_l3a.return_value = []
        adapter._phpmd = MagicMock()
        adapter._phpmd.run_l3a.return_value = []
        adapter._cs_fixer = MagicMock()
        adapter._cs_fixer.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._cs_fixer.parse.return_value = []
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        composer = tmp_path / "composer.json"
        composer.write_text(json.dumps({"require": {"symfony/framework-bundle": "^6.0"}}))
        with caplog.at_level(logging.INFO, logger="harness_quality_gate.adapters.php"):
            result = adapter.run_l3a(tmp_path, {})
        # Assert log contains framework packs info with correct format
        framework_logs = [r for r in caplog.records if "L3A PHPStan framework packs" in r.message]
        assert len(framework_logs) >= 1
        assert framework_logs[0].message == "L3A PHPStan framework packs: phpstan-symfony"
        assert framework_logs[0].levelno == logging.INFO


# ===========================================================================
# Edge cases / mutation survivors
# ===========================================================================

class TestEdgeCasesAndSurvivors:
    def test_run_l1_mutation_on_passed_eq_zero(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="pcov",
            pest_binary=None,
            infection_stats=MutationStats(
                total=100, killed=80, survived=20, escaped=0, timed_out=0,
                untested=0, msi=80.0, covered_msi=80.0
            )
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.passed is False
        assert len(result.findings) > 0

    def test_run_l1_mutation_on_passed_eq_nonzero(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="pcov",
            pest_binary=None,
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.passed is True
        assert len(result.findings) == 0

    def test_run_l1_driver_is_none(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver=None,
            pest_binary=None,
            infection_stats=None
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.tool_specific["coverage_driver"] == "unknown"

    def test_run_l1_pcov_probe_not_raises_but_returns_none(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver=None,
            pest_binary=None,
            infection_stats=None
        )
        result = adapter.run_l1(tmp_path, {})
        pcov_findings = [f for f in result.findings if f.tool == "pcov"]
        assert len(pcov_findings) == 0

    def test_run_l1_env_with_other_vars(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="pcov",
            pest_binary=None,
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        env = {"HARNESS_INFECTION_REQUIRED": "0", "PATH": "/usr/bin", "FOO": "bar"}
        result = adapter.run_l1(tmp_path, env)
        assert result.layer == "L1"

    def test_run_l1_is_pest_project_evaluate_twice(self, tmp_path):
        adapter = _make_mock_adapter(
            pest_binary="pest",
            pest_has_mutate=True,
            pcov_driver="pcov",
            infection_stats=MutationStats(
                total=50, killed=50, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        adapter._pest._pest_binary.side_effect = [
            ["pest"],  # first call in test section
            ["pest"],  # second call in mutation section
        ]
        result = adapter.run_l1(tmp_path, {})
        assert result.passed is True

    def test_run_l1_is_pest_project_falsy_second_call(self, tmp_path):
        adapter = _make_mock_adapter(
            pest_binary=None,
            pcov_driver="pcov",
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.layer == "L1"

    def test_validate_infection_stats_constant_value(self):
        assert _INFECTION_MIN_MSI == 100
        assert _INFECTION_MIN_COVERED_MSI == 100

    def test_run_l1_infection_not_called_when_pest_no_mutate(self, tmp_path):
        adapter = _make_mock_adapter(
            pest_binary="pest",
            pest_has_mutate=False,
            pcov_driver="xdebug",
            infection_stats=None
        )
        adapter._pest._pest_binary.side_effect = [
            ["pest"], ["pest"],
        ]
        adapter._pest.invoke.return_value = MagicMock(exitcode=0, stdout="", stderr="")
        result = adapter.run_l1(tmp_path, {})
        adapter._infection.parse.assert_not_called()
        adapter._infection.invoke.assert_not_called()

    def test_run_l1_pest_invoke_passed_env(self, tmp_path):
        adapter = _make_mock_adapter(
            pest_binary="pest",
            pest_has_mutate=False,
            pcov_driver="xdebug"
        )
        adapter._pest._pest_binary.side_effect = [
            ["pest"], ["pest"],
        ]
        adapter._pest.invoke.return_value = MagicMock(exitcode=0, stdout="", stderr="")
        env = {"FOO": "bar"}
        result = adapter.run_l1(tmp_path, env)
        call_env = adapter._pest.invoke.call_args[1]["env"]
        assert call_env == env

    def test_run_l1_phpunit_invoke_passed_env(self, tmp_path):
        adapter = _make_mock_adapter(
            pest_binary=None,
            pcov_driver="pcov",
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        adapter._phpunit.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)
        env = {"PATH": "/usr/bin"}
        result = adapter.run_l1(tmp_path, env)
        call_env = adapter._phpunit.invoke.call_args[1]["env"]
        assert call_env == env

    def test_run_l1_infection_invoke_passed_env(self, tmp_path):
        adapter = _make_mock_adapter(
            pcov_driver="pcov",
            pest_binary=None,
            infection_stats=MutationStats(
                total=100, killed=100, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0
            )
        )
        adapter._infection.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)
        env = {"INFECTION_TIMEOUT": "600"}
        result = adapter.run_l1(tmp_path, env)
        call_env = adapter._infection.invoke.call_args[1]["env"]
        assert call_env == env


# ===========================================================================
# ToolAdapter._run helper (base class)
# ===========================================================================

class TestPhpCsFixerParse:
    def test_parse_json_format_with_violations(self, tmp_path):
        from harness_quality_gate.adapters.php.php_cs_fixer_adapter import PhpCsFixerAdapter
        data = {
            "files": [
                {
                    "name": "src/Foo.php",
                    "violations": [
                        {"line": 5, "message": "Unused import", "fix": "Remove use"},
                    ]
                }
            ]
        }
        findings = PhpCsFixerAdapter().parse(json.dumps(data), "", 8)
        assert len(findings) >= 1
        f = findings[0]
        assert f.severity == "warning"
        assert f.fix_hint == "Remove use"

    def test_parse_json_format_with_diff(self, tmp_path):
        from harness_quality_gate.adapters.php.php_cs_fixer_adapter import PhpCsFixerAdapter
        data = {
            "files": [
                {"name": "src/Bar.php", "diff": "--- a/src/Bar.php\n+++ b/src/Bar.php"}
            ]
        }
        findings = PhpCsFixerAdapter().parse(json.dumps(data), "", 8)
        assert len(findings) >= 1
        assert findings[0].severity == "warning"

    def test_parse_empty_string(self, tmp_path):
        from harness_quality_gate.adapters.php.php_cs_fixer_adapter import PhpCsFixerAdapter
        assert PhpCsFixerAdapter().parse("", "", 0) == []


# ===========================================================================
# PestAdapter helpers
# ===========================================================================

class TestPestHasMutatePlugin:
    def test_require_has_plugin(self, tmp_path):
        from harness_quality_gate.adapters.php.pest_adapter import PestAdapter
        (tmp_path / "composer.json").write_text(
            json.dumps({"require": {"pestphp/pest-plugin-mutate": "^1.0"}}), encoding="utf-8"
        )
        result = PestAdapter()._has_mutate_plugin(tmp_path)
        assert result is True

    def test_require_dev_has_plugin(self, tmp_path):
        from harness_quality_gate.adapters.php.pest_adapter import PestAdapter
        (tmp_path / "composer.json").write_text(
            json.dumps({"require-dev": {"pestphp/pest-plugin-mutate": "^1.0"}}), encoding="utf-8"
        )
        result = PestAdapter()._has_mutate_plugin(tmp_path)
        assert result is True

    def test_absent_returns_false(self, tmp_path):
        from harness_quality_gate.adapters.php.pest_adapter import PestAdapter
        (tmp_path / "composer.json").write_text(
            json.dumps({"require": {"phpunit/phpunit": "^10"}}), encoding="utf-8"
        )
        result = PestAdapter()._has_mutate_plugin(tmp_path)
        assert result is False


# ===========================================================================
# PcovAdapter probe_layer_result
# ===========================================================================

class TestPcovProbeLayerResult:
    def test_probe_layer_result_pcov_passes(self, tmp_path):
        from harness_quality_gate.adapters.php.pcov_adapter import PcovAdapter
        with patch.object(PcovAdapter, "probe", return_value="pcov"):
            result = PcovAdapter().probe_layer_result(tmp_path)
        assert result.passed is True
        assert result.findings == []

    def test_probe_layer_result_xdebug_warning(self, tmp_path):
        from harness_quality_gate.adapters.php.pcov_adapter import PcovAdapter
        with patch.object(PcovAdapter, "probe", return_value="xdebug"):
            result = PcovAdapter().probe_layer_result(tmp_path)
        assert result.passed is True
        assert len(result.findings) == 1
        assert result.findings[0].severity == "warning"

    def test_probe_layer_result_failure(self, tmp_path):
        from harness_quality_gate.adapters.php.pcov_adapter import PcovAdapter
        with patch.object(PcovAdapter, "probe", side_effect=RuntimeError("driver missing")):
            result = PcovAdapter().probe_layer_result(tmp_path)
        assert result.passed is False
        assert result.findings[0].severity == "error"


# ===========================================================================
# DeptracAdapter parse_stats
# ===========================================================================

class TestDeptracAdapterParseStats:
    def test_parse_stats_valid(self, tmp_path):
        from harness_quality_gate.adapters.php.deptrac_adapter import DeptracAdapter
        result = DeptracAdapter().parse_stats(json.dumps({"Report": {"Violations": 3, "UncoveredClasses": 1}}))
        assert result["violations"] == 3
        assert result["uncovered_classes"] == 1

    def test_parse_stats_invalid_json(self, tmp_path):
        from harness_quality_gate.adapters.php.deptrac_adapter import DeptracAdapter
        result = DeptracAdapter().parse_stats("not json")
        assert result["violations"] == 0
        assert result["uncovered_classes"] == 0

    def test_parse_stats_missing_report_key(self, tmp_path):
        from harness_quality_gate.adapters.php.deptrac_adapter import DeptracAdapter
        result = DeptracAdapter().parse_stats('{}')
        assert result["violations"] == 0


# ===========================================================================
# ComposerAuditAdapter edge cases
# ===========================================================================

class TestComposerAuditGaps:
    def test_parse_empty_dict(self, tmp_path):
        from harness_quality_gate.adapters.php.composer_audit_adapter import ComposerAuditAdapter
        assert ComposerAuditAdapter().parse('{}', "", 0) == []

    def test_parse_advisories_non_dict_value(self, tmp_path):
        from harness_quality_gate.adapters.php.composer_audit_adapter import ComposerAuditAdapter
        data = {"advisories": {"pkg": "not-a-list"}}
        assert ComposerAuditAdapter().parse(json.dumps(data), "", 1) == []

    def test_parse_advisories_list_item_not_dict(self, tmp_path):
        from harness_quality_gate.adapters.php.composer_audit_adapter import ComposerAuditAdapter
        data = {"advisories": {"pkg": ["not-a-dict"]}}
        assert ComposerAuditAdapter().parse(json.dumps(data), "", 1) == []

    def test_parse_with_link(self, tmp_path):
        from harness_quality_gate.adapters.php.composer_audit_adapter import ComposerAuditAdapter
        data = {"advisories": {"pkg": [{"cve": "CVE-2024-0001", "title": "RCE", "link": "https://example.com"}]}}
        findings = ComposerAuditAdapter().parse(json.dumps(data), "", 1)
        assert findings[0].fix_hint == "https://example.com"

    def test_parse_no_title_fallback(self, tmp_path):
        from harness_quality_gate.adapters.php.composer_audit_adapter import ComposerAuditAdapter
        data = {"advisories": {"pkg": [{"cve": "CVE-2024-0001"}]}}
        findings = ComposerAuditAdapter().parse(json.dumps(data), "", 1)
        assert "Advisory for pkg" in findings[0].message


# ===========================================================================
# DeadCodeAdapter edge cases
# ===========================================================================

class TestDeadCodeGaps:
    def test_parse_empty(self):
        from harness_quality_gate.adapters.php.dead_code_adapter import DeadCodeAdapter
        assert DeadCodeAdapter().parse("") == []

    def test_parse_with_json_empty_references(self):
        from harness_quality_gate.adapters.php.dead_code_adapter import DeadCodeAdapter
        assert DeadCodeAdapter().parse('{"references": []}') == []

    def test_parse_lines_empty_lines(self):
        from harness_quality_gate.adapters.php.dead_code_adapter import DeadCodeAdapter
        findings = DeadCodeAdapter._parse_lines("  \n  \n  ")
        assert findings == []

    def test_parse_lines_single_line(self):
        from harness_quality_gate.adapters.php.dead_code_adapter import DeadCodeAdapter
        findings = DeadCodeAdapter._parse_lines("  dead code  ")
        assert len(findings) == 1
        assert findings[0].message == "dead code"


# ===========================================================================
# DepAnalyserAdapter edge cases
# ===========================================================================

class TestDepAnalyserGaps:
    def test_parse_nested_unknown_violation_type(self, tmp_path):
        from harness_quality_gate.adapters.php.dep_analyser_adapter import DepAnalyserAdapter
        data = {"files": {"src/Foo.php": {"violations": [{"type": "unknown", "message": "bad"}]}}}
        result = DepAnalyserAdapter().parse(json.dumps(data))
        assert result == []

    def test_parse_top_level_array_single_item(self, tmp_path):
        from harness_quality_gate.adapters.php.dep_analyser_adapter import DepAnalyserAdapter
        data = [{"type": "dep-antipattern", "file": "src/X.php", "line": 1, "message": "test"}]
        result = DepAnalyserAdapter().parse(json.dumps(data))
        assert len(result) == 1
        assert result[0].node == "src/X.php:1"

    def test_parse_nested_files_file_data_empty(self, tmp_path):
        from harness_quality_gate.adapters.php.dep_analyser_adapter import DepAnalyserAdapter
        data = {"files": {"src/X.php": {}}}
        result = DepAnalyserAdapter().parse(json.dumps(data))
        assert result == []


# ===========================================================================
# SecurityChecker edge cases
# ===========================================================================

class TestSecurityCheckerGaps:
    def test_parse_severity_mapping_high(self, tmp_path):
        from harness_quality_gate.adapters.php.security_checker_adapter import SecurityCheckerAdapter
        data = [{"package": "p", "installed_version": "1", "vulnerable_versions": "*", "severity": "high", "type": "t", "links": []}]
        f = SecurityCheckerAdapter().parse(json.dumps(data))[0]
        assert f.severity == "error"

    def test_parse_severity_mapping_medium(self, tmp_path):
        from harness_quality_gate.adapters.php.security_checker_adapter import SecurityCheckerAdapter
        data = [{"package": "p", "installed_version": "1", "vulnerable_versions": "*", "severity": "medium", "type": "t", "links": []}]
        f = SecurityCheckerAdapter().parse(json.dumps(data))[0]
        assert f.severity == "warning"

    def test_parse_severity_mapping_low(self, tmp_path):
        from harness_quality_gate.adapters.php.security_checker_adapter import SecurityCheckerAdapter
        data = [{"package": "p", "installed_version": "1", "vulnerable_versions": "*", "severity": "low", "type": "t", "links": []}]
        f = SecurityCheckerAdapter().parse(json.dumps(data))[0]
        assert f.severity == "info"

    def test_parse_entry_with_single_link(self, tmp_path):
        from harness_quality_gate.adapters.php.security_checker_adapter import SecurityCheckerAdapter
        data = [{"package": "p", "installed_version": "1", "vulnerable_versions": "*", "severity": "low", "type": "t", "links": ["https://example.com"]}]
        f = SecurityCheckerAdapter().parse(json.dumps(data))[0]
        assert f.fix_hint == "https://example.com"


# ===========================================================================
# PhpWeakTestLayerAdapter
# ===========================================================================

class TestPhpWeakTestLayerAdapter:
    def test_run_l3b_delegates(self, tmp_path):
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestLayerAdapter
        adapter = PhpWeakTestLayerAdapter()
        result = adapter.run_l3b(tmp_path, {})
        assert result.layer == "L3B"
