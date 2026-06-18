"""Comprehensive tests for BanditAdapter — mutation-killing suite.

Targets: parse() with granular asserts on every Finding field.
Design: mutation testing / bandit_adapter coverage.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from harness_quality_gate.adapters.python.bandit_adapter import BanditAdapter
from harness_quality_gate.bootstrap import ToolNotAvailable
from harness_quality_gate.models import Finding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _adapter():
    return BanditAdapter()


# ---------------------------------------------------------------------------
# parse() — empty/invalid inputs
# ---------------------------------------------------------------------------


class TestParseEmptyAndInvalid:
    """Test parse with empty, invalid, or unexpected inputs."""

    def test_empty_stdout(self):
        """Empty stdout → no findings."""
        assert _adapter().parse("") == []
        assert _adapter().parse("   ") == []

    def test_invalid_json_yields_parse_error_finding(self):
        """Non-empty unparseable stdout must NOT be silently empty (F7).

        bandit 1.9 writes a rich progress bar to stdout before the JSON;
        a silent [] turned every L4 bandit run into a vacuous PASS.
        """
        findings = _adapter().parse("Working... ----- 100% 0:00:00\nnot json")
        assert len(findings) == 1
        f = findings[0]
        assert f.severity == "error"
        assert f.rule_id == "parse-error"
        assert f.tool == "bandit"
        assert f.layer == "L4"

    def test_json_not_dict(self):
        """JSON array instead of dict → no findings."""
        data = [
            {
                "filename": "src/x.py",
                "issue_id": "S101",
                "issue_severity": "HIGH",
                "issue_text": "Use hardcoded password",
                "line_number": 10,
            }
        ]
        assert _adapter().parse(json.dumps(data)) == []

    def test_json_dict_no_results(self):
        """JSON dict but no 'results' key → no findings."""
        assert _adapter().parse(json.dumps({"other": "data"})) == []

    def test_results_not_list(self):
        """'results' is not a list → no findings."""
        assert _adapter().parse(json.dumps({"results": {}})) == []


# ---------------------------------------------------------------------------
# parse() — single complete finding
# ---------------------------------------------------------------------------


class TestParseCompleteFinding:
    """Test with a complete bandit JSON entry covering all extraction paths."""

    def test_complete_finding_all_fields(self):
        """One complete finding → all fields populated correctly."""
        data = {
            "results": [
                {
                    "filename": "src/auth.py",
                    "issue_id": "S105",
                    "issue_severity": "HIGH",
                    "issue_text": "Hardcoded password detected",
                    "line_number": 42,
                    "cwe": {"id": "CWE-259", "link": "https://cwe.mitre.org"},
                }
            ]
        }
        findings = _adapter().parse(json.dumps(data))
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "src/auth.py"
        assert f.severity == "error"
        assert f.rule_id == "S105"
        assert f.message == "src/auth.py:42 [S105]: Hardcoded password detected"
        assert "S105" in f.message
        assert f.fix_hint == "Audit and fix S105 at src/auth.py:42"
        assert f.tool == "bandit"
        assert f.layer == "L4"
        assert f.language == "python"
        assert f.cwe == "CWE-259"


# ---------------------------------------------------------------------------
# parse() — severity mapping
# ---------------------------------------------------------------------------


class TestParseSeverityMapping:
    """Test severity mapping from raw bandit severity to internal."""

    def test_high_severity_maps_error(self):
        """HIGH → error."""
        findings = _adapter().parse(
            json.dumps({"results": [{
                "filename": "src/a.py",
                "issue_text": "msg",
                "issue_severity": "HIGH",
            }]})
        )
        assert findings[0].severity == "error"

    def test_medium_severity_maps_warning(self):
        """MEDIUM → warning."""
        findings = _adapter().parse(
            json.dumps({"results": [{
                "filename": "src/a.py",
                "issue_text": "msg",
                "issue_severity": "MEDIUM",
            }]})
        )
        assert findings[0].severity == "warning"

    def test_low_severity_maps_info(self):
        """LOW → info."""
        findings = _adapter().parse(
            json.dumps({"results": [{
                "filename": "src/a.py",
                "issue_text": "msg",
                "issue_severity": "LOW",
            }]})
        )
        assert findings[0].severity == "info"

    def test_unknown_severity_defaults_warning(self):
        """Unknown severity → default 'warning'."""
        findings = _adapter().parse(
            json.dumps({"results": [{
                "filename": "src/a.py",
                "issue_text": "msg",
                "issue_severity": "EXPERT",
            }]})
        )
        assert findings[0].severity == "warning"


# ---------------------------------------------------------------------------
# parse() — field extraction mutations (KILLS mutmut_1,2,9,20,21)
# ---------------------------------------------------------------------------


class TestParseFieldExtraction:
    """Test field extraction kills all field-access mutations.

    Mutmut_1: issue.get("filename", None) → None → node mutation
    Mutmut_2: issue.get("issue_id", None) → None → rule_id mutation
    Mutmut_9: detail message construction (or chain mutation)
    Mutmut_20,21: cwe extraction mutations
    """

    def test_filename_field_extraction(self):
        """Missing filename → node empty string, not None/XXXX."""
        findings = _adapter().parse(
            json.dumps({"results": [{
                "issue_id": "S101",
                "issue_text": "hardcoded password",
                "issue_severity": "HIGH",
                "line_number": 5,
            }]})
        )
        assert len(findings) == 1
        f = findings[0]
        assert f.node == ""
        assert f.rule_id == "S101"
        assert f.message == ":5 [S101]: hardcoded password"
        assert f.tool == "bandit"
        assert f.layer == "L4"
        assert f.language == "python"

    def test_issue_id_field_extraction(self):
        """Missing issue_id → rule_id='' (empty string)."""
        findings = _adapter().parse(
            json.dumps({"results": [{
                "filename": "src/b.py",
                "issue_text": "some issue",
                "issue_severity": "MEDIUM",
                "line_no": 10,
            }]})
        )
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == ""  # issue.get("issue_id") or "" → None or "" → ""
        assert f.node == "src/b.py"

    def test_issue_text_field_extraction(self):
        """Missing issue_text → message uses fallback format.

        Kills mutmut_20,21: get("issue_text"→None/XXXX) mutations.
        """
        findings = _adapter().parse(
            json.dumps({"results": [{
                "filename": "src/c.py",
                "issue_id": "S102",
                "issue_severity": "HIGH",
                "line_number": 99,
            }]})
        )
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "src/c.py"
        # When issue_text="" (falsy), message = detail = "src/c.py:99 [S102]: "
        assert f.node in f.message
        assert f.rule_id == "S102"

    def test_severity_raw_field_extraction(self):
        """Default issue_severity when missing → 'MEDIUM' as per code default.

        Kills mutmut: get("issue_severity"→XXXX) mutation.
        """
        findings = _adapter().parse(
            json.dumps({"results": [{
                "filename": "src/d.py",
                "issue_text": "no severity field",
            }]})
        )
        assert len(findings) == 1
        # Missing issue_severity → defaults to "MEDIUM" → severity="warning"
        assert findings[0].severity == "warning"


# ---------------------------------------------------------------------------
# parse() — CWE extraction mutations (KILLS mutmut_47,48,66,67)
# ---------------------------------------------------------------------------


class TestParseCwe:
    """Test CWE field extraction kills mutations on cwe dict/list handling.

    Mutmut_47: cwe.get("id"→None/XXXX) mutation
    Mutmut_48: cwe.get("link"→None/XXXX) mutation
    Mutmut_66,67: cwe string handling mutations
    """

    def test_cwe_string_value(self):
        """CWE as string → cwe=node value."""
        findings = _adapter().parse(
            json.dumps({"results": [{
                "filename": "src/e.py",
                "issue_text": "msg",
                "line_number": 1,
                "cwe": "CWE-79",
            }]})
        )
        f = findings[0]
        assert f.cwe == "CWE-79"

    def test_cwe_dict_id_and_link(self):
        """CWE as dict → cwe=id (or link if id missing)."""
        findings = _adapter().parse(
            json.dumps({"results": [{
                "filename": "src/f.py",
                "issue_text": "msg",
                "line_number": 1,
                "cwe": {"id": "CWE-476", "link": "https://cwe.mitre.org"},
            }]})
        )
        f = findings[0]
        assert f.cwe == "CWE-476"

    def test_cwe_dict_only_link(self):
        """CWE dict with only 'link' key → cwe=link."""
        findings = _adapter().parse(
            json.dumps({"results": [{
                "filename": "src/g.py",
                "issue_text": "msg",
                "line_number": 1,
                "cwe": {"link": "https://example.com"},
            }]})
        )
        f = findings[0]
        assert f.cwe == "https://example.com"

    def test_cwe_missing(self):
        """No cwe key → cwe empty string."""
        findings = _adapter().parse(
            json.dumps({"results": [{
                "filename": "src/h.py",
                "issue_text": "msg",
                "line_number": 1,
            }]})
        )
        f = findings[0]
        assert f.cwe == ""


# ---------------------------------------------------------------------------
# parse() — fix_hint mutation (KILLS mutmut on line 96)
# ---------------------------------------------------------------------------


class TestParseFixHint:
    """Test fix_hint construction kills mutation on that line."""

    def test_fix_hint_with_issue_id(self):
        """fix_hint contains issue_id at filename:line.

        Kills mutmut on fix hint construction.
        """
        findings = _adapter().parse(
            json.dumps({"results": [{
                "filename": "src/vuln.py",
                "issue_id": "S101",
                "issue_text": "hardcoded password",
                "issue_severity": "HIGH",
                "line_number": 20,
            }]})
        )
        f = findings[0]
        assert f.fix_hint == "Audit and fix S101 at src/vuln.py:20"

    def test_fix_hint_no_line_number(self):
        """fix_hint with zero line number."""
        findings = _adapter().parse(
            json.dumps({"results": [{
                "filename": "src/vuln.py",
                "issue_id": "S102",
                "issue_text": "no line",
                "line_number": 0,
            }]})
        )
        f = findings[0]
        assert f.fix_hint == "Audit and fix S102 at src/vuln.py:0"


# ---------------------------------------------------------------------------
# parse() — detailed message construction (KILLS mutmut_6,7,9)
# ---------------------------------------------------------------------------


class TestParseMessageConstruction:
    """Test detail/message string construction kills mutation survivors."""

    def test_message_format(self):
        """Message follows exact format: filepath:line [issue_id]: text."""
        findings = _adapter().parse(
            json.dumps({"results": [{
                "filename": "app/models.py",
                "issue_id": "S301",
                "issue_text": "pickle deserialization",
                "issue_severity": "HIGH",
                "line_number": 155,
            }]})
        )
        f = findings[0]
        assert f.message == "app/models.py:155 [S301]: pickle deserialization"

    def test_message_no_line_number(self):
        """Missing line number → still valid format."""
        findings = _adapter().parse(
            json.dumps({"results": [{
                "filename": "app/models.py",
                "issue_id": "S302",
                "issue_severity": "MEDIUM",
                "issue_text": "test msg",
            }]})
        )
        assert len(findings) == 1
        f = findings[0]
        # line_number = 0 (default) → detail="app/models.py:0 [S302]: test msg"
        assert f.message == "app/models.py:0 [S302]: test msg"


# ---------------------------------------------------------------------------
# parse() — multiple findings
# ---------------------------------------------------------------------------


class TestParseMultiple:
    """Test parsing multiple findings from bandit output."""

    def test_multiple_findings_all_fields(self):
        """Two findings → each with all fields correct."""
        data = {
            "results": [
                {
                    "filename": "src/web.py",
                    "issue_id": "S101",
                    "issue_severity": "HIGH",
                    "issue_text": "hardcoded pwd in web.py",
                    "line_number": 10,
                    "cwe": {"id": "CWE-259"},
                },
                {
                    "filename": "src/db.py",
                    "issue_id": "S311",
                    "issue_severity": "MEDIUM",
                    "issue_text": "pseudo-random generator",
                    "line_number": 45,
                    "cwe": "CWE-338",
                },
            ]
        }
        findings = _adapter().parse(json.dumps(data))
        assert len(findings) == 2

        f1, f2 = findings[0], findings[1]

        # First finding
        assert f1.severity == "error"
        assert f1.node == "src/web.py"
        assert f1.rule_id == "S101"
        assert f1.message == "src/web.py:10 [S101]: hardcoded pwd in web.py"
        assert f1.fix_hint == "Audit and fix S101 at src/web.py:10"
        assert f1.tool == "bandit"
        assert f1.layer == "L4"
        assert f1.language == "python"
        assert f1.cwe == "CWE-259"

        # Second finding
        assert f2.severity == "warning"
        assert f2.node == "src/db.py"
        assert f2.rule_id == "S311"
        assert f2.message == "src/db.py:45 [S311]: pseudo-random generator"
        assert f2.fix_hint == "Audit and fix S311 at src/db.py:45"
        assert f2.cwe == "CWE-338"

    def test_non_dict_issue_skipped(self):
        """Non-dict entry in issues → skipped (continue, not break)."""
        data = {
            "results": [
                "not a dict",
                None,
                {
                    "filename": "src/good.py",
                    "issue_text": "valid issue",
                    "issue_severity": "HIGH",
                    "line_number": 1,
                },
            ]
        }
        findings = _adapter().parse(json.dumps(data))
        assert len(findings) == 1
        assert findings[0].node == "src/good.py"


# ---------------------------------------------------------------------------
# version() and properties (KILLS remaining mutmut on version)
# ---------------------------------------------------------------------------


class TestVersion:
    """Test version method."""

    def test_version_binary_not_found(self):
        """Binary not found → RuntimeError."""
        with patch(
            "harness_quality_gate.adapters.python.bandit_adapter.resolve_tool",
            side_effect=ToolNotAvailable("bandit"),
        ):
            with pytest.raises(RuntimeError, match="bandit not found on PATH"):
                _adapter().version(Path("/tmp"))

    def test_version_returns_stdout(self):
        """Version returns stripped stdout."""
        mock_result = MagicMock(stdout="bandit 1.7.5\n")
        bandit_bin = "/usr/local/bin/bandit"
        adapter = _adapter()
        with patch(
            "harness_quality_gate.adapters.python.bandit_adapter.resolve_tool",
            return_value=Path(bandit_bin),
        ):
            with patch.object(BanditAdapter, "_run", return_value=mock_result) as mock_run:
                ver = adapter.version(Path("/tmp"))
        assert ver == "bandit 1.7.5"
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == [bandit_bin, "--version"]

    def test_version_empty_returns_unknown(self):
        """Empty stdout → 'unknown'."""
        mock_result = MagicMock(stdout="")
        adapter = _adapter()
        with patch(
            "harness_quality_gate.adapters.python.bandit_adapter.resolve_tool",
            return_value=Path("/usr/local/bin/bandit"),
        ):
            with patch.object(BanditAdapter, "_run", return_value=mock_result):
                ver = adapter.version(Path("/tmp"))
        assert ver == "unknown"

    def test_version_wiring_exact_call_args(self):
        """version() calls _run with exact binary + --version cmd + cwd + env.

        Kills mutmut survivors on version call args (env, cwd mutations).
        """
        mock_result = MagicMock(stdout="bandit 1.7.5\n")
        bandit_bin = "/usr/local/bin/bandit"
        adapter = _adapter()
        with patch(
            "harness_quality_gate.adapters.python.bandit_adapter.resolve_tool",
            return_value=Path(bandit_bin),
        ):
            with patch.object(BanditAdapter, "_run", return_value=mock_result) as mock_run:
                adapter.version(Path("/tmp/repo"), env={"BANDIT_ENV": "1"})
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == [bandit_bin, "--version"]
        assert mock_run.call_args.kwargs["env"] == {"BANDIT_ENV": "1"}

    def test_version_env_none_passed(self):
        """env=None passed to _run when not specified."""
        mock_result = MagicMock(stdout="bandit 1.7.5\n")
        adapter = _adapter()
        with patch(
            "harness_quality_gate.adapters.python.bandit_adapter.resolve_tool",
            return_value=Path("/usr/local/bin/bandit"),
        ):
            with patch.object(BanditAdapter, "_run", return_value=mock_result) as mock_run:
                adapter.version(Path("/tmp"))
        assert mock_run.call_args.kwargs["env"] is None


class TestProperties:
    """Test BanditAdapter properties."""

    def test_name_property(self):
        assert _adapter().name == "bandit"

    def test_name_class_attribute(self):
        assert _adapter()._name == "bandit"

    def test_name_property_full_finding(self):
        """Name property accessed during finding creation path."""
        findings = _adapter().parse(json.dumps({"results": [{
            "filename": "src/x.py",
            "issue_text": "test",
            "issue_severity": "MEDIUM",
        }]}))
        # Name verified through finding
        assert any(f.tool == "bandit" for f in findings)


class TestInvokeQuietFlag:
    """invoke() must pass -q so the progress bar stays out of stdout (F7)."""

    def test_cmd_includes_quiet_flag(self, tmp_path):
        from unittest.mock import MagicMock, patch
        adapter = _adapter()
        with (
            patch(
                "harness_quality_gate.adapters.python.bandit_adapter.resolve_tool",
                return_value=Path("/usr/bin/bandit"),
            ),
            patch.object(adapter, "_run", return_value=MagicMock()) as run,
        ):
            adapter.invoke(tmp_path, [])
        cmd = run.call_args.args[0]
        assert cmd[:5] == ["/usr/bin/bandit", "-r", "-q", "--format", "json"]


class TestParseErrorFindingExact:
    """Pin every field of the bandit parse-error finding (mutation killers)."""

    def test_every_field_exact(self):
        findings = _adapter().parse("Working... not json")
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "bandit"
        assert f.severity == "error"
        assert f.message == "bandit produced unparseable JSON output"
        assert f.fix_hint == ("Run bandit manually in the repo to inspect "
                              "the output (progress noise or crash).")
        assert f.tool == "bandit"
        assert f.layer == "L4"
        assert f.language == "python"
        assert f.rule_id == "parse-error"


# ---------------------------------------------------------------------------
# Phase 2: detect_source_dir usage
# ---------------------------------------------------------------------------


def test_bandit_invoke_uses_detect_source_dir_with_src(tmp_path: Path):
    """When src/ exists, bandit uses detect_source_dir('src').

    Phase 2 convergence: bandit detects the source dir instead of
    hardcoding 'src', enabling config-driven source directories.
    """
    src = tmp_path / "src"
    src.mkdir()

    mock_result = MagicMock()
    mock_result.stdout = "[]"
    mock_result.stderr = ""
    mock_result.returncode = 0

    with patch(
        "harness_quality_gate.adapters.python.bandit_adapter.resolve_tool",
        return_value=Path("/usr/bin/bandit"),
    ):
        with patch.object(BanditAdapter, "_run", return_value=mock_result) as mock_run:
            adapter = BanditAdapter()
            adapter.invoke(tmp_path, [])

    cmd = mock_run.call_args[0][0]
    # bandit command: binary, -r, -q, --format, json, TARGET
    assert "-r" in cmd
    assert "-q" in cmd
    assert "--format" in cmd
    # src/ is a scan target, tests/ should NOT be (exclude_tests=True)
    assert src.name in cmd
    assert "tests" not in cmd


def test_bandit_invoke_fallback_when_no_src(tmp_path: Path):
    """When no src/ or packages exist, bandit falls back to repo root.

    Phase 2 convergence: no source dir found → repo root as target.
    """
    mock_result = MagicMock()
    mock_result.stdout = "[]"
    mock_result.stderr = ""
    mock_result.returncode = 0

    with patch(
        "harness_quality_gate.adapters.python.bandit_adapter.resolve_tool",
        return_value=Path("/usr/bin/bandit"),
    ):
        with patch.object(BanditAdapter, "_run", return_value=mock_result) as mock_run:
            adapter = BanditAdapter()
            adapter.invoke(tmp_path, [])

    cmd = mock_run.call_args[0][0]
    # When no sources, tmp_path root is the target
    assert str(tmp_path) in cmd
