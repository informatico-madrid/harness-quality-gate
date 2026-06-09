"""Trivy Docker-config-security adapter.

Wraps ``trivy config --format json`` into :class:`Finding[]`.

Design: Component Responsibilities / trivy_adapter.
Requirements: FR-29, US-9, FR-21.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter, ToolInvocation


_SEVERITY_MAP = {"CRITICAL": "error", "HIGH": "error", "MEDIUM": "warning", "LOW": "info"}


class TrivyAdapter(ToolAdapter):
    """Wraps ``trivy`` and parses Docker misconfiguration findings."""

    _name = "trivy"

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        binary = shutil.which("trivy")
        if binary is None:
            raise RuntimeError("trivy not found on PATH")
        result = self._run([binary, "--version"], cwd=repo, env=env)
        return result.stdout.strip() or "unknown"

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 180.0,
    ) -> ToolInvocation:
        binary = shutil.which("trivy")
        if binary is None:
            return ToolInvocation(stderr="trivy not found on PATH", exitcode=3)

        # Find Dockerfile
        dockerfile = repo / "Dockerfile.custom"
        if not dockerfile.exists():
            dockerfile = repo / "Dockerfile"
        if not dockerfile.exists():
            return ToolInvocation(stdout=json.dumps({"skipped": True}), exitcode=0)

        cmd = [binary, "config", "--format", "json", "--quiet", str(dockerfile.parent)]
        if args:
            cmd.extend(args)
        return self._run(cmd, cwd=repo, env=env, timeout=timeout)

    def parse(
        self,
        stdout: str,
        stderr: str = "",
        exitcode: int = 0,
    ) -> list[Finding]:
        """Parse trivy JSON config scan output into :class:`Finding` objects."""
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        if not isinstance(data, dict):
            return findings

        for result_item in data.get("Results", []):
            if not isinstance(result_item, dict):
                continue
            for misconf in result_item.get("Misconfigurations", []):
                if not isinstance(misconf, dict):
                    continue
                rule_id = misconf.get("AVDID", misconf.get("ID", "UNKNOWN"))
                severity_raw = misconf.get("Severity", "MEDIUM")
                message = misconf.get("Message", misconf.get("Title", ""))
                cause = misconf.get("Cause") or {}
                if isinstance(cause, dict):
                    filename = cause.get("Provider", "")
                else:
                    filename = ""
                severity = _SEVERITY_MAP.get(severity_raw, "warning")

                findings.append(
                    Finding(
                        node=filename,
                        severity=severity,
                        message=f"trivy [{rule_id}]: {message}",
                        fix_hint=f"Audit misconfiguration {rule_id}",
                        tool="trivy",
                        layer="L4",
                        language="",
                        rule_id=rule_id,
                    )
                )

        return findings
