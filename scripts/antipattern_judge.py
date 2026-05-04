#!/usr/bin/env python3
"""
Antipattern Judge Context Generator — Prepares structured context for BMAD agent review.

This script does NOT call external APIs. Instead, it:
1. Extracts code context from Python source files
2. Generates a structured antipattern review prompt for Tier B patterns
3. Outputs context text for the quality-gate agent to pass to BMAD subagents

Tier B patterns (AP14-AP16, AP19, AP27-AP29, AP32-AP38, AP40-AP50) need semantic
understanding that cannot be achieved with AST alone. BMAD Party Mode agents
(Winston + Murat) evaluate these patterns using the context generated here.

Usage:
    python3 antipattern_judge.py <src_dir> <tests_dir>

Output:
    JSON with structured context for BMAD agents and pattern definitions.
"""

import ast
import json
import sys
from pathlib import Path
from typing import Any


# Tier B pattern definitions (must match antipattern_checker.py)
TIER_B_PATTERNS: dict[str, dict[str, str]] = {
    "AP14": {
        "name": "Divergent Change",
        "description": "A class that is changed in many different ways for different reasons.",
        "red_flags": "Class has methods that belong to different functional domains; "
                     "changes to one feature require modifying unrelated methods in the same class.",
    },
    "AP15": {
        "name": "Shotgun Surgery",
        "description": "One conceptual change requires modifying many different files.",
        "red_flags": "A single feature or bug fix touches >3 files; related logic scattered "
                     "across modules instead of co-located.",
    },
    "AP16": {
        "name": "Parallel Inheritance",
        "description": "Creating a subclass in one hierarchy forces creating one in another.",
        "red_flags": "Class hierarchies that mirror each other (e.g., User/Admin + UserDAO/AdminDAO); "
                     "adding a type in one tree requires adding in another.",
    },
    "AP19": {
        "name": "Temporary Field",
        "description": "Instance variables that are only set in certain circumstances.",
        "red_flags": "Attributes that are None most of the time; fields only used by one method; "
                     "instance variables set conditionally and left as None otherwise.",
    },
    "AP27": {
        "name": "Incomplete Library Class",
        "description": "Extending a third-party class with utility methods instead of wrapping it.",
        "red_flags": "Class inherits from a stdlib or third-party class and adds helper methods; "
                     "monkey-patching external classes.",
    },
    "AP28": {
        "name": "Comments as Deodorant",
        "description": "Comments that exist to explain bad code instead of fixing it.",
        "red_flags": "Long comment blocks before complex conditionals; TODO/FIXME/HACK comments; "
                     "comments that restate what the code does instead of why.",
    },
    "AP29": {
        "name": "Inappropriate Intimacy",
        "description": "One class accesses another class's internals excessively.",
        "red_flags": "Class A accesses private attributes of class B (via _attr); "
                     "excessive use of getattr/setattr; classes that know too much about each other.",
    },
    "AP32": {
        "name": "Stovepipe System",
        "description": "Hardcoded connections between components that should be configurable.",
        "red_flags": "Hardcoded URLs, file paths, or connection strings; direct instantiation "
                     "of dependencies instead of injection; no configuration layer.",
    },
    "AP33": {
        "name": "Vendor Lock-In",
        "description": "Code that is tightly coupled to a specific vendor's API.",
        "red_flags": "Vendor-specific types in business logic; no abstraction layer over external APIs; "
                     "direct use of cloud provider SDKs in domain code.",
    },
    "AP34": {
        "name": "Lava Flow",
        "description": "Dead code from experiments that nobody removes.",
        "red_flags": "Commented-out code blocks; unused functions with 'experimental' comments; "
                     "deprecated code paths that are never called but still exist.",
    },
    "AP35": {
        "name": "Ambiguous Viewpoint",
        "description": "Mixed abstraction levels in the same module or class.",
        "red_flags": "High-level business logic mixed with low-level I/O; utility functions "
                     "in the same file as domain classes; no clear layer separation.",
    },
    "AP36": {
        "name": "Golden Hammer",
        "description": "Using the same familiar solution for every problem.",
        "red_flags": "Using regex for parsing structured data; using lists where dicts/sets are better; "
                     "using inheritance everywhere instead of composition.",
    },
    "AP37": {
        "name": "Reinvent the Wheel",
        "description": "Reimplementing functionality that exists in the stdlib or well-known libraries.",
        "red_flags": "Custom HTTP client instead of requests/httpx; custom JSON parser; "
                     "custom logging instead of Python logging; custom cache instead of functools.lru_cache.",
    },
    "AP38": {
        "name": "Boat Anchor",
        "description": "Keeping unused code 'just in case'.",
        "red_flags": "Functions/classes that are defined but never imported or called; "
                     "entire modules with no external references; dead configuration options.",
    },
    "AP40": {
        "name": "Base Bean",
        "description": "Inheriting from a utility class just to reuse a few methods.",
        "red_flags": "Inheriting from a class with only static/utility methods; "
                     "using inheritance for code reuse instead of composition or delegation.",
    },
    "AP41": {
        "name": "Hard-Coded Test Data",
        "description": "Test data embedded directly in test functions instead of fixtures.",
        "red_flags": "Large string literals or dicts inside test functions; repeated data "
                     "across tests that should be in conftest.py fixtures or factories.",
    },
    "AP42": {
        "name": "Sensitive Equality",
        "description": "Tests that compare full object representations or string representations.",
        "red_flags": "assert str(result) == '...'; assert result.__dict__ == expected.__dict__; "
                     "tests that break when non-functional attributes change.",
    },
    "AP43": {
        "name": "Test Code Duplication",
        "description": "Duplicated setup/teardown logic across test functions.",
        "red_flags": "Same mock setup repeated in multiple tests; copy-pasted arrange sections; "
                     "no use of pytest fixtures or parametrize for common setups.",
    },
    "AP44": {
        "name": "Test Per Method",
        "description": "Only one test per production method, missing edge cases.",
        "red_flags": "One test method per production method with no variation; "
                     "no tests for error paths, boundary conditions, or invalid inputs.",
    },
    "AP45": {
        "name": "Mock Object Abuse",
        "description": "Over-mocking that makes tests brittle and disconnected from reality.",
        "red_flags": ">80% of test code is mock setup; mocking the system under test; "
                     "tests that only verify mock interactions, not behavior.",
    },
    "AP46": {
        "name": "Assertion Roulette",
        "description": "Multiple assertions without messages, hard to identify which failed.",
        "red_flags": "assert x == y without message strings; many assertions in one test; "
                     "no explanation of what each assertion validates.",
    },
    "AP47": {
        "name": "Eager Test",
        "description": "One test function that verifies multiple unrelated behaviors.",
        "red_flags": "Test function >50 lines; testing multiple methods in one test; "
                     "multiple arrange-act-assert cycles in one test.",
    },
    "AP48": {
        "name": "Dependency Hell",
        "description": "Conflicting or redundant dependencies in the project.",
        "red_flags": "Multiple packages providing same functionality; pinned versions with "
                     "known conflicts; duplicate dependencies with different version constraints.",
    },
    "AP49": {
        "name": "Magic Pushbutton",
        "description": "Auto-generated code or configuration that nobody understands.",
        "red_flags": "Generated code checked into version control; complex config files "
                     "with no documentation; boilerplate that nobody dares to modify.",
    },
    "AP50": {
        "name": "Continuous Obsolescence",
        "description": "Using outdated dependencies or deprecated APIs.",
        "red_flags": "Deprecated stdlib modules (e.g., 'imp' instead of 'importlib'); "
                     "old API patterns; dependencies with known security vulnerabilities.",
    },
}


def extract_source_context(src_dir: Path, max_files: int = 20, max_lines_per_file: int = 80) -> list[dict[str, Any]]:
    """Extract source file summaries for BMAD agent review."""
    files_context = []
    count = 0
    for py_file in sorted(src_dir.rglob("*.py")):
        if "__pycache__" in str(py_file):
            continue
        if count >= max_files:
            break
        try:
            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content, str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue

        classes = []
        functions = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = [
                    n.name for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                bases = []
                for b in node.bases:
                    if isinstance(b, ast.Name):
                        bases.append(b.id)
                    elif isinstance(b, ast.Attribute):
                        bases.append(b.attr)
                classes.append({
                    "name": node.name,
                    "bases": bases,
                    "methods": methods,
                    "lineno": node.lineno,
                })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    functions.append({
                        "name": node.name,
                        "lineno": node.lineno,
                        "arity": len([a for a in node.args.args if a.arg not in ("self", "cls")]),
                    })

        # Get source preview (first N lines)
        lines = content.split("\n")[:max_lines_per_file]

        files_context.append({
            "file": str(py_file.relative_to(src_dir)),
            "classes": classes,
            "public_functions": functions,
            "source_preview": "\n".join(lines),
        })
        count += 1

    return files_context


def extract_test_context(tests_dir: Path, max_files: int = 15) -> list[dict[str, Any]]:
    """Extract test file summaries for testing antipattern review."""
    files_context = []
    count = 0
    for py_file in sorted(tests_dir.rglob("test_*.py")):
        if "__pycache__" in str(py_file):
            continue
        if count >= max_files:
            break
        try:
            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content, str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue

        test_functions = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                test_functions.append({
                    "name": node.name,
                    "lineno": node.lineno,
                    "loc": (node.end_lineno or node.lineno) - node.lineno + 1,
                })

        lines = content.split("\n")[:60]
        files_context.append({
            "file": str(py_file.relative_to(tests_dir)),
            "test_functions": test_functions,
            "source_preview": "\n".join(lines),
        })
        count += 1

    return files_context


def generate_review_context(
    src_context: list[dict[str, Any]],
    test_context: list[dict[str, Any]],
) -> str:
    """Generate structured context for BMAD agents to review Tier B antipatterns."""
    lines = []
    lines.append("=" * 70)
    lines.append("ANTIPATTERN REVIEW - TIER B (SEMANTIC PATTERNS)")
    lines.append("=" * 70)
    lines.append("")

    # Source files summary
    lines.append("-" * 50)
    lines.append("SOURCE FILES (" + str(len(src_context)) + " files)")
    lines.append("-" * 50)
    for f in src_context:
        lines.append("")
        lines.append("File: " + f["file"])
        if f["classes"]:
            for cls in f["classes"]:
                bases_str = "(" + ", ".join(cls["bases"]) + ")" if cls["bases"] else ""
                lines.append("  Class: " + cls["name"] + bases_str + " [line " + str(cls["lineno"]) + "]")
                lines.append("    Methods: " + ", ".join(cls["methods"][:15]))
        if f["public_functions"]:
            for func in f["public_functions"]:
                lines.append("  Function: " + func["name"] + "(arity=" + str(func["arity"]) + ") [line " + str(func["lineno"]) + "]")

    # Test files summary
    if test_context:
        lines.append("")
        lines.append("-" * 50)
        lines.append("TEST FILES (" + str(len(test_context)) + " files)")
        lines.append("-" * 50)
        for f in test_context:
            lines.append("")
            lines.append("File: " + f["file"])
            for tf in f["test_functions"]:
                lines.append("  Test: " + tf["name"] + " (loc=" + str(tf["loc"]) + ") [line " + str(tf["lineno"]) + "]")

    # Pattern definitions
    lines.append("")
    lines.append("=" * 70)
    lines.append("PATTERNS TO EVALUATE")
    lines.append("=" * 70)
    for ap_id, pattern in sorted(TIER_B_PATTERNS.items()):
        lines.append("")
        lines.append(ap_id + ": " + pattern["name"])
        lines.append("  Description: " + pattern["description"])
        lines.append("  Red flags: " + pattern["red_flags"])

    lines.append("")
    lines.append("=" * 70)
    lines.append("EVALUATION INSTRUCTIONS")
    lines.append("=" * 70)
    lines.append("")
    lines.append("For each pattern, evaluate whether the codebase exhibits it.")
    lines.append("Respond with a JSON list of confirmed violations:")
    lines.append('{')
    lines.append('  "violations": [')
    lines.append('    {"id": "AP14", "name": "Divergent Change", "file": "src/foo.py", ')
    lines.append('     "class": "Foo", "reason": "...", "severity": "HIGH|MEDIUM|LOW"}')
    lines.append('  ],')
    lines.append('  "PASS": true or false')
    lines.append('}')
    lines.append("")
    lines.append("If no violations found: {\"violations\": [], \"PASS\": true}")
    lines.append("")

    return "\n".join(lines)


def main(src_dir: str, tests_dir: str) -> None:
    src_path = Path(src_dir)
    tests_path = Path(tests_dir)

    if not src_path.exists():
        print("Error: " + src_dir + " does not exist", file=sys.stderr)
        sys.exit(1)

    # Extract context
    src_context = extract_source_context(src_path)
    test_context = []
    if tests_path.exists():
        test_context = extract_test_context(tests_path)

    # Generate review context (human-readable, for BMAD agents)
    review_text = generate_review_context(src_context, test_context)

    # Output JSON summary to stdout (machine-readable)
    result = {
        "tier_b_patterns_total": len(TIER_B_PATTERNS),
        "source_files_analyzed": len(src_context),
        "test_files_analyzed": len(test_context),
        "patterns": {k: {"name": v["name"], "description": v["description"]} for k, v in TIER_B_PATTERNS.items()},
        "review_context_length": len(review_text),
        "review_context": review_text,
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: antipattern_judge.py <src_dir> <tests_dir>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
