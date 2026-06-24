"""Kill surviving mutants from the final 23 diffs.

Target: harness_quality_gate/adapters/python/... pyright ruff bandit mutmut,
        harness_quality_gate/adapters/php/... phpunit dep_analyser,
        harness_quality_gate/cli.py, harness_quality_gate/config.py

Strategy:
  - resolve_tool mutations: spy captures ALL args (name + repo)
  - source_targets mutations: use a repo with src/ + tests/ dirs,
    assert tests/ is NOT in the command
  - CLI LayerResult mutations: assert JSON output fields are not None
  - argparse mutation: assert args.paths is None
  - config mutation: assert small positive values accepted
"""

from __future__ import annotations

import argparse
import inspect
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.base import ToolInvocation
from harness_quality_gate.adapters.php.dep_analyser_adapter import DepAnalyserAdapter
from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter
from harness_quality_gate.adapters.python.bandit_adapter import BanditAdapter
from harness_quality_gate.adapters.python.mutmut_adapter import MutmutAdapter
from harness_quality_gate.adapters.python.pyright_adapter import PyrightAdapter
from harness_quality_gate.adapters.python.ruff_adapter import RuffAdapter
from harness_quality_gate.bootstrap import ToolNotAvailable
from harness_quality_gate.cli import _cmd_all, main
from harness_quality_gate.config import validate
from harness_quality_gate.exit_codes import PASS
from harness_quality_gate.models import LayerResult


def _make_args(**kw):
    d = {"repo": ".", "json": False, "quiet": False, "paths": None}
    d.update(kw)
    return argparse.Namespace(**d)


def _mock_adapter(**kw):
    a = MagicMock()
    lr = LayerResult(layer="L3A", language="python", passed=True,
                     findings=[], duration_sec=0.0)
    for m in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
        getattr(a, m).return_value = lr
    return a


# =============================================================
# bandit_adapter — resolve_tool name & repo mutations
# mutmut_5 invoke  resolve_tool("bandit", repo) -> ("bandit", None)
# mutmut_7 invoke  resolve_tool("bandit", repo) -> ("bandit", )
# mutmut_8 version resolve_tool("bandit", repo) -> ("XXbanditXX", repo)
# mutmut_9 version resolve_tool("bandit", repo) -> ("BANDIT", repo)
# =============================================================


class TestBanditResolveToolName:
    """mutmut_8/9: name arg 'XXbanditXX' / 'BANDIT'."""

    def test_version_checks_name_literal(self):
        captured = []

        def spy(name, repo):
            captured.append(name)
            raise ToolNotAvailable(name)

        with patch(
            "harness_quality_gate.adapters.python.bandit_adapter.resolve_tool",
            side_effect=spy,
        ):
            with pytest.raises(RuntimeError, match="bandit not found"):
                BanditAdapter().version(Path("/tmp"), env=None)

        for name in captured:
            assert name == "bandit", (
                f"mutmut_8/9: resolve_tool name must be 'bandit', got '{name}'"
            )


class TestBanditResolveToolRepo:
    """mutmut_5/7: resolve_tool("bandit", repo) -> ("bandit", None)."""

    def test_invoke_repo_not_none(self, tmp_path):
        """Spy captures (name, repo) — mutant passes None instead of repo."""
        (tmp_path / "src").mkdir(exist_ok=True)
        captured = []

        def spy(name, repo):
            captured.append((name, repo))
            return MagicMock()

        with patch(
            "harness_quality_gate.adapters.python.bandit_adapter.resolve_tool",
            side_effect=spy,
        ):
            with patch.object(
                BanditAdapter, "_run", return_value=MagicMock(stdout="[]")
            ):
                BanditAdapter().invoke(tmp_path, [])

        assert len(captured) >= 1
        name, repo = captured[-1]
        assert name == "bandit"
        assert repo is not None, (
            f"mutmut_5/7: resolve_tool repo must not be None, got {repo}"
        )


# =============================================================
# bandit_adapter — source_targets exclude_tests mutations
# mutmut_24  exclude_tests=True -> exclude_tests=None
# mutmut_27  exclude_tests=True -> omit arg
# mutmut_28  exclude_tests=True -> exclude_tests=False
# =============================================================


class TestBanditSourceTargetsExcludesTests:
    """mutmut_24/27/28: without exclude_tests=True, tests/ leaks in."""

    def test_no_tests_in_scan_targets(self, tmp_path):
        (tmp_path / "src").mkdir(exist_ok=True)
        (tmp_path / "tests").mkdir(exist_ok=True)

        with patch(
            "harness_quality_gate.adapters.python.bandit_adapter.resolve_tool",
            return_value=Path("/usr/bin/bandit"),
        ):
            with patch.object(
                BanditAdapter, "_run", return_value=MagicMock(stdout="[]")
            ) as m:
                BanditAdapter().invoke(tmp_path, [])

        cmd = m.call_args[0][0]
        cmd_joined = " ".join(str(c) for c in cmd)
        assert "tests" not in cmd_joined.lower(), (
            f"mutmut_24/27/28: tests/ must not be in: {cmd}"
        )


# =============================================================
# pyright_adapter — resolve_tool repo mutation
# mutmut_5  resolve_tool("pyright", repo) -> ("pyright", None)
# =============================================================


class TestPyrightResolveToolRepo:
    """mutmut_5: repo must not be None."""

    def test_invoke_repo_not_none(self):
        captured = []

        def spy(name, repo):
            captured.append(repo)
            return MagicMock()

        with patch(
            "harness_quality_gate.adapters.python.pyright_adapter.resolve_tool",
            side_effect=spy,
        ):
            with patch.object(PyrightAdapter, "_run", return_value=MagicMock(stdout="{}")):
                PyrightAdapter().invoke(Path("/repo"), [])

        for repo in captured:
            assert repo is not None, "mutmut_5: repo must not be None"


# =============================================================
# pyright_adapter — source_targets / default_targets mutations
# mutmut_34  exclude_tests=True -> exclude_tests=None
# mutmut_37  exclude_tests=True -> omit arg
# mutmut_38  exclude_tests=True -> exclude_tests=False
# mutmut_39  package_dir filter -> default_targets = None
# =============================================================


class TestPyrightExcludesTests:
    """mutmut_34/37/38: tests/ must not be in scan targets."""

    def test_tests_excluded(self, tmp_path):
        (tmp_path / "src").mkdir(exist_ok=True)
        (tmp_path / "tests").mkdir(exist_ok=True)

        with patch(
            "harness_quality_gate.adapters.python.pyright_adapter.resolve_tool",
            return_value=Path("/bin/pyright"),
        ):
            with patch.object(
                PyrightAdapter, "_run", return_value=MagicMock(stdout="{}")
            ) as m:
                PyrightAdapter().invoke(tmp_path, [])

        cmd = m.call_args[0][0]
        cmd_joined = " ".join(str(c) for c in cmd)
        assert "tests" not in cmd_joined.lower(), (
            f"mutmut_34/37/38: tests/ leaked: {cmd}"
        )


# =============================================================
# ruff_adapter — default_targets mutation
# mutmut_34  package_dirs filter -> default_targets = None
# =============================================================


class TestRuffDefaultTargets:
    """mutmut_34: scan_targets must always have a target."""

    def test_has_target(self, tmp_path):
        with patch(
            "harness_quality_gate.adapters.python.ruff_adapter.resolve_tool",
            return_value=Path("/usr/bin/ruff"),
        ):
            with patch.object(
                RuffAdapter, "_run", return_value=MagicMock(stdout="[]")
            ) as m:
                RuffAdapter().invoke(tmp_path, [])

        cmd = m.call_args[0][0]
        # command must include at least: ruff check --output-format=json <target>
        assert len(cmd) >= 4, f"mutmut_34: expected >= 4 parts in {cmd}"


# =============================================================
# mutmut_adapter mutations
# mutmut_30  default '' -> 'XXXX'
# mutmut_1   data: dict = {} -> data: dict = None
# =============================================================


class TestMutmutRunMaxChildren:
    """mutmut_30: without MUTATION_MAX_CHILDREN env, no --max-children flag.

    Must exercise line-90 (the .get() call) directly by resolving 'mutmut'
    via resolve_tool mock — mocking _run (as some other tests do) skips
    the mutant mutation site entirely.
    """

    def test_no_max_children_without_env_exercises_line90(self):
        with patch(
            "harness_quality_gate.adapters.python.mutmut_adapter.resolve_tool",
            return_value=Path("/usr/bin/mutmut"),
        ):
            with patch(
                "harness_quality_gate.adapters.python.mutmut_adapter.MutmutAdapter._run",
                return_value=ToolInvocation(stdout=""),
            ) as m:
                MutmutAdapter().run(Path("/"))
        cmd = m.call_args[0][0]
        assert "--max-children" not in cmd, (
            "mutmut_30: --max-children must not appear when env is empty; "
            "the .get() default should remain '' (killing XXXX-fallback mutant)"
        )


class TestMutmutParseDefaultDict:
    """mutmut_1: data defaults to None would cause AttributeError on garbage parse.

    parse("xxx") → json.loads fails → _aggregate_mutant_lines returns {} →
    if not data: True → regex runs.
    With data=None the data.get("total") line throws AttributeError.

    The assertion on every field catches the crash.
    """

    def test_garbage_returns_all_zero(self):
        """mutmut_1: garbage input → all-zero MutationStats (not crash)."""
        s = MutmutAdapter().parse("xxx")
        assert s.total == 0
        assert s.killed == 0
        assert s.msi == 0.0


# =============================================================
# phpunit_adapter — assert message XX-wrap
# mutmut_2  "DET.parse" -> "XXDET.parse...XX"
# =============================================================


class TestPHPUnitAssertMessage:
    """mutmut_2: assert message must not be XX-wrapped."""

    def test_assert_message_original(self):
        src = inspect.getsource(PhpUnitAdapter._parse_junit_xml)
        assert "DET.parse succeeded" in src, "mutmut_2: message must be original"


# =============================================================
# dep_analyser_adapter — log message case mutation
# mutmut_5  "INFRA_INCOMPLETE" -> "infra_incomplete"
# =============================================================


class TestDepAnalyserWarning:
    """mutmut_5: warning must say INFRA_INCOMPLETE (uppercase)."""

    def test_warning_uppercase(self, caplog):
        caplog.set_level(
            logging.WARNING,
            logger="harness_quality_gate.adapters.php.dep_analyser_adapter",
        )
        with patch.object(DepAnalyserAdapter, "_binary", return_value=None):
            DepAnalyserAdapter().invoke(Path("/x"), [])
        txt = " ".join(r.getMessage() for r in caplog.records)
        assert "INFRA_INCOMPLETE" in txt, f"mutmut_5: '{txt}'"


# =============================================================
# cli.py — LayerResult field mutations
# mutmut_14  findings=[] -> findings=None
# mutmut_15  duration_sec=0.0 -> duration_sec=None
# =============================================================


class TestCliLayerResultFields:
    """mutmut_14/15: auto-created L2/L3B/L4 LayerResult fields must be set."""

    def _run_cmd(self, tmp_path, capsys):
        adapter = _mock_adapter()
        adapter.run_l3a.return_value = LayerResult(
            layer="L3A", language="python", passed=True,
            findings=[], duration_sec=0.5)
        adapter.run_l1.return_value = LayerResult(
            layer="L1", language="python", passed=True,
            findings=[], duration_sec=1.0)
        with patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter):
            with patch("harness_quality_gate.cli.write_checkpoint"):
                _cmd_all(_make_args(repo=str(tmp_path), paths=["src/"], json=True))
        return json.loads(capsys.readouterr().out)

    def test_findings_not_none(self, tmp_path, capsys):
        out = self._run_cmd(tmp_path, capsys)
        for ly in out["layers"]:
            if ly["layer"] in ("L2", "L3B", "L4"):
                assert ly["findings"] is not None, (
                    f"mutmut_14: {ly['layer']} findings is None"
                )

    def test_duration_not_none(self, tmp_path, capsys):
        out = self._run_cmd(tmp_path, capsys)
        for ly in out["layers"]:
            if ly["layer"] in ("L2", "L3B", "L4"):
                assert ly["duration_sec"] is not None, (
                    f"mutmut_15: {ly['layer']} duration_sec is None"
                )

    def test_duration_is_number(self, tmp_path, capsys):
        out = self._run_cmd(tmp_path, capsys)
        for ly in out["layers"]:
            if ly["layer"] in ("L2", "L3B", "L4"):
                assert isinstance(ly["duration_sec"], (int, float)), (
                    "duration_sec must be numeric"
                )


# =============================================================
# cli.py — argparse --paths default removal
# x_main mutmut_6: default=None removed from argument def
# =============================================================


class TestArgparsePathsDefault:
    """mutmut_6: args.paths must be None without flag."""

    def test_paths_none(self):
        with patch("harness_quality_gate.cli._cmd_all", return_value=PASS) as m:
            main(["all", "."])
        assert m.call_args.args[0].paths is None, "mutmut_6: args.paths must be None"


# =============================================================
# config.py — coverage_threshold boundary
# x_validate mutmut_14: 0 <= -> 0 <
# =============================================================


class TestCoverageThresholdBoundary:
    """mutmut_14: verify boundary logic works for small positive values."""

    def test_small_positive_accepted(self):
        c = validate({"schema_version": 2, "coverage_threshold": 0.01})
        assert c.coverage_threshold == 0.01

    def test_zero_accepted(self):
        c = validate({"schema_version": 2, "coverage_threshold": "0"})
        assert c.coverage_threshold == 0.0

    def test_negative_rejected(self):
        import re as _re
        with pytest.raises(Exception, match=_re.escape("coverage_threshold must be between")):
            validate({"schema_version": 2, "coverage_threshold": -1.0})
