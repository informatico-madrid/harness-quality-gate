"""Composer dependency analyzer adapter (Shipmonk).

Wraps ``composer-dependency-analyser --format=json`` into
:class:`~harness_quality_gate.models.Finding` objects.

Design: Component Responsibilities / dep_analyser_adapter
Requirements: FR-21, US-9
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter, ToolInvocation

# reason: logger name mutation does not change observability; only the __name__ label differs.
# audited: 2026-06-04
logger = logging.getLogger(__name__)  # pragma: no mutate

# Violation types reported by composer-dependency-analyser.
VIOLATION_TYPES = {
    "dep-antipattern",
    "dep-class",
    "dep-function",
    "dep-global-constant",
    "dep-global-variable",
}


class DepAnalyserAdapter(ToolAdapter):
    """Wraps Shipmonk composer-dependency-analyser for L4 analysis."""

    _name = "composer-dependency-analyser"

    # -- abstract interface -----------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    def version(
        self,
        repo: Path,
        env: Mapping[str, str] | None = None,
    ) -> str:
        raise NotImplementedError(
            "composer-dependency-analyser version detection not implemented (POC)"
        )

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        """Run composer-dependency-analyser against *repo*."""
        cmd = self._binary(repo)
        if cmd is None:
            logger.warning(
                "composer-dependency-analyser not found; "
                "returning INFRA_INCOMPLETE"
            )
            return ToolInvocation(
                stdout="",
                stderr="composer-dependency-analyser not found",
                exitcode=3,
                duration_seconds=0.0,
            )
        return self._run(
            [*cmd, *args],
            cwd=repo,
            env=env,
            timeout=timeout,
        )

    def parse(
        self,
        stdout: str,
        stderr: str = "",
        exitcode: int = 0,
    ) -> list[Finding]:
        """Parse JSON output from composer-dependency-analyser into Findings.

        Handles two JSON formats:

        1. **Top-level array** - each item has ``file`` and ``line``.
        2. **Nested files structure** - ``{"files":{"path.json":{...}}}``.
        """
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        # Format 1: top-level array
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                vtype = item.get("type", "")
                if vtype not in VIOLATION_TYPES:
                    continue
                findings.append(
                    self._make_finding(
                        file_name=item.get("file", ""),
                        line=item.get("line"),
                        violation_type=vtype,
                        message=item.get("message", ""),
                    )
                )
            return findings

        # Format 2: nested files structure
        files = data.get("files")
        if isinstance(files, dict):
            for filepath, file_data in files.items():
                if not isinstance(file_data, dict):
                    continue
                violations = file_data.get("violations", [])
                if not isinstance(violations, list):
                    continue
                for v in violations:
                    if not isinstance(v, dict):
                        continue
                    vtype = v.get("type", "")
                    if vtype not in VIOLATION_TYPES:
                        continue
                    findings.append(
                        self._make_finding(
                            file_name=filepath,
                            line=v.get("line"),
                            violation_type=vtype,
                            message=v.get("message", ""),
                        )
                    )
            return findings

        return findings

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _make_finding(
        file_name: str,
        line: int | None,
        violation_type: str,
        message: str,
    ) -> Finding:
        """Build a Finding from a single dependency-analyser violation."""
        prefix = violation_type.replace("dep-", "")
        desc = f"{prefix}: {message}" if message else prefix
        node = file_name
        if line:
            node = f"{file_name}:{line}"
        return Finding(
            node=node,
            severity="warning",
            message=desc,
            fix_hint=violation_type,
            tool="composer-dependency-analyser",
            layer="L4",
            language="php",
            rule_id=violation_type,
        )

    # -- private helpers --------------------------------------------------

    @staticmethod
    def _binary(repo: Path) -> list[str] | None:
        """Resolve the composer-dependency-analyser binary: system PATH > vendor/bin."""
        system = shutil.which("composer-dependency-analyser")
        if system:
            return [system]
        vendor_bin = repo / "vendor" / "bin" / "composer-dependency-analyser"
        if vendor_bin.is_file():
            return [str(vendor_bin)]
        return None
