"""
Weak Test Detector — Strategy-pattern compatible AST scanner for weak/flaky tests.

Detects tests that violate quality criteria (A1-A9):
  A1: <=1 assertion/test  (suspicious)
  A2: assertion count < 3  (insufficient coverage)
  A3: No parametrization, only 1 case  (hardcoded single-input)
  A4: mock count > 80% of test  (not testing real code)
  A5: No setup/teardown or fixtures  (stateless, no real state)
  A6: time.sleep > 0 in test  (flaky by design)
  A7: Empty exception  (pytest.raises(Exception): pass)
  A8: Always-true assertion  (assert True, assert 1==1)
  A9: mock where fixture is needed (anti-evasion)

Strategy-pattern design:
  - WeakTestEngine base class (bmad.weak_test_engine)
  - Concrete detector strategies (weak_test.DetectorA1 .. DetectorA9)
  - Each strategy has evaluate() returning violations for its rule
"""

import ast
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from harness_quality_gate.bmad.weak_test_engine import WeakTestEngine, DetectionResult


class WeakTestVisitor(ast.NodeVisitor):
    """Visit pytest test files and detect weak patterns."""

    def __init__(self) -> None:
        self.tests: list[dict[str, Any]] = []
        self.current_test: dict[str, Any] | None = None
        self._in_test_function = False
        self._assertion_count = 0
        self._mock_count = 0
        self._call_count = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        is_test = node.name.startswith("test_") or any(
            marker.attr == "test"
            for marker in node.decorator_list
            if isinstance(marker, ast.Attribute)
        )

        if is_test:
            self._in_test_function = True
            self.current_test = {
                "name": node.name,
                "lineno": node.lineno,
                "assertions": 0,
                "mocks": 0,
                "calls": 0,
                "has_setup": False,
                "has_teardown": False,
                "has_fixture_ref": False,
                "has_sleep": False,
                "has_empty_raises": False,
                "has_always_true": False,
                "parametrize_count": 0,
                "lines": 0,
            }
            self._assertion_count = 0
            self._mock_count = 0
            self._call_count = 0

            self._check_decorators(node)
            self.generic_visit(node)

            if self.current_test:
                self.current_test["assertions"] = self._assertion_count
                self.current_test["mocks"] = self._mock_count
                self.current_test["calls"] = self._call_count

            self._assertion_count = 0
            self._mock_count = 0
            self._call_count = 0
            self._in_test_function = False

            if self.current_test:
                violations = self._evaluate_weak_rules()
                if violations:
                    self.current_test["violations"] = violations
                    self.tests.append(self.current_test)

            self.current_test = None

        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)

    def _evaluate_weak_rules(self) -> list[dict[str, Any]]:
        """Evaluate all A1-A9 rules against current test."""
        if not self.current_test:
            return []

        t = self.current_test
        violations: list[dict[str, Any]] = []

        # A1: <=1 assertion = ERROR
        if t["assertions"] <= 1:
            violations.append({
                "rule": "A1",
                "description": f"only {t['assertions']} assertion(s) -- suspicious",
                "severity": "ERROR",
            })

        # A2: <3 assertions = WARNING
        if t["assertions"] < 3:
            violations.append({
                "rule": "A2",
                "description": f"only {t['assertions']} assertion(s) -- insufficient coverage",
                "severity": "WARNING",
            })

        # A3: no parametrization + single case = WARNING
        if t["parametrize_count"] == 0:
            violations.append({
                "rule": "A3",
                "description": "no parametrization detected -- hardcoded single-input test",
                "severity": "WARNING",
            })

        # A4: mock ratio > 80% = ERROR
        total_activity = t["assertions"] + t["mocks"] + t["calls"]
        if total_activity > 0:
            mock_ratio = t["mocks"] / total_activity
            if mock_ratio > 0.8:
                violations.append({
                    "rule": "A4",
                    "description": f"mock ratio {mock_ratio:.0%} > 80% -- not testing real code",
                    "severity": "ERROR",
                })

        # A5: no setup/teardown/fixtures = WARNING
        if not (t["has_setup"] or t["has_teardown"] or t["has_fixture_ref"]):
            violations.append({
                "rule": "A5",
                "description": "no setup/teardown/fixtures -- stateless test",
                "severity": "WARNING",
            })

        # A6: time.sleep = ERROR
        if t["has_sleep"]:
            violations.append({
                "rule": "A6",
                "description": "time.sleep detected -- flaky test by design",
                "severity": "ERROR",
            })

        # A7: empty raises = ERROR
        if t["has_empty_raises"]:
            violations.append({
                "rule": "A7",
                "description": "empty pytest.raises() -- no actual validation",
                "severity": "ERROR",
            })

        # A8: always-true assertion = ERROR
        if t["has_always_true"]:
            violations.append({
                "rule": "A8",
                "description": "always-true assertion -- trivial assertion",
                "severity": "ERROR",
            })

        # A9: mock where fixture is needed
        mock_count = t.get("mocks", 0)
        has_fixture = t.get("has_fixture_ref", False)
        if mock_count >= 3 and not has_fixture:
            violations.append({
                "rule": "A9",
                "description": f"{mock_count} mocks without fixtures -- replace with pytest fixtures/factories",
                "severity": "WARNING",
            })

        return violations

    def visit_Call(self, node: ast.Call) -> None:
        if self.current_test is not None:
            self.current_test["calls"] += 1

            if isinstance(node.func, ast.Name):
                if node.func.id in ("mock", "MagicMock", "AsyncMock", "patch"):
                    self.current_test["mocks"] += 1
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr in ("mock", "MagicMock", "AsyncMock"):
                    self.current_test["mocks"] += 1
                if node.func.attr == "sleep":
                    self.current_test["has_sleep"] = True

        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        if self.current_test is not None:
            self.current_test["assertions"] += 1

            if isinstance(node.test, (ast.NameConstant, ast.Constant)) and node.test.value is True:
                self.current_test["has_always_true"] = True

            if isinstance(node.test, ast.Compare):
                if (isinstance(node.test.left, ast.Constant) and
                    isinstance(node.test.comparators[0], ast.Constant) and
                    node.test.left.value == node.test.comparators[0].value):
                    self.current_test["has_always_true"] = True

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self.current_test is not None:
            if node.attr in ("setup", "setup_method"):
                self.current_test["has_setup"] = True
            elif node.attr in ("teardown", "teardown_method"):
                self.current_test["has_teardown"] = True

        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if self.current_test is not None:
            if node.id in ("request", "pytest", "_pytest"):
                self.current_test["has_fixture_ref"] = True

        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        if self.current_test is not None:
            for item in node.items:
                if isinstance(item.context_expr, ast.Call):
                    if isinstance(item.context_expr.func, ast.Attribute):
                        if item.context_expr.func.attr == "raises":
                            if len(node.body) == 0 or (
                                len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
                            ):
                                self.current_test["has_empty_raises"] = True

        self.generic_visit(node)

    def _check_decorators(self, node: ast.FunctionDef) -> None:
        """Check decorators for parametrization."""
        if self.current_test is None:
            return
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                func = decorator.func
                if isinstance(func, ast.Attribute) and func.attr == "parametrize":
                    self.current_test["parametrize_count"] += 1
                elif isinstance(func, ast.Name) and func.id == "parametrize":
                    self.current_test["parametrize_count"] += 1
            elif isinstance(decorator, ast.Name):
                if decorator.id == "parametrize":
                    self.current_test["parametrize_count"] += 1


def analyze_test_file(filepath: Path) -> list[dict[str, Any]]:
    """Parse a single test file and return weak test report."""
    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content, str(filepath))
    except (SyntaxError, UnicodeDecodeError):
        return []

    visitor = WeakTestVisitor()
    visitor.visit(tree)
    return visitor.tests


def run_weak_test_analysis(tests_dir: str, src_dir: str) -> dict[str, Any]:
    """Run weak test detection across test directories.

    Returns a dict with weak_tests array and summary statistics.
    """
    tests_path = Path(tests_dir)
    src_path = Path(src_dir)

    all_weak_tests: list[dict[str, Any]] = []
    estimated_tests = 0

    for test_file in tests_path.rglob("test_*.py"):
        weak = analyze_test_file(test_file)
        for w in weak:
            w["file"] = str(test_file.relative_to(tests_path))
            all_weak_tests.append(w)

        try:
            content = test_file.read_text(encoding="utf-8")
            tree = ast.parse(content, str(test_file))
        except (SyntaxError, UnicodeDecodeError):
            continue

        estimated_tests += sum(
            1 for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        )

    error_count = sum(
        1 for w in all_weak_tests
        if any(v["severity"] == "ERROR" for v in w.get("violations", []))
    )
    warning_count = len(all_weak_tests) - error_count

    result: dict[str, Any] = {
        "weak_tests": all_weak_tests,
        "summary": {
            "total_tests_analyzed": estimated_tests,
            "weak_test_count": len(all_weak_tests),
            "error_count": error_count,
            "warning_count": warning_count,
            "pass_rate": round(max(0.0, (estimated_tests - len(all_weak_tests)) / max(1, estimated_tests)), 3),
        },
    }

    return result


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: weak_test.py <tests_dir> <src_dir>", file=sys.stderr)
        sys.exit(1)
    result = run_weak_test_analysis(sys.argv[1], sys.argv[2])
    print(json.dumps(result, indent=2))
