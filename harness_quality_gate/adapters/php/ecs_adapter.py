"""Easy Coding Standard adapter (Tier A L3A).

Wraps ``ecs check`` via subprocess + JSON parse.

Design: Component Responsibilities / ecs_adapter, PHP Tier A tools.
Requirements: FR-8, US-3.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter, ToolInvocation

# reason: logger name mutation does not change observability; only the __name__ label differs.
# audited: 2026-06-04
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EcsAdapter
# ---------------------------------------------------------------------------


class EcsAdapter(ToolAdapter):
    """Wraps Easy Coding Standard for L3A code-quality checks.

    At POC level only L3A is implemented.  L1-L4 return empty LayerResult.
    """

    _name = "ecs"

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
        cmd = self._ecs_binary(repo)
        if cmd is None:
            raise RuntimeError("ecs not found on PATH or in vendor/bin")
        result = subprocess.run(  # noqa: S603
            [*cmd, "--version"],
            cwd=str(repo),
            env={**os.environ, **(env or {})},
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ecs --version failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def _ecs_binary(self, repo: Path) -> list[str] | None:
        """Resolve the ecs binary: system PATH > bin/ > vendor/bin/ecs."""
        system = shutil.which("ecs")
        if system:
            return [system]
        bin_dir = repo / "bin" / "ecs"
        if bin_dir.is_file():
            return [str(bin_dir)]
        vendor_bin = repo / "vendor" / "bin" / "ecs"
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
        cmd = self._ecs_binary(repo)
        if cmd is None:
            raise RuntimeError("ecs not found on PATH or in vendor/bin")
        return self._run(
            [*cmd, *args, str(repo)],
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
        """Parse ECS JSON output into :class:`Finding` objects.

        Extracts ``files.<path>.errors[]`` from ``--output-format=json``
        output and maps each entry to a Finding with severity="error"
        (ECS/Rector violations must be enforceable — they block the gate).
        """
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        files = data.get("files")
        if not isinstance(files, dict):
            return findings

        for file_path, file_data in files.items():
            if not isinstance(file_data, dict):
                continue
            errors = file_data.get("errors")
            if not isinstance(errors, list):
                errors = []
            # ECS 12.x: "errors" are violations that CANNOT be autofixed.
            # "diffs" are violations that were autofixed (applied_checkers).
            # Both must be flagged so the gate blocks on ANY style violation.
            diffs = file_data.get("diffs")
            if not isinstance(diffs, list):
                diffs = []
            for err in errors:
                if not isinstance(err, dict):
                    continue
                line = err.get("line")
                message = err.get("message", "")
                source_class = err.get("source_class", "")  # pragma: no mutate — "" and None both normalize to None via `source_class if source_class else None`
                detail = message
                if line:
                    detail = f"line {line}: {detail}"
                findings.append(
                    Finding(
                        node=file_path,
                        severity="error",
                        message=detail or file_path,
                        tool="ecs",
                        layer="L3A",
                        rule_id=source_class if source_class else None,
                    )
                )
            for diff in diffs:
                if not isinstance(diff, dict):
                    continue
                applied = diff.get("applied_checkers")
                if not isinstance(applied, list):
                    continue
                raw_diff = diff.get("diff", "")  # pragma: no mutate — "" and None both normalize to None via `raw_diff if raw_diff else None`
                for checker in applied:
                    if not isinstance(checker, str):
                        continue
                    findings.append(
                        Finding(
                            node=file_path,
                            severity="error",
                            message=f"{checker} applied to {file_path}",
                            fix_hint=raw_diff if raw_diff else None,
                            tool="ecs",
                            layer="L3A",
                            rule_id=checker,
                        )
                    )

        return findings
