"""Minimal test file that ONLY tests phpmd_adapter.py.

This is used exclusively by mutmut for mutation testing on phpmd_adapter.py
only to avoid import conflicts from other adapter tests.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.base import ToolAdapter, ToolInvocation
from harness_quality_gate.adapters.php.phpmd_adapter import (
    PhpMdAdapter,
    _priority_to_severity,
)


def _ok(stdout: str = "", stderr: str = "", exitcode: int = 0) -> ToolInvocation:
    return ToolInvocation(stdout=stdout, stderr=stderr, exitcode=exitcode, duration_seconds=0.0)


class TestPhpMdAdapter:
    def test_name(self) -> None:
        assert PhpMdAdapter().name == "phpmd"

    def test_parse_empty(self) -> None:
        assert PhpMdAdapter().parse("", "", 0) == []

    def test_parse_invalid_json(self) -> None:
        assert PhpMdAdapter().parse("not json", "", 1) == []

    def test_parse_no_files_key(self) -> None:
        assert PhpMdAdapter().parse('{"other": 1}', "", 0) == []

    def test_parse_files_not_list(self) -> None:
        assert PhpMdAdapter().parse('{"files": "bad"}', "", 0) == []

    def test_parse_with_violations(self) -> None:
        data = {
            "files": [
                {
                    "file": "src/Foo.php",
                    "violations": [
                        {
                            "beginLine": 10,
                            "rule": "LongVariable",
                            "description": "Variable name is too long",
                            "priority": 2,
                            "class": "FooClass",
                            "method": "doSomething",
                        }
                    ],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "src/Foo.php"
        assert f.severity == "major"
        assert "LongVariable" in (f.fix_hint or "")
        assert "FooClass" in f.message

    def test_parse_exact_message_content(self) -> None:
        """Exact message assertions to kill .get() key mutations."""
        data = {
            "files": [
                {
                    "file": "src/Foo.php",
                    "violations": [
                        {
                            "beginLine": 10,
                            "rule": "LongVariable",
                            "description": "Variable name is too long",
                            "priority": 2,
                            "class": "FooClass",
                            "method": "doSomething",
                        }
                    ],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        f = findings[0]
        assert "Line 10" in f.message
        assert "Variable name is too long" in f.message
        assert "FooClass.doSomething" in f.message

    def test_parse_violation_without_optional_keys(self) -> None:
        """Missing optional keys — kills default-value mutants."""
        data = {
            "files": [
                {
                    "file": "src/x.php",
                    "violations": [
                        {"description": "test desc", "rule": "Bad", "priority": 2},
                    ],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "src/x.php"
        assert "test desc" in f.message
        assert f.severity == "major"
        assert f.fix_hint == "Rule: Bad"
        assert "Line" not in f.message
        assert "::" not in f.message

    def test_parse_context_with_class_and_method(self) -> None:
        """Context built as 'Class.Method'. Kills mutant 75-76."""
        data = {
            "files": [
                {
                    "file": "src/Foo.php",
                    "violations": [
                        {
                            "beginLine": 10,
                            "rule": "LongVariable",
                            "description": "Desc here",
                            "priority": 2,
                            "class": "MyClass",
                            "method": "myMethod",
                        }
                    ],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        f = findings[0]
        assert "MyClass.myMethod" in f.message
        assert "::" not in f.message

    def test_parse_startline_fallback(self) -> None:
        """Falls back to startLine when beginLine missing. Kills mutant 45."""
        data = {
            "files": [
                {
                    "file": "src/Foo.php",
                    "violations": [
                        {
                            "beginLine": 5,
                            "startLine": 20,
                            "rule": "LineRule",
                            "description": "Test",
                            "priority": 3,
                        }
                    ],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        f = findings[0]
        assert "Line 5" in f.message

    def test_parse_multiple_entries_with_breaks(self) -> None:
        """Kills continue→break mutants (11, 25, 27, 32)."""
        data = {
            "files": [
                {
                    "file": "src/A.php",
                    "violations": [{"rule": "R1", "description": "A", "priority": 2}],
                },
                "not-a-dict",
                {
                    "file": "src/B.php",
                    "violations": "not-a-list",
                },
                {
                    "file": "src/D.php",
                    "violations": [
                        {"rule": "R3", "description": "D", "priority": 2},
                        "not-a-dict",
                    ],
                },
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 2

    def test_parse_violation_with_no_begin_line(self) -> None:
        data = {
            "files": [
                {
                    "file": "src/Baz.php",
                    "violations": [{"rule": "UnusedCode", "description": "Unused method", "priority": 4}],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        assert findings[0].severity == "info"

    def test_parse_violation_no_class_no_method(self) -> None:
        data = {
            "files": [
                {
                    "file": "src/Bar.php",
                    "violations": [{"beginLine": 5, "rule": "TooManyMethods", "description": "Too many", "priority": 1}],
                }
            ]
        }
        findings = PhpMdAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        assert findings[0].severity == "critical"

    def test_parse_violations_not_list(self) -> None:
        data = {"files": [{"file": "x.php", "violations": "bad"}]}
        assert PhpMdAdapter().parse(json.dumps(data), "", 0) == []

    def test_parse_violation_not_dict(self) -> None:
        data = {"files": [{"file": "x.php", "violations": ["not-a-dict"]}]}
        assert PhpMdAdapter().parse(json.dumps(data), "", 0) == []

    def test_parse_file_entry_not_dict(self) -> None:
        data = {"files": ["not-a-dict"]}
        assert PhpMdAdapter().parse(json.dumps(data), "", 0) == []

    def test_priority_to_severity_mapping(self) -> None:
        assert _priority_to_severity(1) == "critical"
        assert _priority_to_severity(2) == "major"
        assert _priority_to_severity(3) == "minor"
        assert _priority_to_severity(4) == "info"
        assert _priority_to_severity(5) == "info"
        assert _priority_to_severity(99) == "info"

    def test_invoke_no_binary_raises(self, tmp_path: Path) -> None:
        adapter = PhpMdAdapter()
        with patch("harness_quality_gate.adapters.php.phpmd_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="phpmd not found"):
                adapter.invoke(tmp_path, ["src", "json", "cleancode"])

    def test_invoke_with_system_binary(self, tmp_path: Path) -> None:
        adapter = PhpMdAdapter()
        with patch("harness_quality_gate.adapters.php.phpmd_adapter.shutil.which", return_value="/usr/bin/phpmd"):
            with patch.object(PhpMdAdapter, "_run", return_value=_ok("{}")) as mock_run:
                result = adapter.invoke(tmp_path, ["src", "json", "cleancode"])
        mock_run.assert_called_once()
        assert result.stdout == "{}"

    def test_run_l3a(self, tmp_path: Path) -> None:
        data = {"files": [{"file": "src/Foo.php", "violations": []}]}
        with patch("harness_quality_gate.adapters.php.phpmd_adapter.shutil.which", return_value="/usr/bin/phpmd"):
            with patch.object(PhpMdAdapter, "_run", return_value=_ok(json.dumps(data))):
                findings = PhpMdAdapter().run_l3a(tmp_path, {})
        assert findings == []
