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
    end = (
        test_node.end_lineno
        if hasattr(test_node, "end_lineno") and test_node.end_lineno
        else start + 20
    )
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


def _file_glob_for_language(language: str) -> list[str]:
    """Return file-glob patterns for the given language."""
    if language == "php":
        return ["*Test.php", "test_*.php", "*_test.php"]
    return ["test_*.py"]


# Tool/artifact dirs never holding the project's own tests (self-eval F12):
# sweeping .venv/ and mutants/ pulled in thousands of third-party files.
_ARTIFACT_DIRS = {"venv", "mutants", "node_modules", "vendor", "__pycache__"}

# Pairwise Levenshtein is O(n²); above this many tests the matrix runs on
# a deterministic stride sample (self-eval F12: 2700 tests hung for 30+ min).
_MAX_PAIRWISE_TESTS = 300


def _is_artifact_path(test_file: Path, repo: Path) -> bool:
    """True when *test_file* sits under a hidden or artifact directory."""
    return any(
        part in _ARTIFACT_DIRS or part.startswith(".")
        for part in test_file.relative_to(repo).parts[:-1]
    )


def _extract_tests_python(filepath: Path) -> list[dict[str, Any]]:
    """Extract test functions from a Python file."""
    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content, str(filepath))
    except (SyntaxError, UnicodeDecodeError):
        return []

    tests = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            body_text = get_test_body_text(node, content)
            normalized = " ".join(body_text.split())
            tests.append(
                {
                    "name": node.name,
                    "lineno": node.lineno,
                    "body_text": normalized,
                    "body_length": len(normalized),
                }
            )
    return tests


def _extract_tests_php(filepath: Path) -> list[dict[str, Any]]:
    """Extract test methods from a PHP file using simple text analysis.

    PHP lacks a standard library AST parser in pure Python, so we use
    regex-based extraction of test method signatures and bodies.
    """
    try:
        content = filepath.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []

    tests = []
    lines = content.split("\n")
    import re

    pattern = re.compile(
        r"^\s*public\s+(?:function|async\s+function)\s+(test\w*)\s*\(", re.IGNORECASE
    )
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if m:
            test_name = m.group(1)
            start = i
            end = min(i + 30, len(lines))
            body_text = " ".join(lines[start:end])
            normalized = " ".join(body_text.split())
            tests.append(
                {
                    "name": test_name,
                    "lineno": i + 1,
                    "body_text": normalized,
                    "body_length": len(normalized),
                }
            )
    return tests


def _compute_diversity(all_tests: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute diversity metrics from a list of test dicts."""
    min_distance = float("inf")
    max_distance = 0
    similar_pairs: list[dict[str, Any]] = []

    # Group tests by file for efficiency
    tests_by_file: dict[str, list[dict[str, Any]]] = {}
    for t in all_tests:
        tests_by_file.setdefault(t["file"], []).append(t)

    for file_tests in tests_by_file.values():
        for i, t1 in enumerate(file_tests):
            for t2 in file_tests[i + 1 :]:
                if t1["body_length"] < 20 or t2["body_length"] < 20:
                    continue

                dist = levenshtein_distance(t1["body_text"], t2["body_text"])
                max_len = max(t1["body_length"], t2["body_length"])
                if max_len == 0:
                    continue

                similarity = 1.0 - (dist / max_len)

                min_distance = min(min_distance, dist)
                max_distance = max(max_distance, dist)

                if similarity > 0.8:
                    similar_pairs.append(
                        {
                            "file": t1["file"],
                            "test1": t1["name"],
                            "test2": t2["name"],
                            "edit_distance": dist,
                            "similarity": round(similarity, 3),
                        }
                    )

    if min_distance == float("inf"):
        min_distance = 0
        max_distance = 0
        diversity_score = 1.0
    else:
        diversity_score = round(
            max(0.0, 1.0 - len(similar_pairs) / max(len(all_tests), 1)), 3
        )

    return {
        "total_tests": len(all_tests),
        "diversity_score": diversity_score,
        "min_edit_distance": min_distance,
        "max_edit_distance": max_distance,
        "similar_pairs": sorted(
            similar_pairs, key=lambda x: x["similarity"], reverse=True
        )[:10],
        "summary": {
            "high_diversity": diversity_score >= 0.7,
            "low_diversity": diversity_score < 0.3,
            "similar_pair_count": len(similar_pairs),
        },
    }


def main(tests_dir: str) -> None:
    tests_path = Path(tests_dir)

    all_tests: list[dict[str, Any]] = []
    for test_file in tests_path.rglob("test_*.py"):
        if "__pycache__" in str(test_file):
            continue
        tests = _extract_tests_python(test_file)
        for t in tests:
            t["file"] = str(test_file.relative_to(tests_path))
            all_tests.append(t)

    result = _compute_diversity(all_tests)
    print(json.dumps(result, indent=2))


def diversity(repo: Path, language: str, **kw: dict[str, Any]) -> dict[str, Any]:
    """Analyze test diversity for a repository, parameterized by language.

    Scans the ``repo`` directory for test files matching language conventions,
    extracts test bodies, and computes pairwise Levenshtein distances to
    detect copy-paste duplication.

    Args:
        repo: Path to the repository root.
        language: Programming language — ``"python"`` or ``"php"``.
        **kw: Extra keyword arguments (reserved for future use).

    Returns:
        Dict with total_tests, diversity_score, edit distances,
        similar_pairs, and summary.
    """
    patterns = _file_glob_for_language(language)

    all_tests: list[dict[str, Any]] = []
    for pattern in patterns:
        for test_file in sorted(repo.rglob(pattern)):
            if _is_artifact_path(test_file, repo):
                continue
            if language == "php":
                tests = _extract_tests_php(test_file)
            else:
                tests = _extract_tests_python(test_file)
            for t in tests:
                t["file"] = str(test_file.relative_to(repo))
                all_tests.append(t)

    total = len(all_tests)
    sampled = all_tests
    if total > _MAX_PAIRWISE_TESTS:
        # deterministic stride sample spread across the whole suite
        stride = total / _MAX_PAIRWISE_TESTS
        sampled = [all_tests[int(i * stride)] for i in range(_MAX_PAIRWISE_TESTS)]

    result = _compute_diversity(sampled)
    result["total_tests"] = total
    result["sample_size"] = len(sampled)
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: diversity_metric.py <tests_dir>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
