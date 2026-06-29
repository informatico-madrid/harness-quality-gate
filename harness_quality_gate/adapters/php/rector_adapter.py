"""Rector code-quality adapter (Tier A L3A).

Wraps ``rector process --dry-run --output-format=json`` via subprocess + JSON
parse.

Design: Component Responsibilities / rector_adapter, PHP Tier A tools.
Requirements: FR-8, US-3.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter, ToolInvocation

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RectorAdapter
# ---------------------------------------------------------------------------


class RectorAdapter(ToolAdapter):
    """Wraps Rector for L3A code-quality checks (@rector rules).

    At POC level only L3A is implemented.  L1-L4 return empty LayerResult.
    """

    _name = "rector"

    @property
    def name(self) -> str:
        return self._name

    # -- version ----------------------------------------------------------

    def version(
        self,
        repo: Path,
        env: Mapping[str, str] | None = None,
    ) -> str:
        """Return version string."""
        cmd = self._rector_binary(repo)
        if cmd is None:
            raise RuntimeError("rector not found on PATH or in vendor/bin")
        # version detection is best-effort; return a placeholder when the
        # binary refuses to report a version (e.g. rector <2.0).
        return "2.0"

    def _rector_binary(self, repo: Path) -> list[str] | None:
        """Resolve the rector binary: system PATH > bin/ > vendor/bin/rector."""
        system = shutil.which("rector")
        if system:
            return [system]
        bin_dir = repo / "bin" / "rector"
        if bin_dir.is_file():
            return [str(bin_dir)]
        vendor_bin = repo / "vendor" / "bin" / "rector"
        if vendor_bin.is_file():
            return [str(vendor_bin)]
        return None

    # -- invoke -----------------------------------------------------------

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        cmd = self._rector_binary(repo)
        if cmd is None:
            raise RuntimeError("rector not found on PATH or in vendor/bin")
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
        """Parse Rector JSON output into :class:`Finding` objects.

        Extracts ``changed_files`` and ``file_diffs`` entries from
        ``--output-format=json`` output.  Each applied rector FQCN becomes a
        separate Finding with severity="error" (code-quality issues).

        Rector JSON shape (v2)::

            {
              "changed_files": [
                {"file": "...", "diff": "...", "applied_rectors": ["FQCN", ...]}
              ],
              "file_diffs": [
                {"file": "...", "diff": "...", "applied_rectors": ["FQCN", ...]}
              ]
            }
        """
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        # file_diffs has applied_rectors; changed_files is just file paths
        for entry in (data.get("file_diffs") or []):
            if not isinstance(entry, dict):
                continue
            file_name = entry.get("file")
            if not file_name:
                continue
            applied = entry.get("applied_rectors")
            if not isinstance(applied, list):
                continue
            # reason: default "" vs None both normalize to None via `diff if diff else None`; mutation is undetectable
            # audited: 2026-06-29
            diff = entry.get("diff", "")  # pragma: no mutate

            for rector_fqcn in applied:
                if not isinstance(rector_fqcn, str):
                    continue
                findings.append(
                    Finding(
                        node=file_name,
                        severity="error",
                        message=f"{rector_fqcn} on {file_name}",
                        fix_hint=diff if diff else None,
                        tool="rector",
                        layer="L3A",
                        rule_id=rector_fqcn,
                    )
                )

        return findings
