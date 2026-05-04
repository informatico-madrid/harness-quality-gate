#!/usr/bin/env python3
"""
Antipattern Checker — Detect 50 code antipatterns from canonical literature.

Two-Tier Architecture:
  Tier A (AP01-AP25, AP30-AP31, AP39): AST-based deterministic detection
  Tier B (AP14-AP16, AP19, AP27-AP29, AP32-AP38, AP40-AP50): BMAD Party Mode

Based on:
  - Martin Fowler, "Refactoring" (1999)
  - William Brown et al., "AntiPatterns" (1998)
  - Robert C. Martin, "Clean Code" (2008)
  - Brian Foote and William Opdyke (1992)

Usage:
    python3 antipattern_checker.py <src_dir> <tests_dir>

Output:
    JSON with PASS/FAIL per antipattern and violation details.
"""

import ast
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Thresholds (override via config/quality-gate.yaml if loaded)
# ---------------------------------------------------------------------------
THRESHOLDS: dict[str, dict[str, Any]] = {
    "AP01": {"max_loc": 500, "max_public_methods": 20},
    "AP03": {"max_class_loc": 60},
    "AP06": {"max_lines": 100},
    "AP07": {"max_attributes": 15},
    "AP08": {"max_arity": 5},
    "AP11": {"max_methods": 3},
    "AP13": {"delegation_ratio": 0.8},
    "AP18": {"max_cases": 5},
    "AP20": {"max_nesting": 5},
    "AP21": {"max_chain": 3},
    "AP24": {"max_primitive_args": 5},
    "AP25": {"min_repetitions": 3, "min_param_count": 3},
    "AP30": {"max_cycles": 0},
    "AP31": {"max_incoming_imports": 15},
    "AP39": {"max_inheritance_depth": 5},
}


# ---------------------------------------------------------------------------
# Tier B definitions — patterns that need BMAD Party Mode for detection
# Each entry has: name, description, red_flags (what the LLM should look for)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# AST Visitor — collects metrics for all Tier A patterns
# ---------------------------------------------------------------------------
class AntipatternVisitor(ast.NodeVisitor):
    """Visit AST nodes to collect metrics for antipattern detection."""

    def __init__(self, source_lines: list[str] | None = None) -> None:
        self.classes: list[dict[str, Any]] = []
        self.functions: list[dict[str, Any]] = []
        self.imports: list[str] = []
        self.global_vars: list[str] = []
        self.source_lines = source_lines or []
        self._class_stack: list[dict[str, Any]] = []
        self._func_stack: list[dict[str, Any]] = []
        self._nesting_depth = 0
        self._max_nesting = 0

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self.imports.append(node.module)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        base_names = []
        for b in node.bases:
            if isinstance(b, ast.Name):
                base_names.append(b.id)
            elif isinstance(b, ast.Attribute):
                base_names.append(b.attr)

        # Calculate LOC for this class
        class_loc = 0
        if self.source_lines and node.end_lineno:
            class_loc = node.end_lineno - node.lineno + 1

        cls_data: dict[str, Any] = {
            "name": node.name,
            "lineno": node.lineno,
            "end_lineno": node.end_lineno or node.lineno,
            "loc": class_loc,
            "bases": base_names,
            "is_abc": any(b in base_names for b in ("ABC", "ABCMeta")),
            "public_methods": 0,
            "all_methods": 0,
            "static_methods": 0,
            "class_methods": 0,
            "attributes": set(),
            "methods_detail": [],
            "delegates_to": 0,
            "foreign_calls": 0,
            "self_calls": 0,
            "has_only_properties": True,
            "has_behavior": False,
        }
        self._class_stack.append(cls_data)
        self.generic_visit(node)
        self._class_stack.pop()
        cls_data["attributes"] = len(cls_data["attributes"])
        self.classes.append(cls_data)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._nesting_depth = 0
        self._max_nesting = 0

        # Calculate LOC
        func_loc = 0
        if node.end_lineno:
            func_loc = node.end_lineno - node.lineno + 1

        is_public = not node.name.startswith("_") or node.name in (
            "__init__", "__call__", "__str__", "__repr__"
        )

        # Detect decorators
        decorators = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                decorators.append(dec.attr)

        is_static = "staticmethod" in decorators
        is_classmethod = "classmethod" in decorators
        is_property = "property" in decorators

        arity = len([a for a in node.args.args if a.arg != "self" and a.arg != "cls"])

        # Count primitive-type parameters
        primitive_args = 0
        for arg in node.args.args:
            if arg.arg in ("self", "cls"):
                continue
            annotation = arg.annotation
            if annotation is None:
                primitive_args += 1  # No type hint = assume primitive
            elif isinstance(annotation, ast.Name) and annotation.id in (
                "int", "float", "str", "bool", "bytes", "None"
            ):
                primitive_args += 1

        func_data: dict[str, Any] = {
            "name": node.name,
            "lineno": node.lineno,
            "end_lineno": node.end_lineno or node.lineno,
            "loc": func_loc,
            "arity": arity,
            "max_nesting": 0,
            "is_public": is_public,
            "is_static": is_static,
            "is_classmethod": is_classmethod,
            "is_property": is_property,
            "decorators": decorators,
            "in_class": len(self._class_stack) > 0,
            "calls": [],
            "primitive_args": primitive_args,
            "has_body": False,
            "body_is_pass_or_ellipsis": False,
        }

        # Check if function body is just pass or ...
        if node.body:
            first_stmt = node.body[0]
            if isinstance(first_stmt, ast.Expr) and isinstance(first_stmt.value, ast.Constant):
                if first_stmt.value.value is ...:
                    func_data["body_is_pass_or_ellipsis"] = True
            elif isinstance(first_stmt, ast.Pass):
                func_data["body_is_pass_or_ellipsis"] = True

        # Check if function has real logic (not just return/pass)
        func_data["has_body"] = not func_data["body_is_pass_or_ellipsis"]

        self._func_stack.append(func_data)
        self.generic_visit(node)
        self._func_stack.pop()

        func_data["max_nesting"] = self._max_nesting
        self.functions.append(func_data)

        # Update class data
        if self._class_stack:
            cls = self._class_stack[-1]
            cls["all_methods"] += 1
            if is_public:
                cls["public_methods"] += 1
            if is_static:
                cls["static_methods"] += 1
            if is_classmethod:
                cls["class_methods"] += 1
            if not is_property and func_data["has_body"]:
                cls["has_only_properties"] = False
                cls["has_behavior"] = True
            cls["methods_detail"].append({
                "name": node.name,
                "is_static": is_static,
                "is_classmethod": is_classmethod,
                "is_property": is_property,
                "delegates": func_data.get("delegates", False),
                "foreign_calls": func_data.get("foreign_calls", 0),
                "self_calls": func_data.get("self_calls", 0),
            })

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Track attribute access for Feature Envy (AP09)
        if self._func_stack:
            func = self._func_stack[-1]
            if isinstance(node.value, ast.Name):
                if node.value.id == "self":
                    func["self_calls"] = func.get("self_calls", 0) + 1
                    # Track attribute for class data
                    if self._class_stack:
                        self._class_stack[-1]["attributes"].add(node.attr)
                else:
                    func["foreign_calls"] = func.get("foreign_calls", 0) + 1
                    func["calls"].append(node.value.id + "." + node.attr)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if self._func_stack:
            func = self._func_stack[-1]
            if isinstance(node.func, ast.Attribute):
                func["calls"].append(node.func.attr)
                # Track delegation for Middle Man (AP13)
                if self._class_stack:
                    if isinstance(node.func.value, ast.Name) and node.func.value.id != "self":
                        func["delegates"] = True
                        self._class_stack[-1]["delegates_to"] += 1
            elif isinstance(node.func, ast.Name):
                func["calls"].append(node.func.id)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        self._nesting_depth += 1
        self._max_nesting = max(self._max_nesting, self._nesting_depth)
        self.generic_visit(node)
        self._nesting_depth -= 1

    def visit_For(self, node: ast.For) -> None:
        self._nesting_depth += 1
        self._max_nesting = max(self._max_nesting, self._nesting_depth)
        self.generic_visit(node)
        self._nesting_depth -= 1

    def visit_While(self, node: ast.While) -> None:
        self._nesting_depth += 1
        self._max_nesting = max(self._max_nesting, self._nesting_depth)
        self.generic_visit(node)
        self._nesting_depth -= 1

    def visit_With(self, node: ast.With) -> None:
        self._nesting_depth += 1
        self._max_nesting = max(self._max_nesting, self._nesting_depth)
        self.generic_visit(node)
        self._nesting_depth -= 1

    def visit_Try(self, node: ast.Try) -> None:
        self._nesting_depth += 1
        self._max_nesting = max(self._max_nesting, self._nesting_depth)
        self.generic_visit(node)
        self._nesting_depth -= 1

    def visit_Assign(self, node: ast.Assign) -> None:
        # Track global variables
        if not self._class_stack and not self._func_stack:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.global_vars.append(target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if not self._class_stack and not self._func_stack:
            if isinstance(node.target, ast.Name):
                self.global_vars.append(node.target.id)
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Import Graph Builder — for AP30 (Circular Dependency) and AP31 (Hub)
# ---------------------------------------------------------------------------
class ImportGraphBuilder:
    """Build import graph and detect cycles."""

    def __init__(self, src_dir: Path) -> None:
        self.src_dir = src_dir
        self.graph: dict[str, set[str]] = defaultdict(set)
        self.reverse_graph: dict[str, set[str]] = defaultdict(set)

    def build(self) -> None:
        for py_file in self.src_dir.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            module_name = self._file_to_module(py_file)
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.graph[module_name].add(alias.name)
                        self.reverse_graph[alias.name].add(module_name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self.graph[module_name].add(node.module)
                    self.reverse_graph[node.module].add(module_name)

    def _file_to_module(self, filepath: Path) -> str:
        try:
            rel = filepath.relative_to(self.src_dir)
        except ValueError:
            rel = filepath
        parts = list(rel.parts)
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
        else:
            parts[-1] = parts[-1][:-3]
        return ".".join(parts)

    def find_cycles(self) -> list[list[str]]:
        cycles: list[list[str]] = []
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def dfs(node: str, path: list[str]) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            for neighbor in self.graph.get(node, set()):
                if neighbor not in visited:
                    dfs(neighbor, path.copy())
                elif neighbor in rec_stack:
                    cycle_start = path.index(neighbor) if neighbor in path else 0
                    cycles.append(path[cycle_start:] + [neighbor])
            rec_stack.remove(node)

        for node in self.graph:
            if node not in visited:
                dfs(node, [])

        return cycles[:10]

    def find_hubs(self, max_incoming: int = 15) -> list[dict[str, Any]]:
        """Find modules imported by too many others (Hub/Spoke pattern)."""
        hubs = []
        for module, importers in self.reverse_graph.items():
            if len(importers) > max_incoming:
                hubs.append({
                    "module": module,
                    "imported_by": len(importers),
                    "importers": sorted(importers)[:5],
                })
        return hubs


# ---------------------------------------------------------------------------
# Tier A Detection Functions (AST-based, deterministic)
# ---------------------------------------------------------------------------

def detect_ap01(violations: list[dict[str, Any]], visitor: AntipatternVisitor) -> None:
    """AP01: God Class — >500 LOC or >20 public methods."""
    t = THRESHOLDS["AP01"]
    for cls in visitor.classes:
        issues = []
        if cls["public_methods"] > t["max_public_methods"]:
            issues.append("public_methods=" + str(cls["public_methods"]) + " > " + str(t["max_public_methods"]))
        if cls["loc"] > t["max_loc"]:
            issues.append("loc=" + str(cls["loc"]) + " > " + str(t["max_loc"]))
        if issues:
            violations.append({
                "id": "AP01", "name": "God Class",
                "class": cls["name"], "lineno": cls["lineno"],
                "issue": "; ".join(issues),
            })


def detect_ap02(violations: list[dict[str, Any]], visitor: AntipatternVisitor) -> None:
    """AP02: Functional Decomposition — class with only static/class methods, no instance state."""
    for cls in visitor.classes:
        if cls["all_methods"] == 0:
            continue
        non_static = cls["all_methods"] - cls["static_methods"] - cls["class_methods"]
        if non_static == 0 and cls["all_methods"] >= 3:
            violations.append({
                "id": "AP02", "name": "Functional Decomposition",
                "class": cls["name"], "lineno": cls["lineno"],
                "issue": "all " + str(cls["all_methods"]) + " methods are static/class methods, no instance state",
            })


def detect_ap03(violations: list[dict[str, Any]], visitor: AntipatternVisitor) -> None:
    """AP03: Poltergeist — short-lived controller with no state."""
    max_loc = THRESHOLDS["AP03"]["max_class_loc"]
    for cls in visitor.classes:
        if cls["loc"] <= max_loc and cls["attributes"] == 0 and not cls["is_abc"]:
            if cls["all_methods"] >= 1 and not cls["has_behavior"]:
                violations.append({
                    "id": "AP03", "name": "Poltergeist",
                    "class": cls["name"], "lineno": cls["lineno"],
                    "issue": "short controller class (loc=" + str(cls["loc"]) + ") with no state and no behavior",
                })


def detect_ap04(violations: list[dict[str, Any]], visitor: AntipatternVisitor) -> None:
    """AP04: Spaghetti Code — high cyclomatic complexity + deep nesting."""
    for func in visitor.functions:
        if func["max_nesting"] >= 6 and func["loc"] > 50:
            violations.append({
                "id": "AP04", "name": "Spaghetti Code",
                "function": func["name"], "lineno": func["lineno"],
                "issue": "nesting=" + str(func["max_nesting"]) + " + loc=" + str(func["loc"]),
            })


def detect_ap05(violations: list[dict[str, Any]], src_dir: Path) -> None:
    """AP05: Magic Numbers — hardcoded numeric literals without named constants."""
    whitelist = {0, 1, -1, 2, 10, 100, 1000, 0.0, 1.0, 0.5, -1.0, 2.0, 10.0, 100.0, 255, 256, 360, 1024}
    for py_file in src_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                if node.value not in whitelist and abs(node.value) > 1:
                    violations.append({
                        "id": "AP05", "name": "Magic Numbers",
                        "file": str(py_file.relative_to(src_dir)),
                        "lineno": node.lineno,
                        "issue": "hardcoded value " + str(node.value),
                    })


def detect_ap06(violations: list[dict[str, Any]], visitor: AntipatternVisitor) -> None:
    """AP06: Long Method — function >100 lines (using actual LOC, not nesting)."""
    max_lines = THRESHOLDS["AP06"]["max_lines"]
    for func in visitor.functions:
        if func["loc"] > max_lines:
            violations.append({
                "id": "AP06", "name": "Long Method",
                "function": func["name"], "lineno": func["lineno"],
                "issue": "loc=" + str(func["loc"]) + " > " + str(max_lines),
            })


def detect_ap07(violations: list[dict[str, Any]], visitor: AntipatternVisitor) -> None:
    """AP07: Large Class — >15 instance variables."""
    max_attrs = THRESHOLDS["AP07"]["max_attributes"]
    for cls in visitor.classes:
        if cls["attributes"] > max_attrs:
            violations.append({
                "id": "AP07", "name": "Large Class",
                "class": cls["name"], "lineno": cls["lineno"],
                "issue": "attributes=" + str(cls["attributes"]) + " > " + str(max_attrs),
            })


def detect_ap08(violations: list[dict[str, Any]], visitor: AntipatternVisitor) -> None:
    """AP08: Long Parameter List — >5 parameters."""
    max_arity = THRESHOLDS["AP08"]["max_arity"]
    for func in visitor.functions:
        if func["arity"] > max_arity:
            violations.append({
                "id": "AP08", "name": "Long Parameter List",
                "function": func["name"], "lineno": func["lineno"],
                "issue": "arity=" + str(func["arity"]) + " > " + str(max_arity),
            })


def detect_ap09(violations: list[dict[str, Any]], visitor: AntipatternVisitor) -> None:
    """AP09: Feature Envy — method uses more foreign attributes than self."""
    for func in visitor.functions:
        foreign = func.get("foreign_calls", 0)
        self_calls = func.get("self_calls", 0)
        total = foreign + self_calls
        if total > 0 and foreign > self_calls and foreign >= 3:
            violations.append({
                "id": "AP09", "name": "Feature Envy",
                "function": func["name"], "lineno": func["lineno"],
                "issue": "foreign_calls=" + str(foreign) + " > self_calls=" + str(self_calls),
            })


def detect_ap10(violations: list[dict[str, Any]], visitor: AntipatternVisitor) -> None:
    """AP10: Data Class — class with only fields/properties, no behavior."""
    for cls in visitor.classes:
        if (cls["attributes"] >= 3
                and not cls["has_behavior"]
                and cls["all_methods"] >= 1
                and not cls["is_abc"]):
            violations.append({
                "id": "AP10", "name": "Data Class",
                "class": cls["name"], "lineno": cls["lineno"],
                "issue": "has " + str(cls["attributes"]) + " attributes but no behavioral methods",
            })


def detect_ap11(violations: list[dict[str, Any]], visitor: AntipatternVisitor) -> None:
    """AP11: Lazy Class — class with very few methods and low complexity."""
    max_methods = THRESHOLDS["AP11"]["max_methods"]
    for cls in visitor.classes:
        if (cls["all_methods"] <= max_methods
                and cls["all_methods"] > 0
                and cls["attributes"] <= 2
                and not cls["is_abc"]
                and not cls["has_behavior"]):
            violations.append({
                "id": "AP11", "name": "Lazy Class",
                "class": cls["name"], "lineno": cls["lineno"],
                "issue": "only " + str(cls["all_methods"]) + " methods, " + str(cls["attributes"]) + " attrs, no behavior",
            })


def detect_ap12(violations: list[dict[str, Any]], visitor: AntipatternVisitor) -> None:
    """AP12: Speculative Generality — abstract class with single implementation."""
    abstract_classes = [c for c in visitor.classes if c["is_abc"]]
    concrete_classes = [c for c in visitor.classes if not c["is_abc"]]

    for abs_cls in abstract_classes:
        # Count how many concrete classes inherit from this abstract class
        impl_count = 0
        for conc in concrete_classes:
            if abs_cls["name"] in conc["bases"]:
                impl_count += 1
        if impl_count <= 1:
            violations.append({
                "id": "AP12", "name": "Speculative Generality",
                "class": abs_cls["name"], "lineno": abs_cls["lineno"],
                "issue": "abstract class with only " + str(impl_count) + " concrete implementation(s)",
            })


def detect_ap13(violations: list[dict[str, Any]], visitor: AntipatternVisitor) -> None:
    """AP13: Middle Man — >80% of methods just delegate to other objects."""
    ratio = THRESHOLDS["AP13"]["delegation_ratio"]
    for cls in visitor.classes:
        if cls["all_methods"] >= 3:
            delegation_ratio = cls["delegates_to"] / cls["all_methods"]
            if delegation_ratio > ratio:
                violations.append({
                    "id": "AP13", "name": "Middle Man",
                    "class": cls["name"], "lineno": cls["lineno"],
                    "issue": "delegation_ratio=" + str(round(delegation_ratio, 2)) + " > " + str(ratio),
                })


def detect_ap17(violations: list[dict[str, Any]], visitor: AntipatternVisitor) -> None:
    """AP17: Refused Bequest — subclass that overrides parent methods with pass/ellipsis."""
    # Find classes with bases
    subclasses = [c for c in visitor.classes if c["bases"]]
    parent_names = {c["name"] for c in visitor.classes}

    for subcls in subclasses:
        parent_name = None
        for base in subcls["bases"]:
            if base in parent_names:
                parent_name = base
                break
        if not parent_name:
            continue

        # Check if subclass methods are mostly pass/ellipsis
        empty_methods = 0
        total_methods = 0
        for func in visitor.functions:
            if func["lineno"] >= subcls["lineno"] and func.get("end_lineno", 0) <= subcls.get("end_lineno", 0):
                total_methods += 1
                if func["body_is_pass_or_ellipsis"]:
                    empty_methods += 1

        if total_methods >= 2 and empty_methods > total_methods / 2:
            violations.append({
                "id": "AP17", "name": "Refused Bequest",
                "class": subcls["name"], "lineno": subcls["lineno"],
                "issue": str(empty_methods) + "/" + str(total_methods) + " methods are empty (pass/...)",
            })


def detect_ap18(violations: list[dict[str, Any]], src_dir: Path) -> None:
    """AP18: Switch Statements — >5 case branches (match or if-elif chains)."""
    max_cases = THRESHOLDS["AP18"]["max_cases"]
    for py_file in src_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            # Python 3.10+ match statements
            if isinstance(node, ast.Match):
                if len(node.cases) > max_cases:
                    violations.append({
                        "id": "AP18", "name": "Switch Statements",
                        "file": str(py_file.relative_to(src_dir)),
                        "lineno": node.lineno,
                        "issue": str(len(node.cases)) + " match cases > " + str(max_cases),
                    })

        # Detect long if-elif chains
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                elif_count = _count_elif_chain(node)
                if elif_count > max_cases:
                    violations.append({
                        "id": "AP18", "name": "Switch Statements",
                        "file": str(py_file.relative_to(src_dir)),
                        "lineno": node.lineno,
                        "issue": str(elif_count) + " if-elif branches > " + str(max_cases),
                    })


def _count_elif_chain(node: ast.If) -> int:
    """Count the number of branches in an if-elif-else chain."""
    count = 1
    current = node
    while current.orelse and len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
        count += 1
        current = current.orelse[0]
    if current.orelse:
        count += 1  # else branch
    return count


def detect_ap20(violations: list[dict[str, Any]], visitor: AntipatternVisitor) -> None:
    """AP20: Deep Nesting — nesting depth > 5."""
    max_nesting = THRESHOLDS["AP20"]["max_nesting"]
    for func in visitor.functions:
        if func["max_nesting"] > max_nesting:
            violations.append({
                "id": "AP20", "name": "Deep Nesting",
                "function": func["name"], "lineno": func["lineno"],
                "issue": "nesting=" + str(func["max_nesting"]) + " > " + str(max_nesting),
            })


def detect_ap21(violations: list[dict[str, Any]], src_dir: Path) -> None:
    """AP21: Message Chains — attribute chains > 3 (a.b.c.d)."""
    max_chain = THRESHOLDS["AP21"]["max_chain"]
    for py_file in src_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                chain_len = _count_attr_chain(node)
                if chain_len > max_chain:
                    violations.append({
                        "id": "AP21", "name": "Message Chains",
                        "file": str(py_file.relative_to(src_dir)),
                        "lineno": node.lineno,
                        "issue": "chain_length=" + str(chain_len) + " > " + str(max_chain),
                    })


def _count_attr_chain(node: ast.Attribute) -> int:
    count = 1
    current = node.value
    while isinstance(current, ast.Attribute):
        count += 1
        current = current.value
    return count


def detect_ap22(violations: list[dict[str, Any]], src_dir: Path) -> None:
    """AP22: Dead Code — unreachable code patterns."""
    for py_file in src_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content, str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue

        # Check for code after return/raise/break/continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for i, stmt in enumerate(node.body):
                    if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                        if i < len(node.body) - 1:
                            violations.append({
                                "id": "AP22", "name": "Dead Code",
                                "file": str(py_file.relative_to(src_dir)),
                                "lineno": node.body[i + 1].lineno,
                                "issue": "unreachable code after " + type(stmt).__name__,
                            })

        # Check for commented-out code (heuristic: lines starting with # that look like code)
        for i, line in enumerate(content.split("\n"), 1):
            stripped = line.strip()
            if stripped.startswith("#") and not stripped.startswith("#!"):
                code_part = stripped[1:].strip()
                # Heuristic: looks like Python code
                if any(code_part.startswith(kw) for kw in (
                    "def ", "class ", "import ", "from ", "return ", "if ", "for ", "while ",
                    "try:", "with ", "raise ", "assert ", "print(", "self."
                )):
                    violations.append({
                        "id": "AP22", "name": "Dead Code",
                        "file": str(py_file.relative_to(src_dir)),
                        "lineno": i,
                        "issue": "commented-out code: " + code_part[:60],
                    })


        # Check for pragma: no cover abuse (anti-evasion detection)
        # Only abstract method stubs and truly unreachable defensive code should use pragma: no cover
        # AND any pragma must include a reason= field (e.g., "# pragma: no cover reason=legacy-api")
        pragma_allowed_patterns = (
            "raise NotImplementedError",
            "pass  # pragma: no cover",
            "...  # pragma: no cover",
        )
        for i, line in enumerate(content.split("\n"), 1):
            stripped = line.strip()
            has_pragma = "pragma: no cover" in stripped or "pragma no cover" in stripped
            if has_pragma:
                is_acceptable = any(p in stripped for p in pragma_allowed_patterns)
                has_reason = "reason=" in stripped.lower() or "justification=" in stripped.lower()
                if not is_acceptable and not stripped.startswith("#"):
                    if not has_reason:
                        violations.append({
                            "id": "AP22", "name": "Dead Code",
                            "file": str(py_file.relative_to(src_dir)),
                            "lineno": i,
                            "issue": "pragma: no cover WITHOUT reason= — remove dead code or add reason= to justify exemption (e.g., '# pragma: no cover reason=pending-deprecation')",
                        })
                    else:
                        violations.append({
                            "id": "AP22", "name": "Dead Code",
                            "file": str(py_file.relative_to(src_dir)),
                            "lineno": i,
                            "issue": "pragma: no cover with reason= — accepted but flag for review. Consider removing dead code or writing tests instead.",
                        })


def detect_ap23(violations: list[dict[str, Any]], src_dir: Path) -> None:
    """AP23: Duplicate Code — identical blocks of 6+ lines across files."""
    block_size = 6
    file_blocks: dict[str, list[tuple[int, str]]] = {}

    for py_file in src_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lines = [l.strip() for l in content.split("\n") if l.strip() and not l.strip().startswith("#")]
        blocks = []
        for i in range(len(lines) - block_size + 1):
            block = "\n".join(lines[i:i + block_size])
            if len(block) > 40:  # Ignore trivial blocks
                blocks.append((i + 1, block))
        file_blocks[str(py_file)] = blocks

    seen: dict[str, tuple[str, int]] = {}
    for filepath, blocks in file_blocks.items():
        for line_no, block in blocks:
            if block in seen:
                other_file, other_line = seen[block]
                if other_file != filepath:
                    violations.append({
                        "id": "AP23", "name": "Duplicate Code",
                        "file": filepath, "lineno": line_no,
                        "issue": "duplicate block also in " + other_file + ":" + str(other_line),
                    })
            else:
                seen[block] = (filepath, line_no)


def detect_ap24(violations: list[dict[str, Any]], visitor: AntipatternVisitor) -> None:
    """AP24: Primitive Obsession — >5 primitive parameters in multiple functions."""
    max_primitive = THRESHOLDS["AP24"]["max_primitive_args"]
    for func in visitor.functions:
        if func["primitive_args"] > max_primitive:
            violations.append({
                "id": "AP24", "name": "Primitive Obsession",
                "function": func["name"], "lineno": func["lineno"],
                "issue": "primitive_args=" + str(func["primitive_args"]) + " > " + str(max_primitive),
            })


def detect_ap25(violations: list[dict[str, Any]], src_dir: Path) -> None:
    """AP25: Data Clumps — same parameter group appearing in multiple functions."""
    min_reps = THRESHOLDS["AP25"]["min_repetitions"]
    min_params = THRESHOLDS["AP25"]["min_param_count"]

    param_groups: dict[str, list[tuple[str, int, str]]] = defaultdict(list)

    for py_file in src_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                params = sorted([
                    a.arg for a in node.args.args if a.arg not in ("self", "cls")
                ])
                if len(params) >= min_params:
                    key = ",".join(params)
                    param_groups[key].append((str(py_file), node.lineno, node.name))

    for key, locations in param_groups.items():
        if len(locations) >= min_reps:
            violations.append({
                "id": "AP25", "name": "Data Clumps",
                "file": locations[0][0],
                "lineno": locations[0][1],
                "issue": "parameter group [" + key + "] appears in " + str(len(locations)) + " functions",
            })


def detect_ap26(violations: list[dict[str, Any]], src_dir: Path) -> None:
    """AP26: Inconsistent Naming — detected via ruff N8XX rules."""
    try:
        result = subprocess.run(
            ["python3", "-m", "ruff", "check", str(src_dir), "--select=N802,N803,N804,N805,N806"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            for line in result.stdout.split("\n"):
                if ":" in line and line.strip():
                    parts = line.split(":")
                    violations.append({
                        "id": "AP26", "name": "Inconsistent Naming",
                        "file": parts[0].strip() if parts else "unknown",
                        "lineno": int(parts[1]) if len(parts) > 1 and parts[1].strip().isdigit() else 0,
                        "issue": line.strip()[:100],
                    })
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def detect_ap30(violations: list[dict[str, Any]], graph_builder: ImportGraphBuilder) -> None:
    """AP30: Circular Dependency — import cycles."""
    cycles = graph_builder.find_cycles()
    if cycles:
        violations.append({
            "id": "AP30", "name": "Circular Dependency",
            "type": "CYCLE",
            "modules": [str(c) for c in cycles[:5]],
            "issue": str(len(cycles)) + " cycle(s) detected",
        })


def detect_ap31(violations: list[dict[str, Any]], graph_builder: ImportGraphBuilder) -> None:
    """AP31: Hub/Spoke — module imported by too many others."""
    max_incoming = THRESHOLDS["AP31"]["max_incoming_imports"]
    hubs = graph_builder.find_hubs(max_incoming)
    for hub in hubs:
        violations.append({
            "id": "AP31", "name": "Hub/Spoke",
            "module": hub["module"],
            "issue": "imported by " + str(hub["imported_by"]) + " modules > " + str(max_incoming),
        })


def detect_ap39(violations: list[dict[str, Any]], visitor: AntipatternVisitor) -> None:
    """AP39: Yo-Yo Problem — deep inheritance chain."""
    max_depth = THRESHOLDS["AP39"]["max_inheritance_depth"]

    # Build inheritance tree
    class_map = {c["name"]: c for c in visitor.classes}

    def get_depth(class_name: str, visited: set[str]) -> int:
        if class_name in visited or class_name not in class_map:
            return 0
        visited.add(class_name)
        cls = class_map[class_name]
        if not cls["bases"]:
            return 0
        return 1 + max(get_depth(b, visited.copy()) for b in cls["bases"])

    for cls in visitor.classes:
        depth = get_depth(cls["name"], set())
        if depth > max_depth:
            violations.append({
                "id": "AP39", "name": "Yo-Yo Problem",
                "class": cls["name"], "lineno": cls["lineno"],
                "issue": "inheritance_depth=" + str(depth) + " > " + str(max_depth),
            })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(src_dir: str, tests_dir: str) -> None:
    src_path = Path(src_dir)

    # Collect AST data from all source files
    all_violations: list[dict[str, Any]] = []

    for py_file in src_path.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content, str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue

        source_lines = content.split("\n")
        visitor = AntipatternVisitor(source_lines)
        visitor.visit(tree)

        # Run per-file detections
        detect_ap04(all_violations, visitor)
        detect_ap05(all_violations, src_path)
        detect_ap06(all_violations, visitor)
        detect_ap09(all_violations, visitor)
        detect_ap17(all_violations, visitor)

    # Collect global visitor data
    global_visitor = AntipatternVisitor()
    for py_file in src_path.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content, str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue
        source_lines = content.split("\n")
        gv = AntipatternVisitor(source_lines)
        gv.visit(tree)
        global_visitor.classes.extend(gv.classes)
        global_visitor.functions.extend(gv.functions)
        global_visitor.imports.extend(gv.imports)
        global_visitor.global_vars.extend(gv.global_vars)

    # Run global detections
    detect_ap01(all_violations, global_visitor)
    detect_ap02(all_violations, global_visitor)
    detect_ap03(all_violations, global_visitor)
    detect_ap07(all_violations, global_visitor)
    detect_ap08(all_violations, global_visitor)
    detect_ap10(all_violations, global_visitor)
    detect_ap11(all_violations, global_visitor)
    detect_ap12(all_violations, global_visitor)
    detect_ap13(all_violations, global_visitor)
    detect_ap20(all_violations, global_visitor)
    detect_ap24(all_violations, global_visitor)

    # File-level detections
    detect_ap18(all_violations, src_path)
    detect_ap21(all_violations, src_path)
    detect_ap22(all_violations, src_path)
    detect_ap23(all_violations, src_path)
    detect_ap25(all_violations, src_path)
    detect_ap26(all_violations, src_path)

    # Graph-based detections
    graph_builder = ImportGraphBuilder(src_path)
    graph_builder.build()
    detect_ap30(all_violations, graph_builder)
    detect_ap31(all_violations, graph_builder)
    detect_ap39(all_violations, global_visitor)

    # Build results for all 50 antipatterns
    antipattern_results: dict[str, dict[str, Any]] = {}
    all_ids = ["AP" + str(i).zfill(2) for i in range(1, 51)]
    failed_ids = {v["id"] for v in all_violations}

    for ap_id in all_ids:
        if ap_id in TIER_B_PATTERNS:
            # Tier B patterns are evaluated by BMAD Party Mode
            antipattern_results[ap_id] = {
                "name": TIER_B_PATTERNS[ap_id]["name"],
                "tier": "B",
                "status": "PENDING_BMAD_REVIEW",
                "description": TIER_B_PATTERNS[ap_id]["description"],
                "red_flags": TIER_B_PATTERNS[ap_id]["red_flags"],
                "violations": [v for v in all_violations if v["id"] == ap_id],
            }
        else:
            # Tier A patterns have deterministic results
            ap_violations = [v for v in all_violations if v["id"] == ap_id]
            antipattern_results[ap_id] = {
                "tier": "A",
                "status": "FAIL" if ap_id in failed_ids else "PASS",
                "violations": ap_violations,
            }

    result = {
        "antipatterns": antipattern_results,
        "tier_a_summary": {
            "total": sum(1 for v in antipattern_results.values() if v.get("tier") == "A"),
            "passed": sum(1 for v in antipattern_results.values() if v.get("tier") == "A" and v.get("status") == "PASS"),
            "failed": sum(1 for v in antipattern_results.values() if v.get("tier") == "A" and v.get("status") == "FAIL"),
        },
        "tier_b_summary": {
            "total": sum(1 for v in antipattern_results.values() if v.get("tier") == "B"),
            "pending_bmad": sum(1 for v in antipattern_results.values() if v.get("status") == "PENDING_BMAD_REVIEW"),
        },
        "all_violations": all_violations[:100],
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: antipattern_checker.py <src_dir> <tests_dir>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
