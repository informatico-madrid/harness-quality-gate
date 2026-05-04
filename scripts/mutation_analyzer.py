#!/usr/bin/env python3
"""
Mutation Analyzer — Analyze mutation testing results with per-module thresholds.

Parses mutmut 3.x results via `mutmut results --all true` and produces
per-module kill statistics. Compares against thresholds defined in
pyproject.toml [tool.quality-gate.mutation].

Usage:
    # Original mode: JSON kill-map only
    python3 mutation_analyzer.py <project_root>

    # Gate mode: Compare against thresholds, output OK/NOK
    python3 mutation_analyzer.py <project_root> --gate

    # Gate mode for a single module
    python3 mutation_analyzer.py <project_root> --gate --module calculations

Output:
    JSON with mutation_kill_map per module, overall kill rate, and gate status.

Data source:
    mutmut 3.x stores results in an internal cache (not .mutmut/index.html).
    This script uses `mutmut results --all true` to get per-mutant status,
    then aggregates by module name extracted from the mutant identifier.

    Format: "custom_components.ev_trip_planner.<module>.<func>__mutmut_N: <status>"
"""

import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

PYPROJECT_TOML = "pyproject.toml"

# Pattern to extract module from mutmut 3.x mutant names:
# With module: "custom_components.ev_trip_planner.calculations.x_func__mutmut_42: killed"
# Without module (__init__.py): "custom_components.ev_trip_planner.x_async_setup__mutmut_1: killed"
MUTMUT_NAME_WITH_MODULE = re.compile(
    r"^custom_components\.ev_trip_planner\.(\w+)\.\w+__mutmut_\d+: (\w+)$"
)
MUTMUT_NAME_NO_MODULE = re.compile(
    r"^custom_components\.ev_trip_planner\.\w+__mutmut_\d+: (\w+)$"
)


def parse_mutmut_results(project_root: Path) -> dict[str, Any]:
    """Parse mutmut 3.x results via `mutmut results --all true`.

    Returns a dict with:
    - found: bool
    - mutation_kill_map: dict of module_name -> {killed, survived, timeout, no_tests, total, rate}
    - overall_kill_rate: float
    - overall_killed: int
    - overall_total: int
    """
    try:
        result = subprocess.run(
            [".venv/bin/activate", "&&", "mutmut", "results", "--all", "true"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=60,
            shell=True,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {"error": "mutmut results command failed", "found": False}

    if result.returncode != 0:
        # Try without shell activation (venv might already be active)
        try:
            result = subprocess.run(
                ["mutmut", "results", "--all", "true"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return {"error": "mutmut not available", "found": False}

    if not result.stdout.strip():
        return {"error": "mutmut results empty — run 'mutmut run' first", "found": False}

    # Parse output: "module.submodule.func__mutmut_N: status"
    module_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"killed": 0, "survived": 0, "timeout": 0, "no_tests": 0, "skipped": 0, "suspicious": 0}
    )
    other_count = 0

    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if ": " not in line:
            continue

        name, status = line.rsplit(": ", 1)
        status = status.strip().lower()

        # Try to extract module name from mutmut 3.x naming convention
        # Pattern 1: custom_components.ev_trip_planner.<module>.<func>__mutmut_N
        match = MUTMUT_NAME_WITH_MODULE.match(line)
        if match:
            module_name = match.group(1)
        # Pattern 2: custom_components.ev_trip_planner.<func>__mutmut_N (package-level, __init__.py)
        elif MUTMUT_NAME_NO_MODULE.match(line):
            module_name = "__init__"
        else:
            # Fallback: try to extract from dotted path
            parts = name.split(".")
            if len(parts) >= 4 and parts[0] == "custom_components" and parts[1] == "ev_trip_planner":
                module_name = parts[2]
            else:
                module_name = "_other"
                other_count += 1

        if status in module_stats[module_name]:
            module_stats[module_name][status] += 1

    # Build kill_map with rates
    kill_map: dict[str, dict[str, Any]] = {}
    overall_killed = 0
    overall_total = 0

    for module_name, stats in sorted(module_stats.items()):
        total = stats["killed"] + stats["survived"] + stats["timeout"] + stats["no_tests"]
        if total == 0:
            continue
        rate = round(stats["killed"] / total, 3)
        kill_map[module_name] = {
            "killed": stats["killed"],
            "survived": stats["survived"],
            "timeout": stats["timeout"],
            "no_tests": stats["no_tests"],
            "total": total,
            "rate": rate,
        }
        overall_killed += stats["killed"]
        overall_total += total

    overall_rate = round(overall_killed / overall_total, 3) if overall_total > 0 else 0.0

    return {
        "found": True,
        "mutation_kill_map": kill_map,
        "overall_kill_rate": overall_rate,
        "overall_killed": overall_killed,
        "overall_total": overall_total,
    }


def load_targets_from_pyproject(project_root: Path) -> dict[str, Any]:
    """Load mutation targets from pyproject.toml [tool.quality-gate.mutation].

    Returns a dict with:
    - global_kill_threshold: float
    - fail_on_missing_module: bool
    - increment_step: float
    - target_final: float
    - modules_per_sprint: int
    - modules: dict of module_name -> {kill_threshold, status, notes}
    """
    pyproject_path = project_root / PYPROJECT_TOML
    if not pyproject_path.exists():
        return {}

    if tomllib is None:
        print("[WARN] tomllib not available — cannot read pyproject.toml. Using defaults.", file=sys.stderr)
        return {}

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    qg = data.get("tool", {}).get("quality-gate", {}).get("mutation", {})
    if not qg:
        return {}

    return {
        "global_kill_threshold": qg.get("global_kill_threshold", 0.48),
        "fail_on_missing_module": qg.get("fail_on_missing_module", False),
        "increment_step": qg.get("increment_step", 0.05),
        "target_final": qg.get("target_final", 0.80),
        "modules_per_sprint": qg.get("modules_per_sprint", 2),
        "modules": qg.get("modules", {}),
    }


def run_gate(
    project_root: Path,
    target_module: Optional[str] = None,
) -> dict[str, Any]:
    """Run mutation gate: parse results + compare against thresholds.

    Returns a dict with:
    - gate: "OK" or "NOK"
    - modules: list of per-module results
    - summary: overall statistics
    """
    # 1. Parse mutation results from mutmut 3.x
    mutmut_result = parse_mutmut_results(project_root)
    kill_map = mutmut_result.get("mutation_kill_map", {})

    if not kill_map:
        return {
            "gate": "NOK",
            "error": mutmut_result.get("error", "No mutation results found. Run 'mutmut run' first."),
            "modules": [],
            "summary": {
                "modules_checked": 0,
                "modules_passed": 0,
                "modules_failed": 0,
            },
        }

    # 2. Load targets from pyproject.toml
    targets = load_targets_from_pyproject(project_root)
    global_threshold = targets.get("global_kill_threshold", 0.48)
    fail_on_missing = targets.get("fail_on_missing_module", False)
    module_targets = targets.get("modules", {})

    # 3. Compare per-module
    modules = []
    for module_name, data in kill_map.items():
        if data["total"] == 0:
            continue

        rate = data["rate"]

        # Get threshold for this module from [tool.quality-gate.mutation.modules.<name>]
        module_config = module_targets.get(module_name, {})
        threshold = module_config.get("kill_threshold", global_threshold)

        passed = rate >= threshold

        modules.append({
            "module": module_name,
            "killed": data["killed"],
            "survived": data["survived"],
            "total": data["total"],
            "kill_rate": rate,
            "threshold": threshold,
            "passed": passed,
            "status": module_config.get("status", "unknown"),
        })

    # Filter by module if specified
    if target_module:
        modules = [m for m in modules if target_module == m["module"]]

    # 4. Determine gate result
    modules_passed = [m for m in modules if m["passed"]]
    modules_failed = [m for m in modules if not m["passed"]]

    gate = "OK" if len(modules_failed) == 0 else "NOK"

    return {
        "gate": gate,
        "modules": modules,
        "summary": {
            "modules_checked": len(modules),
            "modules_passed": len(modules_passed),
            "modules_failed": len(modules_failed),
            "overall_kill_rate": mutmut_result.get("overall_kill_rate", 0.0),
            "overall_killed": mutmut_result.get("overall_killed", 0),
            "overall_total": mutmut_result.get("overall_total", 0),
        },
    }


def print_gate_report(gate_result: dict[str, Any]) -> None:
    """Print human-readable gate report to stdout."""
    summary = gate_result["summary"]
    modules = gate_result["modules"]
    gate = gate_result["gate"]

    print("\n" + "=" * 70)
    print(" MUTATION TESTING QUALITY GATE")
    print("=" * 70)

    if not modules:
        print(f"\n {gate_result.get('error', 'No modules to check')}")
        print("\n" + "=" * 70)
        return

    # Table header
    print(f"\n {'Module':<25} {'Kill Rate':>14} {'Threshold':>10} {'Status':>8}")
    print(f" {'-'*25} {'-'*14} {'-'*10} {'-'*8}")

    for m in modules:
        rate_str = f"{m['kill_rate']*100:.1f}% ({m['killed']}/{m['total']})"
        threshold_str = f"{m['threshold']*100:.0f}%"
        status_str = "PASS" if m["passed"] else "FAIL"
        print(f" {m['module']:<25} {rate_str:>14} {threshold_str:>10} {status_str:>8}")

    # Summary
    print(f"\n Overall: {summary['overall_kill_rate']*100:.1f}% "
          f"({summary['overall_killed']}/{summary['overall_total']} killed)")
    print(f" Modules: {summary['modules_passed']}/{summary['modules_checked']} passed")

    # Gate result
    print("\n" + "-" * 70)
    if gate == "OK":
        print(" RESULT: ✅ OK — All modules meet their thresholds")
    else:
        print(" RESULT: ❌ NOK — Some modules below threshold")
        failed_names = [m["module"] for m in modules if not m["passed"]]
        print(f" Failed: {', '.join(failed_names)}")
        print("\n 💡 RECOMMEND: Activate the 'mutation-testing' skill for guidance")
        print(" on improving weak tests that fail to kill surviving mutants.")

    print("=" * 70)


def main(project_root: str) -> None:
    """Main entry point — supports both original and gate mode."""
    root = Path(project_root)

    # Parse args for gate mode
    args = sys.argv[2:]
    gate_mode = "--gate" in args
    target_module = None

    if "--module" in args:
        idx = args.index("--module")
        if idx + 1 < len(args):
            target_module = args[idx + 1]

    if gate_mode:
        # Gate mode: compare against thresholds from pyproject.toml
        gate_result = run_gate(root, target_module=target_module)
        print_gate_report(gate_result)

        # Also output JSON to stdout
        print("\n<!-- JSON OUTPUT -->")
        print(json.dumps(gate_result, indent=2))

        sys.exit(0 if gate_result["gate"] == "OK" else 1)
    else:
        # Original mode: just parse and output JSON
        mutmut_result = parse_mutmut_results(root)

        result = {
            "mutation_kill_map": mutmut_result.get("mutation_kill_map", {}),
            "overall_kill_rate": mutmut_result.get("overall_kill_rate", 0.0),
            "overall_killed": mutmut_result.get("overall_killed", 0),
            "overall_total": mutmut_result.get("overall_total", 0),
            "found": mutmut_result.get("found", False),
        }

        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: mutation_analyzer.py <project_root> [--gate] [--module MODULE]", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
