#!/usr/bin/env python3
"""Parse mutmut run log and generate results.json + summary.

Usage:
    parse_mutmut_results.py <log_file> [module_pattern]

When module_pattern is given, counts only mutants matching the pattern
(useful for partial runs that filter to a specific file).
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

EMOJIS = {
    "killed": "\U0001f389",  # 🎉
    "survived": "\U0001f641",  # 🙁
    "timeout": "\u23f0",   # ⏰ ALARM CLOCK (NOT \U0001f570 = 🕰 mantelpiece)
    "suppressed": "\U0001f507",  # 🔇
    "left_alone": "\U0001f9d9",  # 🧙
    "not_tested": "\U0001fac6",  # 🫥
}


def parse_full_run(text: str) -> dict | None:
    """Parse full mutation run with summary line: '⠇ N/N  🎉 X ...'"""
    for line in reversed(text.strip().split("\n")):
        if re.search(r"\d+/\d+\s*[🎉🙁⏰🔇🧙🫥]", line):
            total_m = re.search(r"(\d+)/(\d+)", line)
            counts = {name: 0 for name in EMOJIS}
            for name, emoji in EMOJIS.items():
                m = re.search(re.escape(emoji) + r"\s*(\d+)", line)
                if m:
                    counts[name] = int(m.group(1))
            if total_m:
                return {"total": int(total_m.group(2)), **counts}
    return None


def parse_partial_run(text: str, pattern: str) -> dict:
    """Parse partial run by counting emoji-prefixed lines matching the module pattern."""
    counts = {name: 0 for name in EMOJIS}
    total = 0
    # Pattern matches lines like "🎉 module.path.x_func__mutmut_N"
    # Convert "harness_quality_gate.adapters.php" to "harness_quality_gate.adapters.php"
    pat = re.escape(pattern.rstrip("*"))
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        for name, emoji in EMOJIS.items():
            # Line starts with emoji and contains the module pattern
            if line.startswith(emoji) and re.search(pat, line):
                counts[name] += 1
                total += 1
                break
    return {"total": total, **counts}


def calculate_msi(counts: dict) -> float:
    denominator = counts["killed"] + counts["survived"] + counts["timeout"]
    if denominator == 0:
        return 0.0
    return (counts["killed"] / denominator) * 100


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <log_file> [module_pattern]")
        sys.exit(1)

    log_path = Path(sys.argv[1])
    module_pattern = sys.argv[2] if len(sys.argv) > 2 else None

    if not log_path.exists():
        print(f"Error: {log_path} not found")
        sys.exit(1)

    text = log_path.read_text(encoding="utf-8", errors="replace")

    if module_pattern:
        counts = parse_partial_run(text, module_pattern)
    else:
        result = parse_full_run(text)
        counts = result if result else {name: 0 for name in EMOJIS}
        counts["total"] = counts.get("total", sum(
            counts[k] for k in ["killed", "survived", "timeout", "suppressed", "left_alone", "not_tested"]
        ))

    msi = calculate_msi(counts)
    checked = counts["killed"] + counts["survived"] + counts["timeout"]

    print(f"  Total:    {counts['total']}")
    for name in EMOJIS:
        val = counts[name]
        if val > 0:
            print(f"    {EMOJIS[name]:>5} {val}")
    if checked > 0:
        print()
        print(f"  MSI:       {msi:.2f}%  ({counts['killed']}/{checked})")
    else:
        print(f"  MSI:       N/A (no mutants processed)")
    print(f"  Survived:  {counts['survived']}  🙁")
    print(f"  Timeout:   {counts['timeout']}  ⏰")
    print(f"  Suppressed:{counts['suppressed']}  🔇")
    print(f"  Left along:{counts['left_alone']}  🧙")
    print(f"  Not tested:{counts['not_tested']}  🫥")

    results = {
        "timestamp": datetime.now().isoformat(),
        "log_file": str(log_path),
        "module_pattern": module_pattern,
        "total": counts["total"],
        "killed": counts["killed"],
        "survived": counts["survived"],
        "timeout": counts["timeout"],
        "suppressed": counts["suppressed"],
        "left_alone": counts["left_alone"],
        "not_tested": counts["not_tested"],
        "msi": round(msi, 2),
        "target_msi": 100.0,
        "status": "PASS" if msi == 100.0 else "FAIL",
    }

    output_json = log_path.parent / "results.json"
    output_json.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    output_txt = log_path.parent / "results.txt"
    lines = [
        "=" * 70,
        "MUTATION TESTING RESULTS",
        "=" * 70,
        f"Generated:  {results['timestamp']}",
        f"Log file:   {log_path}",
        f"Module:     {module_pattern or 'all'}",
        "",
        f"Total:      {counts['total']}",
        f"Killed:     {counts['killed']}  🎉",
        f"Survived:   {counts['survived']}  🙁",
        f"Timeout:    {counts['timeout']}  ⏰",
        f"Suppressed: {counts['suppressed']}  🔇",
        f"Left alone: {counts['left_alone']}  🧙",
        f"Not tested: {counts['not_tested']}  🫥",
        "",
        f"MSI:        {msi:.2f}%",
        f"Target:     100.00%",
        f"Status:     {results['status']}",
        "=" * 70,
    ]
    output_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
