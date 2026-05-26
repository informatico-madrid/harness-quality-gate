"""PHP quality-gate orchestrator.

Composes the three Tier-A tool adapters (PHPStan, PHPMD, php-cs-fixer) into
the L3A ``LayerResult``.  L3B and INFRA are stubbed for POC (passed=True,
empty findings).

Design: Component Responsibilities / php_adapter
Requirements: FR-33, US-12
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Mapping

from ...models import Finding, LayerResult
from ..base import BaseAdapter
from .php_cs_fixer_adapter import PhpCsFixerAdapter
from .phpmd_adapter import PhpMdAdapter
from .phpstan_adapter import PhpStanAdapter

logger = logging.getLogger(__name__)


class PhpAdapter(BaseAdapter):
    """Orchestrates PHP quality tools across the five quality layers.

    At POC level only L3A is wired; L1, L2, L3B, and L4 return stub
    ``LayerResult(passed=True, findings=[])`` so callers can iterate
    without tool dependency.
    """

    _name = "php"

    # -- construction --------------------------------------------------------

    def __init__(self) -> None:
        self._phpstan = PhpStanAdapter()
        self._phpmd = PhpMdAdapter()
        self._cs_fixer = PhpCsFixerAdapter()

    # -- property interface --------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    # -- BaseAdapter abstract contract --------------------------------------

    def tool_versions(self) -> dict[str, str]:
        """Return {tool_name: version} for all composed tools."""
        versions: dict[str, str] = {}
        for tool in (self._phpstan, self._phpmd, self._cs_fixer):
            try:
                versions[tool.name] = tool.version(
                    Path.cwd(), env={}
                )
            except RuntimeError:
                versions[tool.name] = "MISSING"
        return versions

    def check_tools(self) -> list[str]:
        """Raise if any critical tool is missing; return tool list."""
        missing: list[str] = []
        for tool in (self._phpstan, self._phpmd, self._cs_fixer):
            try:
                tool.version(Path.cwd(), env={})
            except RuntimeError:
                missing.append(tool.name)
        if missing:
            raise RuntimeError(
                f"Missing PHP tool(s): {', '.join(missing)}"
            )
        return [t.name for t in (self._phpstan, self._phpmd, self._cs_fixer)]

    # -- L3A (Tier A: static analysis + code quality) -----------------------

    def run_l3a(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Run PHPStan, PHPMD, and php-cs-fixer; merge findings."""
        t0 = time.monotonic()
        all_findings: list[Finding] = []

        # PHPStan — static analysis
        try:
            phpstan_findings = self._phpstan.run_l3a(repo, env)
            all_findings.extend(phpstan_findings)
            logger.info("PHPStan: %d findings", len(phpstan_findings))
        except RuntimeError as exc:
            logger.warning("PHPStan skipped: %s", exc)

        # PHPMD — antipattern / code-quality
        try:
            phpmd_findings = self._phpmd.run_l3a(repo, env)
            all_findings.extend(phpmd_findings)
            logger.info("PHPMD: %d findings", len(phpmd_findings))
        except RuntimeError as exc:
            logger.warning("PHPMD skipped: %s", exc)

        # php-cs-fixer — code style
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
            logger.info("php-cs-fixer: %d findings", len(cs_findings))
        except RuntimeError as exc:
            logger.warning("php-cs-fixer skipped: %s", exc)

        duration = time.monotonic() - t0
        passed = len(all_findings) == 0

        return LayerResult(
            layer="L3A",
            language="php",
            passed=passed,
            findings=all_findings,
            duration_sec=round(duration, 3),
        )

    # -- L1 (Unit-test + coverage) — POC stub --------------------------------

    def run_l1(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        return LayerResult(
            layer="L1",
            language="php",
            passed=True,
            findings=[],
            duration_sec=0.0,
        )

    # -- L2 (Code-quality gates) — POC stub ----------------------------------

    def run_l2(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        return LayerResult(
            layer="L2",
            language="php",
            passed=True,
            findings=[],
            duration_sec=0.0,
        )

    # -- L3B (Weak-test detection) — POC stub --------------------------------

    def run_l3b(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        return LayerResult(
            layer="L3B",
            language="php",
            passed=True,
            findings=[],
            duration_sec=0.0,
        )

    # -- L4 (Security + architecture) — POC stub -----------------------------

    def run_l4(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        return LayerResult(
            layer="L4",
            language="php",
            passed=True,
            findings=[],
            duration_sec=0.0,
        )
