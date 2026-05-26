"""
Tier A Antipattern Detection — AST-based deterministic detection of 22 antipatterns.

Tier A patterns (AP01-AP25, AP30-AP31, AP39):
  AP01: God Class        — >500 LOC or >20 public methods
  AP02: Functional Decomposition — class with only static/class methods
  AP03: Poltergeist      — short-lived controller with no state
  AP04: Spaghetti Code   — high cyclomatic complexity + deep nesting
  AP05: Magic Numbers    — hardcoded numeric literals without named constants
  AP06: Long Method      — function >100 lines
  AP07: Large Class      — >15 instance variables
  AP08: Long Parameter List — >5 parameters
  AP09: Feature Envy     — method uses more foreign attrs than self
  AP10: Data Class       — class with only fields/properties, no behavior
  AP11: Lazy Class       — class with very few methods and low complexity
  AP12: Speculative Generality — abstract class with single implementation
  AP13: Middle Man       — >80% of methods just delegate
  AP17: Refused Bequest  — subclass overrides parent with pass/ellipsis
  AP18: Switch Statements — >5 case branches
  AP20: Deep Nesting     — nesting depth > 5
  AP21: Message Chains   — attribute chains > 3
  AP22: Dead Code        — unreachable code patterns
  AP23: Duplicate Code   — identical blocks of 6+ lines across files
  AP24: Primitive Obsession — >5 primitive parameters
  AP25: Data Clumps      — same parameter group in multiple functions
  AP26: Inconsistent Naming — via ruff N8XX rules
  AP30: Circular Dependency — import cycles
  AP31: Hub/Spoke        — module imported by too many others
  AP39: Yo-Yo Problem    — deep inheritance chain

Based on:
  - Martin Fowler, "Refactoring" (1999)
  - William Brown et al., "AntiPatterns" (1998)
  - Robert C. Martin, "Clean Code" (2008)
  - Brian Foote and William Opdyke (1992)
"""

import ast
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Thresholds
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
            if isinstance(node, ast.Match):
                if len(node.cases) > max_cases:
                    violations.append({
                        "id": "AP18", "name": "Switch Statements",
                        "file": str(py_file.relative_to(src_dir)),
                        "lineno": node.lineno,
                        "issue": str(len(node.cases)) + " match cases > " + str(max_cases),
                    })

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

        # Check for commented-out code
        for i, line in enumerate(content.split("\n"), 1):
            stripped = line.strip()
            if stripped.startswith("#") and not stripped.startswith("#!"):
                code_part = stripped[1:].strip()
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

        # Check for pragma: no cover abuse
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
                            "issue": "pragma: no cover WITHOUT reason= — remove dead code or add reason= to justify exemption",
                        })
                    else:
                        violations.append({
                            "id": "AP22", "name": "Dead Code",
                            "file": str(py_file.relative_to(src_dir)),
                            "lineno": i,
                            "issue": "pragma: no cover with reason= — accepted but flag for review",
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
            if len(block) > 40:
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
# Engine — scan a src directory and return all Tier A violations
# ---------------------------------------------------------------------------
def run_tier_a(src_dir: str) -> dict[str, Any]:
    """Run all Tier A antipattern detectors on a source directory.

    Returns a dict keyed by antipattern ID, each with status (PASS/FAIL)
    and violations list.
    """
    src_path = Path(src_dir)

    all_violations: list[dict[str, Any]] = []

    # Per-file detections (run on each file individually)
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

    # Global detections
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

    # Organize by AP ID
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for v in all_violations:
        by_id[v["id"]].append(v)

    result: dict[str, Any] = {}
    for ap_id in sorted(by_id.keys()):
        violations = by_id[ap_id]
        result[ap_id] = {
            "status": "FAIL" if violations else "PASS",
            "violations": violations,
            "count": len(violations),
        }

    # Add APs with no violations
    for ap_id in THRESHOLDS:
        if ap_id not in result:
            result[ap_id] = {"status": "PASS", "violations": [], "count": 0}

    return result


def run_tier_a(src_dir: str) -> dict[str, Any]:
    """Run all Tier A antipattern detections against the given source directory.

    This is the public API — collects AST data from all source files and
    runs all 22 deterministic Tier A detections.

    Returns:
        Dict with AP01-AP39 keys, each containing status, violations, count.
    """
    src_path = Path(src_dir)
    all_violations: list[dict[str, Any]] = []

    # Per-file detections (AP04, AP05, AP06, AP09, AP17)
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

        detect_ap04(all_violations, visitor)
        detect_ap05(all_violations, src_path)
        detect_ap06(all_violations, visitor)
        detect_ap09(all_violations, visitor)
        detect_ap17(all_violations, visitor)

    # Global visitor data
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

    detect_ap18(all_violations, src_path)
    detect_ap21(all_violations, src_path)
    detect_ap22(all_violations, src_path)
    detect_ap23(all_violations, src_path)
    detect_ap25(all_violations, src_path)
    detect_ap26(all_violations, src_path)

    graph_builder = ImportGraphBuilder(src_path)
    graph_builder.build()
    detect_ap30(all_violations, graph_builder)
    detect_ap31(all_violations, graph_builder)
    detect_ap39(all_violations, global_visitor)

    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for v in all_violations:
        by_id[v["id"]].append(v)

    result: dict[str, Any] = {}
    for ap_id in sorted(by_id.keys()):
        violations = by_id[ap_id]
        result[ap_id] = {
            "status": "FAIL" if violations else "PASS",
            "violations": violations,
            "count": len(violations),
        }

    for ap_id in THRESHOLDS:
        if ap_id not in result:
            result[ap_id] = {"status": "PASS", "violations": [], "count": 0}

    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: antipattern_tier_a.py <src_dir>", file=sys.stderr)
        sys.exit(1)
    import json
    print(json.dumps(run_tier_a(sys.argv[1]), indent=2))
