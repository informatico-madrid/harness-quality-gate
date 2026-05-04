#!/usr/bin/env python3
"""
Diversity Metric — Calculate test diversity using Levenshtein edit distance.

Detects test cases that are essentially copy-paste with minimal changes,
which indicates low-value test duplication.

Usage:
    python3 diversity_metric.py <tests_dir>

Output:
    JSON with diversity_score, min/max edit distance, and similar pairs.
"""

import ast
import json
import sys
from pathlib import Path
from typing import Any


def get_test_body_text(test_node: ast.FunctionDef, source: str) -> str:
    """Extract the body of a test function as normalized text."""
    lines = source.split("\n")
    start = test_node.lineno - 1
    end = test_node.end_lineno if hasattr(test_node, "end_lineno") and test_node.end_lineno else start + 20
    return " ".join(lines[start:end])


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate the Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def analyze_test_file(filepath: Path) -> list[dict[str, Any]]:
    """Extract test functions from a file with their body text."""
    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content, str(filepath))
    except (SyntaxError, UnicodeDecodeError):
        return []

    tests = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            body_text = get_test_body_text(node, content)
            normalized = " ".join(body_text.split())  # Normalize whitespace
            tests.append({
                "name": node.name,
                "lineno": node.lineno,
                "body_text": normalized,
                "body_length": len(normalized),
            })

    return tests


def main(tests_dir: str) -> None:
    tests_path = Path(tests_dir)

    all_tests: list[dict[str, Any]] = []
    for test_file in tests_path.rglob("test_*.py"):
        if "__pycache__" in str(test_file):
            continue
        tests = analyze_test_file(test_file)
        for t in tests:
            t["file"] = str(test_file.relative_to(tests_path))
            all_tests.append(t)

    # Calculate pairwise Levenshtein distances within same file
    min_distance = float("inf")
    max_distance = 0
    similar_pairs: list[dict[str, Any]] = []

    # Group tests by file for efficiency
    tests_by_file: dict[str, list[dict[str, Any]]] = {}
    for t in all_tests:
        tests_by_file.setdefault(t["file"], []).append(t)

    for file_tests in tests_by_file.values():
        for i, t1 in enumerate(file_tests):
            for t2 in file_tests[i + 1:]:
                # Skip very short tests (not meaningful to compare)
                if t1["body_length"] < 20 or t2["body_length"] < 20:
                    continue

                dist = levenshtein_distance(t1["body_text"], t2["body_text"])
                max_len = max(t1["body_length"], t2["body_length"])
                if max_len == 0:
                    continue

                # Normalize distance to 0-1 range (0 = identical, 1 = completely different)
                similarity = 1.0 - (dist / max_len)

                min_distance = min(min_distance, dist)
                max_distance = max(max_distance, dist)

                # Flag tests that are >80% similar (edit distance < 20% of length)
                if similarity > 0.8:
                    similar_pairs.append({
                        "file": t1["file"],
                        "test1": t1["name"],
                        "test2": t2["name"],
                        "edit_distance": dist,
                        "similarity": round(similarity, 3),
                    })

    if min_distance == float("inf"):
        min_distance = 0
        max_distance = 0
        diversity_score = 1.0
    else:
        # Diversity score: 1.0 = all tests are unique, 0.0 = all tests are identical
        diversity_score = round(max(0.0, 1.0 - len(similar_pairs) / max(len(all_tests), 1)), 3)

    result = {
        "total_tests": len(all_tests),
        "diversity_score": diversity_score,
        "min_edit_distance": min_distance,
        "max_edit_distance": max_distance,
        "similar_pairs": sorted(similar_pairs, key=lambda x: x["similarity"], reverse=True)[:10],
        "summary": {
            "high_diversity": diversity_score >= 0.7,
            "low_diversity": diversity_score < 0.3,
            "similar_pair_count": len(similar_pairs),
        },
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: diversity_metric.py <tests_dir>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
