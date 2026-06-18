"""Gitleaks secrets-detection adapter.

Wraps ``gitleaks detect --report-format json`` into :class:`Finding[]`.

Design: Component Responsibilities / gitleaks_adapter.
Requirements: FR-29, US-9, FR-21.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter, ToolInvocation


class GitleaksAdapter(ToolAdapter):
    """Wraps ``gitleaks`` and parses JSON leak findings."""

    _name = "gitleaks"

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        binary = shutil.which("gitleaks")
        if binary is None:
            raise RuntimeError("gitleaks not found on PATH")
        result = self._run([binary, "version"], cwd=repo, env=env)
        return result.stdout.strip() or "unknown"

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 120.0,
    ) -> ToolInvocation:
        binary = shutil.which("gitleaks")
        if binary is None:
            return ToolInvocation(stderr="gitleaks not found on PATH", exitcode=3)
        report_path = repo / "_bmad-output" / "quality-gate" / "gitleaks-report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            binary,
            "detect",
            "--source",
            str(repo),
            "--report-format",
            "json",
            "--report-path",
            str(report_path),
            "--no-banner",
        ]
        if args:
            cmd.extend(args)
        result = self._run(cmd, cwd=repo, env=env, timeout=timeout)
        # Read findings from report file before cleanup
        findings_raw = ""
        try:
            findings_raw = report_path.read_text(encoding="utf-8")
        except OSError:
            pass
        try:
            report_path.unlink(missing_ok=True)
        except OSError:
            pass
        # Return the report file content as stdout
        if findings_raw:
            return ToolInvocation(
                stdout=findings_raw,
                stderr=result.stderr,
                exitcode=result.exitcode,
                duration_seconds=result.duration_seconds,
            )
        return result

    def parse(
        self,
        stdout: str,
        stderr: str = "",
        exitcode: int = 0,
    ) -> list[Finding]:
        """Parse gitleaks report JSON into :class:`Finding` objects."""
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            leaks = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        if not isinstance(leaks, list):
            return findings

        for leak in leaks:
            if not isinstance(leak, dict):
                continue
            rule_id = leak.get("RuleID", "UNKNOWN")
            filename = leak.get("File", "")
            line_no = leak.get("StartLine")
            message = leak.get("Message", leak.get("Description", f"Secret: {rule_id}"))

            findings.append(
                Finding(
                    node=str(filename) if filename else "<unknown>",
                    severity="error",
                    message=f"gitleaks [{rule_id}]: {message}",
                    fix_hint=f"Audit and remove secret at {filename}:{line_no}",
                    tool="gitleaks",
                    layer="L4",
                    language="",
                    rule_id=rule_id,
                )
            )

        return findings
