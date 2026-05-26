"""Composer audit adapter (Tier A L4).

Wraps ``composer audit`` via subprocess + JSON parse.

Design: Component Responsibilities / composer_audit_adapter, PHP Tier A tools.
Requirements: FR-21, US-9.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter

logger = logging.getLogger(__name__)


class ComposerAuditAdapter(ToolAdapter):
    """Wraps Composer audit for L4 vulnerability scanning (Tier A).

    At POC level only L4 is implemented.  L1-L3B return empty LayerResult.
    """

    _name = "composer-audit"

    @property
    def name(self) -> str:
        return self._name

    # -- version ----------------------------------------------------------

    def version(self, repo: Path, env: Mapping[str, str] = None) -> str:
        """Return version string like ``'2.8.3'``."""
        cmd = self._composer_binary(repo)
        if cmd is None:
            raise RuntimeError("composer not found on PATH")
        result = subprocess.run(
            [*cmd, "--version"],
            cwd=str(repo),
            env={**__import__("os").environ, **(env or {})},
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"composer --version failed: {result.stderr.strip()}")
        # Output: "Composer version 2.8.3 ..."
        parts = result.stdout.strip().split()
        for p in parts:
            if p[0].isdigit() and "." in p:
                return p
        return result.stdout.strip()

    def _composer_binary(self, repo: Path) -> list[str] | None:
        """Resolve the composer binary from PATH."""
        return shutil.which("composer")

    # -- invoke -----------------------------------------------------------

    def invoke(
        self,
        repo: Path,
        args: list[str] | None = None,
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        cmd = self._composer_binary(repo)
        if cmd is None:
            raise RuntimeError("composer not found on PATH")
        audit_args = ["audit", "--format=json", "--no-dev"]
        return self._run(
            [*cmd, *audit_args],
            cwd=repo,
            env=env,
            timeout=timeout,
        )

    # -- parse ------------------------------------------------------------

    def parse(
        self,
        stdout: str,
        stderr: str,
        exitcode: int,
    ) -> list[Finding]:
        """Parse composer-audit JSON output into :class:`Finding` objects.

        Expected JSON format (``composer audit --format=json``)::

            {
              "advisories": {
                "vendor/package": [
                  {
                    "advisoryId": "SEC-XXX",
                    "cve": "CVE-2024-1234",
                    "title": "Description",
                    "link": "https://...",
                    "impact": {...},
                    "resolutions": [...],
                    "remediation": {...}
                  }
                ]
              }
            }
        """
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        advisories = data.get("advisories")
        if not isinstance(advisories, dict):
            return findings

        for package, adv_list in advisories.items():
            if not isinstance(adv_list, list):
                continue
            for adv in adv_list:
                if not isinstance(adv, dict):
                    continue
                cve = adv.get("cve") or adv.get("advisoryId", "")
                title = adv.get("title", "")
                link = adv.get("link", "")
                findings.append(
                    Finding(
                        node=package,
                        severity="error",
                        message=f"{title}" if title else f"Advisory for {package}",
                        fix_hint=link if link else None,
                        cve=cve if cve else None,
                        cwe="",
                    )
                )

        return findings
