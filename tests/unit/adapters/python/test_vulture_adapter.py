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

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.base import ToolAdapter, ToolInvocation
from harness_quality_gate.bootstrap import ToolNotAvailable
from harness_quality_gate.models import Finding
from harness_quality_gate.adapters.python.vulture_adapter import VultureAdapter


def _adapter() -> VultureAdapter:
    return VultureAdapter()


def _ok_invocation(stdout: str = "") -> ToolInvocation:
    return ToolInvocation(stdout=stdout, stderr="", exitcode=0, duration_seconds=0.1)


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
    """resolve_tool raises ToolNotAvailable → RuntimeError."""
    with patch(
        "harness_quality_gate.adapters.python.vulture_adapter.resolve_tool",
        side_effect=ToolNotAvailable("vulture"),
    ):
        with pytest.raises(RuntimeError, match="vulture") as exc_info:
            _adapter().version(tmp_path)
    assert "vulture" in exc_info.value.args[0]
    assert "PATH" in exc_info.value.args[0]


def test_version_calls_shutil_which_with_literal_vulture(tmp_path: Path) -> None:
    """resolve_tool('vulture', path) verbatim (kills mutmut_2: resolve(None, path))."""
    with patch(
        "harness_quality_gate.adapters.python.vulture_adapter.resolve_tool",
        return_value=Path("/usr/bin/vulture"),
    ) as resolve_mock:
        with patch.object(
            ToolAdapter, "_run", return_value=MagicMock(stdout="vulture 2.7", stderr="", exitcode=0, duration_seconds=0.1)
        ):
            _adapter().version(tmp_path)
    resolve_mock.assert_called_once_with("vulture", tmp_path)


def test_version_calls_run_version_flag(tmp_path: Path) -> None:
    """Binary found → _run invoked with [binary, '--version']."""
    fake_bin = "/usr/bin/vulture"
    with patch("harness_quality_gate.adapters.python.vulture_adapter.resolve_tool", return_value=Path(fake_bin)):
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
    with patch("harness_quality_gate.adapters.python.vulture_adapter.resolve_tool", return_value=Path("/usr/bin/vulture")):
        with patch.object(
            ToolAdapter, "_run", return_value=MagicMock(stdout="")
        ) as mock_run:
            result = _adapter().version(tmp_path)
    assert result == "unknown"


def test_version_whitespace_only_returns_unknown(tmp_path: Path) -> None:
    """stdout='  \\n  ' → returns 'unknown' (strip leaves empty)."""
    with patch("harness_quality_gate.adapters.python.vulture_adapter.resolve_tool", return_value=Path("/usr/bin/vulture")):
        with patch.object(
            ToolAdapter, "_run", return_value=MagicMock(stdout="  \n  ")
        ) as mock_run:
            result = _adapter().version(tmp_path)
    assert result == "unknown"


def test_version_returns_stripped_output(tmp_path: Path) -> None:
    """Output with surrounding whitespace is stripped."""
    with patch("harness_quality_gate.adapters.python.vulture_adapter.resolve_tool", return_value=Path("/usr/bin/vulture")):
        with patch.object(
            ToolAdapter, "_run", return_value=MagicMock(stdout="  2.11.0  ")
        ) as mock_run:
            result = _adapter().version(tmp_path)
    assert result == "2.11.0"
    assert result != ""


def test_version_forward_env(tmp_path: Path) -> None:
    """version() forwards env dict to _run."""
    with patch("harness_quality_gate.adapters.python.vulture_adapter.resolve_tool", return_value=Path("/usr/bin/vulture")):
        with patch.object(
            ToolAdapter, "_run", return_value=MagicMock(stdout="2.11.0")
        ) as mock_run:
            _adapter().version(tmp_path, env={"VULTURE_CONFIG": "/cfg"})
    assert mock_run.call_args[1]["env"] == {"VULTURE_CONFIG": "/cfg"}


# ---------------------------------------------------------------------------
# invoke()
# ---------------------------------------------------------------------------


def test_invoke_binary_not_found(tmp_path: Path) -> None:
    """resolve_tool raises ToolNotAvailable → ToolInvocation with stderr."""
    with patch("harness_quality_gate.adapters.python.vulture_adapter.resolve_tool", side_effect=ToolNotAvailable("vulture")):
        result = _adapter().invoke(tmp_path, [])

    assert result.exitcode == 3
    assert result.stdout == ""
    assert "vulture" in result.stderr
    assert "PATH" in result.stderr


def test_invoke_binary_not_found_has_no_stderr_mutmut(tmp_path: Path) -> None:
    """invoke() stderr exactly 'vulture not found on PATH' (not mutated string)."""
    with patch("harness_quality_gate.adapters.python.vulture_adapter.resolve_tool", side_effect=ToolNotAvailable("vulture")):
        result = _adapter().invoke(tmp_path, [])
    assert result.stderr == "vulture not found on PATH or .venv"


def test_invoke_command_structure_no_extra_args(tmp_path: Path) -> None:
    """No extra args → cmd = [binary, str(repo)] (vulture has no JSON mode)."""
    fake_bin = "/usr/bin/vulture"
    with patch("harness_quality_gate.adapters.python.vulture_adapter.resolve_tool", return_value=Path(fake_bin)):
        with patch.object(
            ToolAdapter, "_run", return_value=_ok_invocation()
        ) as mock_run:
            _adapter().invoke(tmp_path, [])
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == fake_bin
    assert "--format" not in cmd  # nonexistent flag caused usage error (F8)
    assert str(tmp_path) in cmd


def test_invoke_command_structure_with_extra_args(tmp_path: Path) -> None:
    """Extra args appended after base command."""
    fake_bin = "/usr/bin/vulture"
    with patch("harness_quality_gate.adapters.python.vulture_adapter.resolve_tool", return_value=Path(fake_bin)):
        with patch.object(
            ToolAdapter, "_run", return_value=_ok_invocation()
        ) as mock_run:
            _adapter().invoke(tmp_path, ["--min-confidence", "80", "--ignore-decorators"])
    cmd = mock_run.call_args[0][0]
    assert "--min-confidence" in cmd
    assert "80" in cmd
    assert "--ignore-decorators" in cmd


def test_invoke_empty_args_no_extend(tmp_path: Path) -> None:
    """Empty args list → cmd has exactly 2 parts (binary + fallback target)."""
    fake_bin = "/usr/bin/vulture"
    with patch("harness_quality_gate.adapters.python.vulture_adapter.resolve_tool", return_value=Path(fake_bin)):
        with patch.object(
            ToolAdapter, "_run", return_value=_ok_invocation()
        ) as mock_run:
            _adapter().invoke(tmp_path, [])
    cmd = mock_run.call_args[0][0]
    # Should have exactly: binary, repo (empty tmp repo → root fallback)
    assert cmd == [fake_bin, str(tmp_path)]


def test_invoke_sets_cwd_env_timeout(tmp_path: Path) -> None:
    """invoke() forwards cwd, env, and timeout to _run."""
    fake_bin = "/usr/bin/vulture"
    with patch("harness_quality_gate.adapters.python.vulture_adapter.resolve_tool", return_value=Path(fake_bin)):
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
    with patch("harness_quality_gate.adapters.python.vulture_adapter.resolve_tool", return_value=Path(fake_bin)):
        with patch.object(
            ToolAdapter, "_run", return_value=_ok_invocation()
        ) as mock_run:
            _adapter().invoke(tmp_path, [])
    assert mock_run.call_args[1]["timeout"] == 300.0


def test_invoke_passes_through_result(tmp_path: Path) -> None:
    """invoke() returns whatever _run returns."""
    fake_bin = "/usr/bin/vulture"
    mock_out = _ok_invocation(stdout='[{"name": "x", "type": "unused"}]')
    with patch("harness_quality_gate.adapters.python.vulture_adapter.resolve_tool", return_value=Path(fake_bin)):
        with patch.object(
            ToolAdapter, "_run", return_value=mock_out
        ) as mock_run:
            result = _adapter().invoke(tmp_path, [])
    assert result is mock_out


def test_invoke_not_found_exitcode_is_3(tmp_path: Path) -> None:
    """Binary not found: exitcode is exactly 3 (not 0/1/2)."""
    with patch("harness_quality_gate.adapters.python.vulture_adapter.resolve_tool", side_effect=ToolNotAvailable("vulture")):
        result = _adapter().invoke(tmp_path, [])
    assert result.exitcode == 3


# parse() — real vulture text output (self-eval F8)
# ---------------------------------------------------------------------------
#
# vulture has no JSON output mode; it prints one finding per line:
#   path.py:12: unused function 'helper' (60% confidence)
# The old parse expected JSON that the tool never emits -> L4 was vacuous.

VULTURE_TEXT = """\
src/app.py:12: unused function 'helper' (60% confidence)
src/app.py:30: unused variable 'tmp' (100% confidence)
src/models.py:4: unused import 'os' (90% confidence)
"""


def test_parse_empty_string() -> None:
    """Empty stdout → empty findings (no dead code found)."""
    assert _adapter().parse("") == []


def test_parse_whitespace_only() -> None:
    """Whitespace-only stdout → empty findings."""
    assert _adapter().parse("   \n  ") == []


def test_parse_real_text_single_finding_exact_fields() -> None:
    """One real vulture line → one Finding with exact field mapping."""
    findings = _adapter().parse("src/app.py:12: unused function 'helper' (60% confidence)")
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "src/app.py"
    assert f.message == "src/app.py:12 — unused function 'helper'"
    assert f.severity == "warning"
    assert f.tool == "vulture"
    assert f.layer == "L4"
    assert f.language == "python"
    assert f.rule_id == "dead-code"
    assert f.fix_hint == "Remove dead code at src/app.py:12: unused function 'helper'"


def test_parse_real_text_multiple_findings() -> None:
    """Three real lines → three findings in order."""
    findings = _adapter().parse(VULTURE_TEXT)
    assert len(findings) == 3
    assert findings[0].node == "src/app.py"
    assert findings[1].message == "src/app.py:30 — unused variable 'tmp'"
    assert findings[2].node == "src/models.py"
    for f in findings:
        assert f.severity == "warning"
        assert f.rule_id == "dead-code"


def test_parse_unreachable_code_line() -> None:
    """Non-'unused' messages (e.g. unreachable code) are also captured."""
    findings = _adapter().parse(
        "src/app.py:7: unreachable code after 'return' (100% confidence)"
    )
    assert len(findings) == 1
    assert findings[0].message == "src/app.py:7 — unreachable code after 'return'"


def test_parse_garbage_output_yields_parse_error_finding() -> None:
    """Non-empty stdout with no parseable lines must NOT be silently empty.

    A silent [] here hides real findings (the bug this test pins): the
    adapter must surface an error finding instead.
    """
    findings = _adapter().parse("usage: vulture [options] [PATH ...]\nboom")
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == "error"
    assert f.rule_id == "parse-error"
    assert f.tool == "vulture"


def test_parse_mixed_lines_keeps_matches_only() -> None:
    """Valid lines among noise are kept; no parse-error when something matched."""
    out = "some banner\nsrc/app.py:12: unused function 'helper' (60% confidence)\n"
    findings = _adapter().parse(out)
    assert len(findings) == 1
    assert findings[0].rule_id == "dead-code"


def test_parse_return_type_is_list_of_finding() -> None:
    """Return type is list[Finding] — each element is a Finding."""
    result = _adapter().parse(VULTURE_TEXT)
    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, Finding)


def test_parse_deterministic_on_rerun() -> None:
    """Parsing is stateless — identical results on rerun."""
    r1 = _adapter().parse(VULTURE_TEXT)
    r2 = _adapter().parse(VULTURE_TEXT)
    assert [f.message for f in r1] == [f.message for f in r2]


def test_parse_error_finding_every_field_exact() -> None:
    """Pin every field of the parse-error finding (mutation killers)."""
    findings = _adapter().parse("usage: vulture [options] [PATH ...]")
    assert len(findings) == 1
    f = findings[0]
    assert f.node == "vulture"
    assert f.severity == "error"
    assert f.message == "vulture produced output with no parseable findings"
    assert f.fix_hint == ("Run vulture manually in the repo to inspect "
                          "the output (usage error or format drift).")
    assert f.tool == "vulture"
    assert f.layer == "L4"
    assert f.language == "python"
    assert f.rule_id == "parse-error"


def test_parse_trailing_whitespace_stripped_before_match() -> None:
    """rstrip() not lstrip() — trailing whitespace stripped before regex match.

    Kills mutmut_5: rstrip → lstrip. With lstrip, trailing whitespace
    remains and the regex $ anchor fails to match, yielding zero findings.
    """
    findings = _adapter().parse(
        "src/app.py:12: unused function 'x' (60% confidence)   \t\t"
    )
    assert len(findings) == 1
    assert findings[0].node == "src/app.py"
    assert findings[0].rule_id == "dead-code"
