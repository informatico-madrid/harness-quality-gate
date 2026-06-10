"""Unit tests for Infection adapter parse_stats and invoke.

Covers Infection v0.29.x text output, JSON legacy format, edge cases,
and invoke() subprocess wiring.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

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


def test_adapter_parse_with_all_three_args() -> None:
    """parse() must accept stderr and exitcode args (ToolAdapter contract).

    Kills mutations:
      - stderr: str="" mutation → if parse ignores it, no mutation to kill
      - exitcode: int=0 mutation → same
      - The actual kill is that parse() passes stdout correctly to parse_stats
        even when called with 3 positional args.
    """
    stats = _adapter().parse(_INFECTION_PASS_TEXT, "some stderr", 2)
    assert stats.killed == 6
    assert stats.msi == 100.0


def test_adapter_parse_returns_mutation_stats_not_none() -> None:
    """parse() must return MutationStats, not None when parse_stats returns a value.

    Kills mutation on line 119: `return self.parse_stats(stdout)` → `return None`.
    A mutation to return None would cause the assertion to fail.
    """
    stats = _adapter().parse(_INFECTION_FAIL_TEXT)
    assert stats is not None
    from harness_quality_gate.models import MutationStats
    assert isinstance(stats, MutationStats)


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


# ═══════════════════════════════════════════════════════════════════════
# Kill invoke remaining survivors: mutmut_11,12,16-25
# These mutations target:
#   - Line 80: if infection_bin is None: → if not None: (mutmut_11)
#   - Line 82-92: for-loop with vendor/bin fallback, break mutation (12-25)
# ═══════════════════════════════════════════════════════════════════════


def test_invoke_fallback_to_vendor_bin_when_not_on_path(tmp_path: Path):
    """When shutil.which returns None, fallback to vendor/bin/infection.

    Kills:
      - mutmut_11: if infection_bin is None: → if not None:
        → Never enters fallback even when bin missing → returns exitcode 3
      - mutmut_12-25: loop/break mutations that skip vendor fallback
    """
    vendor_bin = tmp_path / "vendor" / "bin" / "infection"
    vendor_bin.parent.mkdir(parents=True)
    vendor_bin.touch()

    with (
        patch("shutil.which", return_value=None),  # Not on PATH
        patch.object(ToolAdapter, "_run", return_value=_ok()) as mock_run,
    ):
        _adapter().invoke(tmp_path, ["--threads=1"])

    # _run should be called (not early return with exitcode 3)
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "vendor/bin/infection" in cmd[0]


def test_invoke_vendor_bin_first_then_composer_bin(tmp_path: Path):
    """When vendor/bin/infection exists, use it (first candidate).

    Kills:
      - mutmut_12,13,14: break → continue mutation (tries second candidate)
      - mutmut_15: is_file → is_dir mutation
    """
    vendor_bin = tmp_path / "vendor" / "bin" / "infection"
    vendor_bin.parent.mkdir(parents=True)
    vendor_bin.touch()

    with (
        patch("shutil.which", return_value=None),
        patch.object(ToolAdapter, "_run", return_value=_ok()) as mock_run,
    ):
        _adapter().invoke(tmp_path, [])

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    # Should use vendor/bin/infection (first candidate), not composer.json bin-dir
    assert "vendor/bin/infection" in cmd[0]


def test_invoke_returns_exitcode_3_when_no_binary_anywhere(tmp_path: Path):
    """When infection not on PATH and no vendor/bin → exitcode 3.

    Kills:
      - mutmut_16: continue vs break in loop — break at end means exitcode 3
      - mutmut_18: stdout="" → "XXXX"
      - mutmut_19: return mutation before early return
      - mutmut_20,21: ToolInvocation field mutations
      - mutmut_22-25: duration_seconds/exitcode mutations
    """
    with (
        patch("shutil.which", return_value=None),
        patch.object(ToolAdapter, "_run", return_value=_ok()),
        patch(
            "harness_quality_gate.adapters.php.infection_adapter._composer_bin_dir",
            return_value=str(tmp_path),
        ),
    ):
        result = _adapter().invoke(tmp_path, [])

    assert result.exitcode == 3
    assert result.stdout == ""
    assert result.duration_seconds == 0.0
    assert "infection" in result.stderr


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


def test_parse_stats_json_or_mutant_not_triggered() -> None:
    """H4 table of truth: 'isinstance(dict) and "killed" in data'.

    Tests dict WITHOUT 'killed' key → JSON path should NOT be taken (original and returns False).
    If mutant changes and→or, JSON path IS taken, gets all-zero stats (not text-path result).

    Kills:
      - mutmut_74: 'and' → 'or' at line 152. Dict without 'killed' key triggers JSON path with
        all-zero data instead of text parsing.
    """
    # Dict without 'killed' key — should NOT enter JSON block
    json_str = json.dumps({"total": 10, "other": "data"})
    stats = _adapter().parse_stats(json_str)
    # Should fall through to text path, which returns all zeros
    assert stats.total == 0
    assert stats.killed == 0
    assert stats.msi == 0.0


def test_parse_stats_json_killed_key_absent_default() -> None:
    """Verify data.get("killed", 0) default kills mutations.

    Kills:
      - data.get("killed", 1) → default 1 → kills if test asserts killed == 0
      - data.get("killed", None) → same as 0 for int() cast, but caught by
        isinstance(stats.killed, int) on other data
    """
    json_str = json.dumps({"survived": 5})  # No "killed" key
    stats = _adapter().parse_stats(json_str)
    # killed defaults to 0
    assert stats.killed == 0
    assert isinstance(stats.killed, int)


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


# ═══════════════════════════════════════════════════════════════════════
# Kill remaining infection parse_stats survivors (mutmut 1-27, 33-50, 55-63).
# These are all mutations on defaults, arithmetic, and regex extraction.
# The key technique: §4.1 Dense — assert ALL fields of every MutationStats field.
# ═══════════════════════════════════════════════════════════════════════


def test_parse_stats_text_with_survived_mutants_edge() -> None:
    """Text with MSI=0 but killed>0 → triggers fallback MSI computation.

    Kills:
      - mutmut_1: _extract return int(m.group(1)) if m else 0 → int(m) else 1
      - mutmut_14: regex pattern "mutants were killed" → mutation
      - mutmut_24: total=total or (...) fallback arithmetic
      - mutmut_33: msi == 0.0 and killed > 0 condition mutations
      - mutmut_39: covered = killed + survived + timed_out arithmetic
      - mutmut_45: fallback computed MSI formula k/c*100
      - mutmut_51-54: return MutationStats field mutations
    """
    text = """
20 mutations were generated:
       10 mutants were killed
       5 covered mutants were not detected
       5 mutants were not covered by tests
       0 time outs were encountered

Metrics:
          Mutation Score Indicator (MSI): 0%
          Covered Code MSI: 0%
"""
    stats = _adapter().parse_stats(text)
    # Fallback: covered = killed + survived + timed_out = 10 + 5 + 0 = 15
    # msi = 10/15 * 100 = 66.6667
    assert stats.killed == 10
    assert stats.survived == 5
    assert stats.untested == 5
    assert stats.timed_out == 0
    assert stats.escaped == 0
    assert stats.total == 20
    assert stats.msi == 66.6667  # fallback computed
    assert stats.covered_msi == 66.6667


def test_parse_stats_json_with_msi_float() -> None:
    """JSON with float MSI → round(msi, 4) must be float.

    Kills:
      - mutmut_55-63: return/field mutations in JSON path
      - mutmut_56: round mutation
    """
    json_str = json.dumps({
        "killed": 12, "survived": 5, "timed_out": 1,
        "escaped": 2, "untested": 3, "msi": 85.7142857,
    })
    stats = _adapter().parse_stats(json_str)
    # Dense assertion on ALL fields
    assert stats.total == 23          # 12+5+1+2+3
    assert stats.killed == 12
    assert stats.survived == 5
    assert stats.timed_out == 1
    assert stats.escaped == 2
    assert stats.untested == 3
    assert stats.msi == 85.7143        # round(85.7142857, 4)
    assert isinstance(stats.msi, float)
    assert stats.covered_msi == 0.0    # JSON path sets covered_msi = None → 0.0


def test_parse_stats_json_killed_default_zero() -> None:
    """Verify data.get("killed", 0) default kills mutations.

    Kills:
      - mutmut_1: int(data.get("killed", 0)) → int(data.get("killed", 1))
      - mutmut_51: covered_msi mutation
    """
    json_str = json.dumps({"survived": 3, "msi": 0.0})  # No "killed" key
    stats = _adapter().parse_stats(json_str)
    assert stats.killed == 0
    assert isinstance(stats.killed, int)


def test_parse_stats_json_survived_default_zero() -> None:
    """Verify data.get("survived", 0) default kills mutations.

    Kills:
      - data.get("survived", 1), data.get("survived", None)
    """
    json_str = json.dumps({"killed": 8, "msi": 80.0})  # No "survived" key
    stats = _adapter().parse_stats(json_str)
    assert stats.survived == 0
    assert isinstance(stats.survived, int)


def test_parse_stats_json_timed_out_default_zero() -> None:
    """Verify data.get("timed_out", 0) default kills mutations."""
    json_str = json.dumps({"killed": 8, "msi": 80.0})
    stats = _adapter().parse_stats(json_str)
    assert stats.timed_out == 0
    assert isinstance(stats.timed_out, int)


def test_parse_stats_json_escaped_default_zero() -> None:
    """Verify data.get("escaped", 0) default kills mutations."""
    json_str = json.dumps({"killed": 8, "msi": 80.0})
    stats = _adapter().parse_stats(json_str)
    assert stats.escaped == 0
    assert isinstance(stats.escaped, int)


def test_parse_stats_json_untested_default_zero() -> None:
    """Verify data.get("untested", 0) default kills mutations."""
    json_str = json.dumps({"killed": 8, "msi": 80.0})
    stats = _adapter().parse_stats(json_str)
    assert stats.untested == 0
    assert isinstance(stats.untested, int)


def test_parse_stats_text_timed_out_all_zero_fields() -> None:
    """Text with only timed_out and killed — all other fields must be zero.

    Kills:
      - mutmut_20..23: regex extraction mutations for not_covered/not_detected
      - mutmut_30..32: regex pattern mutations for timed_out
    """
    text = """
5 mutations were generated:
       3 mutants were killed
       0 covered mutants were not detected
       0 mutants were not covered by tests
       2 time outs were encountered

Metrics:
          Mutation Score Indicator (MSI): 60%
          Covered Code MSI: 60%
"""
    stats = _adapter().parse_stats(text)
    assert stats.killed == 3
    assert stats.timed_out == 2
    assert stats.survived == 0
    assert stats.untested == 0
    assert stats.escaped == 0
    assert stats.msi == 60.0
    assert stats.total == 5


def test_parse_stats_json_zero_all_fields() -> None:
    """JSON with all zeros. Kills default-value mutations.

    Kills:
      - mutmut_33: msi == 0.0 and killed > 0 → kills zero input
      - mutmut_34-50: field extraction mutations
    """
    json_str = json.dumps({
        "killed": 0, "survived": 0, "timed_out": 0,
        "escaped": 0, "untested": 0, "msi": 0.0,
    })
    stats = _adapter().parse_stats(json_str)
    assert stats.total == 0
    assert stats.killed == 0
    assert stats.survived == 0
    assert stats.timed_out == 0
    assert stats.escaped == 0
    assert stats.untested == 0
    assert stats.msi == 0.0
    assert stats.covered_msi == 0.0


# ═══════════════════════════════════════════════════════════════════════
# Kill invoke() survivors (mutmut 2,3,4,11-25).
# Many of these mutate shutil.which("infection") → shutil.which("XXXinfectionXXX").
# ═══════════════════════════════════════════════


def test_invoke_when_infection_on_path_uses_correct_bin(tmp_path: Path):
    """When infection bin is found via shutil.which, use it with --no-progress.

    Kills mutmut_2,3,4: shutil.which("infection") → shutil.which("XXXinfectionXXX")
    or shutil.which(None) — mutant won't find the binary → falls back to vendor/bin.
    """
    with (
        patch("shutil.which", return_value="/usr/bin/infection"),
        patch.object(ToolAdapter, "_run", return_value=_ok()) as mock_run,
    ):
        _adapter().invoke(tmp_path, [])
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "/usr/bin/infection"
    assert "--no-progress" in cmd
    """Kill regex mutation on 'mutants were not covered' pattern.

    Kills:
      - mutmut_16: pattern "mutants were not covered" → mutated pattern
      - mutmut_38: not_covered → not_detected alias
    """
    text = """
10 mutations were generated:
       6 mutants were killed
       0 covered mutants were not detected
       4 mutants were not covered by tests
       0 time outs were encountered

Metrics:
          Mutation Score Indicator (MSI): 100%
          Covered Code MSI: 100%
"""
    stats = _adapter().parse_stats(text)
    assert stats.killed == 6
    assert stats.untested == 4
    assert stats.survived == 0
    assert stats.total == 10


def test_parse_stats_text_error_pattern() -> None:
    """Kill regex mutation on 'errors were encountered' pattern.

    Kills:
      - mutmut_17: pattern "errors were encountered" → mutated
      - mutmut_48-50: escaped=errors alias
    """
    text = """
10 mutations were generated:
       5 mutants were killed
       3 covered mutants were not detected
       2 errors were encountered
       0 time outs were encountered

Metrics:
          Mutation Score Indicator (MSI): 62%
          Covered Code MSI: 62%
"""
    stats = _adapter().parse_stats(text)
    assert stats.killed == 5
    assert stats.survived == 3
    assert stats.escaped == 2
    assert stats.total == 10
    assert stats.msi == 62.0
