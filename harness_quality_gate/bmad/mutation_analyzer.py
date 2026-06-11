"""Mutation Analyzer — analyze mutation testing results.

Parses ``mutmut results --all true`` and ``infection-log.json`` output,
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
# Example: "src.calculations.x_func__mutmut_42: killed" -> module "calculations"
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


def parse_mutmut(repo: Path) -> dict[str, ModuleMutStats]:
    """Parse ``mutmut results --all true`` output.

    Returns a dict mapping module name to :class:`ModuleMutStats`.
    """
    try:
        result = subprocess.run(
            ["mutmut", "results", "--all", "true"],
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

        stats[module] = _update_mutmut_stats(stats.get(module), status)

    return stats


def parse_infection(repo: Path) -> dict[str, ModuleMutStats]:
    """Parse ``infection-log.json`` output.

    Returns a dict mapping module name to :class:`ModuleMutStats`.
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

    stats: dict[str, ModuleMutStats] = {}

    for module, mutants in (data.get("mutators") or {}).items():
        if not isinstance(mutants, list):
            continue
        killed = sum(1 for m in mutants if m.get("status") == "killed")
        survived = sum(1 for m in mutants if m.get("status") == "survived")
        timeout = sum(1 for m in mutants if m.get("status") == "timed_out")
        skipped = sum(1 for m in mutants if m.get("status") in ("skipped", "no_changes"))
        total = len(mutants)

        stats[module] = ModuleMutStats(
            module=module, total=total, killed=killed,
            survived=survived, timeout=timeout, skipped=skipped,
        )

    return stats


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
    """Extract module name from a mutmut result line."""
    match = MUTMUT_DOTTED_PATH.match(line)
    if match:
        return match.group(2)
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
) -> ModuleMutStats:
    """Add one mutant to stats, returning the updated stats."""
    if existing is None:
        existing = ModuleMutStats(module="", total=0, killed=0, survived=0, timeout=0, skipped=0)

    if status == "killed":
        existing = ModuleMutStats(
            module=existing.module, total=existing.total + 1,
            killed=existing.killed + 1, survived=existing.survived,
            timeout=existing.timeout, skipped=existing.skipped,
        )
    elif status == "survived":
        existing = ModuleMutStats(
            module=existing.module, total=existing.total + 1,
            killed=existing.killed, survived=existing.survived + 1,
            timeout=existing.timeout, skipped=existing.skipped,
        )
    elif status == "timeout":
        existing = ModuleMutStats(
            module=existing.module, total=existing.total + 1,
            killed=existing.killed, survived=existing.survived,
            timeout=existing.timeout + 1, skipped=existing.skipped,
        )
    elif status == "skipped":
        existing = ModuleMutStats(
            module=existing.module, total=existing.total + 1,
            killed=existing.killed, survived=existing.survived,
            timeout=existing.timeout, skipped=existing.skipped + 1,
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
        del args[idx:idx + 2]
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
        ok = all(
            m.survived == 0 and m.timeout == 0 for m in stats.modules.values()
        )
        payload["gate"] = "OK" if ok else "NOK"
        print(json.dumps(payload, indent=2))
        return 0 if ok else 1
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
