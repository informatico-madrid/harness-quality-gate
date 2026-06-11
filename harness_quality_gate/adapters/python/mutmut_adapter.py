"""Mutmut mutation testing adapter.

Wraps ``mutmut results --json`` and ``mutmut show`` into :class:`MutationStats`.

Design: Component Responsibilities / mutmut_adapter.
Requirements: FR-29, US-9.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Mapping

from ...models import MutationStats
from ..base import ToolAdapter, ToolInvocation


class MutmutAdapter(ToolAdapter):
    """Wraps ``mutmut`` mutation testing and parses results."""

    _name = "mutmut"

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        binary = shutil.which("mutmut")
        if binary is None:
            raise RuntimeError("mutmut not found on PATH")
        result = self._run([binary, "--version"], cwd=repo, env=env)
        return result.stdout.strip() or "unknown"

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 600.0,
    ) -> ToolInvocation:
        binary = shutil.which("mutmut")
        if binary is None:
            return ToolInvocation(stderr="mutmut not found on PATH", exitcode=3)
        cmd = [binary, "results", "--json"]
        if args:
            cmd.extend(args)
        return self._run(cmd, cwd=repo, env=env, timeout=timeout)

    def parse(  # type: ignore[override]
        self,
        stdout: str,
        *_compat: object,
    ) -> MutationStats:
        """Parse mutmut JSON output into :class:`MutationStats`.

        Accepts the ``mutmut results --json`` format:
        ``{"total": N, "killed": N, "survived": N, ...}``.
        Falls back to ``mutmut show`` text parsing if JSON is empty.
        """
        data: dict = {}

        # --- try valid JSON first ------------------------------------------
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            pass

        # --- fallback: extract key-value pairs from text output ----------
        if not data:
            import re
            for m in re.finditer(r"(\w+)\s*:\s*(\d+)", stdout):
                data[m.group(1)] = int(m.group(2))

        total = data.get("total") or 0
        killed = data.get("killed") or 0
        survived = data.get("survived") or 0
        timed_out = data.get("timeout") or 0
        escaped = data.get("escaped") or 0
        untested = data.get("untested") or 0

        covered = killed + survived + timed_out + escaped
        msi = killed / covered if covered else 0.0
        # covered_msi: when covered mutations == total mutations (all tested)
        covered_msi = msi

        return MutationStats(
            total=total,
            killed=killed,
            survived=survived,
            timed_out=timed_out,
            escaped=escaped,
            untested=untested,
            msi=round(msi, 4),
            covered_msi=round(covered_msi, 4),
        )
