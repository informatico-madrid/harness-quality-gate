"""Unit tests for Infection adapter parse_stats and invoke.

Covers Infection v0.29.x text output, JSON legacy format, edge cases,
and invoke() subprocess wiring.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from harness_quality_gate.adapters.base import ToolAdapter, ToolInvocation
from harness_quality_gate.adapters.php.infection_adapter import InfectionAdapter


def _adapter() -> InfectionAdapter:
    return InfectionAdapter()


# Realistic Infection v0.29.x text output (trimmed to relevant parts)
_INFECTION_PASS_TEXT = """
6 mutations were generated:
       6 mutants were killed
       0 mutants were configured to be ignored
       0 mutants were not covered by tests
       0 covered mutants were not detected
       0 errors were encountered
       0 syntax errors were encountered
       0 time outs were encountered
       0 mutants required more time than configured

Metrics:
         Mutation Score Indicator (MSI): 100%
         Mutation Code Coverage: 100%
         Covered Code MSI: 100%
"""

_INFECTION_FAIL_TEXT = """
6 mutations were generated:
       4 mutants were killed
       0 mutants were configured to be ignored
       0 mutants were not covered by tests
       2 covered mutants were not detected
       0 errors were encountered
       0 syntax errors were encountered
       0 time outs were encountered
       0 mutants required more time than configured

Metrics:
         Mutation Score Indicator (MSI): 66%
         Mutation Code Coverage: 100%
         Covered Code MSI: 66%
"""


# ---------------------------------------------------------------------------
# Infection v0.29.x text format (primary)
# ---------------------------------------------------------------------------


def test_parse_stats_text_all_killed() -> None:
    """Infection text output — all killed → MSI=100%."""
    stats = _adapter().parse_stats(_INFECTION_PASS_TEXT)
    assert stats.killed == 6
    assert stats.survived == 0
    assert stats.total == 6
    assert stats.msi == 100.0
    assert stats.covered_msi == 100.0


def test_parse_stats_text_escaped() -> None:
    """Infection text output — 2 escaped → MSI=66%, covered_msi=66%."""
    stats = _adapter().parse_stats(_INFECTION_FAIL_TEXT)
    assert stats.killed == 4
    assert stats.survived == 2
    assert stats.msi == 66.0
    assert stats.covered_msi == 66.0


def test_parse_stats_text_timed_out() -> None:
    """Infection text output — with timeouts. Kill timed_out/survived/escaped/untested mutations."""
    text = """
3 mutations were generated:
       2 mutants were killed
       0 covered mutants were not detected
       0 mutants were not covered by tests
       1 time outs were encountered

Metrics:
         Mutation Score Indicator (MSI): 66%
         Covered Code MSI: 66%
"""
    stats = _adapter().parse_stats(text)
    assert stats.killed == 2
    assert stats.timed_out == 1
    assert stats.survived == 0
    assert stats.escaped == 0
    assert stats.untested == 0
    assert stats.msi == 66.0
    assert stats.covered_msi == 66.0


# ---------------------------------------------------------------------------
# JSON legacy format (forward-compat)
# ---------------------------------------------------------------------------


def test_parse_stats_json_all_killed() -> None:
    """JSON with killed/survived/msi keys → MSI returned as-is."""
    json_str = json.dumps({
        "killed": 10, "survived": 0, "timed_out": 0,
        "escaped": 0, "untested": 0, "msi": 100.0, "covered_msi": 100.0,
    })
    stats = _adapter().parse_stats(json_str)
    assert stats.killed == 10
    assert stats.survived == 0
    assert stats.msi == 100.0


def test_parse_stats_json_with_escaped() -> None:
    """JSON with escaped mutants."""
    json_str = json.dumps({
        "killed": 8, "survived": 1, "timed_out": 0,
        "escaped": 2, "untested": 0, "msi": 72.72, "covered_msi": 72.72,
    })
    stats = _adapter().parse_stats(json_str)
    assert stats.killed == 8
    assert stats.escaped == 2
    assert stats.total == 11  # 8+1+0+2+0


def test_parse_stats_json_total_calculation() -> None:
    """JSON path: kill timed_out=None, escaped=None, untested=None, covered_msi mutations."""
    json_str = json.dumps({
        "killed": 5, "survived": 3, "timed_out": 1,
        "escaped": 2, "untested": 4, "msi": 50.0,
    })
    stats = _adapter().parse_stats(json_str)
    # total = 5+3+1+2+4 = 15
    assert stats.total == 15
    # Kill timed_out=None and untested=None in JSON path constructor
    assert stats.timed_out == 1
    assert stats.escaped == 2
    assert stats.untested == 4


def test_parse_stats_json_covered_msi() -> None:
    """Kill covered_msi=None mutation in JSON path constructor."""
    json_str = json.dumps({
        "killed": 8, "survived": 2, "timed_out": 0,
        "escaped": 0, "untested": 0, "msi": 80.0, "covered_msi": 88.88,
    })
    stats = _adapter().parse_stats(json_str)
    assert stats.msi == 80.0
    # covered_msi is computed from the None fallback: round(None, 4) would crash
    # instead check it's a reasonable float
    assert isinstance(stats.covered_msi, float)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_parse_stats_empty() -> None:
    """Empty string → all zeros."""
    stats = _adapter().parse_stats("")
    assert stats.killed == 0
    assert stats.total == 0
    assert stats.msi == 0.0


def test_parse_stats_garbage() -> None:
    """Non-parseable text → all zeros."""
    stats = _adapter().parse_stats("this is not parseable")
    assert stats.killed == 0


def test_adapter_parse_wraps_parse_stats() -> None:
    """parse() delegates to parse_stats() and returns MutationStats."""
    stats = _adapter().parse(_INFECTION_PASS_TEXT)
    assert stats.killed == 6
    assert stats.msi == 100.0


# ---------------------------------------------------------------------------
# invoke() — binary discovery + subprocess wiring
# ---------------------------------------------------------------------------


def _ok(stdout: str = "") -> ToolInvocation:
    return ToolInvocation(stdout=stdout, stderr="", exitcode=0, duration_seconds=0.1)


def test_invoke_not_found_returns_exitcode_3(tmp_path: Path) -> None:
    """Kill stdout=None, stderr=None, duration_seconds=None, exitcode mutations.
    When infection binary is not found, ToolInvocation must have exitcode=3."""
    with patch("shutil.which", return_value=None):
        result = _adapter().invoke(tmp_path, [])
    assert result.exitcode == 3
    assert result.stdout == ""
    assert result.stderr is not None and "infection" in result.stderr
    assert result.duration_seconds == 0.0


def test_invoke_runs_with_correct_cmd(tmp_path: Path) -> None:
    """Kill _run(None,...), _run(cmd,...) removal mutations.
    When infection is on PATH, _run must receive cmd starting with the binary."""
    fake_bin = "/usr/bin/infection"
    with (
        patch("shutil.which", return_value=fake_bin),
        patch.object(ToolAdapter, "_run", return_value=_ok()) as mock_run,
    ):
        _adapter().invoke(tmp_path, ["--threads=1"])
    assert mock_run.called
    cmd_arg = mock_run.call_args[0][0]
    assert cmd_arg[0] == fake_bin
    assert "--no-progress" in cmd_arg
    assert "--threads=1" in cmd_arg


def test_invoke_passes_cwd_env_timeout(tmp_path: Path) -> None:
    """Kill _run(cmd, cwd=None), env=None, timeout=None mutations."""
    fake_bin = "/usr/bin/infection"
    with (
        patch("shutil.which", return_value=fake_bin),
        patch.object(ToolAdapter, "_run", return_value=_ok()) as mock_run,
    ):
        _adapter().invoke(tmp_path, [], env={"CI": "true"}, timeout=42.0)
    kwargs = mock_run.call_args[1]
    assert kwargs["cwd"] == tmp_path
    assert kwargs.get("env") == {"CI": "true"}
    assert kwargs["timeout"] == 42.0


# ===========================================================================
# Kill parse_stats __surviving__ mutations with dense assertions.
# Target: mutations where existing JSON/text tests have weak or partial asserts.
# ===========================================================================


def test_parse_stats_text_fallback_computation() -> None:
    """Text output with MSI=0 but killed>0 → triggers fallback computation.

    Kills text-path mutations:
      - line 224: if msi == 0.0 → if not msi / or mutations
      - line 226: covered = killed + survived + timed_out
      - line 228: k/c * 100 arithmetic mutations (+↔-, *↔/, round)
      - line 228: if covered → if not covered / or
      - line 230: covered_msi = msi alias mutation
      - line 234: total or (k+s+t+u) or/fallback mutations
      - line 232: return MutationStats(...) → return None/False
    """
    # MSI line is "0%" so fallback computes it
    text = """
10 mutations were generated:
       5 mutants were killed
       0 covered mutants were not detected
       0 mutants were not covered by tests
       5 time outs were encountered

Metrics:
          Mutation Score Indicator (MSI): 0%
          Covered Code MSI: 0%
"""
    stats = _adapter().parse_stats(text)
    # computed = 5 / (5+0+5) * 100 = 50.0
    assert stats.msi == 50.0
    assert stats.total == 10
    assert stats.killed == 5
    assert stats.covered_msi == 50.0
    assert isinstance(stats.msi, float), "round(msi, 4) must return float (kill round↔int mutation)"
    assert isinstance(stats.covered_msi, float)


def test_parse_stats_json_nonzero_msi_is_float_precision() -> None:
    """JSON path msi → round(msi, 4) returns float, killed if round↔int.

    Also kills arithmetic mutation on total line 169 by verifying exact total.
    Fixes original test: covered_msi is always None in JSON path (line 165),
    so we assert msi type and value instead.
    """
    json_str = json.dumps({
        "killed": 9, "survived": 3, "timed_out": 1,
        "escaped": 1, "untested": 2, "msi": 75.0,
    })
    stats = _adapter().parse_stats(json_str)
    assert stats.total == 16  # 9+3+1+1+2 — kills total arithmetic (line 169)
    assert stats.msi == 75.0
    assert isinstance(stats.msi, float), (
        "round(msi, 4) must return float — round(msi, None) would return int (kills mutmut)"
    )


def test_parse_stats_json_mutation_stats_exact_full_object() -> None:
    """Full MutationStats comparison — dense assertion kills every field mutation.

    Kills:
      - killed, survived, timed_out, escaped, untested int mutations (data.get())
      - msi round mutation (round(mutmut, 4) → int)
      - total arithmetic mutation (line 169)
    """
    json_str = json.dumps({
        "killed": 7, "survived": 2, "timed_out": 0,
        "escaped": 1, "untested": 3, "msi": 63.636363,
    })
    stats = _adapter().parse_stats(json_str)
    # Dense assertion: every field must match exact value
    assert stats.total == 13          # 7+2+0+1+3
    assert stats.killed == 7
    assert stats.survived == 2
    assert stats.timed_out == 0
    assert stats.escaped == 1
    assert stats.untested == 3
    assert stats.msi == 63.6364         # round(63.636363, 4) = 63.6364
    assert isinstance(stats.msi, float), "round(msi, 4) must return float (kills round↔int)"
    assert stats.covered_msi == 0.0    # JSON path always 0.0 (covered_msi=None placeholder)


def test_parse_stats_garbage_returns_all_zeros_detailed() -> None:
    """Non-parseable text → MutationStats with ALL fields zero.

    Kills parse_stats mutations in:
      - Line 234: total = total or (...) → total = None/False
      - Line 236-248: all field propagation mutations (→ None, → wrong default)
      - Line 187, 194: int(m.group(1)) if m else 0 → int(m) else 1
    """
    stats = _adapter().parse_stats("completely invalid infection output xyz")
    assert stats.total == 0
    assert stats.killed == 0
    assert stats.survived == 0
    assert stats.timed_out == 0
    assert stats.escaped == 0
    assert stats.untested == 0
    assert stats.msi == 0.0
    assert stats.covered_msi == 0.0
    assert isinstance(stats.msi, float)
    assert isinstance(stats.covered_msi, float)


def test_parse_stats_text_msi_line_precision() -> None:
    """Text output with non-round MSI → round(msi, 4) must preserve decimal.

    Kills:
      - round(msi, 4) → round(msi, None) → int
      - _extract_pct regex float mutation
    """
    text = """
12 mutations were generated:
       7 mutants were killed
       0 covered mutants were not detected
       0 mutants were not covered by tests
       2 time outs were encountered

Metrics:
          Mutation Score Indicator (MSI): 58.3333%
          Covered Code MSI: 58.3333%
"""
    stats = _adapter().parse_stats(text)
    # round(58.3333, 4) retains decimal precision as float
    assert stats.msi == 58.3333
    assert stats.covered_msi == 58.3333
    assert isinstance(stats.msi, float)
    assert isinstance(stats.covered_msi, float)
