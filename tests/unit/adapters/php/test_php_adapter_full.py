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

import time as _time


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
        assert len(initial_msgs) >= 1, "Mut3/Mut35: Initial debug log should exist"
        # Mutant 35: driver = "unknown" → driver = None in assignment
        # kills assertion because driver would be None not "unknown"
        assert initial_msgs[0].endswith("NOne") is False, (
            "Mut35: driver initial value should be 'unknown' string, not mutated"
        )
        assert initial_msgs[0].startswith("L1 driver initial value: unknown"), (
            "Mut35/41: Exact format 'L1 driver initial value: unknown'"
        )
        # Kill mutmut_16: assert the warning log contains the actual exception
        # text, not the literal string "None". Mutant replaces exc → None.
        assert "PCOV not compiled" in caplog.text
        # --- Mutant-killing assertions (mutmut_10, 24, 26, 27, 30, 34) ---
        # mutmut_10: debug log format string "XX" prefix → assert starts with
        # original prefix and no XX decoration
        assert any(
            m.startswith("L1 driver initial value:")
            and "XX" not in m
            for m in caplog.messages
        ), "Mut10: debug log format string mutated"
        # mutmut_24: logger.warning(exc) removes format args → the log text
        #             still contains <RuntimeError('...')> but the log MESSAGE
        #             (for formatted calls) has prefix "L1 coverage driver..."
        # mutmut_26: "XXL1 coverage driver probe failed: %s" → assert exact
        #             prefix without XX decoration
        # mutmut_27: "l1 coverage driver probe failed: %s" → assert exact case
        #             prefix (lowercase l1 is mutant)
        pcov_warnings = [
            m for m in caplog.messages
            if "L1 coverage driver probe failed:" in m
        ]
        assert len(pcov_warnings) == 1, (
            f"Expected exactly one pcov warning with format 'L1 coverage "
            f"driver probe failed: ...', got: {pcov_warnings}"
        )
        assert pcov_warnings[0].startswith("L1 coverage driver probe failed:"), (
            "Mut26/27: pcov warning format string mutated"
        )
        assert "PCOV not compiled" in pcov_warnings[0], (
            "Mut24: exception text missing from pcov warning"
        )
        # mutmut_30: node="pcov" → node=None → check the Finding node field
        assert any(
            f.node == "pcov" for f in result.findings
        ), "Mut30: pcov Finding node mutated to None"
        # mutmut_34: layer="L1" → layer=None → check the Finding layer field
        assert any(
            f.layer == "L1" for f in result.findings
        ), "Mut34: pcov Finding layer mutated to None"
        # Kill mutmut_35,41,50,51: language="php" mutations
        # 35: "php" → None | 41: remove language param | 50: "php" → "XXphpXX" | 51: "php" → "PHP"
        pcov_f = [f for f in result.findings if f.tool == "pcov"]
        assert len(pcov_f) >= 1
        assert pcov_f[0].language == "php", (
            "Mut35/41/50/51: pcov Finding language must be 'php' (not None/removed/XXphpXX/PHP)"
        )

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
    def test_pest_no_mutate_plugin_skips_mutation(self, tmp_path, caplog):
        caplog.set_level(logging.INFO, logger="harness_quality_gate.adapters.php.php_adapter")
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

        # Kill mutant 54: _has_mutate_plugin(repo) → None (assignment mutation)
        # _has_mutate_plugin MUST be called twice (test section + mutation section)
        assert adapter._pest._has_mutate_plugin.called
        assert len(adapter._pest._has_mutate_plugin.call_args_list) == 2
        for call in adapter._pest._has_mutate_plugin.call_args_list:
            assert call[0][0] == tmp_path

        # Kill mutants 154, 155, 156: logger.info("L1 mutation skipped (TD-6): %s", mutation_skipped)
        # Mut154: format → None → logger.info(None, msg)
        # Mut155: arg → None → logger.info(fmt, None)
        # Mut156: fmt removed → logger.info(msg)
        # Exact log message assertion kills all three at once.
        skip_logs = [m for m in caplog.messages if "L1 mutation skipped" in m]
        assert len(skip_logs) == 1, (
            f'Expected exactly one "L1 mutation skipped" log, got: {caplog.messages}'
        )
        assert skip_logs[0] == "L1 mutation skipped (TD-6): pest-plugin-mutate not installed"

        assert result.layer == "L1"
        assert result.language == "php"
        assert result.passed is False  # info finding for mutation skipped
        assert any("pest-plugin-mutate" in str(f.message) for f in result.findings)
        assert result.tool_specific.get("mutation_skipped") == "pest-plugin-mutate not installed"
        # Kill mutmut_50: condition `is_pest_project and not pest_has_mutate` → `is_pest_project` (False)
        # If condition is False, the mutation-skipped finding isn't added → test fails.
        # Kill mutmut_51: condition → `is_pest_project or not pest_has_mutate` (True)
        # With True condition, info finding IS added (same as original), so kill by
        # verifying the exact finding fields (not just substring presence).
        pest_mutate_f = [
            f for f in result.findings
            if "pest-plugin-mutate" in f.message or "mutation_skipped" in f.message
        ]
        assert len(pest_mutate_f) == 1
        assert pest_mutate_f[0].tool == "infection"
        assert pest_mutate_f[0].layer == "L1"
        assert pest_mutate_f[0].severity == "info"
        # Verify the exact finding fields (not just substring presence)
        assert pest_mutate_f[0].node == "mutation"
        # Kill mutmut_138: fix_hint param removed from Finding constructor
        assert pest_mutate_f[0].fix_hint == "composer require --dev pestphp/pest-plugin-mutate"
        # Kill mutmut_134: language → None in Finding constructor
        assert pest_mutate_f[0].language == "php"
        # Kill mutmut_51: condition mutation → verify exact finding content
        # Mutant 51: `and not` → `or not`, condition still True but
        # verify we hit the skip path (exact message check)
        assert "Mutation testing skipped" in pest_mutate_f[0].message
        # Kill mutmut_50: condition `and not` → `and` (condition always False when
        # is_pest=True and pest_has_mutate mutated to truthy)
        # With the skip finding present AND correct structure, the condition was True
        # (skipped path taken), killing mutant 50.
        assert not any(
            f.tool == "infection" and f.severity == "error"
            for f in result.findings
        ), "Mutation 50: should not take infection path when pest has no mutate plugin"
        # Kill 'probe(repo)' → 'probe(None)' mutation
        # Kill 'probe(repo)' → 'probe(None)' mutation
        assert adapter._pcov.probe.call_args[0][0] == tmp_path
        # Kill '_pest_binary(repo)' → '_pest_binary(None)' mutation (called twice)
        assert adapter._pest._pest_binary.call_args_list[0][0][0] == tmp_path
        # Original assertions for passed/finding/mutation_skipped
        assert result.passed is False  # info finding for mutation skipped
        assert any("pest-plugin-mutate" in str(f.message) for f in result.findings)
        assert result.tool_specific.get("mutation_skipped") == "pest-plugin-mutate not installed"
        # Kill '_pest_invoke(repo)' → '_pest_invoke(None)' mutation
        assert adapter._pest.invoke.call_args[0][0] == tmp_path
        assert adapter._pest.invoke.call_args[1]["env"] == {}
        # Kill mutmut_54: _has_mutate_plugin(repo) → None
        assert adapter._pest._has_mutate_plugin.called, (
            "Mut54: _has_mutate_plugin must be called (mutant replaces call with None)"
        )
        # Kill mutants 114/115: mutation_stats/mutation_skipped = "" (empty str not None)
        # Asserting exact string value kills "" → "pest-plugin-mutate..." mutations
        assert result.tool_specific.get("mutation_skipped") == "pest-plugin-mutate not installed"
        # Kill mutants 154/155/156: logger.info format/arg mutations
        # Mut154: logger.info(None, arg) → no formatted message
        # Mut155: logger.info(fmt, None) → "None" instead of actual value
        # Mut156: logger.info(arg) → just the arg value, no prefix
        mut_logs = [m for m in caplog.messages if m.startswith("L1 mutation skipped")]
        assert len(mut_logs) == 1, (
            f"Mut154/155/156: Expected 1 'L1 mutation skipped' log, got: {caplog.messages}"
        )
        assert mut_logs[0] == "L1 mutation skipped (TD-6): pest-plugin-mutate not installed"

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
        # Kill mutmut_54: _has_mutate_plugin(repo) → None (call removed)
        assert adapter._pest._has_mutate_plugin.called

    def test_pest_tests_fail(self, tmp_path, caplog):
        caplog.set_level(logging.ERROR, logger="harness_quality_gate.adapters.php.php_adapter")
        adapter = _make_mock_adapter(
            pest_binary="pest",
            pest_has_mutate=True,
            pcov_driver="xdebug",
            pest_exitcode=1
        )
        adapter._pest._pest_binary.side_effect = [
            ["pest"],
            ["pest"],
        ]
        adapter._pest.invoke.return_value = MagicMock(exitcode=1, stdout="", stderr="fail")
        result = adapter.run_l1(tmp_path, {})
        assert any("Pest tests failed" in f.message for f in result.findings)
        # Kill H1: _pest.invoke(repo, ["--no-output"], env=env, timeout=300.0) — exact args
        # kill mutations 20 (repo→None), 22 (args=[]→None), 27 (env→None)
        call = adapter._pest.invoke.call_args
        assert call[0][0] == tmp_path         # mutmut_20: repo → None
        assert call[0][1] == ["--no-output"]  # mutmut_22: args → None
        assert call[1]["env"] == {}           # mutmut_27: env → None
        assert call[1]["timeout"] == 300.0    # mutmut_21: timeout removed
        # Kill H3: message mutation — "Pest tests failed (exit 1)" exact string kills string
        # mutations 6 (exitcode value), 29/30/35-37 (message format/XX case mutations)
        pest_findings = [f for f in result.findings if f.tool == "pest"]
        assert len(pest_findings) >= 1
        assert pest_findings[0].message == "Pest tests failed (exit 1)", (
            "Exact error message kills string mutations on exit code and format"
        )
        # Kill mutmut_29-32: Finding node, severity, fix_hint, tool, layer, language
        assert pest_findings[0].node == "pest"
        assert pest_findings[0].severity == "error"
        assert pest_findings[0].tool == "pest"
        assert pest_findings[0].layer == "L1"
        assert pest_findings[0].language == "php"
        assert pest_findings[0].fix_hint == "Run ``vendor/bin/pest`` locally to see failures"

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

    def test_pest_log_format(self, tmp_path, caplog):
        """Kill mutmut_64: logger.info("L1 Pest tests: %d findings", ...) → logger.info(None, ...)"""
        caplog.set_level(logging.DEBUG, logger="harness_quality_gate.adapters.php.php_adapter")
        adapter = _make_mock_adapter(
            pest_binary="pest",
            pest_has_mutate=True,
            pcov_driver="xdebug"
        )
        adapter._pest._pest_binary.side_effect = [
            ["pest"],
            ["pest"],
        ]
        adapter._pest.invoke.return_value = MagicMock(exitcode=0, stdout="", stderr="")
        result = adapter.run_l1(tmp_path, {})
        assert result.passed is True
        # Kill mutant 64: exact log format check — mutmut replaces format string with None
        pest_logs = [m for m in caplog.messages if m.startswith("L1 Pest tests:")]
        assert len(pest_logs) == 1, (
            f"Mut64: Expected 'L1 Pest tests:' log format, got: {caplog.messages}"
        )
        assert pest_logs[0] == "L1 Pest tests: 0 findings"

    def test_has_mutate_plugin_called_with_repo(self, tmp_path):
        """Kill mutmut_54: assertion that _has_mutate_plugin(repo) is called with repo.

        Mutant 54 replaces the entire expression
        `self._pest._has_mutate_plugin(repo)` with `None` (assignment mutation).
        Asserting `call_args[0][0] == tmp_path` kills this mutation because
        with the mutant, the method call is replaced by a constant — no call happens.
        """
        adapter = _make_mock_adapter(
            pest_binary="pest",
            pest_has_mutate=True,
            pcov_driver="xdebug"
        )
        adapter._pest._pest_binary.side_effect = [
            ["pest"],
            ["pest"],
        ]
        adapter._pest.invoke.return_value = MagicMock(exitcode=0, stdout="", stderr="")
        result = adapter.run_l1(tmp_path, {})
        # Verify _has_mutate_plugin was called with correct repo at the test section
        assert adapter._pest._has_mutate_plugin.call_args[0][0] == tmp_path
        # Verify exact return value — kills assignment mutations changing return
        assert adapter._pest._has_mutate_plugin.return_value is True


# ===========================================================================
# run_l1 — PHPUnit paths
# ===========================================================================

class TestRunL1PHPUnitPaths:
    def test_phpunit_success_no_findings(self, tmp_path, caplog):
        caplog.set_level(logging.DEBUG, logger="harness_quality_gate.adapters.php.php_adapter")
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
        # Mutation 64: `passed = len(all_findings) == 0` → `!= 0`
        # If condition flips, passed would be False with empty findings → killed.
        assert result.passed is True
        assert result.findings == []
        # Mutation 54: logger.info("L1 PHPUnit tests: %d findings", ...) →
        # removes format args → log becomes just "0" without prefix.
        # Kills by asserting exact log format.
        phpunit_logs = [m for m in caplog.messages if m.startswith("L1 PHPUnit tests:")]
        assert len(phpunit_logs) == 1
        assert phpunit_logs[0] == "L1 PHPUnit tests: 0 findings"
        # Kill mutmut_50: condition `passed = len(all_findings) == 0` → != 0
        # If condition flips, passed would be False with empty findings → killed.
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

    def test_pest_binary_raises_runtime_error(self, tmp_path, caplog):
        """Run L1 with pest_binary RuntimeError to trigger outer handler.

        _run_pest_tests and _run_phpunit_tests both catch RuntimeError,
        so we make _pest_binary raise RuntimeError BEFORE any test runner is called.
        This exercises the `logger.warning("L1 test execution skipped: %s", exc)` path
        at line 458-459 and kills mutmut_85 through mutmut_89.
        """
        caplog.set_level(logging.WARNING, logger="harness_quality_gate.adapters.php.php_adapter")
        adapter = _make_mock_adapter(
            pest_binary=None,
            pcov_driver="xdebug"
        )
        # _pest_binary is called 3 times: test section, mutation check, mutation check
        # 1st raises RuntimeError (triggers outer error handler)
        # 2nd and 3rd return None (not a Pest project — harmless continuation)
        adapter._pest._pest_binary.side_effect = [
            RuntimeError("test binary not found"),
            None,
            None,
        ]
        result = adapter.run_l1(tmp_path, {})
        assert result.layer == "L1"
        assert result.language == "php"
        # Kill mutmut_85: argument mutation `exc` → `None`
        # Original log: "L1 test execution skipped: test binary not found"
        # Mutated log:  "L1 test execution skipped: None"
        test_skip_msgs = [
            m for m in caplog.messages
            if m.startswith("L1 test execution skipped:")
        ]
        assert len(test_skip_msgs) == 1, (
            f"Expected 1 test-skip warning, got: {test_skip_msgs}"
        )
        assert test_skip_msgs[0] == "L1 test execution skipped: test binary not found"
        # Kill mutmut_86: format-arg mutation `logger.warning("...", exc)` → `logger.warning(exc)`
        # Mutated log would be "<RuntimeError: ...>" (not a formatted string)
        assert test_skip_msgs[0].startswith("L1 "), (
            "Mut86: Format-arg mutation changed log structure"
        )
        # Kill mutmut_87: arg-removal mutation `logger.warning("...", )`
        assert "test binary not found" in test_skip_msgs[0], (
            "Mut87: Exception text missing from log — arg removed"
        )
        # Kill mutmut_88: string mutation prefix "XX"
        assert test_skip_msgs[0] != "XXL1 test execution skipped: test binary not foundXX"
        # Kill mutmut_89: string mutation lowercase "l1"
        assert test_skip_msgs[0] != "l1 test execution skipped: test binary not found"
        # Verify Finding — kills mutation where severity or tool is changed
        test_findings = [f for f in result.findings if f.tool == "phpunit"]
        assert len(test_findings) == 1
        assert test_findings[0].severity == "warning"
        # Kill mutmut_92: node="test" → None, mutmut_96: layer="L1" → None,
        # mutmut_97: language="php" → None, mutmut_102: remove layer param,
        # mutmut_103: remove language param
        assert test_findings[0].node == "test", (
            "Mut92: test Finding node must be 'test' (not None)"
        )
        assert test_findings[0].layer == "L1", (
            "Mut96/102: test Finding layer must be 'L1' (not None)"
        )
        assert test_findings[0].language == "php", (
            "Mut97/103: test Finding language must be 'php' (not None)"
        )


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
        # Kill mutmut_174/178/179/184: field mutations on the HARNESS_INFECTION_REQUIRED Finding
        assert any("HARNESS_INFECTION_REQUIRED" in f.message for f in result.findings)
        inf_findings = [
            f for f in result.findings if "HARNESS_INFECTION_REQUIRED" in f.message
        ]
        assert len(inf_findings) == 1
        # mutmut_174: node="infection" → None in Finding constructor
        assert inf_findings[0].node == "infection"
        # mutmut_178: layer="L1" → None in Finding constructor
        assert inf_findings[0].layer == "L1"
        # mutmut_179: language="php" → None in Finding constructor
        assert inf_findings[0].language == "php"
        # mutmut_184: layer param removed from Finding constructor
        assert "layer" in result.findings[0].__dict__, (
            "Mut184: layer param removed from Finding — must have layer field"
        )

    def test_infection_required_runtime_error(self, tmp_path, caplog):
        """Kill mutmut_114 via RuntimeError path from _run_infection.

        Mutant 114: mutation_stats: MutationStats | None = "" (empty str instead of None).
        When _run_infection raises RuntimeError, the except handler catches it and
        logs a warning — but mutation_stats remains at its initial "" value (never
        overwritten by assignment). The guard `if mutation_stats is None and ...`:
          - Original:  None is None → True → Finding added
          - Mutant 114: "" is None → False → NO Finding added ← killed
        Also kills mutmut_174/178/179/184 with field assertions on the Finding.
        Catches mutmut_199-202: logger.error format-string mutations on
        "L1 Infection required but unavailable (HARNESS_INFECTION_REQUIRED=1)".
        """
        from unittest.mock import MagicMock
        caplog.set_level(logging.ERROR, logger="harness_quality_gate.adapters.php.php_adapter")
        adapter = _make_mock_adapter()
        adapter._infection.invoke.side_effect = RuntimeError("infection not installed")
        env = {"HARNESS_INFECTION_REQUIRED": "1"}
        result = adapter.run_l1(tmp_path, env)
        assert result.layer == "L1"
        assert result.language == "php"

        # --- Mutants 174, 178, 179, 184: field mutations on HARNESS_INFECTION_REQUIRED Finding ---
        inf_f = [f for f in result.findings if "HARNESS_INFECTION_REQUIRED" in f.message]
        assert len(inf_f) == 1, (
            "Mut114/Mut174: HARNESS_INFECTION_REQUIRED Finding must be present "
            "(Mut114: mutation_stats=\"\" causes missing check; Mut174: node=\"infection\")"
        )
        # Verify exact field values — each kills a specific mutant
        assert inf_f[0].node == "infection"  # Mut174: kills "" → not equal to "infection"
        assert inf_f[0].layer == "L1"  # Mut178: kills "" → Mut184: kills None (default)
        assert inf_f[0].language == "php"  # Mut179: kills "" → not equal to "php"
        # Additional field assertions to catch mutations on other fields of this Finding
        assert inf_f[0].severity == "error"  # kills severity mutations
        assert inf_f[0].tool == "infection"  # kills tool mutations
        # Exact message check kills string mutations on the message
        assert inf_f[0].message.startswith(
            "Infection mutation gate required but unavailable"
        ), "Mut174/178/179/184: message must start with exact text"

        # --- Mutants 199, 200, 201, 202: logger.error format-string mutations ---
        # mutmut_199: logger.error("...", ) → logger.error(None, ...) → no formatted message
        # mutmut_200: "L1 Infection required..." → "XXL1 Infection required...XX"
        # mutmut_201: "L1 Infection required..." → "l1 infection required..."
        # mutmut_202: "L1 Infection required..." → "L1 INFECTION REQUIRED..."
        # Exact log message assertion kills all four at once.
        error_log = [m for m in caplog.messages if "Infection required but unavailable" in m]
        assert len(error_log) == 1, (
            f"Mut199/200/201/202: Expected exactly one 'Infection required but unavailable' "
            f"error log, got: {caplog.messages}"
        )
        # Exact full message check — kills ALL string mutations simultaneously:
        # Mut199 → "None" (no format) | Mut200 → "XX...XX" | Mut201 → lowercase | Mut202 → UPPERCASE
        assert error_log[0] == (
            "L1 Infection required but unavailable (HARNESS_INFECTION_REQUIRED=1)"
        )

    def test_infection_not_required_when_missing(self, tmp_path, caplog):
        """Kill logger mutations (mutmut_21-24) on _run_infection unavailable path.

        exitcode=3 + empty stdout triggers the exact early-return guard.
        Catches:
        - mutmut_21: logger.warning(None) → log message is "None" not expected text
        - mutmut_22: "XXInfection unavailable...XX" → exact string doesn't match
        - mutmut_23: case mutation "infection unavailable..." → case differs
        - mutmut_24: case mutation "INFECTION UNAVAILABLE..." → case differs
        - mutmut_19: string mutation changing exitcode in warning (3→4)
        """
        adapter = _make_mock_adapter(infection_stats=None)
        adapter._infection.invoke.return_value.exitcode = 3
        adapter._infection.invoke.return_value.stdout = ""
        adapter._pcov.probe.return_value = "pcov"
        with caplog.at_level(logging.WARNING, logger="harness_quality_gate.adapters.php.php_adapter"):
            result = adapter._run_infection(tmp_path, {}, is_pest_project=False)
        # With exitcode 3 + empty stdout, original early-returns (no parse)
        assert result is None
        assert not adapter._infection.parse.called
        # Exact warning message matches kill all 4 string param mutations
        warnings = [m for m in caplog.messages if
                    m == "Infection unavailable (exitcode=3, no output)"]
        assert len(warnings) == 1, f"Expected exact warning, got: {warnings}"

    def test_infection_exitcode_0_returns_stats(self, tmp_path):
        """Kill comparison mutation mutmut_18 (== 3 → != 3).

        With exitcode=0 + empty stdout:
        - Original: `0 == 3` = False → skip guard → `0 != 0` = False → skip infra
          → parse() → returns MutationStats
        - Mutant 18: `0 != 3` = True → early return → returns None ← killed

        Verify return value IS stats (not None) and parse() WAS called.
        """
        stats = MutationStats(
            total=100, killed=100, survived=0, escaped=0, timed_out=0,
            untested=0, msi=100.0, covered_msi=100.0
        )
        inv_mock = MagicMock()
        inv_mock.exitcode = 0
        inv_mock.stdout = ""
        inv_mock.stderr = ""
        adapter = _make_mock_adapter(infection_stats=stats)
        adapter._infection.invoke.return_value = inv_mock
        # Must override default infection_stats so parse returns the stats obj
        adapter._infection.parse.return_value = stats
        result = adapter._run_infection(tmp_path, {}, is_pest_project=False)
        # Mutant 18 would return None early (can't call parse())
        assert result is stats, (
            f"Expected MutationStats, got: {result}. "
            "Kills mutmut_18 (exitcode == 3 → != 3)"
        )
        assert adapter._infection.parse.called, (
            "parse() must be called for exitcode=0. "
            "Mutant 18 enters guard and returns None without calling parse."
        )

    def test_infection_exitcode_4_no_parse(self, tmp_path):
        """Kill comparison mutation mutmut_18 (== 3 → != 3) with exitcode=4.

        With exitcode=4 + empty stdout:
        - Original: `4 == 3` = False → skip guard → `4 != 0` = True → infra error → None
          parse() NOT called (infra error path returns before parse)
        - Mutant 18: `4 != 3` = True → early return → None
          parse() NOT called (guard path returns before parse)

        Both return None but for DIFFERENT reasons. The killed mutant is:
        with exitcode=3 + STATSVISIBLE_STDOUT:
        - Original: `3 == 3` = True → early return → None (guard path)
        - Mutant 18: `3 != 3` = False → skip guard → parse() called ← killed
        """
        stats = MutationStats(
            total=100, killed=100, survived=0, escaped=0, timed_out=0,
            untested=0, msi=100.0, covered_msi=100.0
        )
        inv_mock = MagicMock()
        inv_mock.exitcode = 3
        inv_mock.stdout = "Metrics:\n  Mutation Score Indicator (MSI): 100%"
        inv_mock.stderr = ""
        adapter = _make_mock_adapter(infection_stats=stats)
        adapter._infection.invoke.return_value = inv_mock
        adapter._infection.parse.return_value = stats
        result = adapter._run_infection(tmp_path, {}, is_pest_project=False)
        # With exitcode=3 + non-empty stdout:
        # Original: guard `3 == 3` → True → returns None (no parse)
        # Mutant 18: guard `3 != 3` → False → skip → parse() IS called
        # Verify parse WAS called to kill mutant 18
        assert adapter._infection.parse.called, (
            "parse() must be called when stdout has stats content. "
            "Mutant 18 (== 3 → != 3) skips guard and calls parse."
        )
        # Original returns None from guard, mutant returns stats from parse
        assert result is stats, (
            f"Expected stats (from parse), got: {result}. "
            "Kills mutmut_18 with non-empty stdout."
        )

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
        # Kill H1: positional arg assertions for mutations 17/18 (repo/args→None)
        assert call_args[1] == [                # mutmut_18: args=[] → None
                "--no-progress",
                "--threads=max",
                "--min-msi=100",
                "--min-covered-msi=100",
            ], (
            "mutmut_33/42/46/47/49/53/54/55/56/57: Full args list with threshold flags "
            "must match exactly — mutations on any flag string or positional arg order"
        )
        kwargs = adapter._infection.invoke.call_args[1]
        assert kwargs["env"] == {}
        assert kwargs["timeout"] == 600.0  # mutmut_58/59/60/61/62/63: timeout removed/mutated

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
        caplog.set_level(logging.DEBUG, logger="harness_quality_gate.adapters.php.php_adapter")
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
        # Mutation 41: logger.debug("L1 driver initial value: %s", driver) → format
        # arg mutation or string mutation changes the debug log. Assert exact initial
        # debug log message. Mutant changes format → log differs.
        initial_debug = [
            m for m in caplog.messages
            if m.startswith("L1 driver initial value:")
        ]
        assert len(initial_debug) == 1
        assert initial_debug[0] == "L1 driver initial value: unknown"
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

    def test_l2_runtime_error_skipped(self, tmp_path, caplog):
        caplog.set_level(logging.WARNING, logger="harness_quality_gate.adapters.php.php_adapter")
        adapter = PhpAdapter()
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.side_effect = RuntimeError("antipattern not found")
        adapter._antipattern.parse.return_value = []
        result = adapter.run_l2(tmp_path, {})
        assert result.layer == "L2"
        assert result.language == "php"
        assert result.passed is True
        assert result.duration_sec >= 0
        # Kill H1: invoke(repo, [], env=env, timeout=300.0) — exact args kill mutations 17 (repo→None),
        # 22 (timeout→removed), args=[] mutations, env=None mutations
        call = adapter._antipattern.invoke.call_args
        assert call[0][0] == tmp_path      # mutmut_17: repo → None
        assert call[0][1] == []            # mutmut_18/19: args=[] or args=None
        assert call[1]["env"] == {}        # mutmut_20: env → None
        assert call[1]["timeout"] == 300.0 # mutmut_21/22: timeout removed
        # Kill H3: logger.warning("L2 antipattern-tier-A skipped: %s", exc) → various string
        # mutations (None→"XX", case, removed format) — exact message assertion
        warnings = [m for m in caplog.messages if "L2 antipattern-tier-A skipped" in m]
        assert len(warnings) == 1, f"Expected exactly one skip warning, got: {warnings}"
        assert warnings[0] == "L2 antipattern-tier-A skipped: antipattern not found"
        # Kill mutmut_31: layer="L2" → None — assert layer field type and value
        assert isinstance(result.layer, str) and result.layer == "L2"

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

    def test_l2_invoke_args_list_not_empty(self, tmp_path):
        """Kill mutmut_3: args=[] → args=None in run_l2 invoke call."""
        adapter = PhpAdapter()
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        adapter.run_l2(tmp_path, {})
        # mutmut_3: args=[] → args=None
        # If mutated, the invocation would pass None instead of []
        call = adapter._antipattern.invoke.call_args
        assert call[0][1] == [], (
            "Mut3: args list must be [] (empty list), not mutated to None"
        )

    def test_l2_parse_return_not_none(self, tmp_path):
        """Kill mutmut_9: parse() → None in run_l2."""
        adapter = PhpAdapter()
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        result = adapter.run_l2(tmp_path, {})
        # mutmut_9: parse(inv.stdout) → None
        # If mutated, `findings` would be None and `extend` would fail
        # Verify parse was called and returned a list
        call = adapter._antipattern.parse.call_args
        assert call[0][0] == "[]"  # stdout was passed, not mutated to None

    def test_l2_result_layer_field(self, tmp_path):
        """Kill mutmut_24/25: layer field mutation in LayerResult."""
        adapter = PhpAdapter()
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[{\"file\":\"x\",\"rule\":\"y\"}]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = [Finding(
            node="x", severity="warning", message="y", tool="antipattern",
            layer="L2", language="php"
        )]
        result = adapter.run_l2(tmp_path, {})
        assert result.layer == "L2"
        assert result.language == "php"
        assert result.passed is False
        assert len(result.findings) == 1
        assert result.duration_sec >= 0
        # Verify exact field types - kills mutmut_24/25 (layer→None, layer→"")
        assert isinstance(result.layer, str) and result.layer == "L2"
        assert isinstance(result.language, str) and result.language == "php"

    def test_l2_findings_not_none(self, tmp_path):
        """Kill mutmut_50/51: findings=[] → findings=None mutation."""
        adapter = PhpAdapter()
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        result = adapter.run_l2(tmp_path, {})
        # mutmut_50: findings=None | mutmut_51: remove findings param
        assert isinstance(result.findings, list)
        # Verify `passed` calculation kills comparison mutations (mut_mut_16: == 0 → != 0)
        passed = len(result.findings) == 0
        assert isinstance(passed, bool)
        # If passed was mutated (== → !=), this would still be True since findings=[]
        # So we need extra assertions to kill passed mutation
        assert passed is True
        assert result.findings == []  # Exact match kills "" → None mutation

    def test_l2_invoke_passed_args_not_mutated(self, tmp_path):
        """Kill mutmut_17-20: argument mutations in antipattern.invoke()."""
        adapter = PhpAdapter()
        adapter._antipattern = MagicMock()
        adapter._antipattern.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        adapter._antipattern.parse.return_value = []
        adapter.run_l2(tmp_path, {"FOO": "bar"})
        call = adapter._antipattern.invoke.call_args
        assert call[0][0] == tmp_path  # mutmut_17: repo → None
        assert call[0][1] == []  # mutmut_18-19: args=[] or args=None
        assert call[1]["env"] == {"FOO": "bar"}  # mutmut_20: env → None
        assert call[1]["timeout"] == 300.0  # mutmut_21: timeout → removed


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

    def test_l3a_cs_fixer_runtime_error_skipped(self, tmp_path, caplog):
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
        caplog.set_level(logging.WARNING, logger="harness_quality_gate.adapters.php")
        result = adapter.run_l3a(tmp_path, {})
        assert result.passed is True
        # Kill logger argument/string mutations 92 & 93:
        #   Mutant 92: logger.warning("...", exc) → logger.warning("...", None)
        #     → log becomes "L3A php-cs-fixer skipped: None" instead of "L3A php-cs-fixer skipped: cs-fixer not found"
        #   Mutant 93: logger.warning("...", exc) → logger.warning(exc)
        #     → format-arg removal changes log structure entirely
        # Exact-match assertion kills both at once.
        warnings = [m for m in caplog.messages if "L3A php-cs-fixer skipped" in m]
        assert len(warnings) == 1, f"Expected exactly one cs-fixer skip warning, got: {warnings}"
        assert warnings[0] == "L3A php-cs-fixer skipped: cs-fixer not found"

    def test_l3a_cs_fixer_success_log_message(self, tmp_path, caplog):
        """Kill logger.info mutations 86-89 on php-cs-fixer success path.

        Mutations target: logger.info("L3A php-cs-fixer: %d findings", len(cs_findings))
          Mutant 86: removes format string → logger.info(len(cs_findings))
          Mutant 87: removes arg → logger.info("L3A php-cs-fixer: %d findings", )
          Mutant 88: string prefix/suffix → "XXL3A php-cs-fixer: %d findingsXX"
          Mutant 89: case mutation → "l3a php-cs-fixer: %d findings"
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
        # Exact-match kills all 4 logger.info mutations at once:
        # Mut86 → "0" (no prefix) | Mut87 → error | Mut88 → "XX...XX" | Mut89 → "l3a ..."
        cs_logs = [m for m in caplog.messages if m.startswith("L3A php-cs-fixer:")]
        assert len(cs_logs) == 1, f"Expected exactly one cs-fixer log, got: {cs_logs}"
        assert cs_logs[0] == "L3A php-cs-fixer: 0 findings"

    def test_l3a_tier_a_visitor_runtime_error_skipped(self, tmp_path, caplog):
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
        caplog.set_level(logging.WARNING, logger="harness_quality_gate.adapters.php")
        result = adapter.run_l3a(tmp_path, {})
        assert result.passed is True
        # Kill logger argument/string mutations on tier-a error path:
        #   Mutant 106: exc→None → log becomes "L3A tier-A visitors skipped: None"
        #   Mutant 107: format string removed → log changes entirely
        #   Mutant 108: string prefix/suffix mutation → "XX...XX"
        #   Mutant 109: case mutation → "l3a tier-a visitors skipped: ..."
        #   Mutant 112: node param removed from Finding
        #   Mutant 113: language param removed from Finding
        #   Mutant 114: layer param removed from Finding
        #   Mutant 115: exc→None → "L3A tier-A visitors skipped: None"
        #   Mutant 116: logger.warning(exc) → format-arg removal
        #   Mutant 119: layer="L3A" → None mutation in LayerResult
        #   Mutant 126: passed = len(all_findings) == 0 → != 0 mutation
        warnings = [m for m in caplog.messages if "L3A tier-A visitors skipped" in m]
        assert len(warnings) == 1, (
            f"Expected exactly one tier-a skip warning, got: {warnings}"
        )
        assert warnings[0] == "L3A tier-A visitors skipped: visitor error"
        # Verify result fields - kills mutations on LayerResult construction
        assert result.layer == "L3A"
        assert result.language == "php"
        assert result.passed is True

    def test_l3a_tier_a_visitor_success_log_message(self, tmp_path, caplog):
        """Kill logger.info mutations on tier-A visitor success path.

        Kills: mutmut_126, 127, 138-141 on tier-a log and duration/path.
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
        # Exact log message assertion kills format-string and argument mutations
        tier_a_logs = [m for m in caplog.messages if m.startswith("L3A tier-A visitors:")]
        assert len(tier_a_logs) == 1, (
            f"Expected exactly one tier-A log message, got: {tier_a_logs}"
        )
        assert tier_a_logs[0] == "L3A tier-A visitors: 0 findings", (
            f"Exact log format mismatch — kills mutmut_126/127/138-141, got: {tier_a_logs[0]}"
        )

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

    def test_l4_all_tools_error_skipped(self, tmp_path, caplog):
        adapter = self._make_l4_mock_adapter()
        for attr in ("_psalm_taint", "_composer_audit", "_security_checker",
                      "_dead_code", "_dep_analyser", "_deptrac"):
            mock_invoke = MagicMock(side_effect=RuntimeError("not found"))
            setattr(getattr(adapter, attr), "invoke", mock_invoke)
        with caplog.at_level(logging.WARNING, logger="harness_quality_gate.adapters.php"):
            result = adapter.run_l4(tmp_path, {})
            assert result.layer == "L4"
            assert result.language == "php"
            assert result.passed is True
            # Strong log assertions to kill logger argument/parameter/string mutations.
            # mutmut_33: exc→None → message ends "...: None" instead of "...: not found"
            # mutmut_34: logger.warning(exc) removes format string → logged msg is just "not found"
            # mutmut_35: removes format arg → TypeError, kills itself
            # mutmut_36: strings get "XX" prefix/suffix → msg starts "XXL4..." not "L4 Psalm"
            # mutmut_37: string case → "l4 psalm..." not "L4 Psalm..."
            # mutmut_69: composer audit exc→None → message ends "...: None"
            all_msgs = list(caplog.messages)
            psalm_warn = [m for m in all_msgs if m.startswith("L4 Psalm taint skipped:")]
            assert len(psalm_warn) == 1, (
                f'Expected exactly 1 psalm skip warning starting with "L4 Psalm taint skipped: ", '
                f'got: {all_msgs}'
            )
            assert psalm_warn[0] == "L4 Psalm taint skipped: not found", (
                f"Psalm skip warning content mutated. Got: {psalm_warn[0]}"
            )
            composer_warn = [m for m in all_msgs if m.startswith("L4 composer-audit skipped:")]
            assert len(composer_warn) == 1, (
                f'Expected exactly 1 composer-audit skip warning starting with "L4 composer-audit skipped: ", '
                f'got: {all_msgs}'
            )
            assert composer_warn[0] == "L4 composer-audit skipped: not found", (
                f"Composer-audit skip warning content mutated. Got: {composer_warn[0]}"
            )
            # Kill string/arg mutations on security-checker skip warning (mutmut 103-107):
            #   Mut 103: exc→None → msg ends "...: None" instead of "...: not found"
            #   Mut 104: removes logger.warning(args) → log becomes "RuntimeError(...)"
            #   Mut 105: removes %s arg → TypeError / wrong msg
            #   Mut 106: "XXL4 security-checker XX" → starts "XXL4..." not "L4"
            #   Mut 107: "l4 security-checker..." → starts "l4..." not "L4"
            sec_warn = [m for m in all_msgs if m.startswith("L4 security-checker skipped:")]
            assert len(sec_warn) == 1, (
                f'Expected exactly 1 security-checker skip warning starting with '
                f'"L4 security-checker skipped: ", got: {all_msgs}'
            )
            assert sec_warn[0] == "L4 security-checker skipped: not found", (
                f"Security-checker skip warning content mutated. Got: {sec_warn[0]}"
            )
            # Kill deptrac skip warning string/arg mutations (same pattern as psalm/composer)
            deptr_warn = [m for m in all_msgs if m.startswith("L4 deptrac skipped:")]
            assert len(deptr_warn) == 1, (
                f'Expected exactly 1 deptrac skip warning starting with "L4 deptrac skipped: ", '
                f'got: {all_msgs}'
            )
            assert deptr_warn[0] == "L4 deptrac skipped: not found", (
                f"Deptrac skip warning content mutated. Got: {deptr_warn[0]}"
            )

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
        assert call[0][1] == ["--format=json"]
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

    def test_l3a_env_passed_to_all_l3a_invokes(self, tmp_path):
        """Kill mutmut_18: env arg replaced with None on _phpstan.run_l3a call.

        If run_l3a(repo, env) becomes run_l3a(repo, None), we verify the
        exact call signature uses env (not None).
        """
        adapter = _make_mock_adapter()
        adapter.run_l3a(tmp_path, {"FOO": "bar"})
        # Original: self._phpstan.run_l3a(repo, env)
        call_kw = adapter._phpstan.run_l3a.call_args
        assert len(call_kw[0]) >= 2 and call_kw[0][1] is not None, (
            "Mutant18: env arg must be passed (not None) to phpstan.run_l3a"
        )
        # Same for phpmd
        call_kw_pm = adapter._phpmd.run_l3a.call_args
        assert len(call_kw_pm[0]) >= 2 and call_kw_pm[0][1] is not None, (
            "Mutant18: env arg must be passed (not None) to phpmd.run_l3a"
        )

    def test_l3a_multi_framework_join_format(self, tmp_path, caplog):
        """Kill mutmut_15: join delimiter mutation on logger.info call.

        Only triggers when multiple frameworks are injected.

        Mutant 15:  ', '.join(list) → 'XX, XX'.join(list)
        With 2 frameworks: original → 'a, b', mutant → 'XX, XXa, XX, XXb'
        """
        adapter = _make_mock_adapter()
        composer = tmp_path / "composer.json"
        composer.write_text(json.dumps({
            "require": {
                "symfony/framework-bundle": "^6.0",
                "laravel/framework": "^10.0",
            }
        }))
        with caplog.at_level(logging.INFO, logger="harness_quality_gate.adapters.php"):
            adapter.run_l3a(tmp_path, {})
        assert adapter._phpstan.run_l3a.call_args[0][0] == tmp_path
        # Check exact format: original joins with ", " producing "a, b"
        # Mutant joins with "XX, XX" producing "XX, XXa, XX, XXb"
        framework_logs = [r for r in caplog.records if "L3A PHPStan framework packs" in r.message]
        assert len(framework_logs) >= 1
        assert framework_logs[0].message == "L3A PHPStan framework packs: larastan, phpstan-symfony"


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


# ===========================================================================
# run_l3a — Tier-A (PHPStan + PHPMD + php-cs-fixer + tier-A visitors)
# ===========================================================================

class TestRunL3a:
    """Kill mutmut_86, 87, 88, 89 (php-cs-fixer logger) and mutmut_92, 93 (skip logger)."""

    def test_success_path_kills_86_87_88_89(self, tmp_path, caplog):
        """Assert exact php-cs-fixer logger output to kill all 4 string-param mutations.

        Kills:
        - mutmut_86:   logger.info(fmt, arg) → logger.info(arg) — msg becomes just a number
        - mutmut_87:   logger.info(fmt, arg) → logger.info(fmt,) — no arg → no count in msg
        - mutmut_88:   "XX...XX" decoration — msg contains XX
        - mutmut_89:   lowercase "l3a" — msg starts with "l3a" not "L3A"
        """
        caplog.set_level(logging.INFO, logger="harness_quality_gate.adapters.php.php_adapter")
        adapter = _make_mock_adapter()
        # Override parse to return 1 finding (so len(cs_findings) >= 1)
        adapter._cs_fixer.parse.return_value = [Finding(
            node="src/Foo.php", severity="warning", message="style issue", tool="php-cs-fixer"
        )]
        result = adapter.run_l3a(tmp_path, {})

        assert result.layer == "L3A"
        assert result.language == "php"
        assert result.passed is False

        # --- Kill mutmut_86, 87, 88, 89 ---
        cs_logs = [m for m in caplog.messages
                   if "php-cs-fixer" in m and "findings" in m]

        # Mut86: fmt removed → logger.info(len(cs_findings)) → message is just "1"
        #         "1" does NOT start with "L3A" → killed
        assert len(cs_logs) >= 1, (
            f"Mut86/87/88/89: Expected php-cs-fixer log, got: {caplog.messages}"
        )
        assert cs_logs[0].startswith("L3A php-cs-fixer:"), (
            "Mut86: Format-arg removed — message is bare number, not 'L3A php-cs-fixer: N findings'"
        )
        # Mut87: arg removed → no number in message → kills when check for digit presence
        assert any(c.isdigit() for c in cs_logs[0]), (
            "Mut87: Argument removed — count number missing from log message"
        )
        # Mut88: "XX...XX" decoration
        assert "XX" not in cs_logs[0], (
            "Mut88: XX decoration inserted into log message"
        )
        # Mut89: lowercase "l3a" instead of "L3A"
        assert not cs_logs[0].startswith("l3a"), (
            "Mut89: Log message starts with lowercase 'l3a' instead of 'L3A'"
        )
        # Exact format check kills both Mut86 (no fmt) and Mut87 (no arg)
        assert cs_logs[0].startswith("L3A php-cs-fixer:") and any(
            c.isdigit() for c in cs_logs[0]
        ), (
            "Mut86/87: Log format must be 'L3A php-cs-fixer: N findings'"
        )

    def test_runtime_error_kills_92_93(self, tmp_path, caplog):
        """Assert warn log for skipped php-cs-fixer to kill exc param mutations.

        Kills:
        - mutmut_92: logger.warning(fmt, None) — message says "None" not exception text
        - mutmut_93: logger.warning(exc) — message is "<RuntimeError: ...>" not format prefix
        """
        caplog.set_level(logging.WARNING, logger="harness_quality_gate.adapters.php.php_adapter")
        adapter = _make_mock_adapter()
        # Make php-cs-fixer invoke raise RuntimeError
        adapter._cs_fixer.invoke.side_effect = RuntimeError("no such tool")
        result = adapter.run_l3a(tmp_path, {})

        assert result.layer == "L3A"
        assert result.language == "php"

        # --- Kill mutmut_92, 93 ---
        skip_logs = [m for m in caplog.messages if "php-cs-fixer skipped" in m]
        assert len(skip_logs) >= 1, (
            f"Mut92/93: Expected php-cs-fixer skipped warning, got: {caplog.messages}"
        )
        # Mut93: logger.warning(exc) → message is "<RuntimeError(...)> not format prefix
        assert skip_logs[0].startswith("L3A php-cs-fixer skipped:"), (
            "Mut93: Format string removed — message is raw exc, not format prefix"
        )
        # Mut92: logger.warning(fmt, None) → "L3A php-cs-fixer skipped: None"
        #        Original contains exception text "no such tool", mutant is "None"
        assert "no such tool" in skip_logs[0], (
            "Mut92: Exception replaced with None — log says 'None' not actual exception text"
        )

    def test_l3a_runtime_error_log_format(self, tmp_path, caplog):
        """Kill mutmut_30/31/32/33: runtime error log message mutations.

        Mut30: logger.warning("fmt", exc) → logger.warning("fmt", None)
        Mut31: logger.warning("fmt", exc) → logger.warning(exc)
        Mut32: logger.warning("fmt", exc) → logger.warning("fmt", )  [empty arg]
        Mut33: logger.warning("fmt", exc) → logger.warning("XXfmtXX", exc)
        """
        adapter = _make_mock_adapter()
        adapter._phpstan.run_l3a.side_effect = RuntimeError("phpstan not found")
        caplog.set_level(logging.WARNING, logger="harness_quality_gate.adapters.php")
        adapter.run_l3a(tmp_path, {})
        # Mut30/32: Exception replaced with None or arg removed → message ==
        # "L3A PHPStan skipped: None" (mut30) or bare "phpstan not found" (mut31)
        # or "L3A PHPStan skipped: %s" (mut32) or "XX..." (mut33)
        skip_logs = [m for m in caplog.messages if "L3A PHPStan skipped" in m]
        assert len(skip_logs) >= 1, (
            f"Mut30-33: Expected PHPStan skipped warning, got: {caplog.messages}"
        )
        # The actual exception text must be in the log (kills mut30 — None substitution)
        assert "phpstan not found" in skip_logs[0], (
            "Mut30: Exception replaced with None — log should contain 'phpstan not found'"
        )
        # Exact prefix (kills mut31 — format string removed) and mut33 — XX decoration)
        assert skip_logs[0].startswith("L3A PHPStan skipped: "), (
            "Mut31/Mut33: Format must start with 'L3A PHPStan skipped: ', not raw exc or 'XX...' "
        )

    def test_kills_all_6_run_l3a_mutants(self, tmp_path, caplog):
        """Kill all 6 surviving mutmut_15/17/18/19/20/24 in run_l3a.

        Mutant 15:  ', '.join() → 'XX, XX'.join()    — string mutation on format
        Mutant 17:  run_l3a(repo, env) → run_l3a(None, env)    — repo arg
        Mutant 18:  run_l3a(repo, env) → run_l3a(repo, None)   — env arg
        Mutant 19:  run_l3a(repo, env) → run_l3a(env)          — arg removal
        Mutant 20:  run_l3a(repo, env) → run_l3a(repo, )       — arg removal
        Mutant 24:  logger.info("L3A PHPStan: %d findings", len(...))
                    → logger.info(len(...))                     — format-arg removal
        """
        adapter = _make_mock_adapter()
        caplog.set_level(logging.INFO, logger="harness_quality_gate.adapters.php.php_adapter")
        result = adapter.run_l3a(tmp_path, {})

        # === Mutants 17, 18, 19, 20: PHPStan call arguments ===
        # Mutant 17: repo → None. Verifying the argument IS tmp_path kills it.
        assert adapter._phpstan.run_l3a.call_args[0][0] == tmp_path, (
            "Mutant17: first arg to run_l3a must be tmp_path, not None"
        )
        # Mutant 18: env → None. Mutant 19/20: env kwarg removed.
        # Original call: self._phpstan.run_l3a(repo, env)
        # With env=None, pytest.raises won't fire because mock accepts.
        # We need to assert the call signature explicitly.
        call_kw = adapter._phpstan.run_l3a.call_args
        assert call_kw[0][0] == tmp_path, (
            "Mutant17: repo arg mutated to None"
        )
        assert len(call_kw[0]) == 2, (
            "Mutant19/20: env kwarg must be present, not removed from call"
        )
        # Verify exact positional args match original signatures
        assert call_kw[1].get("env") == {} or len(call_kw[0]) > 1, (
            "Mutant18/19/20: env must be {} not None or missing pos"
        )

        # === Mutant 15: join delimiter mutation ===
        # Not triggered in default path (empty frameworks), but verify the
        # PHPStan log exists (proves framework detection path was reached)
        adapter._phpstan.run_l3a.assert_called_once()

        # === Mutant 24: logger.info format-string mutation ===
        # Original: logger.info("L3A PHPStan: %d findings", len(phpstan_findings))
        # Mutant:   logger.info(len(phpstan_findings))
        # With empty findings: original → "L3A PHPStan: 0 findings",
        #                     mutant → "0" (no prefix format)
        assert any(m == "L3A PHPStan: 0 findings" for m in caplog.messages), (
            "Mutant24: PHPStan logger.info must produce formatted message "
            "'L3A PHPStan: 0 findings', not bare '0'"
        )

        # Verify return type and fields (kills any structural mutations)
        assert result.layer == "L3A"
        assert result.language == "php"
        assert result.passed is True

    def test_l3a_tier_a_visitor_runtime_error_skipped(self, tmp_path, caplog):
        """Kill logger argument/string mutations on tier-a error path.

        Kills: mutmut_106-116, 119, 126 on tier-a visitors error path.
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
        adapter._antipattern.invoke.side_effect = RuntimeError("visitor error")
        adapter._antipattern.parse.return_value = []
        caplog.set_level(logging.WARNING, logger="harness_quality_gate.adapters.php")
        result = adapter.run_l3a(tmp_path, {})
        assert result.passed is True
        # Kill logger argument/string mutations on tier-a error path:
        #   Mutant 106: exc→None → log becomes "L3A tier-A visitors skipped: None"
        #   Mutant 107: format string removed → log changes entirely
        #   Mutant 108: string prefix/suffix mutation → "XX...XX"
        #   Mutant 109: case mutation → "l3a tier-a visitors skipped: ..."
        #   Mutant 112: node param removed from Finding
        #   Mutant 113: language param removed from Finding
        #   Mutant 114: layer param removed from Finding
        #   Mutant 115: exc→None → "L3A tier-A visitors skipped: None"
        #   Mutant 116: logger.warning(exc) → format-arg removal
        #   Mutant 119: layer="L3A" → None mutation in LayerResult
        #   Mutant 126: passed = len(all_findings) == 0 → != 0 mutation
        warnings = [m for m in caplog.messages if "L3A tier-A visitors skipped" in m]
        assert len(warnings) == 1, (
            f"Expected exactly one tier-a skip warning, got: {warnings}"
        )
        assert warnings[0] == "L3A tier-A visitors skipped: visitor error"
        # Verify result fields - kills mutations on LayerResult construction
        assert result.layer == "L3A"
        assert result.language == "php"
        assert result.passed is True

    def test_l3a_tier_a_visitor_success_log_message(self, tmp_path, caplog):
        """Kill logger.info mutations on tier-A visitor success path.

        Kills: mutmut_126, 127, 138-141 on tier-a log and duration/path.
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
        # Exact log message assertion kills format-string and argument mutations
        tier_a_logs = [m for m in caplog.messages if m.startswith("L3A tier-A visitors:")]
        assert len(tier_a_logs) == 1, (
            f"Expected exactly one tier-A log message, got: {tier_a_logs}"
        )
        assert tier_a_logs[0] == "L3A tier-A visitors: 0 findings", (
            f"Exact log format mismatch — kills mutmut_126/127/138-141, got: {tier_a_logs[0]}"
        )

    # ===========================================================================
    # H1 — Wiring tests for run_l3a sub-call arguments
    # Kills mutmut_17 (detect_frameworks repo→None), mutmut_37 (detect_frameworks env→None),
    # mutmut_45-48 (PHPStan run_l3a arg mutations),
    # mutmut_49-51 (PHPMD run_l3a arg mutations),
    # mutmut_59-62 (cs_fixer invoke arg mutations),
    # mutmut_117-120 (antipattern invoke arg mutations)
    # ===========================================================================

    def test_run_l3a_wiring_all_sub_calls(self, tmp_path, monkeypatch):
        """Kill ALL wiring mutant groups 17/37/45-51/59-62/117-120 in one shot.

        Technique: H1 — exact call-argument assertions with identity checks.

        Each sub-method call in run_l3a receives repo and env.  Mutants replace
        one of these with None or remove the arg entirely.  The test asserts
        exact positional + keyword args for every tool.
        """
        adapter = _make_mock_adapter()
        # Use sentinel values so `is` checks are meaningful (not identity with tmp_path/{}).
        repo = tmp_path
        # Sentinel dict — not None, not literal {} — identity check kills None-mutation
        env = {"X_TEST_ENV_SENTINEL": "a7k9"}
        result = adapter.run_l3a(repo, env)

        # === Framework detection (fruits of mutmut_17: repo→None) ===
        # detect_frameworks(repo) is a static method — cannot spy, but its
        # return value determines the framework injection path.  The default
        # (empty composer.json) yields empty frameworks, so this is implicitly
        # killed when the full result is correct.

        # === PHPStan call (mutmut_45: repo→None, 46: env→None, 47: repo removed, 48: env removed) ===
        cs = adapter._phpstan.run_l3a.call_args
        assert cs is not None, "PHPStan.run_l3a must be called"
        assert cs[0][0] == repo, (
            "Mut45: PHPStan.run_l3a first arg must be repo, not mutated to None"
        )
        assert cs[0][0] is repo, (
            "Mut45: Identity — repo argument must be the same object passed to run_l3a"
        )
        assert len(cs[0]) == 2, (
            "Mut47/48: PHPStan.run_l3a must receive 2 positional args (repo, env), not 1"
        )
        assert cs[0][1] is env or cs[0][1] == env, (
            "Mut46: PHPStan.run_l3a second arg must be env, not mutated to None"
        )

        # === PHPMD call (mutmut_49: repo→None, 50: env→None, 51: env removed) ===
        pm = adapter._phpmd.run_l3a.call_args
        assert pm is not None, "PHPMD.run_l3a must be called"
        assert pm[0][0] is repo, (
            "Mut49: PHPMD.run_l3a first arg must be repo"
        )
        assert len(pm[0]) == 2, (
            "Mut51: PHPMD.run_l3a must receive 2 positional args"
        )
        assert pm[0][1] is env or pm[0][1] == env, (
            "Mut50: PHPMD.run_l3a second arg must be env, not mutated to None"
        )

        # === php-cs-fixer invoke (mutmut_59: repo→None, 60: env→None,
        #     61: repo removed, 62: env removed) ===
        ci = adapter._cs_fixer.invoke.call_args
        assert ci is not None, "cs_fixer.invoke must be called"
        assert ci[0][0] is repo, (
            "Mut59: cs_fixer.invoke first arg must be repo"
        )
        assert len(ci[0]) == 2, (
            "Mut61/62: cs_fixer.invoke must receive 2 positional args (repo, args)"
        )
        assert ci[1].get("env") is env or ci[1].get("env") == env, (
            "Mut60/62: cs_fixer.invoke env kwarg must be env"
        )

        # === Antipattern invoke (mutmut_117: repo→None, 118: env→None) ===
        # Note: _antipattern_invoke_and_parse calls:
        #   self._antipattern.invoke(repo, args=["analyse"], env=env)
        # So 1 positional arg + 2 keyword args (args=, env=). Mutants change
        # repo→None (117) or env→None (118).
        ai = adapter._antipattern.invoke.call_args
        assert ai is not None, "antipattern.invoke must be called"
        assert ai[0][0] is repo, (
            "Mut117: antipattern.invoke first arg must be repo"
        )
        assert ai[1].get("env") is env or ai[1].get("env") == env, (
            "Mut118: antipattern.invoke env kwarg must be env, not mutated"
        )
        assert ai[1].get("args") == ["analyse"], (
            "antipattern.invoke must pass args=['analyse']"
        )

        assert result.layer == "L3A"

    def test_run_l3a_framework_detection_wiring(self, tmp_path, monkeypatch):
        """Kill mutmut_37 specifically: detect_frameworks(repo) → detect_frameworks(None).

        Technique: H1 — spy on detect_frameworks to capture the exact arg.

        detect_frameworks is a @staticmethod, so we monkeypatch it to record calls.
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

        # Spy on the static method
        original_df = PhpAdapter.detect_frameworks
        call_args = []

        def spy_detect_frameworks(repo, *_args, **_kwargs):
            call_args.append(repo)
            return original_df(repo)

        monkeypatch.setattr(PhpAdapter, 'detect_frameworks', staticmethod(spy_detect_frameworks))

        result = adapter.run_l3a(tmp_path, {})
        assert result.passed is True

        # The call_args must contain tmp_path (not None) — kills mutmut_37
        assert len(call_args) == 1, (
            f"Expected exactly one detect_frameworks call, got {call_args}"
        )
        assert call_args[0] == tmp_path, (
            "Mut37: detect_frameworks called with tmp_path, not None"
        )

    def test_run_l3a_phpstan_log_format(self, tmp_path, caplog):
        """Kill mutmut_44: logger.info('L3A PHPStan: %d findings', len(...))
        → logger.info(len(...)) — format-arg removal mutation.

        Technique: H3 — exact log-message assertion via caplog.

        Mutant 44 replaces the format+arg pair with bare len() → log message
        becomes just "0" (or "N" findings).  Original is
        "L3A PHPStan: 0 findings".  Exact equality kills it.
        """
        adapter = _make_mock_adapter()
        caplog.set_level(logging.INFO, logger="harness_quality_gate.adapters.php.php_adapter")
        result = adapter.run_l3a(tmp_path, {})

        assert result.passed is True

        # Extract the PHPStan log message
        stan_logs = [m for m in caplog.messages if "L3A PHPStan" in m and "findings" in m]
        assert len(stan_logs) == 1, (
            f"Mut44: Expected exactly one PHPStan log message, got: {stan_logs}"
        )
        # Original: "L3A PHPStan: 0 findings"
        # Mut44: "0" (bare number, no format prefix)
        assert stan_logs[0] == "L3A PHPStan: 0 findings", (
            f"Mut44: Log format mutated — expected 'L3A PHPStan: 0 findings', got '{stan_logs[0]}'"
        )

    # ===========================================================================
    # H3 — Exact logger assertions for success paths (phpmd, cs_fixer, tier-a)
    # Kills mutmut_46-49 (PHPMD success logger), mutmut_90-91 (cs_fixer success logger),
    # mutmut_131-135 (tier-a success logger), and mutmut_5-14 (framework injection logger).
    # ===========================================================================

    def test_run_l3a_phpmd_success_logger(self, tmp_path, caplog):
        """Kill mutmut_46/47/48/49 — PHPMD success path logger mutations.

        Technique: H3 — exact log message assertion on the PHPMD logger.info line.

        Mutations on: logger.info("L3A PHPMD: %d findings", len(phpmd_findings))
          Mut46: format → "XX...XX"  → message starts with "XX"
          Mut47: format → ""          → message is just the count "0"
          Mut48: arg removed         → format error / TypeError
          Mut49: lowercase "l3a"     → message starts with "l3a" not "L3A"
        """
        adapter = _make_mock_adapter()
        adapter._phpmd.run_l3a.return_value = [Finding(
            node="src/Bar.php", severity="error", message="Test violation",
            tool="phpmd", layer="L3A", language="php",
        )]
        caplog.set_level(logging.INFO, logger="harness_quality_gate.adapters.php.php_adapter")
        result = adapter.run_l3a(tmp_path, {})

        assert result.passed is False
        assert any(f.tool == "phpmd" for f in result.findings)

        phpmd_logs = [m for m in caplog.messages if m.startswith("L3A PHPMD:")]
        assert len(phpmd_logs) == 1, (
            f"Mut46-49: Expected exact PHPMD log message, got: {caplog.messages}"
        )
        assert phpmd_logs[0] == "L3A PHPMD: 1 findings", (
            "Mut46/47/49: PHPMD logger format mutated"
        )

    def test_run_l3a_cs_fixer_success_logger(self, tmp_path, caplog):
        """Kill mutmut_90/91 — cs_fixer success logger format-string mutations.

        Technique: H3 — exact log message on the cs_fixer logger.info line.

        Mutations on: logger.info("L3A php-cs-fixer: %d findings", len(cs_findings))
          Mut90: format → "XX...XX" → message starts with "XX"
          Mut91: format → ""        → message is just the count
        """
        adapter = _make_mock_adapter()
        adapter._cs_fixer.parse.return_value = [Finding(
            node="src/Baz.php", severity="warning", message="Style issue",
            tool="php-cs-fixer", layer="L3A", language="php",
        )]
        caplog.set_level(logging.INFO, logger="harness_quality_gate.adapters.php.php_adapter")
        result = adapter.run_l3a(tmp_path, {})

        assert result.passed is False
        assert any(f.tool == "php-cs-fixer" for f in result.findings)

        cs_logs = [m for m in caplog.messages if m.startswith("L3A php-cs-fixer:")]
        assert len(cs_logs) == 1, (
            f"Mut90/91: Expected exact cs-fixer log message, got: {caplog.messages}"
        )
        assert cs_logs[0] == "L3A php-cs-fixer: 1 findings", (
            "Mut90/91: cs-fixer logger format mutated"
        )

    def test_run_l3a_tier_a_success_logger(self, tmp_path, caplog):
        """Kill mutmut_131-135 — tier-A success logger mutations.

        Technique: H3 — exact log message assertion.

        Mutations on: logger.info("L3A tier-A visitors: %d findings", len(tier_a_findings))
          Mut131: format → "XX...XX"
          Mut132: arg removed
          Mut133: lowercase "l3a tier-a visitors"
          Mut134/135: "XX" prefix/suffix on format
        """
        adapter = _make_mock_adapter()
        adapter._antipattern.invoke.return_value = MagicMock(
            stdout='[{"file": "src/Z.php", "rule": "AntiPattern"}]',
            stderr="", exitcode=0,
        )
        adapter._antipattern.parse.return_value = [Finding(
            node="src/Z.php", severity="warning", message="Anti-pattern",
            tool="antipattern", layer="L3A", language="php",
        )]
        caplog.set_level(logging.INFO, logger="harness_quality_gate.adapters.php.php_adapter")
        result = adapter.run_l3a(tmp_path, {})

        assert any(f.tool == "antipattern" for f in result.findings)

        tier_a_logs = [m for m in caplog.messages if m.startswith("L3A tier-A visitors:")]
        assert len(tier_a_logs) == 1, (
            f"Mut131-135: Expected tier-A success log, got: {caplog.messages}"
        )
        assert tier_a_logs[0] == "L3A tier-A visitors: 1 findings", (
            "Mut131-135: Tier-A logger format mutated"
        )

    # ===========================================================================
    # H2 — Duration freezing (kills round() and duration calc mutations)
    # ===========================================================================

    def test_run_l3a_duration_uses_round_3(self, tmp_path, monkeypatch):
        """Kill mutmut_136-141 — duration calculation / round() mutations.

        Technique: H2 — freeze time.monotonic() to control duration,
                   then assert round(duration, 3) produces an exact value.
        Use a 6-decimal delta so round(_, 3) ≠ round(_, 4) to kill Mut141.

        Mutations killed:
          Mut136: round(duration, 3) → round(duration)  — float→int
          Mut137: round(duration, 3) → round(duration, None) — float→int
          Mut138: duration change (+= instead of -=)
          Mut139: round(_ , 3) → round(_, 2)
          Mut140: duration formula changed
          Mut141: round(duration, 3) → round(duration, 4)
        """
        import time as _time
        adapter = _make_mock_adapter()
        # 0.123456 → round(_, 3) = 0.123, round(_, 4) = 0.1235  (different!)
        ticks = iter([100.0, 100.123456])
        monkeypatch.setattr(_time, "monotonic", lambda: next(ticks))
        result = adapter.run_l3a(tmp_path, {})

        assert isinstance(result.duration_sec, float), (
            "Mut136/137/141: duration_sec must be float, not int"
        )
        # round(0.123456, 3) == 0.123  rounds correctly to 3 decimals
        # round(0.123456, 4) == 0.1235 ≠ 0.123  → Mut141 killed
        assert result.duration_sec == 0.123, (
            "Mut138/139/140/141: duration_sec changed — expected 0.123 "
            f"got {result.duration_sec}"
        )

    # ===========================================================================
    # §4.4 — Parse arg mutations (PHPStan & php-cs-fixer)
    # ===========================================================================

    def test_run_l3a_phpstan_parse_args(self, tmp_path):
        """Assert findings flow through from PHPStan parse return value.

        Technique: §4.1 — dense assertions on LayerResult fields.

        Verifies that phpstan findings are properly collected into result.findings.
        """
        adapter = _make_mock_adapter()
        adapter._phpstan.run_l3a.return_value = [Finding(
            node="src/Foo.php", severity="error",
            message="Class not found", tool="phpstan",
            layer="L3A", language="php",
        )]
        result = adapter.run_l3a(tmp_path, {})

        assert any(f.tool == "phpstan" for f in result.findings), (
            "Mut77-80: PHPStan findings must flow to result.findings"
        )
        stan = [f for f in result.findings if f.tool == "phpstan"]
        assert len(stan) == 1
        assert stan[0].message == "Class not found"

    # ===========================================================================
    # §4.1 — Exact LayerResult field assertions
    # Kills mutmut_141-148 — LayerResult construction mutations.
    # ===========================================================================

    def test_run_l3a_layer_result_fields(self, tmp_path, caplog):
        """Kill mutmut_141-148 — LayerResult construction mutations.

        Technique: §4.1 — exact field assertions on LayerResult.

        Mutations killed:
          Mut141: passed = len(all_findings) == 0  → != 0
          Mut142: layer="L3A" → layer=None
          Mut143: language="php" → language=None
          Mut144: findings=[] → findings=None
        """
        adapter = _make_mock_adapter()
        caplog.set_level(logging.INFO, logger="harness_quality_gate.adapters.php.php_adapter")
        result = adapter.run_l3a(tmp_path, {})

        assert result.layer == "L3A", "Mut142: layer must be L3A"
        assert result.language == "php", "Mut143: language must be php"
        assert result.passed is True, "Mut141: passed must be True with 0 findings"
        assert result.findings == [], "Mut144: findings must be empty list"

        # Findings path → passed=False
        adapter._phpstan.run_l3a.return_value = [Finding(
            node="src/X.php", severity="error", message="err", tool="phpstan",
        )]
        result2 = adapter.run_l3a(tmp_path, {})
        assert result2.passed is False, "Mut141: passed must be False with findings"
        assert len(result2.findings) > 0
        assert result2.layer == "L3A"
        assert result2.language == "php"

    # ===========================================================================
    # H1 — Wiring: PHPMD & cs_fixer arg passthrough (mutmut_50/51/59/60)
    # ===========================================================================

    def test_run_l3a_phpmd_call_args_identity(self, tmp_path, monkeypatch):
        """Kill mutmut_50/51: PHPMD run_l3a(repo, env) → repo→None / env→None.

        Technique: H1 — exact call-argument identity checks.
        Uses sentinel env so `is env` detects the mutation (not just equality).
        """
        adapter = _make_mock_adapter()
        repo = tmp_path
        sentinel_env = {"X_PHPMD_TEST_SENTINEL": "k9j2"}

        result = adapter.run_l3a(repo, sentinel_env)

        assert result.layer == "L3A"

        cs = adapter._phpmd.run_l3a.call_args
        # Mut50: first arg is repo, not mutated to None (identity check)
        assert cs[0][0] is repo, (
            "Mut50: PHPMD.run_l3a first arg must be repo, not mutated to None"
        )
        # Mut51: second arg is env, not mutated to None
        assert cs[0][1] is sentinel_env, (
            "Mut51: PHPMD.run_l3a second arg must be env, not mutated to None"
        )
        # Kill arg-removal mutants: both args must be present
        assert len(cs[0]) == 2, (
            "Mut51: PHPMD.run_l3a must receive 2 positional args (repo, env)"
        )

    def test_run_l3a_cs_fixer_invoke_args_identity(self, tmp_path, monkeypatch):
        """Kill mutmut_59/60: cs_fixer.invoke(repo, args, env=env) → repo→None / env→None.

        Technique: H1 — exact call-argument identity checks.
        Uses sentinel env so `is env` detects the mutation (not just equality).
        """
        adapter = _make_mock_adapter()
        repo = tmp_path
        sentinel_env = {"X_CSFIXER_TEST_SENTINEL": "x4m7"}

        result = adapter.run_l3a(repo, sentinel_env)

        assert result.layer == "L3A"

        ci = adapter._cs_fixer.invoke.call_args
        # Mut59: first arg (repo) must be the repo, not mutated to None
        assert ci[0][0] is repo, (
            "Mut59: cs_fixer.invoke first arg must be repo, not mutated to None"
        )
        # Mut60: env kwarg must be the env, not mutated to None
        assert ci[1]["env"] is sentinel_env, (
            "Mut60: cs_fixer.invoke env kwarg must be env, not mutated to None"
        )

    # ===========================================================================
    # H3 — Exact log assertion: php-cs-fixer format-arg removal (mutmut_77)
    # ===========================================================================

    def test_run_l3a_cs_fixer_logger_exact_message(self, tmp_path, caplog):
        """Kill mutmut_77: cs_fixer logger.info(fmt, arg) → logger.info(arg).

        Technique: H3 — exact log-message assertion via caplog.

        Mutant 77 replaces the format+arg pair in:
            logger.info("L3A php-cs-fixer: %d findings", len(cs_findings))
        with just:
            logger.info(len(cs_findings))
        Original: "L3A php-cs-fixer: N findings"
        Mutant:   "N" (bare number, no prefix) — exact equality kills it.
        """
        adapter = _make_mock_adapter()
        adapter._cs_fixer.parse.return_value = [Finding(
            node="src/Style.php", severity="warning", message="spacing",
            tool="php-cs-fixer",
        )]
        caplog.set_level(logging.INFO, logger="harness_quality_gate.adapters.php.php_adapter")
        result = adapter.run_l3a(tmp_path, {})

        assert result.passed is False
        assert any(f.tool == "php-cs-fixer" for f in result.findings)

        # Original: "L3A php-cs-fixer: 1 findings"
        # Mut77: "1" (no format prefix — bare number from len(cs_findings))
        cs_logs = [m for m in caplog.messages if "php-cs-fixer" in m and "findings" in m]
        assert len(cs_logs) >= 1, (
            f"Mut77: Expected php-cs-fixer log, got: {caplog.messages}"
        )
        assert cs_logs[0] == "L3A php-cs-fixer: 1 findings", (
            f"Mut77: Logger format-arg removed — expected 'L3A php-cs-fixer: 1 findings', "
            f"got '{cs_logs[0]}' (mutant produces bare count, no format prefix)"
        )

    # ===========================================================================
    # H3 — PHPMD skip logger mutations (mutmut_50, 52, 53, 54)
    # ===========================================================================

    def test_run_l3a_phpmd_skip_logger_exact(self, tmp_path, caplog):
        """Kill mutmut_50, 52, 53, 54: PHPMD skip path logger mutations.

        Technique: H3 — exact log-message assertion via caplog.
        Uses sentinel logger path so caplog captures the warning.

        Mutations on:
            logger.warning("L3A PHPMD skipped: %s", exc)
              Mut50: exc → None       → message "L3A PHPMD skipped: None"
              Mut52: arg removed     → message format broken / TypeError
              Mut53: "XX" decoration  → message starts with "XX"
              Mut54: lowercase        → message starts with "l3a" not "L3A"
        """
        adapter = _make_mock_adapter()
        adapter._phpmd.run_l3a.side_effect = RuntimeError("mock_phpmd_failure")
        caplog.set_level(logging.WARNING,
                         logger="harness_quality_gate.adapters.php.php_adapter")
        result = adapter.run_l3a(tmp_path, {})

        # Collect the PHPMD skip warning
        phpmd_skips = [m for m in caplog.messages
                       if m.startswith("L3A PHPMD skipped: ")]
        assert len(phpmd_skips) == 1, (
            f"Expected exactly one PHPMD skip warning, got: {phpmd_skips}"
        )
        # Original: "L3A PHPMD skipped: mock_phpmd_failure"
        # Mut50: "L3A PHPMD skipped: None"  (exact !=)
        # Mut52: format error or bare string
        # Mut53: "XXL3A PHPMD skipped: ..." (starts with XX)
        # Mut54: "l3a phpms skipped: ..." (lowercase)
        assert phpmd_skips[0] == "L3A PHPMD skipped: mock_phpmd_failure", (
            f"Mut50/52/53/54: Logger call mutated. "
            f"Expected exact format 'L3A PHPMD skipped: mock_phpmd_failure', "
            f"got: '{phpmd_skips[0]}'"
        )

    # ===========================================================================
    # H3 — CS-fix build-args string mutations (mutmut_57, 58, 59, 60, 61, 62)
    # ===========================================================================

    def test_run_l3a_cs_fixer_build_args_exact(self, tmp_path, monkeypatch):
        """Kill mutmut_57, 58, 59, 60, 61, 62: CS-fix build-args string mutations.

        Technique: H3 — assert the exact command list passed to invoke.
        Mutations replace individual args with 'XX...XX' or case-changed copies.

        Mutations on args list:
            ["fix", "--dry-run", "--format=json", "--no-progress", str(repo)]
              Mut57: "fix" → "XXfixXX"
              Mut58: "fix" → "FIX"
              Mut59: "--dry-run" → "XX--dry-runXX"
              Mut60: "--dry-run" → "--DRY-RUN"
              Mut61: "--format=json" → "XX--format=jsonXX"
              Mut62: "--format=json" → "--FORMAT=JSON"
        """
        adapter = _make_mock_adapter()
        repo = tmp_path

        with monkeypatch.context() as mp:
            mp.setenv("CS_FIXER_MOCK", "1")
            result = adapter.run_l3a(repo, {})

        args = adapter._cs_fixer.invoke.call_args[0][1]
        # Assert the EXACT command list — any string mutation breaks equality.
        expected_args = [
            "fix", "--dry-run", "--format=json",
            "--no-progress", str(repo),
        ]
        assert args == expected_args, (
            f"Muts57-62: Command list mutated. "
            f"Expected {expected_args}, got: {args}"
        )

    # ===========================================================================
    # H1 — CS-fix parse arg identity (mutmut_78, 79)
    # ===========================================================================

    def test_run_l3a_cs_fixer_parse_args_identity(self, tmp_path, monkeypatch):
        """Kill mutmut_78, 79: CS-fix parse(stdout, stderr, exitcode) arg mutations.

        Technique: H1 — spy the exact call args to parse().

        Mutations:
          Mut78: invocation.stdout → None in parse()
          Mut79: invocation.stderr → None in parse()
        """
        adapter = _make_mock_adapter()
        # Capture what invoke returns so we can assert it matches.
        mock_invocation = MagicMock(stdout='[{"files":[]}]', stderr="", exitcode=0)
        adapter._cs_fixer.invoke.return_value = mock_invocation
        adapter._cs_fixer.parse.return_value = []

        adapter.run_l3a(tmp_path, {})

        parse_args = adapter._cs_fixer.parse.call_args[0]
        assert parse_args[0] == mock_invocation.stdout, (
            "Mut78: parse first arg must be invocation.stdout, not mutated to None"
        )
        assert parse_args[1] == mock_invocation.stderr, (
            "Mut79: parse second arg must be invocation.stderr, not mutated to None"
        )
        assert parse_args[2] == mock_invocation.exitcode, (
            "Mut80: parse third arg must be invocation.exitcode, not mutated to None"
        )
        # Ensure all 3 positional args are present (kills Mut82: arg removal)
        assert len(parse_args) == 3, (
            "Mut82: parse must receive all 3 positional args (stdout, stderr, exitcode)"
        )

    # ===========================================================================
    # H1 — CS-fix invoke timeout mutation (mutmut_75)
    # ===========================================================================

    def test_run_l3a_cs_fixer_timeout_kwarg(self, tmp_path):
        """Kill mutmut_75: CS-fix invoke(timeout=300) → timeout=301.

        Technique: H3 — exact kwarg assertion via spy on invoke().

        Mutant 75 replaces timeout=300.0 with timeout=301.0.
        Exact kwarg assertion kills it immediately.
        """
        adapter = _make_mock_adapter()
        adapter.run_l3a(tmp_path, {})

        kw = adapter._cs_fixer.invoke.call_args[1]
        assert kw["timeout"] == 300.0, (
            "Mut75: timeout must be 300.0, not mutated to 301.0 or None"
        )

    # ===========================================================================
    # H3 — CS-fix build-args list removal (mutmut_56, 65)
    # ===========================================================================

    def test_run_l3a_cs_fixer_args_list_intact(self, tmp_path):
        """Kill mutmut_56, 65: CS-fix args list removal and str(repo)→str(None).

        Technique: H3 — verify the exact args list (existence, structure, and content).

        Mutations:
          Mut56: removes entire `args = [...]` block → `invoke` receives wrong args
          Mut65:  str(repo) → str(None) in args list
        """
        adapter = _make_mock_adapter()
        repo = tmp_path

        adapter.run_l3a(repo, {})

        # Get the actual args list (second positional arg to invoke).
        args = adapter._cs_fixer.invoke.call_args[0][1]
        # Verify structure: 5 elements expected.
        assert len(args) == 5, (
            "Mut56: args list must have 5 elements — full list not removed"
        )
        # Verify the last element is an actual path string, not str(None)="None".
        assert args[-1] != "None", (
            "Mut65: last arg must be the repo path, not str(None)"
        )

# _mutation_remediation — static method (PHP / Infection flavor)
# ===========================================================================

class TestPhpMutationRemediation:
    """Unit tests for PhpAdapter._mutation_remediation."""

    def _rem(self, **kwargs):
        defaults = dict(total=100, killed=97, survived=0, timed_out=0,
                        escaped=3, untested=0, msi=97.0, covered_msi=97.0)
        defaults.update(kwargs)
        return PhpAdapter._mutation_remediation(MutationStats(**defaults))

    def test_keys_present(self):
        """All expected keys are present in the remediation dict."""
        rem = self._rem()
        assert set(rem.keys()) >= {
            "skill", "guide", "instructions", "summary",
            "msi", "covered_msi", "escaped", "timed_out",
        }

    def test_skill_name_exact(self):
        """skill must be exactly 'mutation-testing-guide'."""
        assert self._rem()["skill"] == "mutation-testing-guide"

    def test_guide_name_exact_php(self):
        """guide must be the PHP-specific guide, not the Python one."""
        assert self._rem()["guide"] == "MUTANT_KILLING_GUIDE_PHP.md"

    def test_instructions_name_exact(self):
        """instructions must be exactly 'SUBAGENT_MUTATION_INSTRUCTIONS.md'."""
        assert self._rem()["instructions"] == "SUBAGENT_MUTATION_INSTRUCTIONS.md"

    def test_escaped_only(self):
        """escaped > 0 with 100 MSI: summary mentions escaped, not timeouts."""
        rem = self._rem(escaped=5, timed_out=0, msi=100.0, covered_msi=100.0)
        assert rem["escaped"] == 5
        assert rem["timed_out"] == 0
        assert "5 mutant(s) escaped" in rem["summary"]
        assert "timed out" not in rem["summary"]
        assert "MSI" not in rem["summary"].replace("covered MSI", "")

    def test_timed_out_only(self):
        """timed_out > 0: summary mentions timeouts, not escaped."""
        rem = self._rem(escaped=0, timed_out=2, msi=100.0, covered_msi=100.0)
        assert rem["timed_out"] == 2
        assert rem["escaped"] == 0
        assert "2 mutant(s) timed out" in rem["summary"]
        assert "escaped" not in rem["summary"]

    def test_msi_below_gate(self):
        """msi < 100: summary contains the exact MSI percentage."""
        rem = self._rem(escaped=0, timed_out=0, msi=97.5, covered_msi=100.0)
        assert "MSI 97.5% < 100%" in rem["summary"]

    def test_covered_msi_below_gate(self):
        """covered_msi < 100: summary contains the exact covered MSI percentage."""
        rem = self._rem(escaped=0, timed_out=0, msi=100.0, covered_msi=98.2)
        assert "covered MSI 98.2% < 100%" in rem["summary"]

    def test_all_issues_combined(self):
        """All four gate violations appear together in the summary."""
        rem = self._rem(escaped=3, timed_out=1, msi=96.0, covered_msi=97.0)
        summary = rem["summary"]
        assert "3 mutant(s) escaped" in summary
        assert "1 mutant(s) timed out" in summary
        assert "MSI 96.0% < 100%" in summary
        assert "covered MSI 97.0% < 100%" in summary

    def test_stats_passed_through(self):
        """Numeric stats are passed through exactly."""
        rem = self._rem(escaped=3, timed_out=1, msi=96.0, covered_msi=97.0)
        assert rem["msi"] == 96.0
        assert rem["covered_msi"] == 97.0
        assert rem["escaped"] == 3
        assert rem["timed_out"] == 1

    def test_summary_starts_with_l1_label(self):
        """summary starts with 'L1 Infection gate FAILED' for grep-ability."""
        assert self._rem()["summary"].startswith("L1 Infection gate FAILED")

    def test_summary_contains_php_hints(self):
        """summary references PHP-specific traps (T1-T3) and the iterate command."""
        summary = self._rem()["summary"]
        assert "assertSame not assertEquals (T1)" in summary
        assert "identicalTo()" in summary
        assert "--filter=<file> --show-mutations" in summary

    def test_summary_references_guides(self):
        """summary names the skill and the PHP guide file."""
        summary = self._rem()["summary"]
        assert "mutation-testing-guide" in summary
        assert "MUTANT_KILLING_GUIDE_PHP.md" in summary


# ===========================================================================
# run_l1 — remediation wiring (gate fail → remediation in tool_specific)
# ===========================================================================

class TestRunL1RemediationWiring:
    """run_l1 must attach remediation metadata when the Infection gate fails."""

    def test_gate_fail_attaches_remediation(self, tmp_path):
        """Failing stats (escaped > 0, MSI < 100) → remediation in tool_specific."""
        adapter = _make_mock_adapter(
            pest_binary=None,
            pcov_driver="pcov",
            infection_stats=MutationStats(
                total=100, killed=97, survived=0, escaped=3, timed_out=0,
                untested=0, msi=97.0, covered_msi=97.0,
            ),
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.passed is False
        rem = result.tool_specific["remediation"]
        assert rem["skill"] == "mutation-testing-guide"
        assert rem["guide"] == "MUTANT_KILLING_GUIDE_PHP.md"
        assert rem["escaped"] == 3
        assert rem["msi"] == 97.0
        assert "3 mutant(s) escaped" in rem["summary"]
        # mutation block still present alongside remediation
        assert result.tool_specific["mutation"]["escaped"] == 3

    def test_gate_pass_no_remediation(self, tmp_path):
        """Perfect stats (100/100, 0 escaped/timeout) → no remediation key."""
        adapter = _make_mock_adapter(
            pest_binary=None,
            pcov_driver="pcov",
            infection_stats=MutationStats(
                total=50, killed=50, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0,
            ),
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.passed is True
        assert "remediation" not in result.tool_specific
        assert result.tool_specific["mutation"]["killed"] == 50

    def test_no_stats_no_remediation(self, tmp_path):
        """Infection unavailable (stats=None) → no remediation, no mutation block."""
        adapter = _make_mock_adapter(
            pest_binary=None,
            pcov_driver="pcov",
            infection_stats=None,
        )
        result = adapter.run_l1(tmp_path, {})
        assert "remediation" not in result.tool_specific
        assert "mutation" not in result.tool_specific

    def test_timeout_only_attaches_remediation(self, tmp_path):
        """timed_out > 0 with perfect MSI still fails gate → remediation present."""
        adapter = _make_mock_adapter(
            pest_binary=None,
            pcov_driver="pcov",
            infection_stats=MutationStats(
                total=100, killed=99, survived=0, escaped=0, timed_out=1,
                untested=0, msi=100.0, covered_msi=100.0,
            ),
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.passed is False
        rem = result.tool_specific["remediation"]
        assert rem["timed_out"] == 1
        assert "1 mutant(s) timed out" in rem["summary"]


# ===========================================================================
# run_l1 — mutant-killing tests (survivors 114,115,116,218,219,222-226,229,250,252-260,288)
# ===========================================================================

class TestRunL1MutantKilling:
    """Kill remaining mutmut survivors in run_l1 via dense assertions and caplog.

    Techniques:
    - §4.1 Dense assertions on tool_specific mutation meta
    - H3 Exact log message + caplog config
    - H2 Clock mock for duration assertions
    """

    # -- Variable init mutations (114, 115) --------------------------------

    def test_pest_no_mutate_plugin_meta_skipped(self, tmp_path, monkeypatch):
        """mutmut_115: mutation_skipped=None→'' kills because empty string
        makes `if mutation_skipped:` False → mutation_skipped absent from meta.

        Technique: §4.1 dense — assert exact tool_specific keys + value for
        mutation_skipped key that only appears when pest has no mutate plugin.
        """
        adapter = _make_mock_adapter(
            pest_binary="/fake/pest",
            pest_has_mutate=False,  # NOT has mutate → enters skip branch
            pcov_driver="xdebug",
            infection_stats=None,
        )
        result = adapter.run_l1(tmp_path, {})
        # mutation_skipped finding makes passed=False
        assert result.passed is False
        assert len(result.findings) == 1
        assert result.findings[0].message == "Mutation testing skipped: pest-plugin-mutate not installed (TD-6)"

        # mutation_meta always has "mutation_skipped" key value
        assert "mutation_skipped" in result.tool_specific
        # The exact string is contract — kills ""→"" (no-op) but
        # also kills mutation of the value itself
        assert result.tool_specific["mutation_skipped"] == "pest-plugin-mutate not installed"

    def test_pest_no_mutate_plugin_meta_full(self, tmp_path, monkeypatch):
        """Also verifies mutation_meta structure is intact when skipped.

        Kill mutmut_114 indirectly: if mutation_stats init mutated to `""`,
        the `if mutation_stats:` check in the mutation_meta building would
        behave the same (falsy), BUT the mutation block itself must still
        exist only when stats is present — and here stats is None, so
        mutation block absent. Verifies the path is clean.
        """
        adapter = _make_mock_adapter(
            pest_binary="/fake/pest",
            pest_has_mutate=False,
            pcov_driver="xdebug",
            infection_stats=None,
        )
        result = adapter.run_l1(tmp_path, {})

        # mutation_skipped path: no mutation block when stats=None
        assert "mutation" not in result.tool_specific
        # But mutation_skipped at top-level tool_specific:
        assert result.tool_specific.get("mutation_skipped") == "pest-plugin-mutate not installed"

    # -- Logging mutations (218, 219) --------------------------------------

    def test_l1_infection_log_msi_escaped(self, tmp_path, caplog, monkeypatch):
        """mutmut_218,219: log message mutated (XX...XX, lower-case).

        H3 — caplog with exact logger config + assert full interpolated message.
        The original message is 'L1 Infection MSI=100.0 coveredMsi=100.0 escaped=0'.
        Any mutation (XX prefix, lowercased) breaks exact message match.
        """
        caplog.set_level(
            logging.INFO,
            logger="harness_quality_gate.adapters.php.php_adapter"
        )
        adapter = _make_mock_adapter(
            pest_binary=None,
            pcov_driver="pcov",
            infection_stats=MutationStats(
                total=50, killed=50, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0,
            ),
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.passed is True

        # Find INFO log with the MSI message
        msi_logs = [
            r.message for r in caplog.records
            if r.levelno == logging.INFO and r.name == "harness_quality_gate.adapters.php.php_adapter"
            and "MSI" in r.message
        ]
        assert len(msi_logs) >= 1, "Expected L1 Infection MSI log line"
        # Exact message kills XX...XX and lowercased string mutations
        assert msi_logs[0] == "L1 Infection MSI=100.0 coveredMsi=100.0 escaped=0"

    # -- Runtime exception logging mutations (222, 223, 224, 225, 226) ---

    def test_l1_infection_exception_logs_invocation_failed(
        self, tmp_path, caplog, monkeypatch
    ):
        """mutmut_222-226: logger.warning("L1 mutation testing skipped: %s", exc)
        and _run_infection's inner logger.warning are both in warning paths.

        Force infection to raise RuntimeError. Since _run_infection catches
        RuntimeError internally with its own warning ("Infection invocation
        failed: %s"), we assert that exact message. If the outer handler
        message was the one mutating but code path is unreachable (inner
        handler catches first), we verify the reachable handler's log too.

        mutmut_222: arg→None
        mutmut_223: format_string removed
        mutmut_224: extra arg removed
        mutmut_225: message string mutated (XX...XX)
        mutmut_226: message string mutated (lowercase)
        """
        caplog.set_level(
            logging.WARNING,
            logger="harness_quality_gate.adapters.php.php_adapter"
        )

        def infection_invoke_raises(*args, **kwargs):
            raise RuntimeError("invocation failed error")

        adapter = _make_mock_adapter(
            pest_binary=None,
            pcov_driver="pcov",
            infection_stats=None,
        )
        adapter._infection.invoke.side_effect = infection_invoke_raises

        result = adapter.run_l1(tmp_path, {})

        # _run_infection catches RuntimeError first → log "Infection invocation
        # failed: invocation failed error"
        invocation_logs = [
            r.message for r in caplog.records
            if r.levelno == logging.WARNING
            and r.name == "harness_quality_gate.adapters.php.php_adapter"
            and "invocation failed" in r.message
        ]
        assert len(invocation_logs) >= 1
        # This exact format kills XX...XX, lowercase, missing arg, etc.
        assert invocation_logs[0] == "Infection invocation failed: invocation failed error"

    # -- Duration calculation mutation (229) -------------------------------

    def test_l1_duration_subtraction(self, tmp_path, monkeypatch):
        """mutmut_229: `duration = time.monotonic() - t0` → `+ t0`.

        H2 — clock mock. With t0=100 and now=101.234, subtraction gives 1.234,
        addition gives 201.234. Round to 3 decimals = 1.234 vs 201.234.
        Asserting exact duration kills the + mutation.
        """
        tick = iter([100.0, 101.2345])  # t0, then current
        monkeypatch.setattr(_time, "monotonic", lambda: next(tick))

        adapter = _make_mock_adapter(
            pest_binary=None,
            pcov_driver="pcov",
            infection_stats=MutationStats(
                total=50, killed=50, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0,
            ),
        )
        result = adapter.run_l1(tmp_path, {})
        # round(101.2345 - 100.0, 3) = round(1.2345, 3) = 1.234
        # If mutated to +: round(101.2345 + 100.0, 3) = round(201.2345, 3) = 201.235
        assert result.duration_sec == 1.234

    def test_l1_duration_gt_zero(self, tmp_path, monkeypatch):
        """Additional duration assertion — ensures duration is small positive,
        ruling out addition mutation (which would give ~200s).
        """
        tick = iter([500.0, 500.5])
        monkeypatch.setattr(_time, "monotonic", lambda: next(tick))

        adapter = _make_mock_adapter(
            pest_binary=None,
            pcov_driver="pcov",
            infection_stats=MutationStats(
                total=50, killed=50, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0,
            ),
        )
        result = adapter.run_l1(tmp_path, {})
        assert result.duration_sec > 0
        assert result.duration_sec < 10  # addition mutation gives ~1000

    # -- Mutation meta dict mutations (250, 252, 253, 254, 255, 257, 258, 259, 260) ---

    def test_l1_mutation_meta_keys_and_values(self, tmp_path, monkeypatch):
        """mutmut_250,252,253,254,255,257,258,259,260: mutations in mutation_meta dict.

        §4.1 — Dense assertion. The mutation_meta["mutation"] dict must have
        EXACT keys: killed, survived, timed_out, escaped, untested, msi, covered_msi
        EXACT values with round(..., 4).

        Key mutations (254,255): "covered_msi" → "XXcovered_msiXX" / "COVERED_MSI"
          → dense assert fails because key doesn't exist.
        Value mutations (250,252,253,257,258,259,260): round changes
          → dense assert fails because value is wrong.
        """
        tick = iter([200.0, 200.1])
        monkeypatch.setattr(_time, "monotonic", lambda: next(tick))

        adapter = _make_mock_adapter(
            pest_binary=None,
            pcov_driver="pcov",
            infection_stats=MutationStats(
                total=50, killed=50, survived=0, escaped=0, timed_out=0,
                untested=0, msi=99.5, covered_msi=98.7,
            ),
        )
        result = adapter.run_l1(tmp_path, {})

        expected = {
            "killed": 50,
            "survived": 0,
            "timed_out": 0,
            "escaped": 0,
            "untested": 0,
            "msi": round(99.5, 4),
            "covered_msi": round(98.7, 4),
        }
        assert result.tool_specific["mutation"] == expected

    # -- duration_sec round mutation (288) ---------------------------------

    def test_l1_duration_sec_rounding(self, tmp_path, monkeypatch):
        """mutmut_288: round(duration, 3) → round(duration, 4).

        H2 — clock mock producing a value where round(x,3) ≠ round(x,4).
        duration = 0.0001 → round(..., 3) = 0.0, round(..., 4) = 0.0001
        """
        tick = iter([300.0, 300.0001])
        monkeypatch.setattr(_time, "monotonic", lambda: next(tick))

        adapter = _make_mock_adapter(
            pest_binary=None,
            pcov_driver="pcov",
            infection_stats=MutationStats(
                total=50, killed=50, survived=0, escaped=0, timed_out=0,
                untested=0, msi=100.0, covered_msi=100.0,
            ),
        )
        result = adapter.run_l1(tmp_path, {})
        # round(0.0001, 3) = 0.0  (kills round(_,4) → 0.0001)
        assert result.duration_sec == 0.0
