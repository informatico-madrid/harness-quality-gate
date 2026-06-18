"""Bandit security scanner adapter.

Wraps ``bandit -r --format json`` into :class:`Finding[]`.

Design: Component Responsibilities / bandit_adapter.
Requirements: FR-29, US-3.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from ...bootstrap import resolve_tool, ToolNotAvailable, detect_source_dir
from ...models import Finding
from ..base import ToolAdapter, ToolInvocation, package_dirs, source_targets


class BanditAdapter(ToolAdapter):
    """Wraps ``bandit`` and parses JSON output into security findings."""

    _name = "bandit"

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        try:
            binary = str(resolve_tool("bandit", repo))
        except ToolNotAvailable:
            raise RuntimeError("bandit not found on PATH or .venv")
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
        try:
            binary = str(resolve_tool("bandit", repo))
        except ToolNotAvailable:
            return ToolInvocation(
                stderr="bandit not found on PATH or .venv", exitcode=3
            )
        # Recurse the source dirs only (src/ or root packages, never tests);
        # the whole repo would sweep mutation artifacts too (H10/F2).
        # -q keeps bandit 1.9's progress bar out of stdout — it corrupts
        # the JSON report otherwise (self-eval F7).
        source_dir = detect_source_dir(repo)
        if source_dir:
            targets = source_targets(repo, source_dir, exclude_tests=True) or [
                str(repo)
            ]
        else:
            # No src/ — fall back to package dirs, excluding tests/
            targets = [
                p if isinstance(p, str) else str(p)
                for p in package_dirs(repo)
                if "test" not in str(p).lower()
            ]
            if not targets:
                targets = [str(repo)]
        cmd = [binary, "-r", "-q", "--format", "json", *targets]
        if args:
            cmd.extend(args)
        return self._run(cmd, cwd=repo, env=env, timeout=timeout)

    def parse(  # type: ignore[override]
        self,
        stdout: str,
        *_compat: object,
    ) -> list[Finding]:
        """Parse bandit JSON output into :class:`Finding` objects."""
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            # Non-empty unparseable output must not pass silently — that
            # turned every bandit run into a vacuous L4 PASS (self-eval F7).
            return [
                Finding(
                    node="bandit",
                    severity="error",
                    message="bandit produced unparseable JSON output",
                    fix_hint="Run bandit manually in the repo to inspect "
                    "the output (progress noise or crash).",
                    tool="bandit",
                    layer="L4",
                    language="python",
                    rule_id="parse-error",
                )
            ]

            # the isinstance guard below collapses a missing key — no default needed
        issues = data.get("results") if isinstance(data, dict) else []
        if not isinstance(issues, list):
            return findings

        # MEDIUM (and anything unexpected) falls through to the "warning" default
        severity_map = {"HIGH": "error", "LOW": "info"}

        for issue in issues:
            if not isinstance(issue, dict):
                continue
            filename = issue.get("filename") or ""
            issue_id = issue.get("issue_id") or ""
            severity_raw = issue.get("issue_severity")
            message = issue.get("issue_text") or ""
            line_no = issue.get("line_number") or 0
            cwe = issue.get("cwe") or {}
            cwe_id = ""
            if isinstance(cwe, dict):
                cwe_id = cwe.get("id") or cwe.get("link") or ""
            elif isinstance(cwe, str):
                cwe_id = cwe
            detail = f"{filename}:{line_no} [{issue_id}]: {message}"
            severity = severity_map.get(severity_raw, "warning")  # type: ignore[arg-type]

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
