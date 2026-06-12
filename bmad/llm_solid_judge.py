#!/usr/bin/env python3
"""
SOLID Judge Context Generator - Prepares structured context for BMAD agent review.

This script does NOT call external APIs. Instead, it:
1. Extracts class definitions from Python source files
2. Generates a structured SOLID review prompt
3. Outputs context text for the quality-gate agent to pass to BMAD subagents

The actual SOLID evaluation is done by:
- BMAD Party Mode (Winston architect + Murat test architect)
- BMAD Adversarial General (cynical review for consensus)

Usage:
    python3 llm_solid_judge.py <src_dir>

Output:
    JSON with structured context for BMAD agents. The review context text
    is embedded in the JSON as the "review_context" field.
"""

import ast
import json
import sys
from pathlib import Path
from typing import Any


def extract_classes_from_dir(src_dir: Path) -> list[dict[str, Any]]:
    """Extract class definitions from Python source files."""
    classes = []
    for py_file in src_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content)
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_lines = content.split('\n')[node.lineno - 1:node.end_lineno]
                class_source = '\n'.join(class_lines)

                bases = []
                for b in node.bases:
                    if isinstance(b, ast.Name):
                        bases.append(b.id)
                    elif isinstance(b, ast.Attribute):
                        bases.append(b.attr)

                methods = []
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        is_public = not item.name.startswith('_')
                        arity = len(item.args.args)
                        has_return = item.returns is not None
                        methods.append({
                            "name": item.name,
                            "is_public": is_public,
                            "arity": arity,
                            "has_return_type": has_return,
                        })

                classes.append({
                    "name": node.name,
                    "file": str(py_file),
                    "bases": bases,
                    "lineno": node.lineno,
                    "methods": methods,
                    "public_method_count": sum(1 for m in methods if m["is_public"]),
                    "source": class_source[:2000],
                })

    return classes


def generate_solid_review_context(classes: list[dict[str, Any]]) -> str:
    """Generate structured context for SOLID review by BMAD agents."""

    lines = []
    lines.append("=" * 70)
    lines.append("SOLID PRINCIPLE REVIEW - CLASS INVENTORY")
    lines.append("=" * 70)
    lines.append("")
    lines.append("Total classes found: " + str(len(classes)))
    lines.append("")

    for i, cls in enumerate(classes[:30]):
        lines.append("-" * 50)
        lines.append("Class #" + str(i + 1) + ": " + cls["name"])
        lines.append("File: " + cls["file"] + ":" + str(cls["lineno"]))
        lines.append("Base classes: " + (", ".join(cls["bases"]) if cls["bases"] else "None"))
        lines.append("Public methods: " + str(cls["public_method_count"]))
        lines.append("")

        for m in cls["methods"]:
            visibility = "PUBLIC" if m["is_public"] else "private"
            ret = "+return" if m["has_return_type"] else "NO-return"
            lines.append("  [" + visibility + "] " + m["name"] + "(arity=" + str(m["arity"]) + ", " + ret + ")")

        lines.append("")
        lines.append("Source preview:")
        lines.append(cls["source"][:800])
        lines.append("")

    if len(classes) > 30:
        lines.append("... and " + str(len(classes) - 30) + " more classes omitted for brevity")

    lines.append("")
    lines.append("=" * 70)
    lines.append("SOLID EVALUATION CRITERIA")
    lines.append("=" * 70)
    lines.append("")
    lines.append("S - Single Responsibility: Does each class have ONE reason to change?")
    lines.append("    Red flags: >7 public methods, handles multiple concerns")
    lines.append("")
    lines.append("O - Open/Closed: Can behavior be extended without modifying source?")
    lines.append("    Red flags: no ABC/Protocol, no inheritance hierarchy")
    lines.append("")
    lines.append("L - Liskov Substitution: Can subclasses replace parents transparently?")
    lines.append("    Red flags: narrowed return types, strengthened preconditions")
    lines.append("")
    lines.append("I - Interface Segregation: Are interfaces small and focused?")
    lines.append("    Red flags: fat interfaces, unused methods")
    lines.append("")
    lines.append("D - Dependency Inversion: Do high-level modules depend on abstractions?")
    lines.append("    Red flags: concrete imports, no dependency injection")
    lines.append("")
    lines.append("=" * 70)

    return "\n".join(lines)


def main(src_dir: str) -> None:
    """CLI entry point."""
    src_path = Path(src_dir)
    if not src_path.exists():
        print("Error: " + src_dir + " does not exist", file=sys.stderr)
        sys.exit(1)

    classes = extract_classes_from_dir(src_path)

    if not classes:
        result = {
            "classes_found": 0,
            "review_needed": False,
            "message": "No classes found - SOLID review not applicable",
            "review_context": "",
        }
        print(json.dumps(result, indent=2))
        return

    # Generate review context
    context = generate_solid_review_context(classes)

    # Output everything as a single JSON (no mixed text+JSON on stdout)
    result = {
        "classes_found": len(classes),
        "review_needed": True,
        "review_context": context,
        "classes_with_many_methods": [
            {"name": c["name"], "file": c["file"], "public_methods": c["public_method_count"]}
            for c in classes if c["public_method_count"] > 7
        ],
        "classes_without_bases": [
            {"name": c["name"], "file": c["file"]}
            for c in classes if not c["bases"]
        ],
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: llm_solid_judge.py <src_dir>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
