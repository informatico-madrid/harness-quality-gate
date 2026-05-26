"""Infection mutation-testing adapter (POC: parse only, no execution).

Wraps ``infection`` Mutation Testing Framework JSON output into
:class:`~harness_quality_gate.models.MutationStats`.

Design: Component Responsibilities / infection_adapter, PHP Tier A tools.
Requirements: FR-14, US-9.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Mapping

from ...models import MutationStats
from ..base import ToolAdapter, ToolInvocation


class InfectionAdapter(ToolAdapter):
    """Parses Infection mutation-testing JSON output into :class:`MutationStats`.

    POC level: parsing only. Actual ``infection`` invocation is Phase 2.
    """

    _name = "infection"

    # -- abstract interface -----------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        raise NotImplementedError("infection version detection not implemented (POC)")

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        raise NotImplementedError("infection invocation not implemented (POC)")

    def parse(  # type: ignore[override]
        self,
        stdout: str,
        stderr: str = "",
        exitcode: int = 0,
    ) -> MutationStats:  # type: ignore[override]
        """Parse Infection JSON output into :class:`MutationStats`.

        POC level: delegates to ``parse_stats()``. Accepts a single
        argument (backward-compatible with the verify command).
        """
        return self.parse_stats(stdout)

    # -- public API -------------------------------------------------------

    def parse_stats(self, stdout: str) -> MutationStats:
        """Parse Infection JSON (or semi-structured text) output into :class:`MutationStats`.

        Accepts both valid JSON and simplified key:value text like
        ``{killed:5,survived:1,...}`` (unquoted keys).

        Args:
            stdout: The tool's stdout string containing mutation results.

        Returns:
            A :class:`MutationStats` instance.
        """
        data: dict = {}

        # --- try valid JSON first ------------------------------------------
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            pass

        # --- fallback: extract key-value pairs from any text ---------------
        if not data:
            for m in re.finditer(r"(\w+)\s*:\s*(\d+)", stdout):
                data[m.group(1)] = int(m.group(2))

        killed = data.get("killed", 0)
        survived = data.get("survived", 0)
        timed_out = data.get("timed_out", 0)
        escaped = data.get("escaped", 0)
        untested = data.get("untested", 0)

        total = killed + survived + timed_out + untested
        covered = killed + survived + timed_out
        msi = killed / covered if covered else 0.0
        covered_msi = msi  # at POC covered = total mutations

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
