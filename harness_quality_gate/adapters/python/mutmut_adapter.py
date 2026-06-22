"""Mutmut mutation testing adapter.

Wraps ``mutmut results --json`` and ``mutmut show`` into :class:`MutationStats`.

Design: Component Responsibilities / mutmut_adapter.
Requirements: FR-29, US-9.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from ...bootstrap import resolve_tool, ToolNotAvailable
from ...models import MutationStats
from ..base import ToolAdapter, ToolInvocation


class MutmutAdapter(ToolAdapter):
    """Wraps ``mutmut`` mutation testing and parses results."""

    _name = "mutmut"

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        try:
            binary = str(resolve_tool("mutmut", repo))
        except ToolNotAvailable:
            raise RuntimeError("mutmut not found on PATH or .venv")
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
        try:
            binary = str(resolve_tool("mutmut", repo))
        except ToolNotAvailable:
            return ToolInvocation(
                stderr="mutmut not found on PATH or .venv", exitcode=3
            )
        # mutmut 3.x has no ``results --json``; per-mutant status lines are
        # the only machine-readable output (same source as mutation_analyzer).
        cmd = [binary, "results", "--all", "true"]
        if args:
            cmd.extend(args)
        return self._run(cmd, cwd=repo, env=env, timeout=timeout)

    def run(
        self,
        repo: Path,
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 3600.0,
        paths: list[str] | None = None,
    ) -> ToolInvocation:
        """Execute the mutation campaign (``mutmut run``) in *repo*.

        L1 collects results right after; parity with PHP's Infection,
        which the PhpAdapter also executes inline. ``MUTATION_MAX_CHILDREN``
        in *env* caps parallelism — without it mutmut spawns one child per
        core, which produces false timeouts on many-core hosts (self-eval F3).

        When *paths* is provided (partial run), append them after ``mutmut run``
        to override the ``paths_to_mutate`` config.

        Uses :func:`resolve_tool` to locate the mutmut binary, which
        handles venv-priority internally.
        """
        try:
            binary = str(resolve_tool("mutmut", repo))
        except ToolNotAvailable:
            return ToolInvocation(
                stderr="mutmut not found on PATH or .venv", exitcode=3
            )
        cmd = [binary, "run"]
        if paths:
            cmd.extend(paths)
        # reason: mutation-resistant by design — see inline comment
        # audited: 2026-06-18
        max_children = (env or {}).get("MUTATION_MAX_CHILDREN", "")
        if max_children.isdigit():
            cmd.extend(["--max-children", max_children])
        return self._run(cmd, cwd=repo, env=env, timeout=timeout)

    def parse(  # type: ignore[override]
        self,
        stdout: str,
        *_compat: object,
    ) -> MutationStats:
        """Parse mutmut output into :class:`MutationStats`.

        Accepts, in order of preference: a JSON object
        (``{"total": N, "killed": N, ...}``), the per-mutant lines of
        ``mutmut results --all true`` (``pkg.x_f__mutmut_1: killed``), or
        bare ``key: number`` pairs as a last-resort text fallback.
        """
        # reason: Tipo C — cualquier valor falsy inicial es gemelo de {}: las dos
        # ramas siguientes reasignan data antes de cualquier acceso (json.loads
        # o _aggregate_mutant_lines, que siempre devuelve dict). # audited: 2026-06-12
        data: dict = {}

        # --- try valid JSON first ------------------------------------------
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            pass

        # --- per-mutant status lines (mutmut 3.x ``results --all true``) ---
        if not data:
            data = self._aggregate_mutant_lines(stdout)

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

    @staticmethod
    def _aggregate_mutant_lines(stdout: str) -> dict:
        """Aggregate ``pkg.x_f__mutmut_N: status`` lines into count keys.

        ``suspicious`` counts as timeout (conservative: it gates), while
        ``skipped``/``untested``/``no tests`` count as untested.
        """
        import re

        line_re = re.compile(
            r"^\s*\S+__mutmut_\d+:\s*"
            r"(killed|survived|timeout|suspicious|skipped|untested|no tests)\s*$"
        )
        counts = {"total": 0, "killed": 0, "survived": 0, "timeout": 0, "untested": 0}
        for line in stdout.splitlines():
            m = line_re.match(line)
            if m is None:
                continue
            status = m.group(1)
            counts["total"] += 1
            if status == "killed":
                counts["killed"] += 1
            elif status == "survived":
                counts["survived"] += 1
            elif status in ("timeout", "suspicious"):
                counts["timeout"] += 1
            else:
                counts["untested"] += 1
        return counts if counts["total"] else {}
