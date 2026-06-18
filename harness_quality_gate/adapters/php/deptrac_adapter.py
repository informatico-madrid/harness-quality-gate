"""Deptrac architecture-violation adapter (POC: parse only, no execution).

Wraps ``deptrac`` Static Analysis / Architecture Enforcement JSON output into
:class:`DeptracResult`.

Design: Component Responsibilities / deptrac_adapter, PHP Tier A tools.
Requirements: FR-19, US-8.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter, ToolInvocation


# ---------------------------------------------------------------------------
# DeptracResult — returned from parse()
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeptracResult:
    """Architecture violation data extracted from deptrac JSON output."""

    architecture: dict = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)


# ---------------------------------------------------------------------------
# DeptracAdapter
# ---------------------------------------------------------------------------


class DeptracAdapter(ToolAdapter):
    """Parses Deptrac architecture-violation JSON output into :class:`DeptracResult`.

    POC level: parsing only. Actual ``deptrac`` invocation is Phase 2.
    """

    _name = "deptrac"

    # -- abstract interface -----------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    def version(
        self,
        repo: Path,
        env: Mapping[str, str] | None = None,
    ) -> str:
        raise NotImplementedError("deptrac version detection not implemented (POC)")

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        """Run deptrac analyse with JSON formatter.

        Command::

            vendor/bin/deptrac analyse --formatter=json

        Args:
            repo: Path to the repository root.
            args: Additional arguments passed after ``analyse``.
            env: Optional environment variables.
            timeout: Timeout in seconds (default 300).

        Returns:
            :class:`ToolInvocation` with stdout, stderr, exit code.

        Raises:
            RuntimeError: If deptrac binary is not found.
        """
        deptrac_bin = repo / "vendor" / "bin" / "deptrac"
        if not deptrac_bin.is_file():
            raise RuntimeError("deptrac not found at vendor/bin/deptrac")
        cmd = [str(deptrac_bin), "analyse", "--formatter=json"]
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
        """Parse deptrac JSON output into :class:`Finding` objects.

        Expects deptrac JSON format::

            {
              "Report": {
                "Violations": 3,
                "UncoveredClasses": 2
              }
            }

        Each violation entry in ``Report.Violations`` becomes a ``Finding``
        with ``tool="deptrac"`` and ``layer="L3B"`` (architecture validation
        belongs to the deep-quality layer per the spec glossary).

        Args:
            stdout: deptrac JSON output string.
            stderr: deptrac stderr (for logging).
            exitcode: deptrac exit code.

        Returns:
            List of :class:`Finding` objects.
        """
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        report = data.get("Report") or {}
        if not isinstance(report, dict):
            return findings

        # Architecture metadata
        violations_count = report.get("Violations") or 0
        uncovered = report.get("UncoveredClasses") or 0

        self._architecture: dict = {
            "violations": violations_count,
            "uncovered_classes": uncovered,
            "stderr": stderr,
            "exitcode": exitcode,
        }

        # Individual violations (if present as a list)
        violations_list = report.get("Violations")
        if isinstance(violations_list, list):
            for v in violations_list:
                if isinstance(v, dict):
                    findings.append(
                        Finding(
                            node=v.get("file", "unknown"),
                            severity="error",
                            message=v.get("message", "Architecture violation"),
                            fix_hint=v.get("fix"),
                            tool=self._name,
                            layer="L3B",
                            language="php",
                        )
                    )
        elif violations_count:
            findings.append(
                Finding(
                    node="deptrac",
                    severity="error",
                    message=f"{violations_count} architecture violation(s) detected",
                    fix_hint=f"Review deptrac.yaml configuration; {uncovered} uncovered class(es)",
                    tool=self._name,
                    layer="L3B",
                    language="php",
                )
            )

        return findings

    # -- concrete helpers -------------------------------------------------

    @property
    def architecture(self) -> dict:
        """Architecture block from the last :meth:`parse` call."""
        return getattr(self, "_architecture", {})

    def parse_stats(self, stdout: str) -> dict:
        """Parse deptrac JSON output and return the architecture block.

        Convenience wrapper for layer runners that need just the
        architecture data without individual findings.

        Args:
            stdout: deptrac JSON output string.

        Returns:
            ``{"violations": N, "uncovered_classes": N}`` dict.
        """
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            return {"violations": 0, "uncovered_classes": 0}

        report = data.get("Report") or {}
        if not isinstance(report, dict):
            return {"violations": 0, "uncovered_classes": 0}

        return {
            "violations": report.get("Violations") or 0,
            "uncovered_classes": report.get("UncoveredClasses") or 0,
        }
