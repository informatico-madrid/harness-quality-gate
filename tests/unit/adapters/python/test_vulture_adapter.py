"""Comprehensive tests for VultureAdapter.

Covers:
  - name property — returns "vulture"
  - version() — binary not found (raises), binary found + _run, empty stdout→"unknown"
  - invoke() — not found→exitcode=3, correct command line, cwd/env/timeout wiring,
               extra args concatenation
  - parse() — empty output, non-string input, JSON decode error, non-list result,
              non-dict items, valid findings (minimal + with all fields), filepath cases,
              description/detail formatting, multiple findings

Design: Component Responsibilities / vulture_adapter
Targets: 96 surviving mutants across version/invoke/parse
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from harness_quality_gate.adapters.base import ToolAdapter, ToolInvocation
from harness_quality_gate.models import Finding
from harness_quality_gate.adapters.python.vulture_adapter import VultureAdapter


def _adapter() -> VultureAdapter:
    return VultureAdapter()


# ---------------------------------------------------------------------------
# name
# ---------------------------------------------------------------------------


def test_adapter_name() -> None:
    """name property returns 'vulture'."""
    assert _adapter().name == "vulture"


# ---------------------------------------------------------------------------
# version()
# ---------------------------------------------------------------------------


def test_version_binary_not_found_raises(tmp_path: Path) -> None:
    """shutil.which returns None → RuntimeError with 'vulture' in message."""
    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="vulture") as exc_info:
            _adapter().version(tmp_path)
    assert "vulture" in exc_info.value.args[0]
    assert "PATH" in exc_info.value.args[0]


def test_version_calls_shutil_which_with_literal_vulture(tmp_path: Path) -> None:
    """version() must call shutil.which('vulture') verbatim (kills mutmut_2: which(None))."""
    with patch("shutil.which", return_value="/usr/bin/vulture") as which_mock:
        with patch.object(
            ToolAdapter, "_run", return_value=MagicMock(stdout="vulture 2.7", stderr="", exitcode=0, duration_seconds=0.1)
        ):
            _adapter().version(tmp_path)
    which_mock.assert_called_once_with("vulture")


def test_version_calls_run_version_flag(tmp_path: Path) -> None:
    """Binary found → _run invoked with [binary, '--version']."""
    fake_bin = "/usr/bin/vulture"
    with patch("shutil.which", return_value=fake_bin):
        with patch.object(
            ToolAdapter, "_run", return_value=MagicMock(stdout="2.11.0")
        ) as mock_run:
            _adapter().version(tmp_path)

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == fake_bin
    assert "--version" in cmd
    assert mock_run.call_args[1]["cwd"] == tmp_path


def test_version_empty_output_returns_unknown(tmp_path: Path) -> None:
    """stdout='' → returns 'unknown'."""
    with patch("shutil.which", return_value="/usr/bin/vulture"):
        with patch.object(
            ToolAdapter, "_run", return_value=MagicMock(stdout="")
        ) as mock_run:
            result = _adapter().version(tmp_path)
    assert result == "unknown"


def test_version_whitespace_only_returns_unknown(tmp_path: Path) -> None:
    """stdout='  \\n  ' → returns 'unknown' (strip leaves empty)."""
    with patch("shutil.which", return_value="/usr/bin/vulture"):
        with patch.object(
            ToolAdapter, "_run", return_value=MagicMock(stdout="  \n  ")
        ) as mock_run:
            result = _adapter().version(tmp_path)
    assert result == "unknown"


def test_version_returns_stripped_output(tmp_path: Path) -> None:
    """Output with surrounding whitespace is stripped."""
    with patch("shutil.which", return_value="/usr/bin/vulture"):
        with patch.object(
            ToolAdapter, "_run", return_value=MagicMock(stdout="  2.11.0  ")
        ) as mock_run:
            result = _adapter().version(tmp_path)
    assert result == "2.11.0"
    assert result != ""


def test_version_forward_env(tmp_path: Path) -> None:
    """version() forwards env dict to _run."""
    with patch("shutil.which", return_value="/usr/bin/vulture"):
        with patch.object(
            ToolAdapter, "_run", return_value=MagicMock(stdout="2.11.0")
        ) as mock_run:
            _adapter().version(tmp_path, env={"VULTURE_CONFIG": "/cfg"})
    assert mock_run.call_args[1]["env"] == {"VULTURE_CONFIG": "/cfg"}


# ---------------------------------------------------------------------------
# invoke()
# ---------------------------------------------------------------------------


def test_invoke_binary_not_found(tmp_path: Path) -> None:
    """shutil.which returns None → ToolInvocation(stderr='vulture not found...', exitcode=3)."""
    with patch("shutil.which", return_value=None):
        result = _adapter().invoke(tmp_path, [])

    assert result.exitcode == 3
    assert result.stdout == ""
    assert "vulture" in result.stderr
    assert "PATH" in result.stderr


def test_invoke_binary_not_found_has_no_stderr_mutmut(tmp_path: Path) -> None:
    """invoke() stderr exactly 'vulture not found on PATH' (not mutated string)."""
    with patch("shutil.which", return_value=None):
        result = _adapter().invoke(tmp_path, [])
    assert result.stderr == "vulture not found on PATH"


def test_invoke_command_structure_no_extra_args(tmp_path: Path) -> None:
    """No extra args → cmd = [binary, '--format', 'json', str(repo)]."""
    fake_bin = "/usr/bin/vulture"
    with patch("shutil.which", return_value=fake_bin):
        with patch.object(
            ToolAdapter, "_run", return_value=_ok_invocation()
        ) as mock_run:
            _adapter().invoke(tmp_path, [])
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == fake_bin
    assert "--format" in cmd
    assert "json" in cmd
    assert str(tmp_path) in cmd


def test_invoke_command_structure_with_extra_args(tmp_path: Path) -> None:
    """Extra args appended after base command."""
    fake_bin = "/usr/bin/vulture"
    with patch("shutil.which", return_value=fake_bin):
        with patch.object(
            ToolAdapter, "_run", return_value=_ok_invocation()
        ) as mock_run:
            _adapter().invoke(tmp_path, ["--min-confidence", "80", "--ignore-decorators"])
    cmd = mock_run.call_args[0][0]
    assert "--min-confidence" in cmd
    assert "80" in cmd
    assert "--ignore-decorators" in cmd


def test_invoke_empty_args_no_extend(tmp_path: Path) -> None:
    """Empty args list → cmd has exactly 4 parts (not extended)."""
    fake_bin = "/usr/bin/vulture"
    with patch("shutil.which", return_value=fake_bin):
        with patch.object(
            ToolAdapter, "_run", return_value=_ok_invocation()
        ) as mock_run:
            _adapter().invoke(tmp_path, [])
    cmd = mock_run.call_args[0][0]
    # Should have exactly: binary, --format, json, repo
    assert len(cmd) == 4


def test_invoke_sets_cwd_env_timeout(tmp_path: Path) -> None:
    """invoke() forwards cwd, env, and timeout to _run."""
    fake_bin = "/usr/bin/vulture"
    with patch("shutil.which", return_value=fake_bin):
        with patch.object(
            ToolAdapter, "_run", return_value=_ok_invocation()
        ) as mock_run:
            _adapter().invoke(
                tmp_path, [], env={"CI": "1"}, timeout=120.0
            )
    assert mock_run.call_args[1]["cwd"] == tmp_path
    assert mock_run.call_args[1]["env"] == {"CI": "1"}
    assert mock_run.call_args[1]["timeout"] == 120.0


def test_invoke_default_timeout(tmp_path: Path) -> None:
    """Default timeout=300.0 forwarded to _run."""
    fake_bin = "/usr/bin/vulture"
    with patch("shutil.which", return_value=fake_bin):
        with patch.object(
            ToolAdapter, "_run", return_value=_ok_invocation()
        ) as mock_run:
            _adapter().invoke(tmp_path, [])
    assert mock_run.call_args[1]["timeout"] == 300.0


def test_invoke_passes_through_result(tmp_path: Path) -> None:
    """invoke() returns whatever _run returns."""
    fake_bin = "/usr/bin/vulture"
    mock_out = _ok_invocation(stdout='[{"name": "x", "type": "unused"}]')
    with patch("shutil.which", return_value=fake_bin):
        with patch.object(
            ToolAdapter, "_run", return_value=mock_out
        ) as mock_run:
            result = _adapter().invoke(tmp_path, [])
    assert result is mock_out


def test_invoke_not_found_exitcode_is_3(tmp_path: Path) -> None:
    """Binary not found: exitcode is exactly 3 (not 0/1/2)."""
    with patch("shutil.which", return_value=None):
        result = _adapter().invoke(tmp_path, [])
    assert result.exitcode == 3


# ---------------------------------------------------------------------------
# parse() — input validation edge cases
# ---------------------------------------------------------------------------

def test_parse_empty_string() -> None:
    """Empty stdout → empty findings."""
    result = _adapter().parse("")
    assert result == []


def test_parse_whitespace_only() -> None:
    """Whitespace-only stdout → empty findings."""
    result = _adapter().parse("   \n\t  ")
    assert result == []


def test_parse_invalid_json() -> None:
    """Non-JSON string → empty findings (json.JSONDecodeError caught)."""
    result = _adapter().parse("this is not json {{{")
    assert result == []


def test_parse_json_object_instead_of_list() -> None:
    """Valid JSON object (not list) → empty findings."""
    result = _adapter().parse('{"name": "foo"}')
    assert result == []


def test_parse_json_empty_list() -> None:
    """Valid JSON empty list → empty findings (not error)."""
    result = _adapter().parse("[]")
    assert result == []
    assert isinstance(result, list)


def test_parse_list_with_non_dict_item() -> None:
    """List containing non-dict items → skipped, returns empty findings."""
    result = _adapter().parse(json.dumps(["string_item", 42, None, True]))
    assert result == []


def test_parse_list_with_mixed_items() -> None:
    """List with mix of dicts and non-dicts → only dicts parsed."""
    raw = json.dumps([
        {"name": "valid_func", "type": "unused", "filename": "app.py", "line": 10},
        "string_item",
        {"name": "another", "type": "unused", "filename": "app.py", "line": 20},
    ])
    result = _adapter().parse(raw)
    assert len(result) == 2
    assert result[0].node == "app.py"
    assert result[0].message.startswith("app.py:10")
    assert result[0].tool == "vulture"


# ---------------------------------------------------------------------------
# parse() — valid findings from JSON
# ---------------------------------------------------------------------------

def test_parse_valid_finding_minimal() -> None:
    """Single finding with name and empty optional fields."""
    raw = json.dumps([{"name": "unused_var", "type": "unused"}])
    result = _adapter().parse(raw)
    assert len(result) == 1
    f = result[0]
    assert f.node == "unused_var"
    assert f.severity == "warning"
    assert f.message == "unused: unused_var"
    assert f.tool == "vulture"
    assert f.layer == "L4"
    assert f.language == "python"
    assert f.rule_id == "unused"


def test_parse_valid_finding_with_all_fields() -> None:
    """Finding with filename + line_no → detail = 'file:line — type: name'."""
    raw = json.dumps([{
        "name": "dead_code",
        "type": "unused",
        "filename": "src/main.py",
        "line": 42,
    }])
    result = _adapter().parse(raw)
    assert len(result) == 1
    f = result[0]
    assert f.node == "src/main.py"
    assert f.severity == "warning"
    assert "src/main.py:42" in f.message
    assert "unused: dead_code" in f.message
    assert "Remove unused unused 'dead_code' at src/main.py:42" in f.fix_hint
    assert f.tool == "vulture"


def test_parse_valid_finding_filename_no_line() -> None:
    """Line missing (0 or absent) → detail = 'file — type: name' (no :0)."""
    raw = json.dumps([{
        "name": "orphan_module",
        "type": "unused",
        "filename": "orphan.py",
        "line": 0,
    }])
    result = _adapter().parse(raw)
    assert len(result) == 1
    f = result[0]
    assert f.node == "orphan.py"
    # When line is 0 (falsy), detail uses filename only + — desc
    assert "orphan.py" in f.message
    assert "—" in f.message
    assert ":0" not in f.message


def test_parse_line_no_fallback_to_line() -> None:
    """'line_no' key used as fallback when 'line' absent."""
    raw = json.dumps([{
        "name": "dead_var",
        "type": "unused",
        "filename": "x.py",
        "line_no": 77,
    }])
    result = _adapter().parse(raw)
    assert len(result) == 1
    assert "77" in result[0].message


def test_parse_multiple_findings() -> None:
    """Multiple valid items → multiple findings in order."""
    raw = json.dumps([
        {"name": "func_a", "type": "unused", "filename": "a.py", "line": 5},
        {"name": "func_b", "type": "unused export", "filename": "b.py", "line": 10},
        {"name": "var_c", "type": "unused", "filename": "c.py", "line": 15},
    ])
    result = _adapter().parse(raw)
    assert len(result) == 3
    assert result[0].node == "a.py"
    assert result[0].message.startswith("a.py:5")
    assert result[1].node == "b.py"
    assert result[2].node == "c.py"


def test_parse_finding_fix_hint_format(tmp_path: Path) -> None:
    """fix_hint = "Remove unused {type.lower()} '{name}' at {filepath}:{line}". """
    raw = json.dumps([{
        "name": "garbage",
        "type": "Unused Function",
        "filename": "test.py",
        "line": 7,
    }])
    result = _adapter().parse(raw)
    assert len(result) == 1
    fix_hint = result[0].fix_hint
    assert "Remove unused" in fix_hint
    assert "unused function" in fix_hint   # lower()
    assert "garbage" in fix_hint
    assert "test.py:7" in fix_hint


def test_parse_type_used_in_description() -> None:
    """Description uses item type field."""
    raw = json.dumps([{
        "name": "x",
        "type": "Unused Import",
        "filename": "m.py",
        "line": 1,
    }])
    result = _adapter().parse(raw)
    assert "Unused Import: x" in result[0].message


# ---------------------------------------------------------------------------
# parse() — assert Finding field values precisely
# ---------------------------------------------------------------------------

def test_parse_finding_all_fields_set(tmp_path: Path) -> None:
    """Every field on the Finding dataclass is correctly set."""
    raw = json.dumps([{
        "name": "dead_code",
        "type": "unused",
        "filename": "src/dead.py",
        "line": 99,
    }])
    result = _adapter().parse(raw)
    f = result[0]

    # All fields present
    assert f.node == "src/dead.py"
    assert f.severity == "warning"
    assert "src/dead.py:99" in f.message
    assert "Remove unused unused" in f.fix_hint
    assert f.tool == "vulture"
    assert f.layer == "L4"
    assert f.language == "python"
    assert f.rule_id == "unused"
    # cve is None by default
    assert f.cve is None
    assert f.cwe == ""


def test_parse_empty_finding_list_is_empty_list_not_none() -> None:
    """parse() always returns a list (even when nothing to parse)."""
    for input_val in ["", "   ", "not json", "{}", "null", "123"]:
        result = _adapter().parse(input_val)
        assert result is not None
        assert isinstance(result, list)


def test_parse_return_type_is_list_of_finding() -> None:
    """Return type is list[Finding] — each element is a Finding."""
    raw = json.dumps([{"name": "x", "type": "unused"}])
    result = _adapter().parse(raw)
    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, Finding)


def test_parse_multiple_findings_all_correct() -> None:
    """All findings in a multi-item list have correct fields."""
    raw = json.dumps([
        {"name": "a", "type": "unused", "filename": "f1.py", "line": 1},
        {"name": "b", "type": "unused export", "filename": "f2.py", "line": 2},
    ])
    findings = _adapter().parse(raw)
    assert len(findings) == 2
    for f in findings:
        assert f.tool == "vulture"
        assert f.layer == "L4"
        assert f.language == "python"
        assert f.severity == "warning"
        assert f.rule_id == "unused"


def test_parse_no_assertion_hang_on_long_run(tmp_path: Path) -> None:
    """Parsing completes and returns findings deterministically on rerun (no stateful bug)."""
    raw = json.dumps([{"name": "deterministic", "type": "unused", "filename": "d.py", "line": 1}])
    r1 = _adapter().parse(raw)
    r2 = _adapter().parse(raw)
    assert len(r1) == len(r2)
    assert r1[0].node == r2[0].node
    assert r1[0].fix_hint == r2[0].fix_hint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok_invocation(stdout: str = "") -> ToolInvocation:
    return ToolInvocation(stdout=stdout, stderr="", exitcode=0, duration_seconds=0.1)
