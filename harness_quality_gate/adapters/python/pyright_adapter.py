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
from ..base import ToolAdapter, ToolInvocation, package_dirs, source_targets

_SEV_MAP = {
    "error": "error",
    "warning": "warning",
    "information": "info",
}


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
        python_path: Path | str | None = None,
    ) -> ToolInvocation:
        binary = shutil.which("pyright")
        if binary is None:
            return ToolInvocation(stderr="pyright not found on PATH", exitcode=3)
        cmd = [binary, "--outputjson"]
        # Venv-aware python path: when pyright is installed globally but the
        # project has a .venv, --pythonpath ensures pyright resolves packages
        # from the venv (radon, pytest, etc.) that exist *only* in the venv.
        if python_path is not None:
            ppath = str(python_path)
            cmd.extend(["--pythonpath", ppath])
        if args:
            cmd.extend(args)
        # Default scan targets for type-checking — exclude_tests ensures
        # pyright never scans test code. L2/L1 handle test quality separately.
        default_targets = source_targets(repo, "src", exclude_tests=True) or [
            str(p) if isinstance(p, Path) else p
            for p in package_dirs(repo) if "test" not in str(p).lower()
        ] or [str(repo)]
        cmd.extend(default_targets)
        return self._run(cmd, cwd=repo, env=env, timeout=timeout)

    @staticmethod
    def _map_severity(severity: str) -> str:
        """Map pyright severity string to internal severity string."""
        return _SEV_MAP.get(severity, "warning")

    def _build_detail(self, filename: str, message: str, rule: str,
                      line: int, char: int) -> str:
        """Build the diagnostic detail string."""
        detail = message
        if line:
            detail = f"{filename}:{line}"
            if char:
                detail += f":{char}"
            detail += f" [{rule}]: {message}"
        return detail

    def parse(  # type: ignore[override]
        self,
        stdout: str,
        *_compat: object,
    ) -> list[Finding]:
        """Parse pyright JSON output into :class:`Finding` objects."""
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        diagnostics = data.get("generalDiagnostics")
        if not diagnostics:
            return findings

        _DEFAULT = ""
        for diag in diagnostics:
            if not isinstance(diag, dict):
                continue
            filename = diag.get("file") or _DEFAULT
            severity = diag.get("severity") or _DEFAULT
            message = diag.get("message") or _DEFAULT
            rule = diag.get("rule") or _DEFAULT
            range_info = diag.get("range") or {}
            start = range_info.get("start") or {}
            line = start.get("line") or 0
            char = start.get("character") or 0
            detail = self._build_detail(filename, message, rule, line, char)
            severity_str = self._map_severity(severity)
            findings.append(
                Finding(
                    node=filename,
                    severity=severity_str,
                    message=detail or message or str(diag),
                        tool="pyright",
                    layer="L3A",
                    language="python",
                    rule_id=rule or None,
                )
            )

        return findings
