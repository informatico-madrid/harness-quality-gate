"""Python quality-gate orchestrator — POC.

Composes ruff check and pyright into the L3A ``LayerResult``.
Other layers raise ``NotImplementedError`` (filled in Phase 2).

Design: Component Responsibilities / python_adapter
Requirements: FR-5, FR-41, US-3
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Mapping

from ...models import Finding, LayerResult
from ..base import BaseAdapter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PythonAdapter
# ---------------------------------------------------------------------------

class PythonAdapter(BaseAdapter):
    """Orchestrates Python quality tools across the five quality layers.

    At POC level only L3A is wired (ruff + pyright).
    L1, L2, L3B, and L4 raise ``NotImplementedError``.
    """

    _name = "python"

    # -- abstract: tool_versions / check_tools ----------------------------

    def tool_versions(self) -> dict[str, str]:
        """Return {tool_name: version} for every Python tool."""
        versions: dict[str, str] = {}
        for tool in ("ruff", "pyright"):
            cmd = shutil.which(tool)
            if cmd:
                versions[tool] = "PRESENT"
            else:
                versions[tool] = "MISSING"
        return versions

    def check_tools(self) -> list[str]:
        """Return the names of critical Python tools.

        Raises ``RuntimeError`` if ruff or pyright are missing.
        """
        missing: list[str] = []
        for tool in ("ruff", "pyright"):
            if shutil.which(tool) is None:
                missing.append(tool)
        if missing:
            raise RuntimeError(
                f"Missing Python tool(s): {', '.join(missing)}"
            )
        return ["ruff", "pyright"]

    # -- L3A (static analysis + type checking) ----------------------------

    def run_l3a(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Run ruff check and pyright; merge findings."""
        t0 = time.monotonic()
        all_findings: list[Finding] = []

        # ruff — linting
        ruff_findings = self._run_ruff(repo, env)
        all_findings.extend(ruff_findings)
        logger.info("ruff: %d findings", len(ruff_findings))

        # pyright — type checking
        pyright_findings = self._run_pyright(repo, env)
        all_findings.extend(pyright_findings)
        logger.info("pyright: %d findings", len(pyright_findings))

        duration = time.monotonic() - t0
        passed = len(all_findings) == 0

        return LayerResult(
            layer="L3A",
            language="python",
            passed=passed,
            findings=all_findings,
            duration_sec=round(duration, 3),
        )

    # -- private helpers --------------------------------------------------

    def _run_ruff(self, repo: Path, env: Mapping[str, str]) -> list[Finding]:
        """Invoke ``ruff check --output-format=json`` and parse findings."""
        binary = shutil.which("ruff")
        if binary is None:
            logger.warning("ruff not found on PATH, skipping")
            return []
        try:
            result = self._run_subprocess(
                [binary, "check", "--output-format=json", str(repo)],
                cwd=repo,
                env=env,
                timeout=300.0,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("ruff invocation failed: %s", exc)
            return []

        return self._parse_ruff(result.stdout, result.stderr, result.returncode)

    @staticmethod
    def _parse_ruff(
        stdout: str, stderr: str, exitcode: int
    ) -> list[Finding]:
        """Parse ruff JSON output into :class:`Finding` objects."""
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
                    layer="L3A",
                    language="python",
                    rule_id=code or None,
                )
            )

        return findings

    def _run_pyright(self, repo: Path, env: Mapping[str, str]) -> list[Finding]:
        """Invoke ``pyright --outputjson`` and parse findings."""
        binary = shutil.which("pyright")
        if binary is None:
            logger.warning("pyright not found on PATH, skipping")
            return []
        try:
            result = self._run_subprocess(
                [binary, "--outputjson", str(repo)],
                cwd=repo,
                env=env,
                timeout=300.0,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("pyright invocation failed: %s", exc)
            return []

        return self._parse_pyright(result.stdout, result.stderr, result.returncode)

    @staticmethod
    def _parse_pyright(
        stdout: str, stderr: str, exitcode: int
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
            sev_map = {"error": "error", "warning": "warning", "information": "info"}
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

    # -- L1 (unit-test + coverage) — Phase 2 ------------------------------

    def run_l1(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        raise NotImplementedError(
            "L1 (unit-test + coverage) is not implemented for Python yet"
        )

    # -- L2 (code-quality gates) — Phase 2 --------------------------------

    def run_l2(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        raise NotImplementedError(
            "L2 (code-quality gates) is not implemented for Python yet"
        )

    # -- L3B (weak-test detection) — Phase 2 ------------------------------

    def run_l3b(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        raise NotImplementedError(
            "L3B (weak-test detection) is not implemented for Python yet"
        )

    # -- L4 (security + architecture) — Phase 2 ---------------------------

    def run_l4(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        raise NotImplementedError(
            "L4 (security + architecture) is not implemented for Python yet"
        )
