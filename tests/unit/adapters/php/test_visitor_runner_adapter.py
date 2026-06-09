"""Comprehensive tests for VisitorRunnerAdapter (Tier-A L3A visitors).

Mutation testing — targets 26 survivor mutants in visitor_runner_adapter.py.
Covers: _discover_visitors, invoke, _build_finding, _merge_findings,
_build_stderr, _build_invocation, _collect_php_files, _parse_visitor_output.
Design: Each public method exercised with granular separate asserts.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.php.visitor_runner_adapter import (
    VISITORS_DIR,
    VisitorRunnerAdapter,
    _discover_visitors,
)
from harness_quality_gate.adapters.base import ToolAdapter, ToolInvocation
from harness_quality_gate.models import Finding


# ===========================================================================
# _discover_visitors()
# ===========================================================================

class TestDiscoverVisitors:
    """_discover_visitors returns sorted visitor names without .php suffix."""

    def test_discover_visitors_empty_dir(self, tmp_path: Path) -> None:
        """Directory with no .php files → empty list."""
        with patch.object(Path, "is_dir", return_value=True):
            with patch.object(Path, "iterdir", return_value=iter([])):
                with patch.object(Path, "__truediv__", return_value=tmp_path):
                    result = _discover_visitors()
                    assert result == []

    def test_discover_visitors_skips_non_php(self, tmp_path: Path) -> None:
        """Non-.php files are excluded."""
        visitors_dir = tmp_path / "visitors"
        visitors_dir.mkdir(parents=True, exist_ok=True)
        (visitors_dir / "test.txt").write_text("dummy")
        (visitors_dir / "god_class.php").write_text("<?php")
        with patch("harness_quality_gate.adapters.php.visitor_runner_adapter.VISITORS_DIR", visitors_dir):
            result = _discover_visitors()
            assert result == ["god_class"]

    def test_discover_visitors_skips_underscore_prefixed(self, tmp_path: Path) -> None:
        """_prefixed files are excluded."""
        visitors_dir = tmp_path / "visitors"
        visitors_dir.mkdir(parents=True, exist_ok=True)
        (visitors_dir / "god_class.php").write_text("<?php")
        (visitors_dir / "_base.php").write_text("<?php")
        with patch("harness_quality_gate.adapters.php.visitor_runner_adapter.VISITORS_DIR", visitors_dir):
            result = _discover_visitors()
            assert result == ["god_class"]

    def test_discover_visitors_sorted(self, tmp_path: Path) -> None:
        """Names must be alphabetically sorted."""
        visitors_dir = tmp_path / "visitors"
        visitors_dir.mkdir(parents=True, exist_ok=True)
        for name in ["zebra", "alpha", "middle"]:
            (visitors_dir / f"{name}.php").write_text("<?php")
        with patch("harness_quality_gate.adapters.php.visitor_runner_adapter.VISITORS_DIR", visitors_dir):
            result = _discover_visitors()
            assert result == ["alpha", "middle", "zebra"]

    def test_discover_visitors_dir_not_present(self) -> None:
        """When VISITORS_DIR doesn't exist → empty list."""
        with patch.object(Path, "is_dir", return_value=False):
            result = _discover_visitors()
            assert result == []


# ===========================================================================
# invoke() — main mutation target
# ===========================================================================

class TestInvoke:
    """invoke() discovers visitors, collects PHP files, runs each visitor."""

    def _make_adapter(self) -> VisitorRunnerAdapter:
        return VisitorRunnerAdapter()

    def test_invoke_no_visitors_returns_early(self, tmp_path: Path) -> None:
        """When no visitor scripts → return early with stderr."""
        adapter = self._make_adapter()
        with patch.object(
            VisitorRunnerAdapter, "_collect_php_files", return_value=[tmp_path / "dummy.php"]
        ), patch(
            "harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors",
            return_value=[],
        ):
            result = adapter.invoke(tmp_path, [])
        assert isinstance(result, ToolInvocation)
        assert result.stdout == "[]"
        assert "no visitors discovered" in result.stderr

    def test_invoke_no_php_files_returns_early(
        self, tmp_path: Path
    ) -> None:
        """When no PHP files → return early with stderr."""
        adapter = self._make_adapter()
        with patch(
            "harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors",
            return_value=["god_class"],
        ):
            with patch.object(
                VisitorRunnerAdapter, "_collect_php_files", return_value=[]
            ):
                result = adapter.invoke(tmp_path, [])
        assert result.stdout == "[]"
        assert "no PHP files found" in result.stderr

    def test_invoke_visitor_script_missing_continues(
        self, tmp_path: Path
    ) -> None:
        """When the visitor script file doesn't exist → skip and continue."""
        adapter = self._make_adapter()
        with patch.object(
            VisitorRunnerAdapter, "_collect_php_files", return_value=[tmp_path / "x.php"]
        ), patch(
            "harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors",
            return_value=["nonexistent"],
        ), patch(
            "harness_quality_gate.adapters.php.visitor_runner_adapter.VISITORS_DIR",
            tmp_path,
        ):
            result = adapter.invoke(tmp_path, [])
        assert isinstance(result, ToolInvocation)
        # Should still return valid empty findings
        assert result.stdout == "[]"

    def test_invoke_single_visitor_success(
        self, tmp_path: Path
    ) -> None:
        """Happy path: visitor runs, produces findings."""
        adapter = self._make_adapter()
        visitor_script = tmp_path / "visitors" / "god_class.php"
        visitor_script.parent.mkdir(parents=True, exist_ok=True)
        visitor_script.write_text("<?php")
        php_file = tmp_path / "src" / "Foo.php"
        php_file.parent.mkdir(parents=True, exist_ok=True)
        php_file.write_text("<?php class Foo {}")

        with patch.object(
            VisitorRunnerAdapter, "_collect_php_files", return_value=[php_file]
        ):
            with patch(
                "harness_quality_gate.adapters.php.visitor_runner_adapter.VISITORS_DIR",
                tmp_path / "visitors",
            ):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(
                        returncode=0,
                        stdout=json.dumps([{"file": "Foo.php", "line": 1, "rule_id": "GOD001"}]),
                        stderr="",
                    )
                    result = adapter.invoke(tmp_path, [])
        assert result.stdout == json.dumps([{"file": "Foo.php", "line": 1, "rule_id": "GOD001"}])
        assert result.exitcode == 0

    def test_invoke_visitor_failure_collects_stderr(
        self, tmp_path: Path
    ) -> None:
        """When visitor fails (non-zero exit) → stderr collected, continue."""
        adapter = self._make_adapter()
        visitor_script = tmp_path / "visitors" / "god_class.php"
        visitor_script.parent.mkdir(parents=True, exist_ok=True)
        visitor_script.write_text("<?php")
        php_file = tmp_path / "src" / "Foo.php"
        php_file.parent.mkdir(parents=True, exist_ok=True)
        php_file.write_text("<?php class Foo {}")

        with patch.object(
            VisitorRunnerAdapter, "_collect_php_files", return_value=[php_file]
        ):
            with patch(
                "harness_quality_gate.adapters.php.visitor_runner_adapter.VISITORS_DIR",
                tmp_path / "visitors",
            ):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(
                        returncode=1, stdout="", stderr="parse error",
                    )
                    result = adapter.invoke(tmp_path, [])
        # stderr_parts are collected → exitcode=1
        assert result.exitcode == 1
        assert "god_class" in result.stderr
        assert "parse error" in result.stderr

    def test_invoke_multiple_visitors_merged(
        self, tmp_path: Path
    ) -> None:
        """Multiple visitors → findings merged."""
        adapter = self._make_adapter()
        visitors_dir = tmp_path / "visitors"
        visitors_dir.mkdir(parents=True, exist_ok=True)
        (visitors_dir / "v1.php").write_text("<?php")
        (visitors_dir / "v2.php").write_text("<?php")
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        php_file = src_dir / "Foo.php"
        php_file.write_text("")

        with patch.object(
            VisitorRunnerAdapter, "_collect_php_files", return_value=[php_file]
        ):
            with patch(
                "harness_quality_gate.adapters.php.visitor_runner_adapter.VISITORS_DIR",
                visitors_dir,
            ):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(
                        returncode=0,
                        stdout=json.dumps([]),
                        stderr="",
                    )
                    result = adapter.invoke(tmp_path, [])
        assert result.stdout == "[]"


# ===========================================================================
# _build_finding()
# ===========================================================================

class TestBuildFinding:
    """_build_finding builds a Finding from a dict, or None for invalid input."""

    def test_build_finding_from_valid_dict(self) -> None:
        item = {"file": "src/Foo.php", "line": 42, "rule_id": "GOD001", "message": "Too many methods"}
        finding = VisitorRunnerAdapter._build_finding(item)
        assert finding is not None
        assert finding.node == "src/Foo.php:42"
        assert finding.severity == "info"
        assert finding.rule_id == "GOD001"
        assert finding.tool == "visitor-runner"
        assert finding.layer == "L3A"
        assert finding.language == "php"

    def test_build_finding_missing_line(self) -> None:
        """When 'line' is missing → node uses filepath only."""
        item = {"file": "src/Foo.php"}
        finding = VisitorRunnerAdapter._build_finding(item)
        assert finding is not None
        assert finding.node == "src/Foo.php"  # no ":line" appended

    def test_build_finding_with_path_alt_key(self) -> None:
        """When 'path' used instead of 'file' → uses 'path' value."""
        item = {"path": "src/Bar.php", "line": 10}
        finding = VisitorRunnerAdapter._build_finding(item)
        assert finding is not None
        assert finding.node == "src/Bar.php:10"

    def test_build_finding_with_severity(self) -> None:
        """Severity field is passed through."""
        item = {"file": "src/Foo.php", "severity": "error"}
        finding = VisitorRunnerAdapter._build_finding(item)
        assert finding is not None
        assert finding.severity == "error"

    def test_build_finding_with_fix_hint(self) -> None:
        """fix_hint field is passed through."""
        item = {"file": "src/Foo.php", "fix_hint": "Split the class"}
        finding = VisitorRunnerAdapter._build_finding(item)
        assert finding is not None
        assert finding.fix_hint == "Split the class"

    def test_build_finding_non_dict_returns_none(self) -> None:
        """Non-dict items return None."""
        assert VisitorRunnerAdapter._build_finding("not a dict") is None
        assert VisitorRunnerAdapter._build_finding(42) is None
        assert VisitorRunnerAdapter._build_finding(None) is None

    def test_build_finding_line_as_string(self) -> None:
        """line as string → converted to int."""
        item = {"file": "src/Foo.php", "line": "99"}
        finding = VisitorRunnerAdapter._build_finding(item)
        assert finding is not None
        # Line should be int 99, so ":" prefix should NOT be added twice
        assert "99" in finding.node
        assert finding.node == "src/Foo.php:99"

    def test_build_finding_empty_string_file(self) -> None:
        """File with empty string → node is just empty string + line."""
        item = {"file": "", "line": 1}
        finding = VisitorRunnerAdapter._build_finding(item)
        assert finding is not None
        assert finding.node == ":1"


# ===========================================================================
# _merge_findings()
# ===========================================================================

class TestMergeFindings:
    """_merge_findings serializes to JSON string."""

    def test_merge_findings_empty(self) -> None:
        result = VisitorRunnerAdapter._merge_findings([])
        assert result == "[]"

    def test_merge_findings_with_findings(self) -> None:
        data = [{"file": "a.php", "rule_id": "R1"}]
        result = VisitorRunnerAdapter._merge_findings(data)
        parsed = json.loads(result)
        assert parsed == data

    def test_merge_findings_unicode(self) -> None:
        """ensure_ascii=False allows unicode in output."""
        data = [{"message": "caf\u00e9"}]
        result = VisitorRunnerAdapter._merge_findings(data)
        assert "caf\u00e9" in result


# ===========================================================================
# _build_stderr()
# ===========================================================================

class TestBuildStderr:
    """_build_stderr joins parts or returns empty string."""

    def test_build_stderr_single_part(self) -> None:
        result = VisitorRunnerAdapter._build_stderr(["error1"])
        assert result == "error1"

    def test_build_stderr_multiple_parts(self) -> None:
        result = VisitorRunnerAdapter._build_stderr(["err1", "err2"])
        assert result == "err1\nerr2"

    def test_build_stderr_empty_list(self) -> None:
        result = VisitorRunnerAdapter._build_stderr([])
        assert result == ""


# ===========================================================================
# _build_invocation()
# ===========================================================================

class TestBuildInvocation:
    """_build_invocation builds ToolInvocation with correct exitcode."""

    def test_build_invocation_no_errors(self) -> None:
        result = VisitorRunnerAdapter._build_invocation([], [])
        assert isinstance(result, ToolInvocation)
        assert result.exitcode == 0
        assert result.stdout == "[]"
        assert result.stderr == ""

    def test_build_invocation_with_errors(self) -> None:
        result = VisitorRunnerAdapter._build_invocation([], ["error1"])
        assert result.exitcode == 1
        assert result.stderr == "error1"

    def test_build_invocation_with_findings(self) -> None:
        data = [{"file": "a.php"}]
        result = VisitorRunnerAdapter._build_invocation(data, [])
        assert json.loads(result.stdout) == data


# ===========================================================================
# _collect_php_files()
# ===========================================================================

class TestCollectPhpFiles:
    """_collect_php_files collects *.php files, skipping vendor."""

    def test_collect_php_files_skips_vendor(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "foo.php").parent.mkdir(parents=True)
        (tmp_path / "src" / "foo.php").write_text("")
        (tmp_path / "vendor" / "bar.php").parent.mkdir(parents=True)
        (tmp_path / "vendor" / "bar.php").write_text("")
        files = VisitorRunnerAdapter._collect_php_files(tmp_path)
        names = [f.name for f in files]
        assert "foo.php" in names
        assert "bar.php" not in names

    def test_collect_php_files_empty_repo(self, tmp_path: Path) -> None:
        files = VisitorRunnerAdapter._collect_php_files(tmp_path)
        assert files == []

    def test_collect_php_files_nested(self, tmp_path: Path) -> None:
        (tmp_path / "a" / "b" / "c.php").parent.mkdir(parents=True)
        (tmp_path / "a" / "b" / "c.php").write_text("")
        files = VisitorRunnerAdapter._collect_php_files(tmp_path)
        assert len(files) == 1
        assert files[0].name == "c.php"


# ===========================================================================
# _parse_visitor_output()
# ===========================================================================

class TestParseVisitorOutput:
    """_parse_visitor_output parses JSON from visitor stdout."""

    def test_parse_empty(self) -> None:
        assert VisitorRunnerAdapter._parse_visitor_output("") == []

    def test_parse_whitespace_only(self) -> None:
        assert VisitorRunnerAdapter._parse_visitor_output("   \n  ") == []

    def test_parse_valid_json_array(self) -> None:
        data = [{"file": "a.php", "line": 1}]
        result = VisitorRunnerAdapter._parse_visitor_output(json.dumps(data))
        assert result == data

    def test_parse_invalid_json_returns_empty(self) -> None:
        assert VisitorRunnerAdapter._parse_visitor_output("not json at all") == []

    def test_parse_json_with_brackets_extractor(self) -> None:
        """Fallback: extract JSON array from surrounding text."""
        text = 'some warning\n[{"file":"a.php"}]'
        result = VisitorRunnerAdapter._parse_visitor_output(text)
        assert result == [{"file": "a.php"}]

    def test_parse_empty_brackets(self) -> None:
        result = VisitorRunnerAdapter._parse_visitor_output("[]")
        assert result == []


# ===========================================================================
# parse() — main mutation target
# ===========================================================================

class TestParse:
    """parse() delegates to _parse_visitor_output and _build_finding."""

    def test_parse_empty(self) -> None:
        findings = VisitorRunnerAdapter().parse("", "", 0)
        assert findings == []

    def test_parse_valid_json_array(self) -> None:
        data = [{"file": "a.php", "line": 10, "rule_id": "R1", "message": "msg"}]
        findings = VisitorRunnerAdapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        f = findings[0]
        assert isinstance(f, Finding)
        assert f.tool == "visitor-runner"
        assert f.layer == "L3A"
        assert f.language == "php"

    def test_parse_invalid_json_returns_empty(self) -> None:
        findings = VisitorRunnerAdapter().parse("garbage", "", 0)
        assert findings == []


# ===========================================================================
# name property
# ===========================================================================

class TestName:
    def test_name_property(self) -> None:
        adapter = VisitorRunnerAdapter()
        assert adapter.name == "visitor-runner"

    def test_name_type(self) -> None:
        assert isinstance(VisitorRunnerAdapter().name, str)


# ===========================================================================
# version()
# ===========================================================================

class TestVersion:
    def test_version_raises(self) -> None:
        adapter = VisitorRunnerAdapter()
        with pytest.raises(NotImplementedError):
            adapter.version(Path.cwd())
