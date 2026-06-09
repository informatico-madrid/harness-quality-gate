"""Vulture dead-code detector adapter.

Wraps ``vulture --format json`` into :class:`Finding[]`.

Design: Component Responsibilities / vulture_adapter.
Requirements: FR-29, US-3.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter, ToolInvocation


class VultureAdapter(ToolAdapter):
    """Wraps ``vulture`` and parses JSON output into unused-code findings."""

    _name = "vulture"

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        binary = shutil.which("vulture")
        if binary is None:
            raise RuntimeError("vulture not found on PATH")
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
        binary = shutil.which("vulture")
        if binary is None:
            return ToolInvocation(stderr="vulture not found on PATH", exitcode=3)
        cmd = [binary, "--format", "json", str(repo)]
        if args:
            cmd.extend(args)
        return self._run(cmd, cwd=repo, env=env, timeout=timeout)

    def parse(
        self,
        stdout: str,
        stderr: str = "",
        exitcode: int = 0,
    ) -> list[Finding]:
        """Parse vulture JSON output into :class:`Finding` objects."""
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            items = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        if not isinstance(items, list):
            return findings

        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or ""
            item_type = item.get("type") or "unused"
            filepath = item.get("filename") or ""
            line_no = item.get("line") or item.get("line_no") or 0
            desc = f"{item_type}: {name}"
            detail = desc
            if filepath:
                detail = f"{filepath}:{line_no}" if line_no else f"{filepath}"
                detail += f" — {desc}"

            findings.append(
                Finding(
                    node=filepath or name,
                    severity="warning",
                    message=detail,
                    fix_hint=f"Remove unused {item_type.lower()} '{name}' at {filepath}:{line_no}",
                    tool="vulture",
                    layer="L2",
                    language="python",
                    rule_id="unused",
                )
            )

        return findings
