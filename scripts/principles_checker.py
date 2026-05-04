#!/usr/bin/env python3
"""
Principles Checker — Validate DRY, KISS, YAGNI, LoD, CoI principles.

DRY   — Don't Repeat Yourself: duplicate_code_threshold: 6 lines
KISS  — Keep It Simple: max_function_complexity: 10, max_nesting_depth: 4, max_parameters: 5
YAGNI — You Aren't Gonna Need It: unused_imports_ratio: 0, dead_code_ratio: 0
LoD   — Law of Demeter: max_chain_length: 3
CoI   — Composition Over Inheritance: inheritance_depth_max: 2

Usage:
    python3 principles_checker.py <src_dir>

Output:
    JSON with PASS/FAIL per principle and violation details.
"""

import ast
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


class PrinciplesVisitor(ast.NodeVisitor):
    """Collect metrics for DRY, KISS, YAGNI, LoD, CoI analysis."""

    def __init__(self) -> None:
        self.functions: list[dict[str, Any]] = []
        self.classes: list[dict[str, Any]] = []
        self.imports: list[dict[str, str]] = []  # {module, alias, lineno}
        self.used_names: set[str] = set()
        self.current_function: dict[str, Any] | None = None
        self.current_class: dict[str, Any] | None = None
        self._in_function = False
        self._nesting_depth = 0
        self._max_nesting = 0

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name_used = alias.asname if alias.asname else alias.name.split(".")[0]
            self.imports.append({
                "module": alias.name,
                "alias": name_used,
                "lineno": node.lineno,
            })
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            for alias in (node.names or []):
                name_used = alias.asname if alias.asname else alias.name.split(".")[0]
                self.imports.append({
                    "module": node.module + "." + alias.name,
                    "alias": name_used,
                    "lineno": node.lineno,
                })
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        self.used_names.add(node.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._in_function = True
        self._nesting_depth = 0
        self._max_nesting = 0

        self.current_function = {
            "name": node.name,
            "lineno": node.lineno,
            "end_lineno": node.end_lineno or node.lineno,
            "arity": len([a for a in node.args.args if a.arg not in ("self", "cls")]),
            "max_nesting": 0,
            "complexity": 1,
            "loc": (node.end_lineno or node.lineno) - node.lineno + 1,
        }

        self.generic_visit(node)

        if self.current_function:
            self.current_function["max_nesting"] = self._max_nesting
            self.functions.append(self.current_function)

        self._in_function = False
        self.current_function = None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        base_names = []
        for b in node.bases:
            if isinstance(b, ast.Name):
                base_names.append(b.id)
            elif isinstance(b, ast.Attribute):
                base_names.append(b.attr)

        self.current_class = {
            "name": node.name,
            "lineno": node.lineno,
            "bases": base_names,
            "methods_count": sum(
                1 for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            ),
        }
        self.generic_visit(node)
        if self.current_class:
            self.classes.append(self.current_class)
        self.current_class = None

    def _increment_complexity(self) -> None:
        self._nesting_depth += 1
        self._max_nesting = max(self._max_nesting, self._nesting_depth)
        if self.current_function:
            self.current_function["complexity"] += 1

    def visit_If(self, node: ast.If) -> None:
        self._increment_complexity()
        self.generic_visit(node)
        self._nesting_depth -= 1

    def visit_For(self, node: ast.For) -> None:
        self._increment_complexity()
        self.generic_visit(node)
        self._nesting_depth -= 1

    def visit_While(self, node: ast.While) -> None:
        self._increment_complexity()
        self.generic_visit(node)
        self._nesting_depth -= 1

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self._increment_complexity()
        self.generic_visit(node)
        self._nesting_depth -= 1

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        # and/or chains add complexity
        if self.current_function:
            self.current_function["complexity"] += len(node.values) - 1
        self.generic_visit(node)


def check_dry(src_dir: Path) -> dict[str, Any]:
    """Check DRY principle: duplicate code detection using N-line blocks."""
    block_size = 6
    file_blocks: dict[str, list[tuple[int, str]]] = {}

    for py_file in src_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lines = [l.rstrip() for l in content.split("\n") if l.strip() and not l.strip().startswith("#")]
        blocks = []
        for i in range(len(lines) - block_size + 1):
            block = "\n".join(lines[i:i + block_size])
            if len(block) > 40:  # Ignore trivial blocks
                blocks.append((i + 1, block))
        file_blocks[str(py_file.relative_to(src_dir))] = blocks

    duplicates: list[dict[str, Any]] = []
    seen: dict[str, tuple[str, int]] = {}

    for filepath, blocks in file_blocks.items():
        for line_no, block in blocks:
            if block in seen:
                other_file, other_line = seen[block]
                if other_file != filepath:
                    duplicates.append({
                        "block_preview": block[:80],
                        "file1": other_file,
                        "line1": other_line,
                        "file2": filepath,
                        "line2": line_no,
                    })
            else:
                seen[block] = (filepath, line_no)

    return {
        "status": "PASS" if len(duplicates) == 0 else "FAIL",
        "violations": len(duplicates),
        "duplicate_blocks": duplicates[:10],
    }


def check_kiss(src_dir: Path) -> dict[str, Any]:
    """Check KISS principle: complexity, nesting, parameters."""
    visitor = PrinciplesVisitor()

    for py_file in src_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        visitor.visit(tree)

    violations = []

    for func in visitor.functions:
        if func["complexity"] > 10:
            violations.append({
                "file": "src/",
                "function": func["name"],
                "lineno": func["lineno"],
                "issue": "complexity=" + str(func["complexity"]) + " > 10",
            })
        if func["max_nesting"] > 4:
            violations.append({
                "file": "src/",
                "function": func["name"],
                "lineno": func["lineno"],
                "issue": "nesting=" + str(func["max_nesting"]) + " > 4",
            })
        if func["arity"] > 5:
            violations.append({
                "file": "src/",
                "function": func["name"],
                "lineno": func["lineno"],
                "issue": "arity=" + str(func["arity"]) + " > 5",
            })

    return {
        "status": "PASS" if len(violations) == 0 else "FAIL",
        "violations": len(violations),
        "details": violations[:20],
    }


def check_yagni(src_dir: Path) -> dict[str, Any]:
    """Check YAGNI principle: unused imports."""
    visitor = PrinciplesVisitor()

    for py_file in src_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        visitor.visit(tree)

    # Compare import aliases against used names
    unused_imports = []
    for imp in visitor.imports:
        if imp["alias"] not in visitor.used_names:
            unused_imports.append(imp)

    return {
        "status": "PASS" if len(unused_imports) == 0 else "FAIL",
        "violations": len(unused_imports),
        "unused_imports": unused_imports[:10],
    }


def check_lod(src_dir: Path) -> dict[str, Any]:
    """Check Law of Demeter: attribute chain depth."""
    violations = []

    for py_file in src_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                chain_length = _count_attribute_chain(node)
                if chain_length > 3:
                    violations.append({
                        "file": str(py_file.relative_to(src_dir)),
                        "lineno": node.lineno,
                        "chain_length": chain_length,
                    })

    return {
        "status": "PASS" if len(violations) == 0 else "FAIL",
        "violations": len(violations),
        "details": violations[:10],
    }


def _count_attribute_chain(node: ast.Attribute) -> int:
    """Count the depth of an attribute access chain."""
    count = 1
    current = node.value
    while isinstance(current, ast.Attribute):
        count += 1
        current = current.value
    return count


def check_coi(src_dir: Path) -> dict[str, Any]:
    """Check Composition Over Inheritance: real inheritance depth."""
    visitor = PrinciplesVisitor()

    for py_file in src_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        visitor.visit(tree)

    # Build inheritance tree and calculate actual depth
    class_map = {c["name"]: c for c in visitor.classes}
    max_allowed = 2

    violations = []

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
        if depth > max_allowed:
            violations.append({
                "file": "src/",
                "class": cls["name"],
                "lineno": cls["lineno"],
                "inheritance_depth": depth,
                "bases": cls["bases"],
            })

    return {
        "status": "PASS" if len(violations) == 0 else "FAIL",
        "violations": len(violations),
        "details": violations[:10],
    }


def main(src_dir: str) -> None:
    src_path = Path(src_dir)

    result = {
        "DRY": check_dry(src_path),
        "KISS": check_kiss(src_path),
        "YAGNI": check_yagni(src_path),
        "LoD": check_lod(src_path),
        "CoI": check_coi(src_path),
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: principles_checker.py <src_dir>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
