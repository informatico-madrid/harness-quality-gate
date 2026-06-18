"""Unit tests for mutation_analyzer — Phase 3 convergence plan.

Covers:
- Bug fix 1: _extract_mutmut_module returns group(1) (dotted path)
- Bug fix 3: ModuleMutStats.module is set correctly
- New feature: parse_survivors() and SurvivedMutant
- Bug fix 2: parse_mutmut survivors_only parameter
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.bmad.mutation_analyzer import (
    ModuleMutStats,
    MutationStats,
    SurvivedMutant,
    _extract_mutmut_module,
    _extract_mutmut_status,
    _update_mutmut_stats,
    analyze,
    parse_mutmut,
    parse_survivors,
)


# ---------------------------------------------------------------------------
# Bug fix 1: _extract_mutmut_module returns the dotted module path (group 1)
# ---------------------------------------------------------------------------

class TestExtractMutmutModule:
    """Verify _extract_mutmut_module returns the full dotted path, not just the function name."""

    def test_dotted_path_returns_full_module(self):
        """BUG FIX 1: group(1) must return the full dotted module path."""
        line = "harness_quality_gate.adapters.base.x_func__mutmut_42: survived"
        result = _extract_mutmut_module(line)
        assert result == "harness_quality_gate.adapters.base"
        assert result != "x_func"  # Must NOT be the function name

    def test_nested_module_path(self):
        """Deeper module hierarchies are also preserved correctly."""
        line = "harness_quality_gate.adapters.python.mutmut_adapter.x_func__mutmut_8: survived"
        result = _extract_mutmut_module(line)
        assert result == "harness_quality_gate.adapters.python.mutmut_adapter"

    def test_simple_module(self):
        """Single-level module names work too."""
        line = "src.calculations.x_func__mutmut_42: killed"
        result = _extract_mutmut_module(line)
        assert result == "src.calculations"

    def test_pyc_file_returns_filename_stem(self):
        """MUTMUT_PYC_FILE should return just the filename stem."""
        line = "base.py::x_func__mutmut_7: timeout"
        result = _extract_mutmut_module(line)
        assert result == "base"

    def test_pyc_file_without_pyc_suffix(self):
        """MUTMUT_PYC_FILE handles paths already without .py extension."""
        line = "base.py::x_func__mutmut_7: timeout"
        result = _extract_mutmut_module(line)
        assert isinstance(result, str)
        assert result == "base"

    def test_unrecognized_line_returns_none(self):
        """Lines that don't match either regex return None."""
        assert _extract_mutmut_module("not a valid mutmut line") is None
        assert _extract_mutmut_module("") is None

    def test_status_extraction(self):
        """Verify status is correctly extracted from various lines."""
        assert _extract_mutmut_status("harness_quality_gate.base.x__mutmut_1: survived") == "survived"
        assert _extract_mutmut_status("harness_quality_gate.base.x__mutmut_2: killed") == "killed"
        assert _extract_mutmut_status("harness_quality_gate.base.x__mutmut_3: timeout") == "timeout"
        assert _extract_mutmut_status("harness_quality_gate.base.x__mutmut_4: skipped") == "skipped"


# ---------------------------------------------------------------------------
# Bug fix 3: _update_mutmut_stats propagates module_name
# ---------------------------------------------------------------------------

class TestUpdateMutmutStats:
    """Verify that ModuleMutStats.module is set when creating a new entry."""

    def test_new_stats_gets_module_name(self):
        """BUG FIX 3: module_name must be set when creating a new ModuleMutStats."""
        result = _update_mutmut_stats(None, "survived", module_name="harness_quality_gate.base")
        assert result.module == "harness_quality_gate.base"
        assert result.total == 1
        assert result.survived == 1
        assert result.killed == 0

    def test_existing_stats_preserves_module_name(self):
        """Existing stats should keep their module name."""
        existing = ModuleMutStats(module="my.module", total=5, killed=3, survived=2)
        result = _update_mutmut_stats(existing, "killed", module_name="harness_quality_gate.base")
        assert result.module == "my.module"
        assert result.total == 6
        assert result.killed == 4

    def test_multiple_statuses_accumulate(self):
        """Multiple statuses accumulate correctly on the same module."""
        stats = _update_mutmut_stats(None, "killed", module_name="mod")
        stats = _update_mutmut_stats(stats, "survived", module_name="mod")
        stats = _update_mutmut_stats(stats, "timeout", module_name="mod")
        stats = _update_mutmut_stats(stats, "skipped", module_name="mod")
        assert stats.module == "mod"
        assert stats.total == 4
        assert stats.killed == 1
        assert stats.survived == 1
        assert stats.timeout == 1
        assert stats.skipped == 1

    def test_kill_rate_full_kills(self):
        """Kill rate 1.0 when all mutants killed."""
        stats = ModuleMutStats(module="m", total=10, killed=10)
        assert stats.kill_rate == 1.0

    def test_kill_rate_zero_kills(self):
        """Kill rate 0.0 when 0 killed out of total > 0."""
        stats = _update_mutmut_stats(None, "survived", module_name="mod")
        assert stats.kill_rate == 0.0


# ---------------------------------------------------------------------------
# parse_survivors() — new feature
# ---------------------------------------------------------------------------

class TestParseSurvivors:
    """Test the new parse_survivors() function."""

    def _mock_result(self, stdout_text):
        return MagicMock(
            stdout=stdout_text,
            returncode=0,
            stderr="",
        )

    def test_basic_surviving_mutants(self):
        """Basic case: survive one mutant, return a SurvivedMutant object."""
        stdout = "harness_quality_gate.adapters.base.x_func__mutmut_8: survived\n"
        with patch(
            "harness_quality_gate.bmad.mutation_analyzer.subprocess.run",
            return_value=self._mock_result(stdout),
        ):
            result = parse_survivors(Path("/tmp/fake"))
        assert len(result) == 1
        assert isinstance(result[0], SurvivedMutant)
        assert result[0].module == "harness_quality_gate.adapters.base"
        assert result[0].status == "survived"
        assert result[0].file_path == "harness_quality_gate/adapters/base.py"

    def test_file_path_conversion(self):
        """BUG FIX 3 companion: file_path should convert dots to slashes + .py."""
        stdout = "harness_quality_gate.adapters.python.mutmut_adapter.worker__mutmut_42: survived\n"
        with patch(
            "harness_quality_gate.bmad.mutation_analyzer.subprocess.run",
            return_value=self._mock_result(stdout),
        ):
            result = parse_survivors(Path("/tmp/fake"))
        assert result[0].file_path == "harness_quality_gate/adapters/python/mutmut_adapter.py"

    def test_timeout_survivors_included(self):
        """Timeout mutants should also be captured."""
        stdout = "mod.worker__mutmut_5: timeout\n"
        with patch(
            "harness_quality_gate.bmad.mutation_analyzer.subprocess.run",
            return_value=self._mock_result(stdout),
        ):
            result = parse_survivors(Path("/tmp/fake"))
        assert len(result) == 1
        assert result[0].status == "timeout"

    def test_empty_output_returns_empty_list(self):
        """When mutmut returns no output, an empty list is returned."""
        with patch(
            "harness_quality_gate.bmad.mutation_analyzer.subprocess.run",
            return_value=self._mock_result(""),
        ):
            result = parse_survivors(Path("/tmp/fake"))
        assert result == []

    def test_mixed_statuses_excludes_killed(self):
        """Only survived and timeout are included; killed is filtered out."""
        stdout = (
            "mod.a__mutmut_1: survived\n"
            "mod.b__mutmut_2: killed\n"
            "mod.c__mutmut_3: timeout\n"
        )
        with patch(
            "harness_quality_gate.bmad.mutation_analyzer.subprocess.run",
            return_value=self._mock_result(stdout),
        ):
            result = parse_survivors(Path("/tmp/fake"))
        assert len(result) == 2
        statuses = {r.status for r in result}
        assert statuses == {"survived", "timeout"}

    def test_mixed_statuses_survived_only(self):
        """Only survived mutants are captured (no killed)."""
        stdout = (
            "mod.a__mutmut_1: survived\n"
            "mod.b__mutmut_2: killed\n"
        )
        with patch(
            "harness_quality_gate.bmad.mutation_analyzer.subprocess.run",
            return_value=self._mock_result(stdout),
        ):
            result = parse_survivors(Path("/tmp/fake"))
        assert len(result) == 1
        assert result[0].status == "survived"

    def test_sorting_by_file_path_then_mutant_id(self):
        """Results are sorted by file_path first, then mutant_id."""
        # Regex captures single-level modules: "a_module" (the dotted path before ".__")
        # All a_module lines produce file_path "a_module.py"
        # All z_module lines produce file_path "z_module.py"
        stdout = (
            "z_module.z__mutmut_2: survived\n"
            "a_module.a__mutmut_5: survived\n"
            "a_module.a__mutmut_1: survived\n"
            "a_module.b__mutmut_3: timeout\n"
        )
        with patch(
            "harness_quality_gate.bmad.mutation_analyzer.subprocess.run",
            return_value=self._mock_result(stdout),
        ):
            result = parse_survivors(Path("/tmp/fake"))
        assert len(result) == 4
        # Verify sorting: file_path first, then mutant_id within same file
        assert result[0].file_path == "a_module.py"
        assert result[0].mutant_id == "a__mutmut_1"
        assert result[1].file_path == "a_module.py"
        assert result[1].mutant_id == "a__mutmut_5"
        assert result[2].file_path == "a_module.py"
        assert result[2].mutant_id == "b__mutmut_3"
        assert result[3].file_path == "z_module.py"

    def test_multilevel_module_different_paths(self):
        """Multi-level dotted module paths produce different file paths."""
        stdout = (
            "harness_quality_gate.adapters.a__mutmut_1: survived\n"
            "harness_quality_gate.adapters.b__mutmut_2: survived\n"
            "harness_quality_gate.base.c__mutmut_3: timeout\n"
        )
        with patch(
            "harness_quality_gate.bmad.mutation_analyzer.subprocess.run",
            return_value=self._mock_result(stdout),
        ):
            result = parse_survivors(Path("/tmp/fake"))
        assert len(result) == 3
        # harness_quality_gate.adapters -> harness_quality_gate/adapters.py
        # harness_quality_gate.base    -> harness_quality_gate/base.py
        paths = [r.file_path for r in result]
        assert "harness_quality_gate/adapters.py" in paths
        assert "harness_quality_gate/base.py" in paths

    def test_fnf_returns_empty_list(self):
        """FileNotFoundError should return an empty list."""
        with patch(
            "harness_quality_gate.bmad.mutation_analyzer.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = parse_survivors(Path("/nonexistent"))
        assert result == []

    def test_timeout_returns_empty_list(self):
        """subprocess.TimeoutExpired should return an empty list."""
        with patch(
            "harness_quality_gate.bmad.mutation_analyzer.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="mutmut", timeout=120),
        ):
            result = parse_survivors(Path("/tmp/fake"))
        assert result == []

    def test_survived_mutant_dataclass_fields(self):
        """Verify SurvivedMutant has all expected fields."""
        survivor = SurvivedMutant(
            mutant_id="x__mutmut_1",
            module="test.mod",
            file_path="test/mod.py",
            status="survived",
        )
        assert survivor.mutant_id == "x__mutmut_1"
        assert survivor.module == "test.mod"
        assert survivor.file_path == "test/mod.py"
        assert survivor.status == "survived"


# ---------------------------------------------------------------------------
# Bug fix 2: parse_mutmut survivors_only parameter
# ---------------------------------------------------------------------------

class TestParseMutmutSurvivorsOnly:
    """Verify parse_mutmut accepts and respects the survivors_only parameter."""

    def _mock_result(self, stdout_text):
        return MagicMock(
            stdout=stdout_text,
            returncode=0,
            stderr="",
        )

    def test_survivors_only_true_no_all_flag(self):
        """When survivors_only=True, the command should NOT include --all true."""
        with patch(
            "harness_quality_gate.bmad.mutation_analyzer.subprocess.run",
            return_value=self._mock_result(""),
        ) as mock_run:
            parse_mutmut(Path("/tmp/fake"), survivors_only=True)
        # The command should be exactly ["mutmut", "results"]
        mock_run.assert_called_once()
        cmd = mock_run.call_args.args[0] if mock_run.call_args.args else mock_run.call_args.kwargs.get("args", [])
        assert cmd == ["mutmut", "results"]

    def test_survivors_only_false_includes_all_flag(self):
        """When survivors_only=False (default), --all true should be included."""
        with patch(
            "harness_quality_gate.bmad.mutation_analyzer.subprocess.run",
            return_value=self._mock_result(""),
        ) as mock_run:
            parse_mutmut(Path("/tmp/fake"), survivors_only=False)
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args.args[0] if call_args.args else call_args.kwargs.get("args", [])
        assert "--all" in cmd
        assert "true" in cmd

    def test_default_is_full_stats(self):
        """By default (no survivors_only arg), parse_mutmut runs full stats."""
        with patch(
            "harness_quality_gate.bmad.mutation_analyzer.subprocess.run",
            return_value=self._mock_result(""),
        ) as mock_run:
            parse_mutmut(Path("/tmp/fake"))
        call_args = mock_run.call_args
        cmd = call_args.args[0] if call_args.args else call_args.kwargs.get("args", [])
        assert "--all" in cmd
        assert "true" in cmd

    def test_survivors_only_module_name_propagated(self):
        """Module name should be set correctly in ModuleMutStats when using survivors_only."""
        stdout = "harness_quality_gate.adapters.base.x_func__mutmut_8: survived\n"
        with patch(
            "harness_quality_gate.bmad.mutation_analyzer.subprocess.run",
            return_value=self._mock_result(stdout),
        ):
            result = parse_mutmut(Path("/tmp/fake"), survivors_only=True)
        assert "harness_quality_gate.adapters.base" in result
        stats = result["harness_quality_gate.adapters.base"]
        assert stats.module == "harness_quality_gate.adapters.base"
        assert stats.survived == 1
        assert stats.total == 1

    def test_full_stats_module_name_propagated(self):
        """Module name should be set correctly with full stats (--all true)."""
        stdout = (
            "harness_quality_gate.adapters.base.x_func__mutmut_8: survived\n"
            "harness_quality_gate.adapters.base.y_func__mutmut_9: killed\n"
        )
        with patch(
            "harness_quality_gate.bmad.mutation_analyzer.subprocess.run",
            return_value=self._mock_result(stdout),
        ):
            result = parse_mutmut(Path("/tmp/fake"), survivors_only=False)
        assert "harness_quality_gate.adapters.base" in result
        stats = result["harness_quality_gate.adapters.base"]
        assert stats.module == "harness_quality_gate.adapters.base"
        assert stats.survived == 1
        assert stats.killed == 1
        assert stats.total == 2

    def test_parse_mutmut_fnf_returns_empty(self):
        """FileNotFoundError should return an empty dict."""
        with patch(
            "harness_quality_gate.bmad.mutation_analyzer.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = parse_mutmut(Path("/nonexistent"))
        assert result == {}

    def test_parse_mutmut_timeout_returns_empty(self):
        """subprocess.TimeoutExpired should return an empty dict."""
        with patch(
            "harness_quality_gate.bmad.mutation_analyzer.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="mutmut", timeout=120),
        ):
            result = parse_mutmut(Path("/tmp/fake"))
        assert result == {}


# ---------------------------------------------------------------------------
# Integration: analyze() calls parse_mutmut correctly
# ---------------------------------------------------------------------------

class TestAnalyze:
    """Verify the analyze() function still works correctly."""

    def test_analyze_calls_parse_mutmut_default(self):
        """analyze() should call parse_mutmut without survivors_only by default."""
        with patch(
            "harness_quality_gate.bmad.mutation_analyzer.parse_mutmut",
            return_value={"mod": ModuleMutStats(module="mod", total=10, killed=8, survived=2)},
        ) as mock_parse:
            with patch(
                "harness_quality_gate.bmad.mutation_analyzer.parse_infection",
                return_value={},
            ):
                result = analyze(Path("/tmp/fake"), tool="mutmut")
        assert result.tool == "mutmut"
        # Verify parse_mutmut was called with default (survivors_only=False for full stats)
        assert mock_parse.call_count == 1
        call_kwargs = mock_parse.call_args.kwargs
        assert call_kwargs.get("survivors_only", False) is False
        assert isinstance(result, MutationStats)
        assert result.modules["mod"].module == "mod"

    def test_analyze_calls_parse_infection(self):
        """analyze() with tool=infection should call parse_infection."""
        with patch(
            "harness_quality_gate.bmad.mutation_analyzer.parse_infection",
            return_value={"Greeter": ModuleMutStats(module="Greeter", total=5, killed=4, survived=1)},
        ) as mock_parse:
            with patch(
                "harness_quality_gate.bmad.mutation_analyzer.parse_mutmut",
                return_value={},
            ) as mock_mutmut:
                result = analyze(Path("/tmp/fake"), tool="infection")
        assert result.tool == "infection"
        assert mock_parse.call_count == 1
        mock_mutmut.assert_not_called()
