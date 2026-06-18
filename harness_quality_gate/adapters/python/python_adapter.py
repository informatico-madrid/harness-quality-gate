"""Python quality-gate orchestrator.

Composes the Python toolchain into the five quality layers per the spec
glossary:

  L3A  smoke          ruff + pyright
  L1   test execution pytest + mutmut (mutation gate)
  L2   test quality   weak-test detection (A1-A8) + diversity
  L3B  deep quality   SOLID metrics + antipattern Tier A (Tier B BMAD is
                      LLM-orchestrated through the skill steps)
  L4   security       bandit + vulture (dead code) + deptry (dependencies)

Design: Component Responsibilities / python_adapter
Requirements: FR-5, FR-41, US-3
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Mapping

from ...bootstrap import resolve_tool, ToolNotAvailable
from ...bmad.diversity_metric import diversity
from ...models import Finding, LayerResult, MutationStats
from ..base import BaseAdapter, package_dirs
from .antipattern_tier_a import run_tier_a
from .bandit_adapter import BanditAdapter
from .deptry_adapter import DeptryAdapter
from .mutmut_adapter import MutmutAdapter
from .pyright_adapter import PyrightAdapter
from .pytest_adapter import PytestAdapter
from .ruff_adapter import RuffAdapter
from .solid_metrics import analyze_solid
from .vulture_adapter import VultureAdapter
from .weak_test import run_weak_test_analysis

# reason: logger name mutation doesn't change observability; only the __name__ label differs.
# audited: 2026-06-04
logger = logging.getLogger(__name__)  # pragma: no mutate


# ---------------------------------------------------------------------------
# PythonAdapter
# ---------------------------------------------------------------------------

class PythonAdapter(BaseAdapter):
    """Orchestrates Python quality tools across the five quality layers."""

    _name = "python"

    def __init__(self) -> None:
        """Instantiate all tool adapters."""
        self.ruff = RuffAdapter()
        self.pyright = PyrightAdapter()
        self.pytest = PytestAdapter()
        self.mutmut = MutmutAdapter()
        self.bandit = BanditAdapter()
        self.vulture = VultureAdapter()
        self.deptry = DeptryAdapter()

    # -- abstract: tool_versions / check_tools ----------------------------

    def tool_versions(self) -> dict[str, str]:
        """Return {tool_name: version} for every Python tool."""
        versions: dict[str, str] = {}
        for adapter in (self.ruff, self.pyright, self.pytest, self.mutmut,
                        self.bandit, self.vulture, self.deptry):
            try:
                versions[adapter.name] = adapter.version(Path("."), {})
            except (RuntimeError, OSError):
                versions[adapter.name] = "MISSING"
        return versions

    def check_tools(self) -> list[str]:
        """Return the names of critical Python tools."""
        missing: list[str] = []
        for tool in ("ruff", "pyright"):
            try:
                resolve_tool(tool, Path("."))
            except ToolNotAvailable:
                missing.append(tool)
        if missing:
            raise RuntimeError(
                f"Missing Python tool(s): {', '.join(missing)}"
            )
        return ["ruff", "pyright"]

    # -- L3A (static analysis + type checking) ----------------------------

    def run_l3a(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Run ruff check and pyright; merge findings."""
        t0 = time.monotonic()
        all_findings: list[Finding] = []

        ruff_findings = self._run_ruff(repo, env)
        all_findings.extend(ruff_findings)
        logger.info("ruff: %d findings", len(ruff_findings))

        pyright_findings = self._run_pyright(repo, env)
        all_findings.extend(pyright_findings)
        logger.info("pyright: %d findings", len(pyright_findings))

        duration = time.monotonic() - t0
        # Uniform severity policy: only error findings gate (warnings/info
        # are reported but non-blocking), same as L1/L4 and all PHP layers.
        passed = not any(f.severity == "error" for f in all_findings)

        return LayerResult(
            layer="L3A",
            language="python",
            passed=passed,
            findings=all_findings,
            duration_sec=round(duration, 3),
        )

    # -- L1 (test execution: pytest + mutation gate) -----------------------

    def run_l1(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Run pytest + mutmut; merge findings and mutation stats.

        L1 is the test-execution layer per the spec glossary: test run,
        coverage, and the mutation gate (parity with PHP's Infection L1).
        If mutmut is not on PATH the mutation part degrades to empty stats
        (graceful skip), matching the original Python behaviour.
        """
        t0 = time.monotonic()
        all_findings: list[Finding] = []

        pytest_findings = self._run_pytest(repo, env)
        all_findings.extend(pytest_findings)
        logger.info("pytest: %d findings", len(pytest_findings))

        mutation_stats, mutmut_run_ok = self._run_mutmut(repo, env)
        mutation_passed = mutmut_run_ok and mutation_stats.survived == 0 and mutation_stats.timed_out == 0

        tool_spec: dict[str, object] = {"mutation_stats": mutation_stats}
        if not mutation_passed:
            tool_spec["remediation"] = self._mutation_remediation(mutation_stats)

        duration = time.monotonic() - t0
        # Severity policy: only error-severity findings gate (skipped tests
        # map to info and must not block — simulation bug H9).
        has_errors = any(f.severity == "error" for f in all_findings)
        passed = not has_errors and mutation_passed

        return LayerResult(
            layer="L1",
            language="python",
            passed=passed,
            findings=all_findings,
            duration_sec=round(duration, 3),
            tool_specific=tool_spec,
        )

    # -- L2 (test quality: weak-test detection + diversity) ----------------

    def run_l2(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Run weak-test detection (A1-A8) + test diversity metrics.

        L2 is the test-quality layer per the spec glossary. The diversity
        report is informational and travels in ``tool_specific``. The gate
        is decided by ERROR-severity weak-test findings only (A1, A4, A6,
        A7, A8); WARNING-severity rules (A2, A3, A5, A9) inform but do not
        fail the layer.
        """
        t0 = time.monotonic()

        findings = self._weak_test_findings(repo)
        logger.info("weak-test: %d findings", len(findings))

        diversity_report = diversity(repo, "python")
        logger.info(
            "diversity: score %s over %s tests",
            diversity_report.get("diversity_score"),
            diversity_report.get("total_tests"),
        )

        duration = time.monotonic() - t0
        passed = not any(f.severity == "error" for f in findings)

        return LayerResult(
            layer="L2",
            language="python",
            passed=passed,
            findings=findings,
            duration_sec=round(duration, 3),
            tool_specific={"diversity": diversity_report},
        )

    # -- L3B (deep quality: SOLID + antipattern Tier A) ---------------------

    def run_l3b(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Run SOLID metrics + antipattern Tier A (deterministic deep quality).

        L3B is the deep-quality layer per the spec glossary. The Tier B
        BMAD multi-judge consensus is orchestrated by the LLM through the
        skill steps, not by this adapter.
        """
        t0 = time.monotonic()
        all_findings: list[Finding] = []

        solid_findings = self._solid_findings(repo)
        all_findings.extend(solid_findings)
        logger.info("solid-metrics: %d findings", len(solid_findings))

        tier_a_findings = self._tier_a_findings(repo)
        all_findings.extend(tier_a_findings)
        logger.info("antipattern-tier-a: %d findings", len(tier_a_findings))

        duration = time.monotonic() - t0
        # Uniform severity policy: only error findings gate; solid-metrics
        # and Tier A emit warnings (heuristic counsel, self-eval F11).
        passed = not any(f.severity == "error" for f in all_findings)

        return LayerResult(
            layer="L3B",
            language="python",
            passed=passed,
            findings=all_findings,
            duration_sec=round(duration, 3),
        )

    @staticmethod
    def _mutation_remediation(stats: MutationStats) -> dict[str, object]:
        """Build remediation guidance for agents when the L1 mutation gate fails."""
        issues: list[str] = []
        if stats.survived > 0:
            issues.append(f"{stats.survived} mutant(s) survived")
        if stats.timed_out > 0:
            issues.append(f"{stats.timed_out} mutant(s) timed out")
        return {
            "skill": "mutation-testing-guide",
            "guide": "MUTANT_KILLING_GUIDE.md",
            "instructions": "SUBAGENT_MUTATION_INSTRUCTIONS.md",
            "summary": (
                f"L1 FAILED — {', '.join(issues)}. "
                "Read skill 'mutation-testing-guide' or MUTANT_KILLING_GUIDE.md Part II "
                "(cases H1-H12). "
                "Priority: assert_called_once_with complete (§4.4), dense assertions (§4.1), "
                "boundary tests (§4.2). H1=passthrough to mocked deps is the dominant pattern."
            ),
            "msi": stats.msi,
            "survived": stats.survived,
            "timed_out": stats.timed_out,
        }

    # Required L4 tools per language. If a required tool is missing from PATH,
    # L4 must FAIL rather than pass vacuously (bug H15).
    _REQUIRED_L4_TOOLS: dict[str, tuple[str, ...]] = {
        "python": ("bandit",),
        "php": (),
    }

    def run_l4(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Run bandit, vulture, deptry; merge security findings.

        vulture and deptry are the Python equivalents of PHP's
        dead-code-detector and composer-dependency-analyser, which run in
        L4 per the spec glossary (security defense: dep-analysis).
        """
        t0 = time.monotonic()
        all_findings: list[Finding] = []
        required_tools_skipped: list[str] = []

        bandit_findings = self._run_bandit(repo, env)
        all_findings.extend(bandit_findings)
        logger.info("bandit: %d findings", len(bandit_findings))
        if not bandit_findings:
            try:
                resolve_tool("bandit", repo)
            except ToolNotAvailable:
                logger.warning("bandit not found on PATH or .venv -- required L4 tool missing")
                required_tools_skipped.append("bandit")

        vulture_findings = self._run_vulture(repo, env)
        all_findings.extend(vulture_findings)
        logger.info("vulture: %d findings", len(vulture_findings))

        deptry_findings = self._run_deptry(repo, env)
        all_findings.extend(deptry_findings)
        logger.info("deptry: %d findings", len(deptry_findings))

        duration = time.monotonic() - t0
        # Severity policy: only error-severity findings block the gate
        # (bandit LOW/info -- e.g. B101 asserts in tests -- must not fail a
        # clean repo; simulation bug H1).
        # Required-tools policy: if a required L4 tool is missing, gate fails
        # rather than pass vacuously (bug H15).
        required_tools = self._REQUIRED_L4_TOOLS.get(self._name, ())
        for tool_name in required_tools:
            if tool_name not in required_tools_skipped:
                try:
                    resolve_tool(tool_name, repo)
                except ToolNotAvailable:
                    required_tools_skipped.append(tool_name)

        if required_tools_skipped:
            all_findings.append(
                Finding(
                    node="L4",
                    severity="error",
                    message="Required L4 tool(s) not installed: " + ", ".join(required_tools_skipped) + ". Install them to enable full security scanning.",
                    tool="L4",
                    layer="L4",
                    language="python",
                )
            )

        passed = not any(f.severity == "error" for f in all_findings)

        return LayerResult(
            layer="L4",
            language="python",
            passed=passed,
            findings=all_findings,
            duration_sec=round(duration, 3),
        )

    # -- in-process analysis helpers (L2 / L3B) -----------------------------

    @staticmethod
    def _src_dir(repo: Path) -> Path:
        """Return the source dir: ``src/``, else the root package, else repo.

        Falling straight back to the repo walked ``.venv/`` and ``mutants/``
        too — L2/L3B hung for minutes on real repos (self-eval F10).
        """
        src = repo / "src"
        if src.is_dir():
            return src
        pkgs = package_dirs(repo)
        if pkgs:
            return repo / pkgs[0]
        return repo

    def _weak_test_findings(self, repo: Path) -> list[Finding]:
        """Run weak-test analysis (A1-A8) and convert violations to Findings."""
        tests_dir = repo / "tests"
        if not tests_dir.is_dir():
            logger.warning("no tests/ directory in %s, skipping weak-test analysis", repo)
            return []
        report = run_weak_test_analysis(str(tests_dir), str(self._src_dir(repo)))
        findings: list[Finding] = []
        for weak in report.get("weak_tests") or []:
            node = f"{weak.get('file', '')}:{weak.get('lineno', 0)}"
            for violation in weak.get("violations") or []:
                findings.append(
                    Finding(
                        node=node,
                        severity="error" if violation.get("severity") == "ERROR" else "warning",
                        message=f"{weak.get('name', '')}: {violation.get('description', '')}",
                        tool="weak-test",
                        layer="L2",
                        language="python",
                        rule_id=violation.get("rule"),
                    )
                )
        return findings

    def _solid_findings(self, repo: Path) -> list[Finding]:
        """Run SOLID metrics and convert per-principle violations to Findings."""
        report = analyze_solid(self._src_dir(repo))
        findings: list[Finding] = []
        for principle in ("S", "O", "L", "I", "D"):
            data = report.get(principle) or {}
            if data.get("status") != "FAIL":
                continue
            for violation in data.get("violations") or []:
                if "issues" in violation:
                    detail = "; ".join(violation["issues"])
                else:
                    detail = violation.get("issue") or str(violation)
                node = violation.get("class") or violation.get("file") or principle
                findings.append(
                    Finding(
                        node=str(node),
                        severity="warning",
                        message=f"SOLID {principle}: {detail}",
                        tool="solid-metrics",
                        layer="L3B",
                        language="python",
                        rule_id=f"SOLID-{principle}",
                    )
                )
        return findings

    def _tier_a_findings(self, repo: Path) -> list[Finding]:
        """Run antipattern Tier A and convert FAIL violations to Findings."""
        report = run_tier_a(str(self._src_dir(repo)))
        findings: list[Finding] = []
        for ap_id in sorted(report):
            data = report[ap_id]
            if data.get("status") != "FAIL":
                continue
            for violation in data.get("violations") or []:
                node = violation.get("class") or violation.get("file") or ap_id
                lineno = violation.get("lineno")
                findings.append(
                    Finding(
                        node=f"{node}:{lineno}" if lineno else str(node),
                        severity="warning",
                        message=f"{violation.get('name', ap_id)}: {violation.get('issue', '')}",
                        tool="antipattern-tier-a",
                        layer="L3B",
                        language="python",
                        rule_id=ap_id,
                    )
                )
        return findings

    # -- private helpers --------------------------------------------------

    def _run_ruff(self, repo: Path, env: Mapping[str, str]) -> list[Finding]:
        """Invoke ruff and parse findings.

        Uses :func:`resolve_tool` to locate the ruff binary, which handles
        venv-priority internally.
        """
        try:
            binary = str(resolve_tool("ruff", repo))
        except ToolNotAvailable:
            logger.warning("ruff not found on PATH or .venv, skipping")
            return []
        try:
            inv = self.ruff.invoke(repo, [], env=dict(env) if env else {})
            return self.ruff.parse(inv.stdout, inv.stderr, inv.exitcode)
        except (OSError, RuntimeError) as exc:
            logger.warning("ruff invocation failed: %s", exc)
            return []

    def _run_pyright(self, repo: Path, env: Mapping[str, str]) -> list[Finding]:
        """Invoke pyright and parse findings."""
        try:
            binary = str(resolve_tool("pyright", repo))
        except ToolNotAvailable:
            logger.warning("pyright not found on PATH or .venv, skipping")
            return []
        try:
            inv = self.pyright.invoke(
                repo, [], env=dict(env) if env else {},
                python_path=sys.executable,
            )
            return self.pyright.parse(inv.stdout, inv.stderr, inv.exitcode)
        except (OSError, RuntimeError) as exc:
            logger.warning("pyright invocation failed: %s", exc)
            return []

    def _run_pytest(self, repo: Path, env: Mapping[str, str]) -> list[Finding]:
        """Invoke pytest and parse JUnit XML findings.

        Uses the venv pytest via ``sys.executable -m pytest`` which
        automatically resolves to the venv's Python interpreter.
        """
        if not sys.executable:
            logger.warning("Python interpreter not found (sys.executable empty), skipping")
            return []

        venv_dir: str | None = None
        if os.path.isfile(str(repo / ".venv" / "bin" / "pytest")):
            venv_dir = str(repo / ".venv" / "bin")

        try:
            if venv_dir:
                patched_env = dict(env) if env else {}
                prev_path = patched_env.get("PATH", os.environ.get("PATH", ""))
                patched_env["PATH"] = venv_dir + os.pathsep + prev_path
                env = patched_env  # type: ignore[assignment]
            inv = self.pytest.invoke(repo, [], env=dict(env) if env else {})
            return self.pytest.parse(inv.stdout, inv.stderr, inv.exitcode)
        except (OSError, RuntimeError) as exc:
            logger.warning("pytest invocation failed: %s", exc)
            return []

    def _run_vulture(self, repo: Path, env: Mapping[str, str]) -> list[Finding]:
        """Invoke vulture and parse dead-code findings."""
        try:
            binary = str(resolve_tool("vulture", repo))
        except ToolNotAvailable:
            logger.warning("vulture not found on PATH or .venv, skipping")
            return []
        try:
            inv = self.vulture.invoke(repo, [], env=dict(env) if env else {})
            return self.vulture.parse(inv.stdout, inv.stderr, inv.exitcode)
        except (OSError, RuntimeError) as exc:
            logger.warning("vulture invocation failed: %s", exc)
            return []

    def _run_deptry(self, repo: Path, env: Mapping[str, str]) -> list[Finding]:
        """Invoke deptry and parse dependency findings."""
        try:
            binary = str(resolve_tool("deptry", repo))
        except ToolNotAvailable:
            logger.warning("deptry not found on PATH or .venv, skipping")
            return []
        try:
            inv = self.deptry.invoke(repo, [], env=dict(env) if env else {})
            return self.deptry.parse(inv.stdout, inv.stderr, inv.exitcode)
        except (OSError, RuntimeError) as exc:
            logger.warning("deptry invocation failed: %s", exc)
            return []

    def _run_mutmut(self, repo: Path, env: Mapping[str, str]):
        """Invoke mutmut and return (MutationStats, run_ok).

        Returns a tuple of (MutationStats, bool) where run_ok is False
        when the mutmut run failed or the tool is not found.

        Uses :func:`resolve_tool` to locate the mutmut binary, which
        handles venv-priority internally.
        """
        empty_stats = MutationStats(
            total=0, killed=0, survived=0, timed_out=0,
            escaped=0, untested=0, msi=0.0, covered_msi=0.0,
        )
        try:
            binary = str(resolve_tool("mutmut", repo))
        except ToolNotAvailable:
            logger.warning("mutmut not found on PATH or .venv, returning empty stats")
            return (empty_stats, False)

        try:
            # Execute the campaign first (parity with PHP's Infection);
            # ``mutmut results`` alone is empty on a fresh repo (bug H2).
            run_inv = self.mutmut.run(repo, env=dict(env) if env else {})
            run_ok = run_inv.exitcode == 0
            if not run_ok:
                logger.warning("mutmut run exited %d: %s",
                               run_inv.exitcode, run_inv.stderr.strip())
            inv = self.mutmut.invoke(repo, [], env=dict(env) if env else {})
            stats = self.mutmut.parse(inv.stdout, inv.stderr, inv.exitcode)
            return (stats, run_ok)
        except (OSError, RuntimeError) as exc:
            logger.warning("mutmut invocation failed: %s", exc)
            return (empty_stats, False)

    def _run_bandit(self, repo: Path, env: Mapping[str, str]) -> list[Finding]:
        """Invoke bandit and parse security findings."""
        try:
            binary = str(resolve_tool("bandit", repo))
        except ToolNotAvailable:
            logger.warning("bandit not found on PATH or .venv, skipping")
            return []
        try:
            inv = self.bandit.invoke(repo, [], env=dict(env) if env else {})
            return self.bandit.parse(inv.stdout, inv.stderr, inv.exitcode)
        except (OSError, RuntimeError) as exc:
            logger.warning("bandit invocation failed: %s", exc)
            return []
