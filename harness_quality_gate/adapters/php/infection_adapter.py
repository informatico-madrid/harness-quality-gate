"""Infection mutation-testing adapter (POC: parse only, no execution).

Wraps ``infection`` Mutation Testing Framework JSON output into
:class:`~harness_quality_gate.models.MutationStats`.

Design: Component Responsibilities / infection_adapter, PHP Tier A tools.
Requirements: FR-14, US-9.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Mapping

from ...models import MutationStats
from ..base import ToolAdapter, ToolInvocation


def _composer_bin_dir(repo: Path) -> str:
    """Return the bin-dir configured in composer.json, or 'vendor/bin'."""
    try:
        data = json.loads((repo / "composer.json").read_text(encoding="utf-8"))
        return data.get("config", {}).get("bin-dir", "vendor/bin")
    except (OSError, json.JSONDecodeError):
        return "vendor/bin"


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
        timeout: float = 600.0,
    ) -> ToolInvocation:
        """Run Infection mutation testing against *repo*.

        Uses ``vendor/bin/infection`` or the ``infection`` binary on PATH.
        Default arguments produce JSON log + text summary.

        Args:
            repo: Root path of the PHP repository.
            args: Additional CLI arguments.
            env: Optional environment variables.
            timeout: Maximum seconds to wait (default 600).

        Returns:
            A :class:`ToolInvocation` with stdout/stderr/exit code.
        """
        infection_bin = shutil.which("infection")
        if infection_bin is None:
            # Try vendor/bin/infection (default bin-dir), then composer.json bin-dir
            for candidate in [
                repo / "vendor" / "bin" / "infection",
                repo / _composer_bin_dir(repo) / "infection",
            ]:
                if candidate.is_file():
                    infection_bin = str(candidate)
                    break
        if infection_bin is None:
            # stdout/duration_seconds keep their dataclass defaults
            return ToolInvocation(
                stderr="infection not found on PATH or in vendor/bin",
                exitcode=3,
            )
        # --no-progress: suppress progress bar.
        # No --log-nums (removed in 0.29.x). Caller supplies --formatter=json.
        cmd = [infection_bin, "--no-progress"]
        if args:
            cmd.extend(args)
        return self._run(cmd, cwd=repo, env=env, timeout=timeout)

    def parse(  # type: ignore[override]
        self,
        stdout: str,
        *_compat: object,
    ) -> MutationStats:  # type: ignore[override]
        """Parse Infection JSON output into :class:`MutationStats`.

        POC level: delegates to ``parse_stats()``. Accepts a single
        argument (backward-compatible with the verify command).
        """
        return self.parse_stats(stdout)

    # -- public API -------------------------------------------------------

    def parse_stats(self, stdout: str) -> MutationStats:
        """Parse Infection text output (v0.29.x) into :class:`MutationStats`.

        Infection 0.29.x writes human-readable text like::

            6 mutations were generated:
                   6 mutants were killed
                   0 covered mutants were not detected
            Metrics:
                     Mutation Score Indicator (MSI): 100%
                     Covered Code MSI: 100%

        Also accepts legacy JSON output for forward-compatibility.

        Args:
            stdout: The tool's stdout string containing mutation results.

        Returns:
            A :class:`MutationStats` instance.
        """
        # --- try valid JSON first (legacy / future format) ----------------
        # The condition requires BOTH a dict AND a root-level "killed" key:
        # that is the JSON-format contract (a bare JSON string containing the
        # word "killed" must fall through to the text parser).
        try:
            data = json.loads(stdout)
            if isinstance(data, dict) and "killed" in data:
                # "killed" presence guaranteed by the guard above
                killed = int(data["killed"])
                survived = int(data.get("survived", 0))
                timed_out = int(data.get("timed_out", 0))
                escaped = int(data.get("escaped", 0))
                untested = int(data.get("untested", 0))
                msi = float(data.get("msi", 0.0))
                covered_msi = data.get("covered_msi")
                return MutationStats(
                    total=killed + survived + timed_out + escaped + untested,
                    killed=killed, survived=survived, timed_out=timed_out,
                    escaped=escaped, untested=untested,
                    msi=round(msi, 4),
                    covered_msi=round(covered_msi, 4) if covered_msi is not None else 0.0,
                )
        except (json.JSONDecodeError, ValueError):
            pass

        # --- parse Infection 0.29.x text output ---------------------------
        # Pattern: "N mutants were killed", "N covered mutants were not detected", etc.
        def _extract(pattern: str) -> int:
            m = re.search(pattern, stdout)
            return int(m.group(1)) if m else 0

        def _extract_pct(pattern: str) -> float:
            m = re.search(pattern, stdout)
            return float(m.group(1)) if m else 0.0

        killed = _extract(r"(\d+)\s+mutants were killed")
        not_detected = _extract(r"(\d+)\s+covered mutants were not detected")
        not_covered = _extract(r"(\d+)\s+mutants were not covered")
        errors = _extract(r"(\d+)\s+errors were encountered")
        timed_out = _extract(r"(\d+)\s+time\s*outs were encountered")
        total = _extract(r"(\d+)\s+mutations were generated")

        # "not detected" = survived/escaped mutants (covered but not killed)
        survived = not_detected
        untested = not_covered
        escaped = errors  # Infection v0.29 errors ≈ escaped (fatal errors in mutant)

        msi = _extract_pct(r"Mutation Score Indicator \(MSI\):\s*([\d.]+)%")
        covered_msi = _extract_pct(r"Covered Code MSI:\s*([\d.]+)%")

        # Fall back to computation if regex didn't find metrics line
        if msi == 0.0 and killed > 0:
            # covered >= killed > 0 here, so the division is always defined;
            # the MutationStats constructor below does the rounding.
            covered = killed + survived + timed_out
            msi = killed / covered * 100
            covered_msi = msi

        return MutationStats(
            total=total or (killed + survived + timed_out + untested),
            killed=killed,
            survived=survived,
            timed_out=timed_out,
            escaped=escaped,
            untested=untested,
            msi=round(msi, 4),
            covered_msi=round(covered_msi, 4),
        )
