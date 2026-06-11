"""Helper: extract survived mutants by method, in a clean format for subagents.

Usage:
    .venv/bin/python scripts/extract_survivors.py <module_path> [--with-code]

Example:
    .venv/bin/python scripts/extract_survivors.py harness_quality_gate/adapters/php/php_adapter.py
    .venv/bin/python scripts/extract_survivors.py harness_quality_gate/adapters/php/php_adapter.py --with-code

The --with-code flag reads the meta keys and uses the dict format to show
context. By default, only shows mutant IDs grouped by method.

Mutant key format:
    harness_quality_gate.adapters.php.php_adapter.xǁPhpAdapterǁrun_l1__mutmut_114
       ^module path                             ^class sep  ^method ^mutant_id
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from collections import defaultdict


def main(meta_rel_path: str, with_code: bool = False) -> None:
    meta_path = Path("mutants") / meta_rel_path
    if meta_path.suffix == ".py":
        meta_path = meta_path.with_suffix(".py.meta")
    elif not meta_path.suffix:
        meta_path = meta_path.with_suffix(".meta")
    if not meta_path.exists():
        print(f"ERROR: meta not found: {meta_path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(meta_path.read_text())
    exit_codes = data.get("exit_code_by_key", {})

    by_method: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for k, v in exit_codes.items():
        if v == 0:  # survived
            # Class methods: ...xǁClassǁmethod__mutmut_N
            m = re.search(r"ǁ\w+ǁ(\w+)__mutmut_(\d+)", k)
            if m is None:
                # Module-level functions: ...x_name__mutmut_N
                m = re.search(r"\.x_(\w+?)__mutmut_(\d+)$", k)
            if m:
                method, num = m.group(1), int(m.group(2))
                by_method[method].append((num, k))

    if not by_method:
        print("No survivors.")
        return

    src_path = Path("harness_quality_gate") / Path(meta_rel_path).relative_to("harness_quality_gate") if False else None

    # Compute source path (meta_rel_path already starts without mutants/)
    src_path = Path(meta_rel_path)

    print(f"## {meta_rel_path}: {sum(len(v) for v in by_method.values())} survivors\n")

    for method, mutants in sorted(by_method.items(), key=lambda x: -len(x[1])):
        mutants.sort()
        print(f"### {method} ({len(mutants)} survivors)")
        for num, full_key in mutants[:20]:
            print(f"  - mutmut_{num}")
        if len(mutants) > 20:
            print(f"  ... +{len(mutants) - 20} more")
        print()

    if with_code:
        print("\n## Mutant details (sample of 5 per method):")
        for method, mutants in sorted(by_method.items(), key=lambda x: -len(x[1])):
            mutants.sort()
            print(f"\n### {method}:")
            for num, full_key in mutants[:5]:
                print(f"  - {full_key}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("meta_rel_path", help="e.g. harness_quality_gate/adapters/php/php_adapter.py")
    parser.add_argument("--with-code", action="store_true")
    args = parser.parse_args()
    main(args.meta_rel_path, args.with_code)
