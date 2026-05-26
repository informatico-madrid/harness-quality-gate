"""Python quality-gate orchestrator.

Composes ruff, pyright, pytest, mutmut, bandit, vulture, and deptry
into the appropriate quality layers (L3A, L1, L2, L3B, L4).

Design: Component Responsibilities / python_adapter
Requirements: FR-5, FR-41, US-3
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Mapping

from ...models import Finding, LayerResult, MutationStats
from ..base import BaseAdapter
from .bandit_adapter import BanditAdapter
from .deptry_adapter import DeptryAdapter
from .mutmut_adapter import MutmutAdapter
from .pyright_adapter import PyrightAdapter
from .pytest_adapter import PytestAdapter
from .ruff_adapter import RuffAdapter
from .vulture_adapter import VultureAdapter

logger = logging.getLogger(__name__)


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
                versions[adapter.name] = adapter.version(self.repo_placeholder(Path(".")), {})
            except (RuntimeError, OSError):
                versions[adapter.name] = "MISSING"
        return versions

    def check_tools(self) -> list[str]:
        """Return the names of critical Python tools."""
        missing: list[str] = []
        for tool in ("ruff", "pyright"):
            if shutil.which(tool) is None:
                missing.append(tool)
        if missing:
            raise RuntimeError(
                f"Missing Python tool(s): {', '.join(missing)}"
            )
        return ["ruff", "pyright"]

    @staticmethod
    def repo_placeholder(repo: Path) -> Path:
        """Identity helper to satisfy version() calls."""
        return repo

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
        passed = len(all_findings) == 0

        return LayerResult(
            layer="L3A",
            language="python",
            passed=passed,
            findings=all_findings,
            duration_sec=round(duration, 3),
        )

    # -- L1 (unit-test + coverage) ----------------------------------------

    def run_l1(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Run pytest; parse JUnit XML; merge findings."""
        t0 = time.monotonic()
        all_findings: list[Finding] = []

        pytest_findings = self._run_pytest(repo, env)
        all_findings.extend(pytest_findings)
        logger.info("pytest: %d findings", len(pytest_findings))

        duration = time.monotonic() - t0
        passed = len(all_findings) == 0

        return LayerResult(
            layer="L1",
            language="python",
            passed=passed,
            findings=all_findings,
            duration_sec=round(duration, 3),
        )

    # -- L2 (code-quality gates) ------------------------------------------

    def run_l2(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Run ruff, vulture, deptry; merge code-quality findings."""
        t0 = time.monotonic()
        all_findings: list[Finding] = []

        ruff_findings = self._run_ruff(repo, env)
        all_findings.extend(ruff_findings)
        logger.info("ruff (L2): %d findings", len(ruff_findings))

        vulture_findings = self._run_vulture(repo, env)
        all_findings.extend(vulture_findings)
        logger.info("vulture: %d findings", len(vulture_findings))

        deptry_findings = self._run_deptry(repo, env)
        all_findings.extend(deptry_findings)
        logger.info("deptry: %d findings", len(deptry_findings))

        duration = time.monotonic() - t0
        passed = len(all_findings) == 0

        return LayerResult(
            layer="L2",
            language="python",
            passed=passed,
            findings=all_findings,
            duration_sec=round(duration, 3),
        )

    # -- L3B (weak-test detection / mutation) -----------------------------

    def run_l3b(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Run mutmut; return MutationStats in tool_specific."""
        t0 = time.monotonic()
        mutation_stats = self._run_mutmut(repo, env)

        duration = time.monotonic() - t0
        passed = mutation_stats.survived == 0 and mutation_stats.timed_out == 0

        return LayerResult(
            layer="L3B",
            language="python",
            passed=passed,
            findings=[],
            duration_sec=round(duration, 3),
            tool_specific={"mutation_stats": mutation_stats},
        )

    # -- L4 (security + architecture) -------------------------------------

    def run_l4(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Run bandit; merge security findings."""
        t0 = time.monotonic()
        all_findings: list[Finding] = []

        bandit_findings = self._run_bandit(repo, env)
        all_findings.extend(bandit_findings)
        logger.info("bandit: %d findings", len(bandit_findings))

        duration = time.monotonic() - t0
        passed = len(all_findings) == 0

        return LayerResult(
            layer="L4",
            language="python",
            passed=passed,
            findings=all_findings,
            duration_sec=round(duration, 3),
        )

    # -- private helpers --------------------------------------------------

    def _run_ruff(self, repo: Path, env: Mapping[str, str]) -> list[Finding]:
        """Invoke ruff and parse findings."""
        if shutil.which("ruff") is None:
            logger.warning("ruff not found on PATH, skipping")
            return []
        try:
            inv = self.ruff.invoke(repo, [])
            return self.ruff.parse(inv.stdout, inv.stderr, inv.exitcode)
        except (OSError, RuntimeError) as exc:
            logger.warning("ruff invocation failed: %s", exc)
            return []

    def _run_pyright(self, repo: Path, env: Mapping[str, str]) -> list[Finding]:
        """Invoke pyright and parse findings."""
        if shutil.which("pyright") is None:
            logger.warning("pyright not found on PATH, skipping")
            return []
        try:
            inv = self.pyright.invoke(repo, [])
            return self.pyright.parse(inv.stdout, inv.stderr, inv.exitcode)
        except (OSError, RuntimeError) as exc:
            logger.warning("pyright invocation failed: %s", exc)
            return []

    def _run_pytest(self, repo: Path, env: Mapping[str, str]) -> list[Finding]:
        """Invoke pytest and parse JUnit XML findings."""
        python = shutil.which("python3") or "python3"
        if shutil.which(python) is None:
            logger.warning("python3 not found on PATH, skipping")
            return []
        try:
            inv = self.pytest.invoke(repo, [])
            return self.pytest.parse(inv.stdout, inv.stderr, inv.exitcode)
        except (OSError, RuntimeError) as exc:
            logger.warning("pytest invocation failed: %s", exc)
            return []

    def _run_vulture(self, repo: Path, env: Mapping[str, str]) -> list[Finding]:
        """Invoke vulture and parse dead-code findings."""
        if shutil.which("vulture") is None:
            logger.warning("vulture not found on PATH, skipping")
            return []
        try:
            inv = self.vulture.invoke(repo, [])
            return self.vulture.parse(inv.stdout, inv.stderr, inv.exitcode)
        except (OSError, RuntimeError) as exc:
            logger.warning("vulture invocation failed: %s", exc)
            return []

    def _run_deptry(self, repo: Path, env: Mapping[str, str]) -> list[Finding]:
        """Invoke deptry and parse dependency findings."""
        if shutil.which("deptry") is None:
            logger.warning("deptry not found on PATH, skipping")
            return []
        try:
            inv = self.deptry.invoke(repo, [])
            return self.deptry.parse(inv.stdout, inv.stderr, inv.exitcode)
        except (OSError, RuntimeError) as exc:
            logger.warning("deptry invocation failed: %s", exc)
            return []

    def _run_mutmut(self, repo: Path, env: Mapping[str, str]) -> MutationStats:
        """Invoke mutmut and return MutationStats."""
        if shutil.which("mutmut") is None:
            logger.warning("mutmut not found on PATH, returning empty stats")
            return MutationStats(
                total=0, killed=0, survived=0, timed_out=0,
                escaped=0, untested=0, msi=0.0, covered_msi=0.0,
            )
        try:
            inv = self.mutmut.invoke(repo, [])
            return self.mutmut.parse(inv.stdout, inv.stderr, inv.exitcode)
        except (OSError, RuntimeError) as exc:
            logger.warning("mutmut invocation failed: %s", exc)
            return MutationStats(
                total=0, killed=0, survived=0, timed_out=0,
                escaped=0, untested=0, msi=0.0, covered_msi=0.0,
            )

    def _run_bandit(self, repo: Path, env: Mapping[str, str]) -> list[Finding]:
        """Invoke bandit and parse security findings."""
        if shutil.which("bandit") is None:
            logger.warning("bandit not found on PATH, skipping")
            return []
        try:
            inv = self.bandit.invoke(repo, [])
            return self.bandit.parse(inv.stdout, inv.stderr, inv.exitcode)
        except (OSError, RuntimeError) as exc:
            logger.warning("bandit invocation failed: %s", exc)
            return []
