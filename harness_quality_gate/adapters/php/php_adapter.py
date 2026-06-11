"""PHP quality-gate orchestrator.

Composes the three Tier-A tool adapters (PHPStan, PHPMD, php-cs-fixer) into
the L3A ``LayerResult``.  L1, L2, L3B, and L4 are fully wired in 2.9.

Design: Component Responsibilities / php_adapter
Requirements: FR-6, FR-11, FR-13, FR-14, FR-22, US-7, US-14
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Mapping

from ...models import Finding, LayerResult, MutationStats
from ..base import BaseAdapter
from .antipattern_tier_a_php import PhpAntipatternTierAAdapter
from .composer_audit_adapter import ComposerAuditAdapter
from .dead_code_adapter import DeadCodeAdapter
from .dep_analyser_adapter import DepAnalyserAdapter
from .deptrac_adapter import DeptracAdapter
from .infection_adapter import InfectionAdapter
from .pcov_adapter import PcovAdapter
from .pest_adapter import PestAdapter
from .php_cs_fixer_adapter import PhpCsFixerAdapter
from .phpmd_adapter import PhpMdAdapter
from .phpstan_adapter import PhpStanAdapter
from .phpunit_adapter import PhpUnitAdapter
from .psalm_taint_adapter import PsalmTaintAdapter
from .security_checker_adapter import SecurityCheckerAdapter
from .weak_test_php import PhpWeakTestLayerAdapter

logger = logging.getLogger(__name__)

# -- Infection strict thresholds (FR-13, FR-14, FR-15) --------------------

_INFECTION_MIN_MSI: float = 100
_INFECTION_MIN_COVERED_MSI: float = 100


class PhpAdapter(BaseAdapter):
    """Orchestrates PHP quality tools across the five quality layers.

    Fully wired in 2.9: L3A (PHPStan + PHPMD + php-cs-fixer),
    L1 (PHPUnit/Pest + PCov/Xdebug + Infection mutation), L2
    (antipattern tier A), L3B (weak-test A1-A8), L4 (Psalm-taint,
    composer audit, security checker, dead code, dep-analyser, deptrac).
    """

    _name = "php"

    # -- construction --------------------------------------------------------

    def __init__(self) -> None:
        # Tier-A static-analysis tools (L3A)
        self._phpstan = PhpStanAdapter()
        self._phpmd = PhpMdAdapter()
        self._cs_fixer = PhpCsFixerAdapter()

        # L1 test / coverage / mutation tools
        self._phpunit = PhpUnitAdapter()
        self._pest = PestAdapter()
        self._pcov = PcovAdapter()
        self._infection = InfectionAdapter()

        # L2 antipattern tier A
        self._antipattern = PhpAntipatternTierAAdapter()

        # L3B weak-test detection
        self._weak_test = PhpWeakTestLayerAdapter()

        # L4 security + architecture tools
        self._psalm_taint = PsalmTaintAdapter()
        self._composer_audit = ComposerAuditAdapter()
        self._security_checker = SecurityCheckerAdapter()
        self._dead_code = DeadCodeAdapter()
        self._dep_analyser = DepAnalyserAdapter()
        self._deptrac = DeptracAdapter()

    # -- property interface --------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    # -- abstract: tool_versions / check_tools ----------------------------

    def tool_versions(self) -> dict[str, str]:
        """Return {tool_name: version} for all composed tools."""
        versions: dict[str, str] = {}
        for tool in (self._phpstan, self._phpmd, self._cs_fixer):
            try:
                versions[tool.name] = tool.version(Path.cwd(), env={})
            except (OSError, RuntimeError):
                versions[tool.name] = "MISSING"
        return versions

    def check_tools(self) -> list[str]:
        """Raise if any critical tool is missing; return tool list."""
        missing: list[str] = []
        for tool in (self._phpstan, self._phpmd, self._cs_fixer):
            try:
                tool.version(Path.cwd(), env={})
            except (OSError, RuntimeError):
                missing.append(tool.name)
        if missing:
            raise RuntimeError(
                f"Missing PHP tool(s): {', '.join(missing)}"
            )
        return [t.name for t in (self._phpstan, self._phpmd, self._cs_fixer)]

    # -- framework-conditional packs (FR-22) -------------------------------

    @staticmethod
    def detect_frameworks(repo: Path) -> dict[str, list[str]]:
        """Detect PHP frameworks from composer.json require keys.

        Returns {detected_framework: [packages]}.  Checks for
        symfony/framework-bundle, laravel/framework, drupal/core-composer-scaffold,
        and wordpress/wordpress (via require keys).

        Returns:
            Framework dict matching the ``Detection.frameworks`` shape.
        """
        composer_path = repo / "composer.json"
        detected: dict[str, list[str]] = {}
        if not composer_path.is_file():
            return detected

        try:
            data = json.loads(composer_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return detected

        require = data.get("require") or {}
        require_dev = data.get("require-dev") or {}
        all_deps: dict[str, str] = {**require, **require_dev}
        require_keys = set(all_deps.keys()) if isinstance(all_deps, dict) else set()

        if "symfony/framework-bundle" in require_keys:
            detected["symfony"] = ["phpstan-symfony"]
        if "laravel/framework" in require_keys:
            detected["laravel"] = ["larastan"]
        if "drupal/core-composer-scaffold" in require_keys:
            detected["drupal"] = ["phpstan-drupal"]
        if "wordpress/wordpress" in require_keys:
            detected["wordpress"] = ["phpstan-wordpress"]

        return detected

    def _injection_packages(self, frameworks: dict[str, list[str]]) -> list[str]:
        """Return the ordered list of PHPStan extension packages to inject.

        Consumes ``frameworks`` (from Detection or ``detect_frameworks``)
        and returns e.g. ``["phpstan-symfony", "larastan"]`` for a
        Symfony+Laravel project.

        Args:
            frameworks: Framework dict matching the ``Detection.frameworks``
                shape.  Keys are framework names (symfony, laravel, ...).

        Returns:
            List of PHPStan extension package names to inject.
        """
        packages: list[str] = []
        for _fw_name, pkgs in sorted(frameworks.items()):
            if pkgs:
                packages.extend(pkgs)
        return packages

    def _antipattern_invoke_and_parse(
        self, repo: Path, env: Mapping[str, str] | None = None
    ) -> list[Finding]:
        """Invoke antipattern tier-A tool and return parsed findings."""
        invocation = self._antipattern.invoke(repo, args=["analyse"], env=env)
        return self._antipattern.parse(invocation.stdout)

    @staticmethod
    def _build_phpstan_extra_config(
        injection_packages: list[str],
    ) -> str:
        """Build a ``phpstan.neon`` extension-block string for injected packages.

        Returns a minimal neon block like::

            parameters:
                bootstrapFiles:
                    - vendor/phpstan-symfony/extension.neon

        Args:
            injection_packages: PHPStan extension packages to inject.

        Returns:
            Neon config string (empty if no packages).
        """
        if not injection_packages:
            return ""

        lines: list[str] = [
            "parameters:",
            "    bootstrapFiles:",
        ]
        for pkg in sorted(injection_packages):
            lines.append(f"        - vendor/{pkg}/extension.neon")
        return "\n".join(lines)

    @staticmethod
    def _validate_infection_stats(stats: MutationStats) -> list[Finding]:
        """Validate Infection mutation-stats against strict 100/100 gate (FR-14).

        Fails when:
        - ``stats.msi < 100``
        - ``stats.coveredMsi < 100``
        - ``stats.escaped > 0``
        - ``stats.timed_out > 0`` (timeouts-as-escaped per FR-13)

        Returns findings for any violated gate.

        Args:
            stats: ``MutationStats`` from Infection output.

        Returns:
            List of ``Finding`` objects (empty if gate passes).
        """
        findings: list[Finding] = []

        if stats.msi < _INFECTION_MIN_MSI:
            findings.append(
                Finding(
                    node="infection",
                    severity="error",
                    message=(
                        f"Mutation score {stats.msi:.1f}% below hard gate "
                        f"{_INFECTION_MIN_MSI}% (FR-14)"
                    ),
                    fix_hint="Increase test coverage for mutants — see notCovered[] in checkpoint",
                    tool="infection",
                    layer="L1",
                    language="php",
                )
            )

        if stats.covered_msi < _INFECTION_MIN_COVERED_MSI:
            findings.append(
                Finding(
                    node="infection",
                    severity="error",
                    message=(
                        f"Covered mutation score {stats.covered_msi:.1f}% below "
                        f"hard gate {_INFECTION_MIN_COVERED_MSI}% (FR-14)"
                    ),
                    fix_hint="Write tests for mutants in covered code",
                    tool="infection",
                    layer="L1",
                    language="php",
                )
            )

        if stats.escaped > 0:
            findings.append(
                Finding(
                    node="infection",
                    severity="error",
                    message=(
                        f"{stats.escaped} mutant(s) escaped — "
                        f"100/100 hard gate violated (FR-14)"
                    ),
                    fix_hint="Review survived mutants and improve tests",
                    tool="infection",
                    layer="L1",
                    language="php",
                )
            )

        if stats.timed_out > 0:
            # Per FR-13: timeouts-as-escaped (maxTimeouts=0)
            findings.append(
                Finding(
                    node="infection",
                    severity="error",
                    message=(
                        f"{stats.timed_out} mutant(s) timed out — "
                        f"timeouts-as-escaped with maxTimeouts=0 (FR-13)"
                    ),
                    fix_hint="Investigate slow mutants; increase timeout or fix performance",
                    tool="infection",
                    layer="L1",
                    language="php",
                )
            )

        return findings

    @staticmethod
    def _mutation_remediation(stats: MutationStats) -> dict[str, object]:
        """Build remediation guidance for agents when the L1 Infection gate fails."""
        issues: list[str] = []
        if stats.escaped > 0:
            issues.append(f"{stats.escaped} mutant(s) escaped")
        if stats.timed_out > 0:
            issues.append(f"{stats.timed_out} mutant(s) timed out")
        if stats.msi < _INFECTION_MIN_MSI:
            issues.append(f"MSI {stats.msi:.1f}% < {_INFECTION_MIN_MSI}%")
        if stats.covered_msi < _INFECTION_MIN_COVERED_MSI:
            issues.append(f"covered MSI {stats.covered_msi:.1f}% < {_INFECTION_MIN_COVERED_MSI}%")
        return {
            "skill": "mutation-testing-guide",
            "guide": "MUTANT_KILLING_GUIDE_PHP.md",
            "instructions": "SUBAGENT_MUTATION_INSTRUCTIONS.md",
            "summary": (
                f"L1 Infection gate FAILED — {', '.join(issues)}. "
                "Read skill 'mutation-testing-guide' or MUTANT_KILLING_GUIDE_PHP.md. "
                "Priority: assertSame not assertEquals (T1), strict mock "
                "expects()->with(identicalTo()) (T2), full coverage before killing (T3). "
                "Iterate with: vendor/bin/infection --filter=<file> --show-mutations."
            ),
            "msi": stats.msi,
            "covered_msi": stats.covered_msi,
            "escaped": stats.escaped,
            "timed_out": stats.timed_out,
        }

    # -- private helpers ----------------------------------------------------

    @staticmethod
    def _collect_test_files(repo: Path) -> list[Path]:
        """Collect PHP test files under *repo* (skipping vendor)."""
        files: list[Path] = []
        try:
            for p in repo.rglob("*.php"):
                parts = [str(part) for part in p.parts]
                if any(excluded in parts for excluded in ["vendor", "node_modules"]):
                    continue
                files.append(p)
        except OSError:
            pass
        return sorted(files)

    # -- L3A (Tier A: static analysis + code quality) -----------------------

    def run_l3a(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Run PHPStan, PHPMD, php-cs-fixer, and Tier-A visitors.

        PHPStan receives framework-conditional extension injection per
        ``detection.frameworks`` (FR-22).

        Returns:
            ``LayerResult`` with merged findings from all L3A tools.
        """
        t0 = time.monotonic()
        all_findings: list[Finding] = []

        # --- Detect frameworks & build PHPStan injection list (FR-22) -------
        frameworks = self.detect_frameworks(repo)
        injection_packages = self._injection_packages(frameworks)
        if injection_packages:
            logger.info(
                "L3A PHPStan framework packs: %s",
                ", ".join(injection_packages),
            )

        # --- PHPStan — static analysis (FR-7) -----------------------------
        try:
            phpstan_findings = self._phpstan.run_l3a(repo, env)
            all_findings.extend(phpstan_findings)
            logger.info("L3A PHPStan: %d findings", len(phpstan_findings))
        except (OSError, RuntimeError) as exc:
            logger.warning("L3A PHPStan skipped: %s", exc)

        # --- PHPMD — antipattern analysis (FR-9) --------------------------
        try:
            phpmd_findings = self._phpmd.run_l3a(repo, env)
            all_findings.extend(phpmd_findings)
            logger.info("L3A PHPMD: %d findings", len(phpmd_findings))
        except (OSError, RuntimeError) as exc:
            logger.warning("L3A PHPMD skipped: %s", exc)

        # --- php-cs-fixer — code style (FR-8) -----------------------------
        try:
            args = [
                "fix",
                "--dry-run",
                "--format=json",
                "--no-progress",
                str(repo),
            ]
            invocation = self._cs_fixer.invoke(
                repo, args, env=env, timeout=300.0
            )
            cs_findings = self._cs_fixer.parse(
                invocation.stdout, invocation.stderr, invocation.exitcode
            )
            all_findings.extend(cs_findings)
            logger.info("L3A php-cs-fixer: %d findings", len(cs_findings))
        except (OSError, RuntimeError) as exc:
            logger.warning("L3A php-cs-fixer skipped: %s", exc)

        # --- Tier-A visitors — antipatterns not covered by PHPMD ----------
        try:
            tier_a_findings = self._antipattern_invoke_and_parse(repo, env)
            all_findings.extend(tier_a_findings)
            logger.info("L3A tier-A visitors: %d findings", len(tier_a_findings))
        except (OSError, RuntimeError) as exc:
            logger.warning("L3A tier-A visitors skipped: %s", exc)

        duration = time.monotonic() - t0
        passed = len(all_findings) == 0

        return LayerResult(
            layer="L3A",
            language="php",
            passed=passed,
            findings=all_findings,
            duration_sec=round(duration, 3),
        )

    # -- L1 (Unit-test + coverage + mutation) ------------------------------

    def run_l1(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Run PHPUnit/Pest tests, check coverage, and run Infection mutation.

        Sequence (per design doc L1 sequence diagram):
        1. PCOV probe → coverage driver (PCOV or Xdebug fallback)
        2. PHPUnit execution with JUnit XML + coverage
        3. Pest detection — if Pest without mutate plugin, mark mutation_skipped
        4. Infection mutation testing with 100/100 hard gate (FR-14)

        Args:
            repo: Root path of the PHP repository.
            env: Environment variables.

        Returns:
            ``LayerResult`` with test/coverage/mutation findings.
        """
        t0 = time.monotonic()
        all_findings: list[Finding] = []

        # --- 1. Coverage driver probe (FR-28) ----------------------------
        driver: str | None = "unknown"
        logger.debug("L1 driver initial value: %s", driver)
        try:
            driver = self._pcov.probe(repo)
            logger.info("L1 coverage driver: %s", driver)
        except (OSError, RuntimeError) as exc:
            logger.warning("L1 coverage driver probe failed: %s", exc)
            all_findings.append(
                Finding(
                    node="pcov",
                    severity="error",
                    message=f"Coverage driver probe failed: {exc}",
                    tool="pcov",
                    layer="L1",
                    language="php",
                )
            )

        # --- 2. Test execution (PHPUnit or Pest) --------------------------
        try:
            # Check if Pest is available (FR-11)
            pest_binary = self._pest._pest_binary(repo)
            pest_has_mutate = self._pest._has_mutate_plugin(repo)
            is_pest_project = pest_binary is not None

            if is_pest_project:
                # Pest project — use Pest for test execution
                test_findings = self._run_pest_tests(repo, env)
                all_findings.extend(test_findings)
                logger.info("L1 Pest tests: %d findings", len(test_findings))
            else:
                # PHPUnit project
                test_findings = self._run_phpunit_tests(repo, env)
                all_findings.extend(test_findings)
                logger.info("L1 PHPUnit tests: %d findings", len(test_findings))

        except (OSError, RuntimeError) as exc:
            logger.warning("L1 test execution skipped: %s", exc)
            all_findings.append(
                Finding(
                    node="test",
                    severity="warning",
                    message=f"Test execution skipped: {exc}",
                    tool="phpunit",
                    layer="L1",
                    language="php",
                )
            )

        # --- 3. Mutation testing (FR-13, FR-14, TD-6) ---------------------
        mutation_stats: MutationStats | None = None
        mutation_skipped: str | None = None
        mutation_remediation: dict[str, object] | None = None

        try:
            pest_binary = self._pest._pest_binary(repo)
            pest_has_mutate = self._pest._has_mutate_plugin(repo)
            is_pest_project = pest_binary is not None

            if is_pest_project and not pest_has_mutate:
                # TD-6: Pest without mutate plugin → skip mutation
                mutation_skipped = "pest-plugin-mutate not installed"
                all_findings.append(
                    Finding(
                        node="mutation",
                        severity="info",
                        message=(
                            f"Mutation testing skipped: {mutation_skipped} (TD-6)"
                        ),
                        fix_hint="composer require --dev pestphp/pest-plugin-mutate",
                        tool="infection",
                        layer="L1",
                        language="php",
                    )
                )
                logger.info("L1 mutation skipped (TD-6): %s", mutation_skipped)
            else:
                # Run Infection with strict thresholds (FR-13, FR-14)
                mutation_stats = self._run_infection(
                    repo, env, is_pest_project
                )

                # Hard-gate: if env flag set and Infection unavailable, fail hard
                if mutation_stats is None and env.get("HARNESS_INFECTION_REQUIRED"):
                    all_findings.append(
                        Finding(
                            node="infection",
                            severity="error",
                            message=(
                                "Infection mutation gate required but unavailable "
                                "(HARNESS_INFECTION_REQUIRED=1). "
                                "Ensure Infection is installed via install-tools."
                            ),
                            tool="infection",
                            layer="L1",
                            language="php",
                        )
                    )
                    logger.error(
                        "L1 Infection required but unavailable (HARNESS_INFECTION_REQUIRED=1)"
                    )

                if mutation_stats is not None:
                    # Gate check (FR-14)
                    gate_findings = self._validate_infection_stats(mutation_stats)
                    all_findings.extend(gate_findings)
                    if gate_findings:
                        mutation_remediation = self._mutation_remediation(mutation_stats)
                    logger.info(
                        "L1 Infection MSI=%.1f coveredMsi=%.1f escaped=%d",
                        mutation_stats.msi,
                        mutation_stats.covered_msi,
                        mutation_stats.escaped,
                    )

        except (OSError, RuntimeError) as exc:
            logger.warning("L1 mutation testing skipped: %s", exc)

        duration = time.monotonic() - t0

        # Build mutation-specific metadata for checkpoint v2
        mutation_meta: dict = {}
        if mutation_skipped is not None:
            mutation_meta["mutation_skipped"] = mutation_skipped
        if mutation_stats is not None:
            mutation_meta["mutation"] = {
                "killed": mutation_stats.killed,
                "survived": mutation_stats.survived,
                "timed_out": mutation_stats.timed_out,
                "escaped": mutation_stats.escaped,
                "untested": mutation_stats.untested,
                "msi": round(mutation_stats.msi, 4),
                "covered_msi": round(mutation_stats.covered_msi, 4),
            }
            if mutation_remediation is not None:
                mutation_meta["remediation"] = mutation_remediation

        passed = len(all_findings) == 0

        return LayerResult(
            layer="L1",
            language="php",
            passed=passed,
            findings=all_findings,
            duration_sec=round(duration, 3),
            tool_specific={
                "coverage_driver": driver if driver is not None else "unknown",
                "infection_thresholds": {
                    "min_msi": _INFECTION_MIN_MSI,
                    "min_covered_msi": _INFECTION_MIN_COVERED_MSI,
                    "timeouts_as_escaped": True,
                    "max_timeouts": 0,
                },
                **mutation_meta,
            },
        )

    def _pcov_initial_tests_option(self) -> str:
        """Return a PHP -d flag string to enable PCOV for Infection's initial test run.

        Returns empty string if PCOV is already loaded (no extra flag needed)
        or if PCOV cannot be found on this system.
        """
        import subprocess as _sp  # noqa: PLC0415
        import glob as _glob  # noqa: PLC0415

        # If PCOV is already loaded by PHP, no extra flag needed.
        try:
            result = _sp.run(
                ["php", "-m"],
                capture_output=True, text=True, timeout=5
            )
            if "pcov" in result.stdout.lower():
                return ""
        except (OSError, _sp.TimeoutExpired):
            return ""

        # Search for pcov.so in known locations.
        candidates = [
            "/tmp/pcov-extract/usr/lib/php/*/pcov.so",
            "/usr/lib/php/*/pcov.so",
        ]
        for pattern in candidates:
            found = _glob.glob(pattern)
            if found:
                return f"-dextension={found[0]}"

        return ""

    def _run_phpunit_tests(
        self, repo: Path, env: Mapping[str, str]
    ) -> list[Finding]:
        """Run PHPUnit tests and parse JUnit XML output."""
        findings: list[Finding] = []
        try:
            invocation = self._phpunit.invoke(
                repo, ["--log-junit", "junit.xml"],
                env=env, timeout=300.0
            )
            # Parse JUnit XML
            findings = self._phpunit.parse(
                invocation.stdout, invocation.stderr, invocation.exitcode
            )
        except (OSError, RuntimeError):
            # Tool not found — skip silently
            pass
        return findings

    def _run_pest_tests(
        self, repo: Path, env: Mapping[str, str]
    ) -> list[Finding]:
        """Run Pest tests and return test findings."""
        findings: list[Finding] = []
        try:
            invocation = self._pest.invoke(
                repo, ["--no-output"],
                env=env, timeout=300.0
            )
            # Pest parse returns empty list (it's a test runner, not analysis)
            # Findings are derived from exit code
            if invocation.exitcode != 0:
                findings.append(
                    Finding(
                        node="pest",
                        severity="error",
                        message=f"Pest tests failed (exit {invocation.exitcode})",
                        fix_hint="Run ``vendor/bin/pest`` locally to see failures",
                        tool="pest",
                        layer="L1",
                        language="php",
                    )
                )
        except (OSError, RuntimeError):
            # Tool not found — skip silently
            pass
        return findings

    def _run_infection(
        self,
        repo: Path,
        env: Mapping[str, str],
        is_pest_project: bool,
    ) -> MutationStats | None:
        """Run Infection mutation testing with strict thresholds.

        Configures thresholds: min_msi=100, min_covered_msi=100,
        timeoutsAsEscaped=true, maxTimeouts=0 (FR-13).

        Args:
            repo: Root path of the PHP repository.
            env: Environment variables.
            is_pest_project: Whether to use Pest as the test framework.

        Returns:
            ``MutationStats`` or None if Infection is unavailable.
        """
        try:
            # Build infection arguments with strict thresholds.
            # Flags compatible with Infection 0.29.x (--formatter is "dot"/"progress", not "json").
            args: list[str] = [
                "--no-progress",
                "--threads=max",
                "--min-msi=100",
                "--min-covered-msi=100",
            ]

            # Pass PCOV to PHPUnit's initial test run for coverage collection.
            pcov_flag = self._pcov_initial_tests_option()
            if pcov_flag:
                args.append(f"--initial-tests-php-options={pcov_flag}")

            if is_pest_project:
                args.append("--test-framework=pest")

            invocation = self._infection.invoke(
                repo, args, env=env, timeout=600.0
            )

            # Binary missing: invoke() returns exitcode=3 with empty stdout.
            if invocation.exitcode == 3 and not invocation.stdout.strip():
                logger.warning("Infection unavailable (exitcode=3, no output)")
                return None

            # Distinguish infra errors from threshold failures.
            # A threshold failure (MSI < 100%) produces text output with mutation
            # stats and a non-zero exit; that is NOT an infra error.
            # An infra error (no PCOV, invalid flags) produces error text with NO stats.
            has_stats = any(
                marker in (invocation.stdout + invocation.stderr)
                for marker in ("Mutation Score Indicator", "mutations were generated", "mutants were killed")
            )
            if not has_stats and invocation.exitcode != 0:
                logger.warning(
                    "Infection infra error (exitcode=%d, no stats): %s",
                    invocation.exitcode,
                    (invocation.stderr or invocation.stdout)[:200],
                )
                return None

            # Parse JSON log → MutationStats
            stats = self._infection.parse(invocation.stdout, invocation.stderr, invocation.exitcode)
            return stats

        except (OSError, RuntimeError) as exc:
            logger.warning("Infection invocation failed: %s", exc)
            return None

    # -- L2 (Test quality: weak-test detection) ------------------------------

    def run_l2(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Run all weak-test visitors (A1-A8) via PhpWeakTestLayerAdapter.

        L2 is the test-quality layer per the spec glossary (weak-test
        detection + diversity + mutation kill-map).  Detects:
        - A1: Zero-assertion tests
        - A2-PHP: Mocks-only tests
        - A3: SUT-mocked tests
        - A4: Overly-broad expectException
        - A5: markTestSkipped / markTestIncomplete
        - A6: @codeCoverageIgnore spam
        - A7: Only constructor + instanceof
        - A8: Assertion on tautology

        Returns:
            ``LayerResult`` with weak-test findings.
        """
        return self._weak_test.run_l2(repo, env)

    # -- L3B (Deep quality: antipatterns Tier A + architecture) -------------

    def run_l3b(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Run deep-quality checks: antipattern tier-A + deptrac architecture.

        L3B is the deep-quality layer per the spec glossary (SOLID +
        antipatterns + architecture).  The deterministic part runs here:

        - Antipattern tier-A (PHPMD + nikic/php-parser visitors merge).
          PHPMD covers 13 antipattern categories; the visitor runner covers
          4 additional patterns.  The 8 PHPMD antipatterns with no visitor
          equivalent are tracked via ``PhpAntipatternTierAAdapter.parity_gap``.
        - deptrac architecture violations (FR-19).

        The Tier B BMAD multi-judge consensus is orchestrated by the LLM
        through the skill steps, not by this adapter.

        Returns:
            ``LayerResult`` with merged antipattern + architecture findings.
        """
        t0 = time.monotonic()
        all_findings: list[Finding] = []

        try:
            # Invoke antipattern tier-A (PHPMD + visitors)
            invocation = self._antipattern.invoke(
                repo, [], env=env, timeout=300.0
            )
            findings = self._antipattern.parse(invocation.stdout)
            all_findings.extend(findings)
            logger.info("L3B antipattern-tier-A: %d findings", len(findings))
        except (OSError, RuntimeError) as exc:
            logger.warning("L3B antipattern-tier-A skipped: %s", exc)

        # --- deptrac architecture violations (FR-19) -------------------
        try:
            deptrac_invocation = self._deptrac.invoke(
                repo,
                ["--formatter=json"],
                env=env,
                timeout=300.0,
            )
            deptrac_findings = self._deptrac.parse(
                deptrac_invocation.stdout,
                deptrac_invocation.stderr,
                deptrac_invocation.exitcode,
            )
            all_findings.extend(deptrac_findings)
            logger.info("L3B deptrac: %d findings", len(deptrac_findings))
        except (OSError, RuntimeError) as exc:
            logger.warning("L3B deptrac skipped: %s", exc)

        duration = time.monotonic() - t0
        passed = len(all_findings) == 0

        return LayerResult(
            layer="L3B",
            language="php",
            passed=passed,
            findings=all_findings,
            duration_sec=round(duration, 3),
        )

    # -- L4 (Security + architecture) --------------------------------------

    def run_l4(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Run all L4 security tools.

        Tools:
        - Psalm taint analysis (FR-21, US-9)
        - Composer audit (FR-21)
        - local-php-security-checker (FR-21)
        - ShipMonk dead-code-detector (FR-21)
        - ShipMonk composer-dependency-analyser (FR-21)

        deptrac (architecture) runs in L3B — deep quality per the spec
        glossary.

        Returns:
            ``LayerResult`` with security findings.
        """
        t0 = time.monotonic()
        all_findings: list[Finding] = []

        # --- Psalm taint analysis ----------------------------------------
        try:
            psalm_invocation = self._psalm_taint.invoke(
                repo,
                ["--taint-analysis", "--no-progress"],
                env=env,
                timeout=600.0,
            )
            psalm_findings = self._psalm_taint.parse(
                psalm_invocation.stdout,
                psalm_invocation.stderr,
                psalm_invocation.exitcode,
            )
            all_findings.extend(psalm_findings)
            logger.info("L4 Psalm taint: %d findings", len(psalm_findings))
        except (OSError, RuntimeError) as exc:
            logger.warning("L4 Psalm taint skipped: %s", exc)

        # --- Composer security audit (FR-21) ---------------------------
        try:
            audit_invocation = self._composer_audit.invoke(
                repo,
                ["--format=json", "--no-dev"],
                env=env,
                timeout=300.0,
            )
            audit_findings = self._composer_audit.parse(
                audit_invocation.stdout,
                audit_invocation.stderr,
                audit_invocation.exitcode,
            )
            all_findings.extend(audit_findings)
            logger.info("L4 composer-audit: %d findings", len(audit_findings))
        except (OSError, RuntimeError) as exc:
            logger.warning("L4 composer-audit skipped: %s", exc)

        # --- local-php-security-checker (FR-21) ------------------------
        try:
            checker_invocation = self._security_checker.invoke(
                repo, ["--format=json"],
                env=env,
                timeout=300.0,
            )
            checker_findings = self._security_checker.parse(
                checker_invocation.stdout,
                checker_invocation.stderr,
                checker_invocation.exitcode,
            )
            all_findings.extend(checker_findings)
            logger.info("L4 security-checker: %d findings", len(checker_findings))
        except (OSError, RuntimeError) as exc:
            logger.warning("L4 security-checker skipped: %s", exc)

        # --- ShipMonk dead-code-detector (FR-21) -----------------------
        try:
            dead_code_invocation = self._dead_code.invoke(
                repo,
                ["--format=json"],
                env=env,
                timeout=300.0,
            )
            dead_code_findings = self._dead_code.parse(
                dead_code_invocation.stdout,
                dead_code_invocation.stderr,
                dead_code_invocation.exitcode,
            )
            all_findings.extend(dead_code_findings)
            logger.info("L4 dead-code: %d findings", len(dead_code_findings))
        except (OSError, RuntimeError) as exc:
            logger.warning("L4 dead-code skipped: %s", exc)

        # --- ShipMonk dep-analyser (FR-21) -----------------------------
        try:
            dep_analyser_invocation = self._dep_analyser.invoke(
                repo,
                ["--format=json"],
                env=env,
                timeout=300.0,
            )
            dep_analyser_findings = self._dep_analyser.parse(
                dep_analyser_invocation.stdout,
                dep_analyser_invocation.stderr,
                dep_analyser_invocation.exitcode,
            )
            all_findings.extend(dep_analyser_findings)
            logger.info("L4 dep-analyser: %d findings", len(dep_analyser_findings))
        except (OSError, RuntimeError) as exc:
            logger.warning("L4 dep-analyser skipped: %s", exc)

        duration = time.monotonic() - t0
        passed = len(all_findings) == 0

        return LayerResult(
            layer="L4",
            language="php",
            passed=passed,
            findings=all_findings,
            duration_sec=round(duration, 3),
        )
