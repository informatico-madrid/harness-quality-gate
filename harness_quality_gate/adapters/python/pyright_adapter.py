"""Pyright type-checking adapter.

Wraps ``pyright --outputjson`` into :class:`Finding[]`.

Design: Component Responsibilities / pyright_adapter.
Requirements: FR-29, US-3.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter


class PyrightAdapter(ToolAdapter):
    """Wraps ``pyright`` and parses JSON output into findings."""

    _name = "pyright"

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        binary = shutil.which("pyright")
        if binary is None:
            raise RuntimeError("pyright not found on PATH")
        result = self._run([binary, "--version"], cwd=repo, env=env)
        return result.stdout.strip().split()[-1] if result.stdout else "unknown"

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        binary = shutil.which("pyright")
        if binary is None:
            return ToolInvocation(stderr="pyright not found on PATH", exitcode=3)
        cmd = [binary, "--outputjson"]
        if args:
            cmd.extend(args)
        cmd.append(str(repo))
        return self._run(cmd, cwd=repo, env=env, timeout=timeout)

    def parse(
        self,
        stdout: str,
        stderr: str = "",
        exitcode: int = 0,
    ) -> list[Finding]:
        """Parse pyright JSON output into :class:`Finding` objects."""
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        for diag in data.get("generalDiagnostics", []):
            if not isinstance(diag, dict):
                continue
            filename = diag.get("file", "")
            severity = diag.get("severity", "")
            message = diag.get("message", "")
            rule = diag.get("rule") or ""
            start = diag.get("range", {}).get("start", {})
            line = start.get("line", 0)
            char = start.get("character", 0)
            detail = message
            if line:
                detail = f"{filename}:{line}"
                if char:
                    detail += f":{char}"
                detail += f" [{rule}]: {message}"
            sev_map = {
                "error": "error",
                "warning": "warning",
                "information": "info",
            }
            severity_str = sev_map.get(severity, "warning")
            findings.append(
                Finding(
                    node=filename,
                    severity=severity_str,
                    message=detail or message or str(diag),
                    fix_hint=None,
                    tool="pyright",
                    layer="L3A",
                    language="python",
                    rule_id=rule or None,
                )
            )

        return findings
