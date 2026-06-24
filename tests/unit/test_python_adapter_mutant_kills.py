"""Kill mutants 1 and 2 on _run_pytest in python_adapter.py.

Mutants targeted:

  mutant_1 (_run_pytest mutmut_3 — Logger string XX-wrap):
    "Python interpreter not found (sys.executable empty), skipping"
    → "XX...XX" wrap that breaks substring assertion.

  mutant_2 (_run_pytest mutmut_6 — Falsy twin None→""):
    venv_dir: str | None = None → venv_dir: str | None = ""
    After coordinator refactor (if venv_dir: → if venv_dir is not None:),
    empty string enters the block and adds extra pathsep at start of PATH.

Strategy §H3:
  - Mutant 1: caplog with set_level + logger name, exact getMessage() assertion
  - Mutant 2: spy on env dict captured from invoke() call, assert PATH doesn't
    start with os.pathsep
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.python.python_adapter import PythonAdapter


class TestRunPytestLoggerString:
    """KILL: _run_pytest mutmut_3 (Logger string XX-wrap).

    When sys.executable is empty, _run_pytest must log the exact warning
    message. An XX-wrap mutation on the logger string makes substring
    assertions fail.

    Recipe §H3: caplog.set_level(level, logger=...) for exact interpolated message.
    """

    def test_run_pytest_empty_sys_executable_logs_exact_warning(
        self, tmp_path: Path, caplog
    ) -> None:
        """KILL: _run_pytest mutmut_3.

        Trigger sys.executable == "" (empty, falsy) and verify caplog
        captures the exact warning message. An XX-wrapped string like
        "XXPython interpreter not found (sys.executable empty), skippingXX"
        would NOT contain the un-wrapped substring.
        """
        caplog.set_level(
            logging.WARNING,
            logger="harness_quality_gate.adapters.python.python_adapter",
        )

        adapter = PythonAdapter()
        adapter.pytest = MagicMock()

        with patch.object(sys, "executable", ""):
            result = adapter._run_pytest(tmp_path, {})

        assert result == []

        messages = [r.getMessage() for r in caplog.records]
        warning_msgs = [m for m in messages if "Python interpreter not found" in m]
        assert len(warning_msgs) >= 1, (
            f"No warning logged for empty sys.executable. Messages: {messages}"
        )

        # Exact assertion kills XX-wraps (mutmut_3)
        expected = "Python interpreter not found (sys.executable empty), skipping"
        assert warning_msgs[0] == expected, (
            f"Expected exact message {expected!r} but got: {warning_msgs[0]}"
        )

    def test_run_pytest_empty_sys_executable_returns_empty_list(
        self, tmp_path: Path
    ) -> None:
        """KILL: _run_pytest mutmut_3 (early return path).

        Even if the log string is mutated, the early return must still
        yield [] (not None, not [], not a side effect).
        """
        adapter = PythonAdapter()
        adapter.pytest = MagicMock()

        with patch.object(sys, "executable", ""):
            result = adapter._run_pytest(tmp_path, {})

        assert result == []
        assert isinstance(result, list)
        assert result is not None


class TestRunPytestVenvDirPathsep:
    """KILL: _run_pytest mutmut_6 (Falsy twin None->'').

    After the coordinator refactor changed `if venv_dir:` to
    `if venv_dir is not None:`, an empty string `""` passes the check
    and produces `PATH = "" + os.pathsep + prev_path` — an extra
    pathsep at the beginning.

    Original `venv_dir=None` → skips the block → PATH unchanged.
    """

    def test_run_pytest_no_venv_no_extra_pathsep(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """KILL: _run_pytest mutmut_6.

        Without a .venv directory, PATH must NOT have an extra pathsep
        at the start. With the mutation (venv_dir=""), the block
        enters and prepends "" + pathsep + prev_path = ":/usr/bin".

        Recipe: spy on env captured from mock invoke call arg.
        """
        original_path = "/usr/bin:/bin:/usr/local/bin"
        monkeypatch.setenv("PATH", original_path)

        # Capture env dict from the invoke call
        captured_env: dict = {}

        def fake_invoke(*args, **kwargs) -> MagicMock:
            captured_env["value"] = dict(kwargs.get("env", {}))
            return MagicMock(stdout="", stderr="", exitcode=0)

        adapter = PythonAdapter()
        adapter.pytest = MagicMock()
        adapter.pytest.invoke = fake_invoke
        adapter.pytest.parse.return_value = []

        result = adapter._run_pytest(tmp_path, {})

        assert result == []

        path_value = captured_env.get("value", {}).get("PATH", "")
        # Original: PATH unchanged → "/usr/bin:/bin:/usr/local/bin"
        # Mutated:  PATH = ":/usr/bin:/bin:/usr/local/bin" (extra pathsep)
        assert not path_value.startswith(os.pathsep), (
            f"KILLS mutmut_6: PATH must not start with pathsep, got: {path_value!r}"
        )

    def test_run_pytest_with_venv_prepends_correctly(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Verify venv path is prepended when .venv/bin/pytest exists.

        This ensures the original unmutated code works correctly — venv
        PATH is properly prepended, not broken by any mutation.
        """
        original_path = "/usr/bin:/bin"
        monkeypatch.setenv("PATH", original_path)

        # Create .venv/bin/pytest so venv_dir gets set
        (tmp_path / ".venv" / "bin").mkdir(parents=True)
        (tmp_path / ".venv" / "bin" / "pytest").touch()

        captured: dict = {}

        def fake_invoke(*args, **kwargs) -> MagicMock:
            captured["env"] = dict(kwargs.get("env", {}))
            return MagicMock(stdout="", stderr="", exitcode=0)

        adapter = PythonAdapter()
        adapter.pytest = MagicMock()
        adapter.pytest.invoke = fake_invoke
        adapter.pytest.parse.return_value = []

        result = adapter._run_pytest(tmp_path, {})

        assert result == []

        path_value = captured.get("env", {}).get("PATH", "")
        venv_bin = str(tmp_path / ".venv" / "bin")

        # PATH should start with venv_bin + pathsep
        assert path_value.startswith(venv_bin), (
            f"PATH must start with venv dir, got: {path_value!r}"
        )
        assert path_value.startswith(venv_bin + os.pathsep), (
            f"PATH must be venv_dir + pathsep + prev_path, got: {path_value!r}"
        )


class TestRunPytestPrevPathExact:
    """KILL: _run_pytest prev_path lookups.

    ``prev_path = patched_env.get("PATH", os.environ.get("PATH", ""))`` feeds
    straight into ``patched_env["PATH"] = venv_dir + os.pathsep + prev_path``,
    so the exact resulting PATH pins every key/default mutation on that line.
    Three scenarios isolate (a) env-provided PATH, (b) os.environ fallback,
    (c) empty-default fallback.
    """

    @staticmethod
    def _adapter_capturing_env() -> tuple[PythonAdapter, dict]:
        captured: dict = {}

        def fake_invoke(*args, **kwargs) -> MagicMock:
            captured["env"] = dict(kwargs.get("env", {}))
            return MagicMock(stdout="", stderr="", exitcode=0)

        adapter = PythonAdapter()
        adapter.pytest = MagicMock()
        adapter.pytest.invoke = fake_invoke
        adapter.pytest.parse.return_value = []
        return adapter, captured

    @staticmethod
    def _make_venv(repo: Path) -> str:
        (repo / ".venv" / "bin").mkdir(parents=True)
        (repo / ".venv" / "bin" / "pytest").touch()
        return str(repo / ".venv" / "bin")

    def test_env_path_wins_over_os_environ(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """env's own PATH is used (kills get("PATH")->None/"path"/XXPATHXX)."""
        venv_bin = self._make_venv(tmp_path)
        monkeypatch.setenv("PATH", "OS_SENTINEL")
        adapter, captured = self._adapter_capturing_env()

        adapter._run_pytest(tmp_path, {"PATH": "ENV_SENTINEL"})

        assert captured["env"]["PATH"] == f"{venv_bin}{os.pathsep}ENV_SENTINEL"

    def test_falls_back_to_os_environ_path(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """With no PATH in env, os.environ's PATH is used (kills the inner
        os.environ.get("PATH", "") key mutations)."""
        venv_bin = self._make_venv(tmp_path)
        monkeypatch.setenv("PATH", "OS_SENTINEL")
        adapter, captured = self._adapter_capturing_env()

        adapter._run_pytest(tmp_path, {})

        assert captured["env"]["PATH"] == f"{venv_bin}{os.pathsep}OS_SENTINEL"

    def test_empty_default_when_no_path_anywhere(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """With PATH absent from env AND os.environ, prev_path is the empty
        default (kills os.environ.get default ""->None/removed/"XXXX")."""
        venv_bin = self._make_venv(tmp_path)
        monkeypatch.delenv("PATH", raising=False)
        adapter, captured = self._adapter_capturing_env()

        adapter._run_pytest(tmp_path, {})

        assert captured["env"]["PATH"] == f"{venv_bin}{os.pathsep}"
