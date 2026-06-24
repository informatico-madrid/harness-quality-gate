"""Mutant killers for the L3A/L4 tool adapters' scan-target selection.

Covers, for ruff / pyright / vulture / bandit:
  - the invoked command uses the resolved binary (kills binary=None/str(None));
  - production scan honours exclude_tests=True (test dirs are stripped);
  - the no-src fallback comprehension also excludes test packages.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from harness_quality_gate.adapters.python.bandit_adapter import BanditAdapter
from harness_quality_gate.adapters.python.pyright_adapter import PyrightAdapter
from harness_quality_gate.adapters.python.ruff_adapter import RuffAdapter
from harness_quality_gate.adapters.python.vulture_adapter import VultureAdapter

_FAKE_BIN = "/fake/bin/tool"
def _invoke_capturing_cmd(adapter_cls, modname, repo, *, patches=()):
    captured = {}

    def fake_run(self, cmd, *a, **k):
        captured["cmd"] = cmd
        return MagicMock(stdout="", stderr="", exitcode=0)

    mod = f"harness_quality_gate.adapters.python.{modname}"
    ctxs = [
        patch(f"{mod}.resolve_tool", return_value=Path(_FAKE_BIN)),
        patch.object(adapter_cls, "_run", fake_run),
        *patches,
    ]
    import contextlib

    with contextlib.ExitStack() as stack:
        for c in ctxs:
            stack.enter_context(c)
        adapter_cls().invoke(repo, [])
    return captured["cmd"]


class TestBinaryInCommand:
    def test_ruff_command_starts_with_binary(self, tmp_path: Path) -> None:
        cmd = _invoke_capturing_cmd(RuffAdapter, "ruff_adapter", tmp_path)
        assert cmd[0] == _FAKE_BIN

    def test_pyright_command_starts_with_binary(self, tmp_path: Path) -> None:
        cmd = _invoke_capturing_cmd(PyrightAdapter, "pyright_adapter", tmp_path)
        assert cmd[0] == _FAKE_BIN

    def test_vulture_command_starts_with_binary(self, tmp_path: Path) -> None:
        cmd = _invoke_capturing_cmd(VultureAdapter, "vulture_adapter", tmp_path)
        assert cmd[0] == _FAKE_BIN

    def test_bandit_command_starts_with_binary(self, tmp_path: Path) -> None:
        cmd = _invoke_capturing_cmd(BanditAdapter, "bandit_adapter", tmp_path)
        assert cmd[0] == _FAKE_BIN


class TestExcludeTestsFromTargets:
    """A test-named source_dir is stripped by exclude_tests=True.

    ``package_dirs`` already drops test packages, so the only way a test dir
    reaches ``source_targets`` is as the explicit source_dir candidate (e.g. a
    project pointing ``source_dir`` at a ``tests``-style directory).
    """

    def _check(self, adapter_cls, modname, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "__init__.py").touch()
        mod = f"harness_quality_gate.adapters.python.{modname}"
        patches = [patch(f"{mod}.detect_source_dir", return_value="tests")]
        cmd = _invoke_capturing_cmd(
            adapter_cls, modname, tmp_path, patches=patches
        )
        assert "tests" not in cmd

    def test_ruff(self, tmp_path: Path) -> None:
        self._check(RuffAdapter, "ruff_adapter", tmp_path)

    def test_pyright(self, tmp_path: Path) -> None:
        self._check(PyrightAdapter, "pyright_adapter", tmp_path)

    def test_vulture(self, tmp_path: Path) -> None:
        self._check(VultureAdapter, "vulture_adapter", tmp_path)

    def test_bandit(self, tmp_path: Path) -> None:
        self._check(BanditAdapter, "bandit_adapter", tmp_path)


class TestNoSrcFallbackExcludesTests:
    """No src/ → the package-dir fallback also strips test packages."""

    def _check(self, adapter_cls, modname, tmp_path):
        # 'mytests' contains "test" but is NOT the exact name package_dirs drops,
        # so it reaches the comprehension's own ``"test" not in ...`` filter.
        for name in ("pkg", "mytests"):
            (tmp_path / name).mkdir()
            (tmp_path / name / "__init__.py").touch()
        mod = f"harness_quality_gate.adapters.python.{modname}"
        # Force the no-src fallback path (detect_source_dir -> "" → else branch).
        patches = [patch(f"{mod}.detect_source_dir", return_value="")]
        cmd = _invoke_capturing_cmd(adapter_cls, modname, tmp_path, patches=patches)
        assert "pkg" in cmd
        assert "mytests" not in cmd

    def test_ruff(self, tmp_path: Path) -> None:
        self._check(RuffAdapter, "ruff_adapter", tmp_path)

    def test_pyright(self, tmp_path: Path) -> None:
        self._check(PyrightAdapter, "pyright_adapter", tmp_path)

    def test_vulture(self, tmp_path: Path) -> None:
        self._check(VultureAdapter, "vulture_adapter", tmp_path)

    def test_bandit(self, tmp_path: Path) -> None:
        self._check(BanditAdapter, "bandit_adapter", tmp_path)


class TestNoTargetsFallsBackToRepo:
    """An empty repo falls back to scanning str(repo), never str(None).

    Two fallbacks reach str(repo): the no-src package-dir branch
    (detect_source_dir -> "") and the source_targets-empty branch
    (detect_source_dir -> a name that isn't a real dir).
    """

    def _check(self, adapter_cls, modname, tmp_path, source_dir):
        mod = f"harness_quality_gate.adapters.python.{modname}"
        patches = [patch(f"{mod}.detect_source_dir", return_value=source_dir)]
        cmd = _invoke_capturing_cmd(
            adapter_cls, modname, tmp_path, patches=patches
        )
        assert str(tmp_path) in cmd

    def test_vulture_no_src(self, tmp_path: Path) -> None:
        self._check(VultureAdapter, "vulture_adapter", tmp_path, "")

    def test_vulture_source_targets_empty(self, tmp_path: Path) -> None:
        self._check(VultureAdapter, "vulture_adapter", tmp_path, "ghost")

    def test_bandit_no_src(self, tmp_path: Path) -> None:
        self._check(BanditAdapter, "bandit_adapter", tmp_path, "")

    def test_bandit_source_targets_empty(self, tmp_path: Path) -> None:
        self._check(BanditAdapter, "bandit_adapter", tmp_path, "ghost")

    def test_pyright_no_src(self, tmp_path: Path) -> None:
        self._check(PyrightAdapter, "pyright_adapter", tmp_path, "")

    def test_pyright_source_targets_empty(self, tmp_path: Path) -> None:
        self._check(PyrightAdapter, "pyright_adapter", tmp_path, "ghost")
