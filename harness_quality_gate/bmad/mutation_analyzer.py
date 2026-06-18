"""Mutation Analyzer — analyze mutation testing results.

Parses ``mutmut results`` and ``infection-log.json`` output,
producing per-module kill statistics as :class:`MutationStats`.

Design: Component Responsibilities / mutation_analyzer.
Requirements: FR-34, US-15.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# Pattern to extract module from mutmut 3.x mutant names:
# Format: "src.calculations.x_func__mutmut_N: status"
# Group 1: dotted module path, Group 2: function name, Group 3: status
MUTMUT_DOTTED_PATH = re.compile(
    r"^([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)\.(\w+)__mutmut_\d+: (\w+)$"
)
MUTMUT_PYC_FILE = re.compile(
    r"^([a-zA-Z_][a-zA-Z0-9_]*\.py)::(\w+)__mutmut_\d+: (\w+)$"
)
INFECTION_LOG = re.compile(r"infection-log\.json$")


@dataclass
class ModuleMutStats:
    """Mutation stats for a single module."""

    module: str
    total: int = 0
    killed: int = 0
    survived: int = 0
    timeout: int = 0
    skipped: int = 0

    @property
    def kill_rate(self) -> float:
        """Return kill rate as a fraction (0.0-1.0)."""
        if self.total == 0:
            return 1.0
        return self.killed / self.total


@dataclass
class SurvivedMutant:
    """A single survived or timeout mutant with actionable detail."""

    mutant_id: str
    module: str
    file_path: str
    status: str  # "survived" or "timeout"


def parse_survivors(repo: Path) -> list[SurvivedMutant]:
    """Parse survived and timeout mutants from ``mutmut results`` output.

    Returns a list of each non-killed mutant with:
    - mutant_id: the mutmut ID (e.g., ``x_source_targets__mutmut_8``)
    - module: dotted module path (e.g., ``harness_quality_gate.adapters.base``)
    - file_path: filesystem path (e.g., ``harness_quality_gate/adapters/base.py``)
    - status: ``"survived"`` or ``"timeout"``

    Sorted by file_path, then mutant_id.
    """
    try:
        result = subprocess.run(
            ["mutmut", "results"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    if not result.stdout.strip():
        return []

    survivors: list[SurvivedMutant] = []

    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue

        module = _extract_mutmut_module(line)
        status = _extract_mutmut_status(line)
        if module is None or status is None:
            continue

        if status not in ("survived", "timeout"):
            continue

        # Extract the mutant_id: split dotted path on last segment before __mutmut_N
        full_key = line.rsplit(":", 1)[0].strip()
        # full_key = "harness_quality_gate.adapters.base.x_source_targets__mutmut_8"
        # We know module = "harness_quality_gate.adapters.base"
        # mutant_id is the part after module + "."
        suffix = full_key[len(module) :].lstrip(".")
        # suffix could be like "base.x_source_targets__mutmut_8"
        # The last component after the last dot is the mutant function name
        func_name = suffix.rsplit(".", 1)[-1]  # e.g. "x_source_targets__mutmut_8"

        module_path = module.replace(".", "/") + ".py"

        survivors.append(
            SurvivedMutant(
                mutant_id=func_name,
                module=module,
                file_path=module_path,
                status=status,
            )
        )

    survivors.sort(key=lambda s: (s.file_path, s.mutant_id))
    return survivors


def parse_mutmut(
    repo: Path,
    *,
    survivors_only: bool = False,
) -> dict[str, ModuleMutStats]:
    """Parse mutmut result output.

    Args:
        repo: Path to the repository root.
        survivors_only: If True, run ``mutmut results`` (survivors only).
            If False, run ``mutmut results --all true`` (all mutants).

    Returns:
        A dict mapping module name to :class:`ModuleMutStats`.
    """
    cmd = ["mutmut", "results"]
    if not survivors_only:
        cmd.extend(["--all", "true"])

    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}

    if not result.stdout.strip():
        return {}

    stats: dict[str, ModuleMutStats] = {}

    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue

        module = _extract_mutmut_module(line)
        status = _extract_mutmut_status(line)
        if module is None or status is None:
            continue

        stats[module] = _update_mutmut_stats(
            stats.get(module),
            status,
            module_name=module,
        )

    return stats


# Infection 0.29 groups mutants into per-status LISTS; each entry carries
# mutator.originalFilePath. Maps each list to the ModuleMutStats field it
# increments (simulation bug H13: the legacy "mutators" mapping never
# existed in modern Infection, so the kill-map was always empty).
_INFECTION_STATUS_FIELDS = {
    "killed": "killed",
    "escaped": "survived",
    "timeouted": "timeout",
    "uncovered": "skipped",
    "ignored": "skipped",
}


def parse_infection(repo: Path) -> dict[str, ModuleMutStats]:
    """Parse ``infection-log.json`` (Infection 0.29 JSON logger format).

    Returns a dict mapping module name (source file stem) to
    :class:`ModuleMutStats`.
    """
    log_file = _find_infection_log(repo)
    if log_file is None or not log_file.exists():
        return {}

    try:
        data = json.loads(log_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    if not isinstance(data, dict):
        return {}

    counts: dict[str, dict[str, int]] = {}

    for status_list, field_name in _INFECTION_STATUS_FIELDS.items():
        mutants = data.get(status_list)
        if not isinstance(mutants, list):
            continue
        for mutant in mutants:
            if not isinstance(mutant, dict):
                continue
            file_path = (mutant.get("mutator") or {}).get("originalFilePath")
            if not file_path:
                continue
            module = Path(file_path).stem
            module_counts = counts.setdefault(
                module,
                {"total": 0, "killed": 0, "survived": 0, "timeout": 0, "skipped": 0},
            )
            module_counts["total"] += 1
            module_counts[field_name] += 1

    return {module: ModuleMutStats(module=module, **c) for module, c in counts.items()}


@dataclass
class MutationStats:
    """Unified mutation stats for a project."""

    tool: str
    modules: dict[str, ModuleMutStats] = field(default_factory=dict)

    @property
    def total_mutants(self) -> int:
        return sum(m.total for m in self.modules.values())

    @property
    def total_killed(self) -> int:
        return sum(m.killed for m in self.modules.values())

    @property
    def kill_rate(self) -> float:
        """Return overall kill rate as a fraction (0.0-1.0)."""
        if self.total_mutants == 0:
            return 1.0
        return self.total_killed / self.total_mutants


def analyze(repo: Path, tool: str = "mutmut") -> MutationStats:
    """Analyze mutation testing results from the specified tool.

    Args:
        repo: Path to the repository root.
        tool: Tool to parse — "mutmut" or "infection".

    Returns:
        Unified :class:`MutationStats`.
    """
    if tool == "infection":
        modules = parse_infection(repo)
    else:
        modules = parse_mutmut(repo)

    return MutationStats(tool=tool, modules=modules)


def _extract_mutmut_module(line: str) -> Optional[str]:
    """Extract dotted module path from a mutmut result line.

    For ``MUTMUT_DOTTED_PATH`` returns group(1) — the dotted module path.
    For ``MUTMUT_PYC_FILE`` returns group(1) — the .py filename stem.
    """
    match = MUTMUT_DOTTED_PATH.match(line)
    if match:
        return match.group(1)
    match = MUTMUT_PYC_FILE.match(line)
    if match:
        base = match.group(1)
        if base.endswith(".py"):
            base = base[:-3]
        return base
    return None


def _extract_mutmut_status(line: str) -> Optional[str]:
    """Extract status from a mutmut result line."""
    parts = line.rsplit(":", 1)
    if len(parts) == 2:
        return parts[1].strip()
    return None


def _update_mutmut_stats(
    existing: Optional[ModuleMutStats],
    status: str,
    module_name: str = "",
) -> ModuleMutStats:
    """Add one mutant to stats, returning the updated stats."""
    if existing is None:
        existing = ModuleMutStats(
            module=module_name,
            total=0,
            killed=0,
            survived=0,
            timeout=0,
            skipped=0,
        )

    if status == "killed":
        existing = ModuleMutStats(
            module=existing.module,
            total=existing.total + 1,
            killed=existing.killed + 1,
            survived=existing.survived,
            timeout=existing.timeout,
            skipped=existing.skipped,
        )
    elif status == "survived":
        existing = ModuleMutStats(
            module=existing.module,
            total=existing.total + 1,
            killed=existing.killed,
            survived=existing.survived + 1,
            timeout=existing.timeout,
            skipped=existing.skipped,
        )
    elif status == "timeout":
        existing = ModuleMutStats(
            module=existing.module,
            total=existing.total + 1,
            killed=existing.killed,
            survived=existing.survived,
            timeout=existing.timeout + 1,
            skipped=existing.skipped,
        )
    elif status == "skipped":
        existing = ModuleMutStats(
            module=existing.module,
            total=existing.total + 1,
            killed=existing.killed,
            survived=existing.survived,
            timeout=existing.timeout,
            skipped=existing.skipped + 1,
        )
    return existing


def _find_infection_log(repo: Path) -> Optional[Path]:
    """Find infection-log.json anywhere under repo."""
    for candidate in repo.rglob("infection-log.json"):
        if INFECTION_LOG.search(str(candidate)):
            return candidate
    return None


def main(argv: list[str]) -> int:
    """CLI: print the mutation kill-map; with ``--gate`` also gate on 100%.

    Usage::

        python3 -m harness_quality_gate.bmad.mutation_analyzer <repo> [--gate] [--tool mutmut|infection]

    Default output is the kill-map JSON consumed by step-03-layer2.
    With ``--gate`` (step-02-layer1) the exit code is 0 only when every
    module killed all its mutants (no survivors, no timeouts) — the
    100/100 hard-gate policy; per-module threshold ramps are not supported.
    """
    args = list(argv)
    gate = "--gate" in args
    if gate:
        args.remove("--gate")
    tool = "mutmut"
    if "--tool" in args:
        idx = args.index("--tool")
        tool = args[idx + 1]
        del args[idx : idx + 2]
    if len(args) != 1:
        print(
            "Usage: mutation_analyzer <repo> [--gate] [--tool mutmut|infection]",
            file=sys.stderr,
        )
        return 2

    stats = analyze(Path(args[0]), tool=tool)
    payload: dict[str, object] = {
        "tool": stats.tool,
        "mutation_kill_map": {
            name: {"killed": m.killed, "total": m.total, "rate": round(m.kill_rate, 3)}
            for name, m in stats.modules.items()
        },
        "overall_kill_rate": round(stats.kill_rate, 3),
    }
    if gate:
        ok = all(m.survived == 0 and m.timeout == 0 for m in stats.modules.values())
        payload["gate"] = "OK" if ok else "NOK"
        print(json.dumps(payload, indent=2))
        return 0 if ok else 1
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
