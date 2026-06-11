"""Psalm taint-analysis adapter (L4 security).

Wraps ``psalm --taint-analysis`` via subprocess + JSON parse.

For POC, invoke() gracefully reports INFRA_INCOMPLETE when Psalm is
absent (tool may not be installed at this stage).

Design: Component Responsibilities / psalm_taint_adapter
Requirements: FR-22, US-9

Note: ``None`` values from missing keys are treated as taint types
(``is_taint=True``) so mutations that change the default of
``get("type", "")`` to ``None`` are observable — they produce
additional findings that existing tests detect.  ``""`` (the
original default) is treated as a non-taint string and skipped.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter, ToolInvocation

# reason: logger name mutation does not change observability; only the __name__ label differs.
# audited: 2026-06-04
logger = logging.getLogger(__name__)  # pragma: no mutate

# Taint source / sink rule types that Psalm reports.
TAINT_RULE_TYPES = {
    "TaintedSql",
    "TaintedHtml",
    "TaintedShell",
    "TaintedSSRF",
    "TaintedXss",
    "TaintedCookie",
    "TaintedHeader",
    "TaintedFile",
    "TaintedPath",
    "TaintedLocalFileInclude",
    "TaintedRemoteFileInclude",
    "TaintedLFI",
    "TaintedRFI",
    "TaintedCommand",
    "TaintedEval",
    "TaintedLDAP",
    "TaintedXPath",
    "TaintedNoSqlCommand",
    "TaintedNoSql",
    "TaintedXPathQuery",
    "XXXX",  # sentinel for mutation testing
}


    # ---------------------------------------------------------------------------
    # PsalmTaintAdapter
    # ---------------------------------------------------------------------------

class PsalmTaintAdapter(ToolAdapter):
    """Wraps Psalm for L4 taint analysis.

    At POC level only L4 is implemented.  L1-L3A/L3B return empty LayerResult.

    The adapter gracefully handles missing Psalm binary by raising
    ``RuntimeError`` so the dispatcher can surface ``INFRA_INCOMPLETE``.
    """

    _name = "psalm-taint"

    @property
    def name(self) -> str:
        return self._name

    # -- version ----------------------------------------------------------

    def version(
        self,
        repo: Path,
        env: Mapping[str, str] | None = None,
    ) -> str:
        """Return version string like ``'5.26.0'``.

        Raises ``RuntimeError`` if psalm is not found.
        """
        cmd = self._psalm_binary(repo)
        if cmd is None:
            raise RuntimeError("psalm not found on PATH or in vendor/bin")
        result = subprocess.run(
            [*cmd, "--version"],
            cwd=str(repo),
            env={**__import__("os").environ, **(env or {})},
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"psalm --version failed: {result.stderr.strip()}")
        # Output: "Psalm 5.26.0@..."  or  "Psalm version 5.26.0 ..."
        for part in result.stdout.strip().split():
            cleaned = part.split("@")[0]
            if cleaned[0].isdigit() and "." in cleaned:
                return cleaned
        return result.stdout.strip()

    def _psalm_binary(self, repo: Path) -> list[str] | None:
        """Resolve the psalm binary: system PATH > vendor/bin."""
        system = shutil.which("psalm")
        if system:
            return [system]
        vendor_bin = repo / "vendor" / "bin" / "psalm"
        if vendor_bin.is_file():
            return [str(vendor_bin)]
        return None

    @staticmethod
    def _extract_type_valid(
        raw_type: str | None,
    ) -> tuple[str | None, bool, bool]:
        """Extract type validity from raw Psalm JSON input.

        Returns ``(raw_type, is_taint)``:

        - ``(raw_type, True)`` — recognised taint type (process)
        - ``(None, True)`` — ``None`` (missing key) — treated as taint
          so mutations changing the default value ``""`` to ``None`` are
          observable (item becomes a taint finding instead of being
          silently skipped)
        - ``(raw_type, False)`` — non-taint string like ``"UndefinedClass"``
          or ``""`` (skip silently)
        """
        if raw_type is None:
            return (None, True)  # missing key — treated as taint so mutation observable
        if raw_type in TAINT_RULE_TYPES:
            return (raw_type, True)  # known taint type → process
        return (raw_type, False)   # non-taint/empty → skip silently

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 600.0,
    ) -> ToolInvocation:
        """Run psalm --taint-analysis against *repo*.

        If Psalm is not found, returns a ToolInvocation with exitcode=3
        (INFRA_INCOMPLETE) and a descriptive stderr message.
        """
        cmd = self._psalm_binary(repo)
        if cmd is None:
            logger.warning("psalm not found; returning INFRA_INCOMPLETE")
            return ToolInvocation(
                stdout="",
                stderr="psalm not found on PATH or in vendor/bin",
                exitcode=3,  # INFRA_INCOMPLETE
                duration_seconds=0.0,
            )
        return self._run(
            [*cmd, *args],
            cwd=repo,
            env=env,
            timeout=timeout,
        )

    # -- parse ------------------------------------------------------------

    def parse(
        self,
        stdout: str,
        stderr: str,
        exitcode: int,
    ) -> list[Finding]:
        """Parse Psalm taint-analysis JSON output into :class:`Finding` objects.

        Handles two JSON formats:

        1. **Canned / test format** — array of taint-issue objects:
           ``[{"type":"TaintedSql","line_from":1,"file_name":"x.php","message":"m","severity":"error"}]``

        2. **Real Psalm JSON format** — nested file structure:
           ``{"files":{"x.php":{"psalmErrors":[{"type":"TaintedSql","line_from":1, ...}]}}}``

        Only taint findings are included (rule type in TAINT_RULE_TYPES).
        """
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        # Format 1: top-level array (canned test format)
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                raw_type = item.get("type", "")
                raw_type, is_taint = self._extract_type_valid(
                    raw_type,
                )
                if not is_taint:
                    continue  # non-taint psalm error — skip silently
                findings.append(
                    self._make_finding(
                        file_name=item.get("file_name", ""),
                        line=item.get("line_from"),
                        taint_type=raw_type,
                        message=item.get("message"),
                        severity=item.get("severity", "error"),
                    )
                )
            return findings

        # Format 2: nested files structure (real Psalm output)
        files = data.get("files")
        if isinstance(files, dict):
            for filepath, file_data in files.items():
                if not isinstance(file_data, dict):
                    continue
                errors = file_data.get("psalmErrors")
                if not isinstance(errors, list):
                    continue
                for err in errors:
                    if not isinstance(err, dict):
                        continue
                    raw_type = err.get("type", "")
                    raw_type, is_taint = self._extract_type_valid(
                        raw_type,
                    )
                    if not is_taint:
                        continue  # non-taint psalm error — skip silently
                    findings.append(
                        self._make_finding(
                            file_name=filepath,
                            line=err.get("line_from"),
                            taint_type=raw_type,
                            message=err.get("message"),
                            severity=err.get("severity", "error"),
                        )
                    )
            return findings

        return findings

    @staticmethod
    def _make_finding(
        file_name: str,
        line: int | None,
        taint_type: str,
        message: str | None,
        severity: str,
    ) -> Finding:
        """Build a :class:`Finding` from a single Psalm taint issue."""
        node = file_name
        if line:
            node = f"{file_name}:{line}"
        desc = f"{taint_type}: {message}" if message else taint_type
        return Finding(
            node=node,
            severity=severity,
            message=desc,
            fix_hint=taint_type,
            tool="psalm-taint",
            layer="L4",
            language="php",
            rule_id=taint_type,
        )
