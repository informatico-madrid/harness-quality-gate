"""Checkov infrastructure-validation adapter.

Wraps ``checkov -d --framework dockerfile,yaml,-json --output json`` into
:class:`Finding[]`.

Design: Component Responsibilities / checkov_adapter.
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


class CheckovAdapter(ToolAdapter):
    """Wraps ``checkov`` and parses JSON output into infrastructure findings."""

    _name = "checkov"

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        result = self._run(
            [shutil.which("python3") or "python3", "-m", "checkov", "--version"],
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
        timeout: float = 180.0,
    ) -> ToolInvocation:
        python = shutil.which("python3") or "python3"
        cmd = [
            python, "-m", "checkov",
            "-d", str(repo),
            "--framework", "dockerfile", "yaml", "json",
            "--output", "json",
            "--compact",
            "--quiet",
        ]
        skip_dirs = [".git", "__pycache__", "node_modules", ".venv", ".mypy_cache", "_bmad-output"]
        cmd.extend(["--skip-path", ",".join(skip_dirs)])
        if args:
            cmd.extend(args)
        return self._run(cmd, cwd=repo, env=env, timeout=timeout)

    def parse(
        self,
        stdout: str,
        stderr: str = "",
        exitcode: int = 0,
    ) -> list[Finding]:
        """Parse checkov JSON output into :class:`Finding` objects."""
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        if not isinstance(data, dict):
            return findings

        results = data.get("results", {})
        if not isinstance(results, dict):
            return findings

        failed = results.get("failed_checks", [])
        if not isinstance(failed, list):
            return findings

        for check in failed:
            if not isinstance(check, dict):
                continue
            filename = check.get("file_path", "")
            rule_id = check.get("check_id", "UNKNOWN")
            severity_raw = check.get("severity", "MEDIUM")
            message = check.get("check_name", "")
            line = check.get("resource", "")
            severity = _SEVERITY_MAP.get(severity_raw, "warning")

            findings.append(
                Finding(
                    node=filename,
                    severity=severity,
                    message=f"checkov [{rule_id}]: {message}",
                    fix_hint=f"Audit check {rule_id} at {filename}:{line}",
                    tool="checkov",
                    layer="L4",
                    language="",
                    rule_id=rule_id,
                )
            )

        return findings
