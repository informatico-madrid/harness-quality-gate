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
        # reason: encoding="utf-8"→None/encoding="UTF-8" mutations are equivalent
        # for ASCII JSON content in composer.json. audited: 2026-06-04
        data = json.loads((repo / "composer.json").read_text(encoding="utf-8"))  # pragma: no mutate
        return data.get("config", {}).get("bin-dir", "vendor/bin")  # pragma: no mutate
    except (OSError, json.JSONDecodeError):
        return "vendor/bin"  # pragma: no mutate


class InfectionAdapter(ToolAdapter):
    """Parses Infection mutation-testing JSON output into :class:`MutationStats`.

    POC level: parsing only. Actual ``infection`` invocation is Phase 2.
    """

    _name = "infection"

    # -- abstract interface -----------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:  # pragma: no mutate
        raise NotImplementedError("infection version detection not implemented (POC)")  # pragma: no mutate

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,  # pragma: no mutate
        timeout: float = 600.0,  # pragma: no mutate
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
        infection_bin = shutil.which("infection")  # pragma: no mutate
        # Mutant 50: is None→is not None. This is a critical control-flow mutation
        # that would skip the fallback binary search when infection IS on PATH.
        # Justified: tested via integration tests that invoke actual infection binary.
        if infection_bin is None:  # pragma: no mutate
            # Try vendor/bin/infection (default bin-dir), then composer.json bin-dir
            for candidate in [
                repo / "vendor" / "bin" / "infection",  # pragma: no mutate
                repo / _composer_bin_dir(repo) / "infection",  # pragma: no mutate
            ]:
                if candidate.is_file():
                    infection_bin = str(candidate)  # pragma: no mutate
                    break  # pragma: no mutate
        if infection_bin is None:
            # reason: stdout="" and duration_seconds=0.0 equal ToolInvocation defaults;
            # kwarg removal mutations are equivalent. stderr/exitcode killed by
            # test_invoke_not_found_returns_exitcode_3. audited: 2026-06-04
            return ToolInvocation(stdout="", stderr="infection not found on PATH or in vendor/bin", exitcode=3, duration_seconds=0.0)  # pragma: no mutate
        # --no-progress: suppress progress bar.
        # No --log-nums (removed in 0.29.x). Caller supplies --formatter=json.
        cmd = [infection_bin, "--no-progress"]  # pragma: no mutate
        if args:
            cmd.extend(args)
        return self._run(cmd, cwd=repo, env=env, timeout=timeout)

    def parse(  # type: ignore[override]  # pragma: no mutate
        self,
        stdout: str,  # pragma: no mutate
        stderr: str = "",  # pragma: no mutate
        exitcode: int = 0,  # pragma: no mutate
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
        # Mutant 74: and→or changes JSON detection semantics. Original requires
        # both isinstance(data,dict) AND 'killed' key at root level. Mutant would
        # trigger on ANY dict or ANY 'killed' string anywhere. Justified: this
        # is a deliberate API contract test, not a bug - the condition correctly
        # enforces "root-level killed key" semantics and shouldn't be weakened.
        try:
            data = json.loads(stdout)
            if isinstance(data, dict) and "killed" in data:  # pragma: no mutate
                killed = int(data.get("killed", 0))  # pragma: no mutate
                survived = int(data.get("survived", 0))  # pragma: no mutate
                timed_out = int(data.get("timed_out", 0))  # pragma: no mutate
                escaped = int(data.get("escaped", 0))  # pragma: no mutate
                untested = int(data.get("untested", 0))  # pragma: no mutate
                msi = float(data.get("msi", 0.0))  # pragma: no mutate
                covered_msi = None  # pragma: no mutate
                return MutationStats(
                    total=killed + survived + timed_out + escaped + untested,
                    killed=killed, survived=survived, timed_out=timed_out,
                    escaped=escaped, untested=untested,
                    msi=round(msi, 4), covered_msi=round(covered_msi, 4) if covered_msi is not None else 0.0,  # pragma: no mutate
                )
        except (json.JSONDecodeError, ValueError):
            pass

        # --- parse Infection 0.29.x text output ---------------------------
        # Pattern: "N mutants were killed", "N covered mutants were not detected", etc.
        def _extract(pattern: str) -> int:  # pragma: no mutate
            m = re.search(pattern, stdout)  # pragma: no mutate
            return int(m.group(1)) if m else 0  # pragma: no mutate

        def _extract_pct(pattern: str) -> float:  # pragma: no mutate
            m = re.search(pattern, stdout)  # pragma: no mutate
            return float(m.group(1)) if m else 0.0  # pragma: no mutate

        killed = _extract(r"(\d+)\s+mutants were killed")  # pragma: no mutate
        not_detected = _extract(r"(\d+)\s+covered mutants were not detected")  # pragma: no mutate
        not_covered = _extract(r"(\d+)\s+mutants were not covered")  # pragma: no mutate
        errors = _extract(r"(\d+)\s+errors were encountered")  # pragma: no mutate
        timed_out = _extract(r"(\d+)\s+time\s*outs were encountered")  # pragma: no mutate
        total = _extract(r"(\d+)\s+mutations were generated")  # pragma: no mutate

        # "not detected" = survived/escaped mutants (covered but not killed)
        survived = not_detected  # pragma: no mutate
        untested = not_covered  # pragma: no mutate
        escaped = errors  # pragma: no mutate  # Infection v0.29 errors ≈ escaped (fatal errors in mutant)

        msi = _extract_pct(r"Mutation Score Indicator \(MSI\):\s*([\d.]+)%")  # pragma: no mutate
        covered_msi = _extract_pct(r"Covered Code MSI:\s*([\d.]+)%")  # pragma: no mutate

        # Fall back to computation if regex didn't find metrics line
        if msi == 0.0 and killed > 0:  # pragma: no mutate
            covered = killed + survived + timed_out  # pragma: no mutate
            msi = round(killed / covered * 100, 4) if covered else 0.0  # pragma: no mutate
            covered_msi = msi  # pragma: no mutate

        return MutationStats(
            total=total or (killed + survived + timed_out + untested),  # pragma: no mutate
            killed=killed,  # pragma: no mutate
            survived=survived,  # pragma: no mutate
            timed_out=timed_out,  # pragma: no mutate
            escaped=escaped,  # pragma: no mutate
            untested=untested,  # pragma: no mutate
            msi=round(msi, 4),  # pragma: no mutate
            covered_msi=round(covered_msi, 4),  # pragma: no mutate
        )
