"""Local PHP Security Checker adapter (Tier A L4).

Wraps ``local-php-security-checker --format=json`` and parses its
JSON output into :class:`~harness_quality_gate.models.Finding` objects.

Design: Component Responsibilities / security_checker_adapter, PHP Tier A tools.
Requirements: FR-21, US-9.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter, ToolInvocation

logger = logging.getLogger(__name__)  # pragma: no mutate


class SecurityCheckerAdapter(ToolAdapter):
    """Wraps local-php-security-checker for L4 vulnerability scanning (Tier A).

    POC level: invocation via ``invoke()`` and JSON ``parse()`` into
    :class:`Finding` objects.
    """

    _name = "local-php-security-checker"

    # -- abstract interface -----------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        raise NotImplementedError(
            "security-checker version detection not implemented (POC)"
        )

    def invoke(
        self,
        repo: Path,
        args: list[str] | None = None,
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        """Run local-php-security-checker against *repo* with ``--format=json``.

        Args:
            repo: Path to the PHP repository root.
            args: Extra CLI arguments (optional).
            env: Additional environment variables.
            timeout: Maximum seconds to wait (default 300).

        Returns:
            A :class:`ToolInvocation` with stdout/stderr/exit code.

        Raises:
            RuntimeError: If the checker binary is not found.
        """
        checker = shutil.which("local-php-security-checker")
        if checker is None:
            checker = shutil.which("php-security-checker")
        if checker is None:
            raise RuntimeError(
                "local-php-security-checker not found on PATH"
            )
        cmd = [checker, "--format=json"]
        if args:
            cmd.extend(args)
        start = datetime.now(timezone.utc)
        try:
            result = subprocess.run(
                cmd,
                cwd=str(repo),
                env={**__import__("os").environ, **(env or {})},
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            duration = (
                datetime.now(timezone.utc) - start
            ).total_seconds()
            return ToolInvocation(
                stdout=result.stdout,
                stderr=result.stderr or "",
                exitcode=result.returncode,
                duration_seconds=round(duration, 3),
            )
        except subprocess.TimeoutExpired as exc:
            duration = (
                datetime.now(timezone.utc) - start
            ).total_seconds()
            return ToolInvocation(
                stdout=(
                    exc.stdout
                    if isinstance(exc.stdout, str)
                    else (exc.stdout.decode() if exc.stdout else "")
                ),
                stderr=(
                    exc.stderr
                    if isinstance(exc.stderr, str)
                    else (exc.stderr.decode() if exc.stderr else "TIMEOUT")
                ),
                exitcode=-1,
                duration_seconds=round(duration, 3),
            )

    def parse(
        self,
        stdout: str,
        stderr: str = "",
        exitcode: int = 0,
    ) -> list[Finding]:
        """Parse local-php-security-checker JSON output into :class:`Finding`.

        Expected JSON format (``--format=json``)::

            [
              {
                "package": "vendor/package",
                "installed_version": "1.0.0",
                "vulnerable_versions": "<2.0.0",
                "severity": "high",
                "type": "xss",
                "adapter": "composer",
                "adapter_version": "1.0.0",
                "links": ["https://..."]
              }
            ]

        Args:
            stdout: The tool's stdout JSON string.
            stderr: The tool's stderr string.
            exitcode: The tool's exit code.

        Returns:
            A list of :class:`Finding` objects.
        """
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        if not isinstance(data, list):
            return findings

        for entry in data:
            if not isinstance(entry, dict):
                continue
            package = entry.get("package", "unknown")
            severity = self._normalise_severity(entry.get("severity", ""))
            vuln_versions = entry.get("vulnerable_versions", "")
            pkg_type = entry.get("type", "")
            links = entry.get("links", [])
            link_str = links[0] if links else None
            installed = entry.get("installed_version", "")
            findings.append(
                Finding(
                    node=package,
                    severity=severity,
                    message=(
                        f"{package} {installed} "
                        f"has vulnerability in {vuln_versions} ({pkg_type})"
                    ),
                    fix_hint=link_str,
                    cve=None,
                    cwe="",
                    tool=self._name,
                    layer="L4",
                    language="php",
                )
            )

        return findings

    # -- helpers ------------------------------------------------------------

    _severity_map: dict[str, str] = {
        "critical": "error",
        "high": "error",
        "medium": "warning",
        "low": "info",
    }

    @staticmethod
    def _normalise_severity(severity: str) -> str:
        return SecurityCheckerAdapter._severity_map.get(
            severity.lower(), "warning"
        )
