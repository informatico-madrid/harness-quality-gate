"""Deptry dependency checker adapter.

Wraps ``deptry .`` into :class:`Finding[]`.

Design: Component Responsibilities / deptry_adapter.
Requirements: FR-29, US-3.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter


class DeptryAdapter(ToolAdapter):
    """Wraps ``deptry`` and parses JSON output into dependency findings."""

    _name = "deptry"

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        binary = shutil.which("deptry")
        if binary is None:
            raise RuntimeError("deptry not found on PATH")
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
        binary = shutil.which("deptry")
        if binary is None:
            return ToolInvocation(stderr="deptry not found on PATH", exitcode=3)
        # deptry supports JSON via --output or --no-color + --quiet with format
        cmd = [binary, "--output", "json", "."]
        if args:
            cmd.extend(args)
        return self._run(cmd, cwd=repo, env=env, timeout=timeout)

    def parse(
        self,
        stdout: str,
        stderr: str = "",
        exitcode: int = 0,
    ) -> list[Finding]:
        """Parse deptry JSON output into :class:`Finding` objects.

        Accepts ``deptry`` JSON output with structure:
        ``{"errors": {"unused_imports": [...], "missing_imports": [...], ...}}``.
        Also handles the legacy text-parseable format for robustness.
        """
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        if not isinstance(data, dict):
            return findings

        errors = data.get("errors", {}) if isinstance(data.get("errors"), dict) else {}

        category_severity = {
            "unused_imports": "warning",
            "missing_imports": "error",
            "incorrectly_placed_imports": "warning",
            "type_fragment_without_import": "warning",
        }

        for category, items in errors.items():
            severity = category_severity.get(category, "info")
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    module = item.get("module", item.get("name", ""))
                    filepath = item.get("filepath", "")
                    line = item.get("line", item.get("line_no", 0))
                else:
                    module = str(item)
                    filepath = ""
                    line = 0
                desc = f"{category}: {module}"
                detail = desc
                if filepath:
                    detail = f"{filepath}:{line}" if line else f"{filepath}"
                    detail += f" — {desc}"

                findings.append(
                    Finding(
                        node=filepath or module,
                        severity=severity,
                        message=detail,
                        fix_hint=f"Review {category} for '{module}'",
                        tool="deptry",
                        layer="L2",
                        language="python",
                        rule_id=category,
                    )
                )

        return findings
