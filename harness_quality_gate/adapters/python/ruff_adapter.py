"""Ruff linting adapter.

Wraps ``ruff check --output-format=json`` into :class:`Finding[]`.

Design: Component Responsibilities / ruff_adapter.
Requirements: FR-29, US-3.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter


class RuffAdapter(ToolAdapter):
    """Wraps ``ruff check`` and parses JSON output into findings."""

    _name = "ruff"

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        binary = shutil.which("ruff")
        if binary is None:
            raise RuntimeError("ruff not found on PATH")
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
        binary = shutil.which("ruff")
        if binary is None:
            return ToolInvocation(stderr="ruff not found on PATH", exitcode=3)
        cmd = [binary, "check", "--output-format=json"]
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
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            entries = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        if not isinstance(entries, list):
            return findings

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            code = entry.get("code", "") or entry.get("rule", "")
            filename = entry.get("filename", "")
            location = entry.get("location", {})
            line = location.get("row", 0)
            col = location.get("column", 0)
            message = entry.get("message", "")
            fix = entry.get("fix", {})
            fix_hint = None
            if isinstance(fix, dict):
                fix_msg = fix.get("message")
                if isinstance(fix_msg, str):
                    fix_hint = fix_msg
            detail = message
            if line:
                detail = f"{filename}:{line}"
                if col:
                    detail += f":{col}"
                detail += f" [{code}]: {message}"
            findings.append(
                Finding(
                    node=filename,
                    severity="warning" if code else "error",
                    message=detail or message or str(entry),
                    fix_hint=fix_hint,
                    tool="ruff",
                    layer="L2",
                    language="python",
                    rule_id=code or None,
                )
            )

        return findings
