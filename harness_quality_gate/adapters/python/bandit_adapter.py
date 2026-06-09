"""Bandit security scanner adapter.

Wraps ``bandit -r --format json`` into :class:`Finding[]`.

Design: Component Responsibilities / bandit_adapter.
Requirements: FR-29, US-3.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter, ToolInvocation


class BanditAdapter(ToolAdapter):
    """Wraps ``bandit`` and parses JSON output into security findings."""

    _name = "bandit"

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        binary = shutil.which("bandit")
        if binary is None:
            raise RuntimeError("bandit not found on PATH")
        result = self._run([binary, "--version"], cwd=repo, env=env)
        return result.stdout.strip() or "unknown"

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        binary = shutil.which("bandit")
        if binary is None:
            return ToolInvocation(stderr="bandit not found on PATH", exitcode=3)
        cmd = [binary, "-r", "--format", "json", str(repo)]
        if args:
            cmd.extend(args)
        return self._run(cmd, cwd=repo, env=env, timeout=timeout)

    def parse(
        self,
        stdout: str,
        stderr: str = "",
        exitcode: int = 0,
    ) -> list[Finding]:
        """Parse bandit JSON output into :class:`Finding` objects."""
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        issues = data.get("results", []) if isinstance(data, dict) else []
        if not isinstance(issues, list):
            return findings

        severity_map = {"HIGH": "error", "MEDIUM": "warning", "LOW": "info"}

        for issue in issues:
            if not isinstance(issue, dict):
                continue
            filename = issue.get("filename", "")
            issue_id = issue.get("issue_id", "")
            severity_raw = issue.get("issue_severity", "MEDIUM")
            message = issue.get("issue_text", "")
            line_no = issue.get("line_number") or 0
            cwe = issue.get("cwe") or {}
            cwe_id = ""
            if isinstance(cwe, dict):
                cwe_id = cwe.get("id", "") or cwe.get("link", "")
            elif isinstance(cwe, str):
                cwe_id = cwe
            detail = f"{filename}:{line_no} [{issue_id}]: {message}"
            severity = severity_map.get(severity_raw, "warning")

            findings.append(
                Finding(
                    node=filename,
                    severity=severity,
                    message=detail,
                    fix_hint=f"Audit and fix {issue_id} at {filename}:{line_no}",
                    tool="bandit",
                    layer="L4",
                    language="python",
                    rule_id=issue_id,
                    cwe=cwe_id,
                )
            )

        return findings
