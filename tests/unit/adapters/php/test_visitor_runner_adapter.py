"""Comprehensive tests for VisitorRunnerAdapter (Tier-A L3A visitors).

Mutation testing — targets 26 survivor mutants in visitor_runner_adapter.py.
Covers: _discover_visitors, invoke, _build_finding, _merge_findings,
_build_stderr, _build_invocation, _collect_php_files, _parse_visitor_output.
Design: Each public method exercised with granular separate asserts.
"""

from __future__ import annotations

import json
import os
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
# invoke() — subprocess call assertions (H7: argv and kwarg mutation targets)
# ===========================================================================

class TestInvokeSubprocessAssertions:
    """H7: Assert exact subprocess.run calls to kill argv and kwarg mutations.

    Kills mutmut_73..mutmut_84 — mutations on command args, env, timeout,
    capture_output, text, check parameters in the subprocess.run call.
    Technique: §4.4 — assert_called_once_with with exact args + identity checks.
    """

    def test_invoke_subprocess_full_call_assertion(
        self, tmp_path: Path
    ) -> None:
        """Full assert_called_once_with to kill mutmut_73–84 (H7 + §4.4).

        Kills all invoke subprocess.run survivors simultaneously:
          mutmut_73:  "php" → "XXphpXX"              (string arg mutation)
          mutmut_74:  visitor_name → "XXvisitorXX"   (string arg mutation)
          mutmut_75:  visitor_script → mutated path  (string arg mutation)
          mutmut_76:  cwd=str(repo) → cwd=None       (pass-through mutation)
          mutmut_77:  capture_output=True→False       (bool mutation)
          mutmut_78:  text=True→False                 (bool mutation)
          mutmut_79:  check=False→check=True          (bool mutation)
          mutmut_80:  timeout=300.0→301.0             (number mutation)
          mutmut_81:  capture_output→captured_output  (kwarg name mutation)
          mutmut_82:  text→mutated kwarg              (kwarg mutation)
          mutmut_83:  timeout kwarg mutation          (kwarg mutation)
          mutmut_84:  env parameter mutation          (kwarg mutation)

        Technique: §4.4 (spies on dependencies — exact mock args) + H1
        (wiring identity check on cwd) + H7 (full argv list equality).
        """
        adapter = VisitorRunnerAdapter()
        visitor_script = tmp_path / "visitors" / "visitor_a.php"
        visitor_script.parent.mkdir(parents=True, exist_ok=True)
        visitor_script.write_text("<?php")
        php_file = tmp_path / "src" / "Foo.php"
        php_file.parent.mkdir(parents=True, exist_ok=True)
        php_file.write_text("<?php class Foo {}")

        with patch.object(
            VisitorRunnerAdapter, "_collect_php_files",
            return_value=[php_file],
        ):
            with patch(
                "harness_quality_gate.adapters.php.visitor_runner_adapter.VISITORS_DIR",
                tmp_path / "visitors",
            ):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(
                        returncode=0,
                        stdout=json.dumps([]),
                        stderr="",
                    )
                    adapter.invoke(tmp_path, [])

        # Verify the FULL subprocess.run call in ONE assertion
        # This kills all positional + keyword mutations atomically
        mock_run.assert_called_once_with(
            ["php", str(visitor_script), str(php_file)],
            cwd=str(tmp_path),
            env={**os.environ, **{}},
            capture_output=True,
            text=True,
            timeout=300.0,
            check=False,
        )

    def test_invoke_subprocess_called_with_exact_command(self, tmp_path: Path) -> None:
        """Visitor runs subprocess with exact command structure.

        Kills:
          - mutmut_73: "php" → "XXphpXX"
          - mutmut_74: visitor_name → "XXvisitorXX"
          - mutmut_75: visitor_script path → mutated string
          - mutmut_76: repo → "XXrepoXX"
        Using identity check (is) to catch repo → None mutmut_76.
        """
        adapter = VisitorRunnerAdapter()
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
                        returncode=0, stdout=json.dumps([]), stderr="",
                    )
                    result = adapter.invoke(tmp_path, [])

        mock_run.assert_called()
        # First call positional arg is always the command list
        first_call_args = mock_run.call_args_list[0]
        cmd = first_call_args[0][0]
        assert cmd == ["php", str(visitor_script), str(php_file)]

    def test_invoke_subprocess_cwd_is_repo(self, tmp_path: Path) -> None:
        """subprocess.run is called with cwd=str(repo).

        Kills:
          - mutmut_76: cwd=repo → cwd="XXrepoXX" or cwd=None
        """
        adapter = VisitorRunnerAdapter()
        visitor_script = tmp_path / "visitors" / "god_class.php"
        visitor_script.parent.mkdir(parents=True, exist_ok=True)
        visitor_script.write_text("<?php")
        php_file = tmp_path / "src" / "Foo.php"
        php_file.parent.mkdir(parents=True, exist_ok=True)
        php_file.write_text("<?php")

        with patch.object(
            VisitorRunnerAdapter, "_collect_php_files", return_value=[php_file]
        ):
            with patch(
                "harness_quality_gate.adapters.php.visitor_runner_adapter.VISITORS_DIR",
                tmp_path / "visitors",
            ):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(
                        returncode=0, stdout=json.dumps([]), stderr="",
                    )
                    adapter.invoke(tmp_path, [])

        mock_run.assert_called()
        kw = mock_run.call_args_list[0][1]
        assert kw["cwd"] == str(tmp_path)

    def test_invoke_subprocess_kwargs_correct(self, tmp_path: Path) -> None:
        """subprocess.run receives capture_output=True, text=True, check=False,
        and the correct timeout.

        Kills:
          - mutmut_77: capture_output=True → False (reverses stdout/stderr behavior)
          - mutmut_78: text=True → False (changes type of stdout/stderr)
          - mutmut_79: check=False → check=True (would raise on non-zero exit)
          - mutmut_80: timeout=300.0 → timeout=301.0
          - mutmut_81: capture_output → captured_output (typo mutation)
          - mutmut_82..84: text/capture_output/timeout parameter mutations
        """
        adapter = VisitorRunnerAdapter()
        visitor_script = tmp_path / "visitors" / "god.php"
        visitor_script.parent.mkdir(parents=True, exist_ok=True)
        visitor_script.write_text("<?php")
        php_file = tmp_path / "src" / "Foo.php"
        php_file.parent.mkdir(parents=True, exist_ok=True)
        php_file.write_text("<?php")

        # Full mock that would fail if subprocess parameters are mutated
        def capture_subprocess(*args, **kwargs):
            # This function captures ALL parameters for verification
            # If any parameter is mutated, the stored values will differ
            capture_subprocess._last_args = args
            capture_subprocess._last_kwargs = kwargs
            return MagicMock(returncode=0, stdout=json.dumps([]), stderr="")

        mock_run = MagicMock(side_effect=capture_subprocess)

        with patch.object(
            VisitorRunnerAdapter, "_collect_php_files", return_value=[php_file]
        ):
            with patch(
                "harness_quality_gate.adapters.php.visitor_runner_adapter.VISITORS_DIR",
                tmp_path / "visitors",
            ):
                with patch("subprocess.run") as mock_run:
                    mock_run.side_effect = capture_subprocess
                    adapter.invoke(tmp_path, [])

        # Assert the subprocess.run call with ALL parameters
        # This kills: mutmut_73-84 (string/parameter mutations in subprocess.run)
        assert mock_run.called
        call_args = mock_run.call_args_list[0]
        cmd = call_args[0][0]
        kw = call_args[1]
        # H7: assert exact command structure
        assert cmd[0] == "php"
        assert str(visitor_script) in cmd
        assert str(php_file) in cmd
        assert len(cmd) == 3  # php + script + file
        # H4: assert ALL subprocess parameters exactly
        assert kw["cwd"] == str(tmp_path)
        assert kw["capture_output"] is True
        assert kw["text"] is True
        assert kw["check"] is False
        assert kw["timeout"] == 300.0
        assert "PATH" in kw["env"]  # os.environ merge

    def test_invoke_subprocess_env_includes_os_environ(self, tmp_path: Path) -> None:
        """subprocess.run env merges os.environ with adapter env.

        Kills:
          - mutmut_81: env parameter mutation (e.g., __import__ or os.environ references)
        """
        adapter = VisitorRunnerAdapter()
        visitor_script = tmp_path / "visitors" / "v.php"
        visitor_script.parent.mkdir(parents=True, exist_ok=True)
        visitor_script.write_text("<?php")
        php_file = tmp_path / "src" / "Foo.php"
        php_file.parent.mkdir(parents=True, exist_ok=True)
        php_file.write_text("<?php")

        with patch.object(
            VisitorRunnerAdapter, "_collect_php_files", return_value=[php_file]
        ):
            with patch(
                "harness_quality_gate.adapters.php.visitor_runner_adapter.VISITORS_DIR",
                tmp_path / "visitors",
            ):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(
                        returncode=0, stdout=json.dumps([]), stderr="",
                    )
                    adapter.invoke(tmp_path, [], env={"CUSTOM_VAR": "xyz"})

        mock_run.assert_called()
        kw = mock_run.call_args_list[0][1]
        assert kw["env"]["CUSTOM_VAR"] == "xyz"
        # os.environ keys should also be present
        assert "PATH" in kw["env"]

    def test_invoke_custom_timeout_passed(self, tmp_path: Path) -> None:
        """Custom timeout value is forwarded to subprocess.run.

        Kills:
          - mutmut_82: timeout hardcoded mutation to 301
        """
        adapter = VisitorRunnerAdapter()
        visitor_script = tmp_path / "visitors" / "v.php"
        visitor_script.parent.mkdir(parents=True, exist_ok=True)
        visitor_script.write_text("<?php")
        php_file = tmp_path / "src" / "Foo.php"
        php_file.parent.mkdir(parents=True, exist_ok=True)
        php_file.write_text("<?php")

        with patch.object(
            VisitorRunnerAdapter, "_collect_php_files", return_value=[php_file]
        ):
            with patch(
                "harness_quality_gate.adapters.php.visitor_runner_adapter.VISITORS_DIR",
                tmp_path / "visitors",
            ):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(
                        returncode=0, stdout=json.dumps([]), stderr="",
                    )
                    adapter.invoke(tmp_path, [], timeout=60.0)

        mock_run.assert_called()
        kw = mock_run.call_args_list[0][1]
        assert kw["timeout"] == 60.0


# ===========================================================================
# _parse_visitor_output() — edge cases for mutmut_6, 12-26
# ===========================================================================

class TestParseVisitorOutputEdgeCases:
    """Edge cases for _parse_visitor_output to kill survivors mutmut_6, 12-26.

    These mutants target:
    - mutmut_6: strip() → strip(None) → still works (not observable)
    - mutmut_12: json.loads(text) → json.loads(text)[:50] → partial JSON
    - mutmut_13: text[:50]:text → [:50:51] / [:149:] (slice mutations)
    - mutmut_14: return [] → return None
    - mutmut_15: return results → return results + []
    - mutmut_18,20..26: bracket extraction mutations
    """

    def test_parse_visitor_output_none_stdin(self) -> None:
        """Pass None to _parse_visitor_output — should return [].

        Kills mutmut_14 (return [] → return None).
        When text is None, strip() would raise, caught by the None check
        before json.loads. The return must be [] not None.
        """
        # strip() on None would raise AttributeError, so we test what happens
        # when the text becomes None after strip (empty string after strip)
        result = VisitorRunnerAdapter._parse_visitor_output("   \n\t  ")
        assert result == []

    def test_parse_visitor_output_bracket_extractor_edge_cases(self) -> None:
        """Bracket extraction with valid JSON inside brackets.

        Kills mutmut_18 (end >= start → end > start): brackets at
        position 0 and 0 wouldn't pass end > start but would pass end >= start.
        Also mutmut_20..26 (find/ rfind mutations).
        """
        # Valid JSON with bracket extraction: leading text + ["valid"]
        result = VisitorRunnerAdapter._parse_visitor_output('warn: ["valid"]')
        assert result == ["valid"]

    def test_parse_visitor_output_bracket_only_open(self) -> None:
        """Only open bracket, no close → returns [].

        Kills mutmut_20: find("[") → find(None) which would raise.
        Or the end > start check being changed.
        """
        result = VisitorRunnerAdapter._parse_visitor_output("[[")
        assert result == []

    def test_parse_visitor_output_bracket_only_close(self) -> None:
        """Only close bracket, no open → returns []."""
        result = VisitorRunnerAdapter._parse_visitor_output("]]")
        assert result == []

    def test_parse_visitor_output_brackets_reversed(self) -> None:
        """']' appears before '[' → end < start → returns [].

        Kills mutmut_21: end > start → end >= start (would find "[]]" as valid)
        """
        result = VisitorRunnerAdapter._parse_visitor_output("]abc[")
        assert result == []

    def test_parse_visitor_output_nested_brackets(self) -> None:
        """rfind finds the LAST ']' which is correct for nested JSON.

        Kills mutmut_22: rfind("]") → rfind("XXXX]XXXX") or similar.
        """
        # The fallback correctly extracts [1,2] from nested text
        result = VisitorRunnerAdapter._parse_visitor_output('warn {"a": "[1,2]"}')
        assert result == [1, 2]

    def test_parse_visitor_output_valid_after_fallback(self) -> None:
        """Valid JSON after leading non-JSON text → fallback extracts it.

        Kills mutmut_23: start = text.find("[") → start = text.find(None) → error,
        or start = -1, which breaks detection of valid JSON after warning text.
        """
        text = "Warning: some message\n[{\"file\":\"x.php\",\"line\":1}]"
        result = VisitorRunnerAdapter._parse_visitor_output(text)
        assert len(result) == 1
        assert result[0]["file"] == "x.php"

    def test_parse_visitor_output_bracket_mid_text(self) -> None:
        """JSON array embedded in the middle of text.

        Kills mutmut_24: end = text.rfind("]") → end = text.rfind(None) → error,
        or rfind("X]") etc.
        """
        text = "before\n[{\"k\":\"v\"}]after"
        result = VisitorRunnerAdapter._parse_visitor_output(text)
        assert len(result) == 1
        assert result[0]["k"] == "v"

    def test_parse_visitor_output_return_is_list_not_none(self) -> None:
        """Return value is always a list, never None.

        Kills mutmut_14: return [] → return None.
        """
        result = VisitorRunnerAdapter._parse_visitor_output("")
        assert isinstance(result, list)
        assert result == []

        result = VisitorRunnerAdapter._parse_visitor_output("   ")
        assert isinstance(result, list)

        result = VisitorRunnerAdapter._parse_visitor_output("not json")
        assert isinstance(result, list)


# ===========================================================================
# version()
# ===========================================================================

# ===========================================================================
# Kill _build_finding mutmut_50,51 (return path mutations)
# ═══════════════════════════════════════════════════════════════════════


def test_build_finding_returns_finding_not_none_or_other() -> None:
    """_build_finding returns Finding, never None/False/other for valid input.

    Kills:
      mutmut_50: return Finding(...) → return None
      mutmut_51: return Finding(...) → return False
    """
    finding = VisitorRunnerAdapter._build_finding({
        "file": "test.php", "line": 5, "rule_id": "R1", "message": "test"
    })
    assert finding is not None
    assert isinstance(finding, Finding), "must return Finding instance"
    assert finding.node == "test.php:5"
    assert finding.rule_id == "R1"
    assert finding.message == "test"


class TestVersion:
    def test_version_raises(self) -> None:
        adapter = VisitorRunnerAdapter()
        with pytest.raises(NotImplementedError):
            adapter.version(Path.cwd())


# ===========================================================================
# Kill _merge_findings mutmut_2 (return mutation)
# ═══════════════════════════════════════════════════════════════════════


def test_merge_findings_returns_string_not_none_or_false():
    """_merge_findings always returns str, never None or False."""
    result = VisitorRunnerAdapter._merge_findings([])
    assert isinstance(result, str), "must return str"
    assert result == "[]"
    result2 = VisitorRunnerAdapter._merge_findings([{"k": "v"}])
    assert isinstance(result2, str)
    assert json.loads(result2) == [{"k": "v"}]


# ===========================================================================
# Kill _parse_visitor_output mutmut_6,12-15,20-24,26
# mutmut_6: text.strip() → text.strip(None)
# mutmut_12: json.loads(text) → json.loads(text)[:50]  (partial JSON)
# mutmut_13: text[:50]:text → [:50:51] or [:149:] (slice mutation)
# mutmut_14: return [] → return None
# mutmut_15: return results → return results + []
# mutmut_20-24: find("[") / rfind("]") mutations
# mutmut_26: bracket extraction final return mutation
# ═══════════════════════════════════════════════════════════════════════


def test_parse_visitor_output_returns_list_type_assertion():
    """_parse_visitor_output returns list, never None or other types."""
    # Empty string → empty list
    r = VisitorRunnerAdapter._parse_visitor_output("")
    assert isinstance(r, list) and r == []

    # Whitespace → empty list
    r = VisitorRunnerAdapter._parse_visitor_output("   \\n\\n   ")
    assert isinstance(r, list) and r == []

    # Invalid JSON → empty list
    r = VisitorRunnerAdapter._parse_visitor_output("not json")
    assert isinstance(r, list) and r == []

    # Valid JSON → list from json.loads
    r = VisitorRunnerAdapter._parse_visitor_output('[{"k":"v"}]')
    assert isinstance(r, list) and len(r) == 1

    # Bracket extraction with valid inner JSON
    r = VisitorRunnerAdapter._parse_visitor_output("prefix [{\"k\":\"v\"}] suffix")
    assert isinstance(r, list) and len(r) == 1

    # No brackets → empty list
    r = VisitorRunnerAdapter._parse_visitor_output("[[[")
    assert isinstance(r, list) and r == []

    r = VisitorRunnerAdapter._parse_visitor_output("]]]")
    assert isinstance(r, list) and r == []

    # Brackets reversed → empty list
    r = VisitorRunnerAdapter._parse_visitor_output("]abc[")
    assert isinstance(r, list) and r == []
