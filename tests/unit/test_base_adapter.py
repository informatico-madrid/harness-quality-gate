"""Unit tests for harness_quality_gate/adapters/base.py.

Specifically targets `ToolAdapter._run` to kill the mutmut mutations on
subprocess.run kwargs (cmd, cwd, env, capture_output, text, timeout).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.base import ToolAdapter


def _ok(stdout: str = "", stderr: str = "", returncode: int = 0) -> MagicMock:
    result = MagicMock(spec=subprocess.CompletedProcess)
    result.stdout = stdout
    result.stderr = stderr
    result.returncode = returncode
    return result


def test_run_calls_subprocess_run_with_cmd() -> None:
    """Kill cmd=None, cmd→... mutations: cmd arg must be passed verbatim to subprocess.run."""
    fake_result = _ok(stdout="hi")
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        ToolAdapter._run(["echo", "hi"], cwd=Path("/tmp"))
    assert mock_run.called
    # cmd is first positional arg
    assert mock_run.call_args.args[0] == ["echo", "hi"]


def test_run_cwd_str_conversion() -> None:
    """Kill cwd=None, cwd=... mutations: cwd must be converted to str when not None."""
    fake_result = _ok()
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        ToolAdapter._run(["ls"], cwd=Path("/tmp"))
    assert mock_run.call_args.kwargs["cwd"] == "/tmp"


def test_run_cwd_none_when_path_is_none() -> None:
    """When cwd is None, str(cwd) would be 'None'; we want None via ternary."""
    fake_result = _ok()
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        ToolAdapter._run(["ls"], cwd=None)
    assert mock_run.call_args.kwargs["cwd"] is None


def test_run_env_merges_with_os_environ() -> None:
    """Kill env=merged_env mutations: env must contain os.environ + extras."""
    fake_result = _ok()
    with (
        patch("subprocess.run", return_value=fake_result) as mock_run,
        patch.dict("os.environ", {"FOO": "bar"}, clear=False),
    ):
        ToolAdapter._run(["env"], env={"EXTRA": "value"})
    assert mock_run.call_args.kwargs["env"]["FOO"] == "bar"
    assert mock_run.call_args.kwargs["env"]["EXTRA"] == "value"


def test_run_capture_output_true() -> None:
    """Kill capture_output=False mutation."""
    fake_result = _ok()
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        ToolAdapter._run(["ls"], cwd=Path("/tmp"))
    assert mock_run.call_args.kwargs["capture_output"] is True


def test_run_text_true() -> None:
    """Kill text=False mutation."""
    fake_result = _ok()
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        ToolAdapter._run(["ls"], cwd=Path("/tmp"))
    assert mock_run.call_args.kwargs["text"] is True


def test_run_timeout_passed() -> None:
    """Kill timeout=None, timeout=0 mutations: timeout must be the configured value."""
    fake_result = _ok()
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        ToolAdapter._run(["ls"], cwd=Path("/tmp"), timeout=42.0)
    assert mock_run.call_args.kwargs["timeout"] == 42.0


def test_run_returns_tool_invocation() -> None:
    """Must return a ToolInvocation with stdout/stderr/exitcode/duration_seconds."""
    from harness_quality_gate.adapters.base import ToolInvocation

    fake_result = _ok(stdout="output", returncode=0)
    with patch("subprocess.run", return_value=fake_result):
        result = ToolAdapter._run(["ls"], cwd=Path("/tmp"))
    assert isinstance(result, ToolInvocation)
    assert result.stdout == "output"
    assert result.exitcode == 0


def test_run_timeout_raises_runtime_error() -> None:
    """When subprocess.run raises TimeoutExpired, _run re-raises as RuntimeError
    so callers can classify as infra_error (AC5/NFR-8a: timeout is infra not quality)."""
    import re

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ls", 30)):
        with pytest.raises(RuntimeError, match=r"timed out.*timeout=30.*cwd=/tmp"):
            ToolAdapter._run(["ls"], cwd=Path("/tmp"), timeout=30)


def test_run_duration_rounded_to_3_decimals() -> None:
    """Kill round(x, 3)→round(x, 4) mutation: duration_seconds must be 3-decimal float."""
    from harness_quality_gate.adapters.base import ToolInvocation

    fake_result = _ok(stdout="output", returncode=0)
    with patch("subprocess.run", return_value=fake_result):
        result = ToolAdapter._run(["ls"], cwd=Path("/tmp"))
    assert isinstance(result, ToolInvocation)
    # duration_seconds should be a float (round to 3 decimals)
    assert isinstance(result.duration_seconds, float)


def test_run_exact_invocation_with_fixed_clock() -> None:
    """Pin the full ToolInvocation with a controlled clock: kills the round
    variants (None / round(3) / kwarg removal) and the stderr passthrough."""
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock, patch

    from harness_quality_gate.adapters.base import ToolAdapter, ToolInvocation

    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t1 = t0 + timedelta(seconds=1.23456)
    completed = MagicMock(stdout="OUT", stderr="ERR", returncode=7)
    fake_dt = MagicMock()
    fake_dt.now.side_effect = [t0, t1]
    with (
        patch("harness_quality_gate.adapters.base.subprocess.run", return_value=completed) as run,
        patch("harness_quality_gate.adapters.base.datetime", fake_dt),
    ):
        result = ToolAdapter._run(["tool", "--x"], timeout=12.5)
    assert result == ToolInvocation(
        stdout="OUT", stderr="ERR", exitcode=7, duration_seconds=1.235,
    )
    kwargs = run.call_args.kwargs
    assert kwargs["timeout"] == 12.5
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True


def test_run_relies_on_subprocess_check_default() -> None:
    """_run does not pass check= at all — subprocess.run defaults to False
    (the redundant explicit kwarg was removed as dead code)."""
    fake_result = _ok()
    with patch(
        "harness_quality_gate.adapters.base.subprocess.run", return_value=fake_result,
    ) as mock_run:
        ToolAdapter._run(["echo", "x"])
    assert "check" not in mock_run.call_args.kwargs
