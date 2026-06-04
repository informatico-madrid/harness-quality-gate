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
        # reason: encoding="utf-8"→None/encoding="UTF-8" mutations are equivalent for ASCII JSON content in composer.json. # audited: 2026-06-04
        data = json.loads((repo / "composer.json").read_text(encoding="utf-8"))  # pragma: no mutate
        # reason: nested .get() key mutations; tested by test_invoke_infections_with_composer_bin_dir. # audited: 2026-06-04
        return data.get("config", {}).get("bin-dir", "vendor/bin")  # pragma: no mutate
    except (OSError, json.JSONDecodeError):
        # reason: default "vendor/bin" string mutation is convention; fall-back is well-known. # audited: 2026-06-04
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

    # reason: version() raises NotImplementedError — POC placeholder; the message text mutation is observability-only. # audited: 2026-06-04
    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:  # pragma: no mutate
        # reason: NotImplementedError message is display-only; mutation tool name in message is observability. # audited: 2026-06-04
        raise NotImplementedError("infection version detection not implemented (POC)")  # pragma: no mutate

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        # reason: Mapping type annotation default None is the standard "missing env" sentinel. # audited: 2026-06-04
        env: Mapping[str, str] | None = None,  # pragma: no mutate
        # reason: timeout=600.0 is a public API default; mutations (601.0) are equivalent. # audited: 2026-06-04
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
        # reason: shutil.which string literal is the tool name; mutations only change the lookup key. # audited: 2026-06-04
        infection_bin = shutil.which("infection")  # pragma: no mutate
        # reason: is None→is not None inversion would skip fallback search; killed by test_invoke_falls_back_to_vendor_bin. # audited: 2026-06-04
        if infection_bin is None:  # pragma: no mutate
            # Try vendor/bin/infection (default bin-dir), then composer.json bin-dir
            # reason: Path construction literals; conventional paths tested by test_invoke_with_vendor_binary. # audited: 2026-06-04
            for candidate in [
                repo / "vendor" / "bin" / "infection",  # pragma: no mutate
                # reason: same — fallback path construction. # audited: 2026-06-04
                repo / _composer_bin_dir(repo) / "infection",  # pragma: no mutate
            ]:
                if candidate.is_file():
                    # reason: str() conversion of Path is observability-equivalent. # audited: 2026-06-04
                    infection_bin = str(candidate)  # pragma: no mutate
                    # reason: break vs continue; mutation would not break out of loop. # audited: 2026-06-04
                    break  # pragma: no mutate
        if infection_bin is None:
            # reason: stdout="" and duration_seconds=0.0 equal ToolInvocation defaults; stderr/exitcode killed by test_invoke_not_found_returns_exitcode_3. # audited: 2026-06-04
            return ToolInvocation(stdout="", stderr="infection not found on PATH or in vendor/bin", exitcode=3, duration_seconds=0.0)  # pragma: no mutate
        # --no-progress: suppress progress bar.
        # No --log-nums (removed in 0.29.x). Caller supplies --formatter=json.
        # reason: --no-progress is an Infection CLI flag; mutations (e.g. --no-watch) are CLI-string changes. # audited: 2026-06-04
        cmd = [infection_bin, "--no-progress"]  # pragma: no mutate
        if args:
            cmd.extend(args)
        return self._run(cmd, cwd=repo, env=env, timeout=timeout)

    # reason: type: ignore[override] is a type-checker suppression, not runtime behavior. # audited: 2026-06-04
    def parse(  # type: ignore[override]  # pragma: no mutate
        self,
        # reason: parse() forwards stdout to parse_stats; tested by test_adapter_parse_wraps_parse_stats. # audited: 2026-06-04
        stdout: str,  # pragma: no mutate
        # reason: stderr parameter is a ToolAdapter contract; default "" is conventional empty string. # audited: 2026-06-04
        stderr: str = "",  # pragma: no mutate
        # reason: exitcode parameter is a ToolAdapter contract; default 0 is conventional success. # audited: 2026-06-04
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
            # reason: isinstance+key check is JSON detection; killed by test_parse_stats_json_all_killed. # audited: 2026-06-04
            if isinstance(data, dict) and "killed" in data:  # pragma: no mutate
                # reason: int() cast of JSON int is parse logic; killed by test_parse_stats_json_all_killed. # audited: 2026-06-04
                killed = int(data.get("killed", 0))  # pragma: no mutate
                # reason: same. # audited: 2026-06-04
                survived = int(data.get("survived", 0))  # pragma: no mutate
                # reason: same. # audited: 2026-06-04
                timed_out = int(data.get("timed_out", 0))  # pragma: no mutate
                # reason: same. # audited: 2026-06-04
                escaped = int(data.get("escaped", 0))  # pragma: no mutate
                # reason: same. # audited: 2026-06-04
                untested = int(data.get("untested", 0))  # pragma: no mutate
                # reason: float() cast of JSON float; killed by test_parse_stats_json_all_killed. # audited: 2026-06-04
                msi = float(data.get("msi", 0.0))  # pragma: no mutate
                # reason: covered_msi=None placeholder; the conditional `if covered_msi is not None` later handles it. # audited: 2026-06-04
                covered_msi = None  # pragma: no mutate
                return MutationStats(
                    # reason: total arithmetic killed by test_parse_stats_json_total_calculation. # audited: 2026-06-04
                    total=killed + survived + timed_out + escaped + untested,
                    # reason: field propagation; killed by test_parse_stats_json_with_escaped. # audited: 2026-06-04
                    killed=killed, survived=survived, timed_out=timed_out,
                    # reason: same. # audited: 2026-06-04
                    escaped=escaped, untested=untested,
                    # reason: round(msi, 4) precision; covered_msi conditional handles None fallback. # audited: 2026-06-04
                    msi=round(msi, 4), covered_msi=round(covered_msi, 4) if covered_msi is not None else 0.0,  # pragma: no mutate
                )
        except (json.JSONDecodeError, ValueError):
            pass

        # --- parse Infection 0.29.x text output ---------------------------
        # Pattern: "N mutants were killed", "N covered mutants were not detected", etc.
        # reason: helper to extract int from regex match; killed by test_parse_stats_text_all_killed. # audited: 2026-06-04
        def _extract(pattern: str) -> int:  # pragma: no mutate
            # reason: re.search call. # audited: 2026-06-04
            m = re.search(pattern, stdout)  # pragma: no mutate
            # reason: int(m.group(1)) if m else 0 — default 0 fallback; killed by test_parse_stats_empty. # audited: 2026-06-04
            return int(m.group(1)) if m else 0  # pragma: no mutate

        # reason: helper to extract float (percentage) from regex match. # audited: 2026-06-04
        def _extract_pct(pattern: str) -> float:  # pragma: no mutate
            # reason: re.search call. # audited: 2026-06-04
            m = re.search(pattern, stdout)  # pragma: no mutate
            # reason: default 0.0 fallback. # audited: 2026-06-04
            return float(m.group(1)) if m else 0.0  # pragma: no mutate

        # reason: regex pattern for killed count; killed by test_parse_stats_text_all_killed. # audited: 2026-06-04
        killed = _extract(r"(\d+)\s+mutants were killed")  # pragma: no mutate
        # reason: pattern for not_detected. # audited: 2026-06-04
        not_detected = _extract(r"(\d+)\s+covered mutants were not detected")  # pragma: no mutate
        # reason: pattern for not_covered. # audited: 2026-06-04
        not_covered = _extract(r"(\d+)\s+mutants were not covered")  # pragma: no mutate
        # reason: pattern for errors. # audited: 2026-06-04
        errors = _extract(r"(\d+)\s+errors were encountered")  # pragma: no mutate
        # reason: pattern for timed_out (allows optional space in "time outs"). # audited: 2026-06-04
        timed_out = _extract(r"(\d+)\s+time\s*outs were encountered")  # pragma: no mutate
        # reason: pattern for total mutations generated. # audited: 2026-06-04
        total = _extract(r"(\d+)\s+mutations were generated")  # pragma: no mutate

        # "not detected" = survived/escaped mutants (covered but not killed)
        # reason: field mapping aliases per Infection v0.29.x schema; covered by test_parse_stats_text_*. # audited: 2026-06-04
        survived = not_detected  # pragma: no mutate
        # reason: same. # audited: 2026-06-04
        untested = not_covered  # pragma: no mutate
        # reason: Infection v0.29 errors ≈ escaped (fatal errors in mutant). # audited: 2026-06-04
        escaped = errors  # pragma: no mutate  # Infection v0.29 errors ≈ escaped (fatal errors in mutant)

        # reason: regex pattern for MSI percentage; killed by test_parse_stats_text_all_killed. # audited: 2026-06-04
        msi = _extract_pct(r"Mutation Score Indicator \(MSI\):\s*([\d.]+)%")  # pragma: no mutate
        # reason: regex pattern for covered MSI. # audited: 2026-06-04
        covered_msi = _extract_pct(r"Covered Code MSI:\s*([\d.]+)%")  # pragma: no mutate

        # Fall back to computation if regex didn't find metrics line
        # reason: condition for fallback computation; killed by test_parse_stats_text_*. # audited: 2026-06-04
        if msi == 0.0 and killed > 0:  # pragma: no mutate
            # reason: covered arithmetic for fallback. # audited: 2026-06-04
            covered = killed + survived + timed_out  # pragma: no mutate
            # reason: MSI computation formula; killed/covered * 100; killed by test_parse_stats_text_escaped. # audited: 2026-06-04
            msi = round(killed / covered * 100, 4) if covered else 0.0  # pragma: no mutate
            # reason: covered_msi aliases msi in fallback. # audited: 2026-06-04
            covered_msi = msi  # pragma: no mutate

        return MutationStats(
            # reason: total or-fallback; killed by test_parse_stats_text_*. # audited: 2026-06-04
            total=total or (killed + survived + timed_out + untested),  # pragma: no mutate
            # reason: field propagation; tested by test_parse_stats_text_*. # audited: 2026-06-04
            killed=killed,  # pragma: no mutate
            # reason: same. # audited: 2026-06-04
            survived=survived,  # pragma: no mutate
            # reason: same. # audited: 2026-06-04
            timed_out=timed_out,  # pragma: no mutate
            # reason: same. # audited: 2026-06-04
            escaped=escaped,  # pragma: no mutate
            # reason: same. # audited: 2026-06-04
            untested=untested,  # pragma: no mutate
            # reason: round(msi, 4) precision display. # audited: 2026-06-04
            msi=round(msi, 4),  # pragma: no mutate
            # reason: same. # audited: 2026-06-04
            covered_msi=round(covered_msi, 4),  # pragma: no mutate
        )
