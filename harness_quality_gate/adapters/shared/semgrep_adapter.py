"""Semgrep security-scanning adapter.

Wraps ``semgrep --config p/security-audit --json`` into :class:`Finding[]`.

Design: Component Responsibilities / semgrep_adapter.
Requirements: FR-29, US-9, FR-21.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter, ToolInvocation


_SEVERITY_MAP = {
    "ERROR": "error",
    "WARNING": "warning",
    "INFO": "info",
    "LOW": "info",
    "MEDIUM": "warning",
    "HIGH": "error",
}


class SemgrepAdapter(ToolAdapter):
    """Wraps ``semgrep`` and parses JSON security findings."""

    _name = "semgrep"

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        result = self._run(
            [sys.executable, "-m", "semgrep", "--version"],
            cwd=repo,
            env=env,
        )
        return result.stdout.strip() or "unknown"

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        python = sys.executable
        configs = ["p/security-audit", "p/owasp-top-ten"]
        cmd = [
            python, "-m", "semgrep",
            "--config", ",".join(configs),
            "--json",
            "--quiet",
            str(repo),
        ]
        if args:
            cmd.extend(args)
        return self._run(cmd, cwd=repo, env=env, timeout=timeout)

    def parse(
        self,
        stdout: str,
        stderr: str = "",
        exitcode: int = 0,
    ) -> list[Finding]:
        """Parse semgrep JSON output into :class:`Finding` objects."""
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        if not isinstance(data, dict):
            return findings

        for finding in data.get("results", []):
            if not isinstance(finding, dict):
                continue
            rule_id = finding.get("check_id", "UNKNOWN")
            filename = finding.get("path", "")
            start = finding.get("start") or {}
            line = start.get("line", 0) if isinstance(start, dict) else 0
            extra = finding.get("extra") or {}
            if not isinstance(extra, dict):
                extra = {}
            severity_raw = extra.get("severity", "WARNING")
            message = extra.get("message", "")
            severity = _SEVERITY_MAP.get(severity_raw, "warning")

            findings.append(
                Finding(
                    node=filename,
                    severity=severity,
                    message=f"semgrep [{rule_id}]: {message}",
                    fix_hint=f"Audit semgrep rule {rule_id} at {filename}:{line}",
                    tool="semgrep",
                    layer="L4",
                    language="",
                    rule_id=rule_id,
                )
            )

        return findings
