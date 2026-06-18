"""Tests for PythonAdapter partial-run support (paths parameter).

Covers:
  - PythonAdapter(paths=["src/foo.py"]).paths == ["src/foo.py"]
  - PythonAdapter() without args → paths is None (backward compatible)
  - _run_ruff passes paths to ruff invoke when self.paths is set
  - _run_pyright passes paths to pyright invoke when self.paths is set
  - _run_pytest passes paths to pytest invoke when self.paths is set
  - _run_mutmut passes paths to mutmut.run when self.paths is set
  - run_l2/run_l3b/run_l4 work correctly when paths is set
    (quick-pass was removed from adapter; now handled only in CLI via
    supports_partial_run property)
  - MutmutAdapter.run(repo, paths=["src/foo.py"]) passes paths to command
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.models import Finding, LayerResult, MutationStats


def _make_finding(
    severity: str = "error",
    message: str = "test finding",
    node: str = "test.py",
    rule_id: str | None = None,
    fix_hint: str | None = None,
    tool: str = "ruff",
    layer: str = "L3A",
    language: str = "python",
    cwe: str = "",
) -> Finding:
    return Finding(
        severity=severity, message=message, node=node, rule_id=rule_id,
        fix_hint=fix_hint, tool=tool, layer=layer, language=language, cwe=cwe,
    )


# ---------------------------------------------------------------------------
# PythonAdapter __init__ paths parameter
# ---------------------------------------------------------------------------

class TestPythonAdapterInit:
    def test_paths_stored(self):
        """PythonAdapter(paths=['src/foo.py']).paths == ['src/foo.py']."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter(paths=["src/foo.py"])
        assert a.paths == ["src/foo.py"]

    def test_no_paths_is_none(self):
        """PythonAdapter() → paths is None (backward compatible)."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter()
        assert a.paths is None

    def test_empty_paths_list(self):
        """PythonAdapter(paths=[]) → paths is []."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter(paths=[])
        assert a.paths == []

    def test_subadapters_always_created(self):
        """Sub-adapters are always instantiated regardless of paths."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter(paths=["x"])
        assert a.ruff is not None
        assert a.pyright is not None
        assert a.pytest is not None
        assert a.mutmut is not None
        assert a.bandit is not None
        assert a.vulture is not None
        assert a.deptry is not None


# ---------------------------------------------------------------------------
# _run_ruff passes paths
# ---------------------------------------------------------------------------

class TestRunRuffPaths:
    def _adapter_with_paths(self, paths=None):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        from harness_quality_gate.bootstrap import ToolNotAvailable
        a = PythonAdapter(paths=paths)
        with patch(
            "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
            side_effect=lambda name, repo: (
                Path("/bin/ruff") if name == "ruff" else None
            ),
        ):
            with _stub_source_dirs():
                yield a

    def test_ruff_invoke_receives_paths(self, tmp_path):
        """_run_ruff passes self.paths to ruff.invoke() when paths is set."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter(paths=["src/foo.py"])
        a.ruff = MagicMock()
        a.ruff.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)

        with _stub_resolve_tool_for_ruff():
            a._run_ruff(tmp_path, {})

        a.ruff.invoke.assert_called_once()
        _, kwargs = a.ruff.invoke.call_args
        assert kwargs["paths"] == ["src/foo.py"]

    def test_ruff_invoke_paths_none_when_no_paths_set(self, tmp_path):
        """_run_ruff passes paths=None to ruff.invoke() when self.paths is None."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter()
        a.ruff = MagicMock()
        a.ruff.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)

        with _stub_resolve_tool_for_ruff():
            a._run_ruff(tmp_path, {})

        a.ruff.invoke.assert_called_once()
        _, kwargs = a.ruff.invoke.call_args
        assert kwargs["paths"] is None


# ---------------------------------------------------------------------------
# _run_pyright passes paths
# ---------------------------------------------------------------------------

class TestRunPyrightPaths:
    def test_pyright_invoke_receives_paths(self, tmp_path):
        """_run_pyright passes self.paths to pyright.invoke() when paths is set."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter(paths=["src/bar.py"])
        a.pyright = MagicMock()
        a.pyright.invoke.return_value = MagicMock(
            stdout=json.dumps({"generalDiagnostics": []}), stderr="", exitcode=0
        )

        with _stub_resolve_tool_for_pyright():
            a._run_pyright(tmp_path, {})

        a.pyright.invoke.assert_called_once()
        _, kwargs = a.pyright.invoke.call_args
        assert kwargs["paths"] == ["src/bar.py"]

    def test_pyright_invoke_paths_none_when_no_paths_set(self, tmp_path):
        """_run_pyright passes paths=None when self.paths is None."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter()
        a.pyright = MagicMock()
        a.pyright.invoke.return_value = MagicMock(
            stdout=json.dumps({"generalDiagnostics": []}), stderr="", exitcode=0
        )

        with _stub_resolve_tool_for_pyright():
            a._run_pyright(tmp_path, {})

        _, kwargs = a.pyright.invoke.call_args
        assert kwargs["paths"] is None


# ---------------------------------------------------------------------------
# _run_pytest passes paths
# ---------------------------------------------------------------------------

class TestRunPytestPaths:
    def test_pytest_invoke_receives_paths(self, tmp_path):
        """_run_pytest passes self.paths to pytest.invoke() when paths is set."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter(paths=["tests/test_foo.py"])
        a.pytest = MagicMock()
        a.pytest.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)

        # sys.executable is always available
        a._run_pytest(tmp_path, {})

        a.pytest.invoke.assert_called_once()
        _, kwargs = a.pytest.invoke.call_args
        assert kwargs["paths"] == ["tests/test_foo.py"]

    def test_pytest_invoke_paths_none_when_no_paths_set(self, tmp_path):
        """_run_pytest passes paths=None when self.paths is None."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter()
        a.pytest = MagicMock()
        a.pytest.invoke.return_value = MagicMock(stdout="", stderr="", exitcode=0)

        a._run_pytest(tmp_path, {})

        _, kwargs = a.pytest.invoke.call_args
        assert kwargs["paths"] is None


# ---------------------------------------------------------------------------
# _run_mutmut passes paths
# ---------------------------------------------------------------------------

class TestRunMutmutPaths:
    def test_mutmut_run_receives_paths(self, tmp_path):
        """_run_mutmut passes self.paths to mutmut.run() when paths is set."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter(paths=["src/bar.py"])
        a.mutmut = MagicMock()
        a.mutmut.run.return_value = MagicMock(stdout="", stderr="", exitcode=0)
        a.mutmut.invoke.return_value = MagicMock(stdout="{}", stderr="", exitcode=0)
        a.mutmut.parse.return_value = MutationStats(
            total=0, killed=0, survived=0, timed_out=0,
            escaped=0, untested=0, msi=0.0, covered_msi=0.0,
        )

        with _stub_resolve_tool_for_mutmut():
            stats, run_ok = a._run_mutmut(tmp_path, {})

        a.mutmut.run.assert_called_once()
        _, kwargs = a.mutmut.run.call_args
        assert kwargs["paths"] == ["src/bar.py"]

    def test_mutmut_run_paths_none_when_no_paths_set(self, tmp_path):
        """_run_mutmut passes paths=None when self.paths is None."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter()
        a.mutmut = MagicMock()
        a.mutmut.run.return_value = MagicMock(stdout="", stderr="", exitcode=0)
        a.mutmut.invoke.return_value = MagicMock(stdout="{}", stderr="", exitcode=0)
        a.mutmut.parse.return_value = MutationStats(
            total=0, killed=0, survived=0, timed_out=0,
            escaped=0, untested=0, msi=0.0, covered_msi=0.0,
        )

        with _stub_resolve_tool_for_mutmut():
            stats, run_ok = a._run_mutmut(tmp_path, {})

        _, kwargs = a.mutmut.run.call_args
        assert kwargs["paths"] is None


# ---------------------------------------------------------------------------
# run_l2/run_l3b/run_l4 still return quick-pass when paths is set
# (adapter-level quick-pass still exists alongside CLI partial_run property)
# ---------------------------------------------------------------------------

class TestLayersWithPathsSet:
    """Verify layers return quick-pass when invoked directly with paths set.
    The CLI uses supports_partial_run to handle partial runs; the adapter
    itself still returns quick-pass LayerResults when --paths is provided."""

    def test_l2_quick_pass_with_paths(self, tmp_path):
        """run_l2 returns quick-pass LayerResult when self.paths is set."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter(paths=["src/foo.py"])
        layer = a.run_l2(tmp_path, {})
        assert layer.layer == "L2"
        assert layer.language == "python"
        assert layer.passed is True
        assert layer.findings == []
        assert layer.duration_sec == 0.0
        assert layer.tool_specific is None

    def test_l3b_quick_pass_with_paths(self, tmp_path):
        """run_l3b returns quick-pass LayerResult when self.paths is set."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter(paths=["src/foo.py"])
        layer = a.run_l3b(tmp_path, {})
        assert layer.layer == "L3B"
        assert layer.language == "python"
        assert layer.passed is True
        assert layer.findings == []
        assert layer.duration_sec == 0.0
        assert layer.tool_specific is None

    def test_l4_quick_pass_with_paths(self, tmp_path):
        """run_l4 returns quick-pass LayerResult when self.paths is set."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter(paths=["src/foo.py"])
        layer = a.run_l4(tmp_path, {})
        assert layer.layer == "L4"
        assert layer.language == "python"
        assert layer.passed is True


# ---------------------------------------------------------------------------
# MutmutAdapter.run paths parameter
# ---------------------------------------------------------------------------

class TestMutmutRunPaths:
    def test_mutmut_run_appends_paths(self, tmp_path):
        """MutmutAdapter.run(repo, paths=['src/foo.py']) appends paths to command."""
        from harness_quality_gate.adapters.python.mutmut_adapter import MutmutAdapter
        adapter = MutmutAdapter()
        with patch(
            "harness_quality_gate.adapters.python.mutmut_adapter.resolve_tool",
            return_value=Path("/bin/mutmut"),
        ) as resolve_mock:
            with patch.object(adapter, "_run") as mock_run:
                mock_run.return_value = MagicMock(stdout="", stderr="", exitcode=0)
                inv = adapter.run(tmp_path, paths=["src/bar.py"])

        cmd = mock_run.call_args[0][0]
        assert "src/bar.py" in cmd
        # mutmut run should come before paths
        run_idx = cmd.index("run")
        path_idx = cmd.index("src/bar.py")
        assert run_idx < path_idx

    def test_mutmut_run_no_paths(self, tmp_path):
        """MutmutAdapter.run(repo) without paths has no file args."""
        from harness_quality_gate.adapters.python.mutmut_adapter import MutmutAdapter
        adapter = MutmutAdapter()
        with patch(
            "harness_quality_gate.adapters.python.mutmut_adapter.resolve_tool",
            return_value=Path("/bin/mutmut"),
        ):
            with patch.object(adapter, "_run") as mock_run:
                mock_run.return_value = MagicMock(stdout="", stderr="", exitcode=0)
                adapter.run(tmp_path)

        cmd = mock_run.call_args[0][0]
        # Should be [binary, 'run', ...]
        assert "run" in cmd
        # No file paths in the command
        assert cmd[1] == "run"


# ---------------------------------------------------------------------------
# Backward compatibility: PythonAdapter without args still works
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_python_adapter_no_args(self, tmp_path):
        """PythonAdapter() with no args works as before."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter()
        # Should have all sub-adapters
        assert hasattr(a, "ruff")
        assert hasattr(a, "pyright")
        assert hasattr(a, "pytest")
        assert hasattr(a, "mutmut")
        assert hasattr(a, "bandit")
        assert hasattr(a, "vulture")
        assert hasattr(a, "deptry")

    def test_l3a_full_run_with_no_paths(self, tmp_path):
        """L3A runs normally when paths=None (no shortcut)."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        a = PythonAdapter()
        a.ruff = MagicMock()
        a.ruff.invoke.return_value = MagicMock(stdout="[]", stderr="", exitcode=0)
        a.pyright = MagicMock()
        a.pyright.invoke.return_value = MagicMock(
            stdout=json.dumps({"generalDiagnostics": []}), stderr="", exitcode=0
        )
        a.pyright.name = "pyright"

        with _stub_resolve_tool_for_ruff():
            with _stub_resolve_tool_for_pyright():
                layer = a.run_l3a(tmp_path, {})

        assert layer.passed is True
        # Invoked with paths=None, not shortcut
        _, ruff_kwargs = a.ruff.invoke.call_args
        assert ruff_kwargs["paths"] is None
        _, pyright_kwargs = a.pyright.invoke.call_args
        assert pyright_kwargs["paths"] is None


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _stub_resolve_tool_for_ruff():
    """Stub resolve_tool for ruff-related calls."""
    return patch(
        "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
        side_effect=lambda name, repo: (
            Path("/bin/ruff") if name == "ruff" else None
        ),
    )


def _stub_resolve_tool_for_pyright():
    """Stub resolve_tool for pyright-related calls."""
    return patch(
        "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
        side_effect=lambda name, repo: (
            Path("/bin/pyright") if name == "pyright" else None
        ),
    )


def _stub_resolve_tool_for_mutmut():
    """Stub resolve_tool for mutmut-related calls."""
    return patch(
        "harness_quality_gate.adapters.python.python_adapter.resolve_tool",
        side_effect=lambda name, repo: (
            Path("/bin/mutmut") if name == "mutmut" else None
        ),
    )


def _stub_source_dirs():
    """Prevent detect_source_dir from walking real dirs."""
    return patch(
        "harness_quality_gate.adapters.python.python_adapter.detect_source_dir",
        return_value=None,
    )
