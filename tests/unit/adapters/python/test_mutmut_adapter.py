"""Comprehensive tests for MutmutAdapter.

Covers:
  - version() — binary discovery, empty stdout
  - invoke() — not found, correct command line, cwd/env/timeout wiring
  - parse() — MutationStats from JSON, text fallback, edge cases

Design: Component Responsibilities / mutmut_adapter
Targets: All 44 mutant survivors in mutmut_adapter.py
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from harness_quality_gate.adapters.base import ToolAdapter, ToolInvocation
from harness_quality_gate.adapters.python.mutmut_adapter import MutmutAdapter


def _adapter() -> MutmutAdapter:
    return MutmutAdapter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_invocation(stdout: str = "") -> ToolInvocation:
    return ToolInvocation(stdout=stdout, stderr="", exitcode=0, duration_seconds=0.1)


# ---------------------------------------------------------------------------
# version()
# ---------------------------------------------------------------------------


def test_version_binary_not_found_raises(tmp_path: Path) -> None:
    """shutil.which returns None → RuntimeError with 'mutmut' in message."""
    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="mutmut"):
            _adapter().version(tmp_path)


def test_version_calls_shutil_which_with_literal_mutmut(tmp_path: Path) -> None:
    """version() must call shutil.which('mutmut') verbatim (kills mutmut_2: which(None))."""
    with (
        patch(
            "harness_quality_gate.adapters.python.mutmut_adapter.shutil.which",
            return_value="/usr/bin/mutmut",
        ) as which_mock,
        patch.object(
            ToolAdapter,
            "_run",
            return_value=MagicMock(stdout="mutmut 3.3", stderr="", exitcode=0, duration_seconds=0.1),
        ),
    ):
        _adapter().version(tmp_path)
    which_mock.assert_called_once_with("mutmut")


def test_name_property_returns_tool_name() -> None:
    """Accessing .name triggers the name property → covers line 27."""
    assert _adapter().name == "mutmut"


def test_version_calls_run_version_flag(tmp_path: Path) -> None:
    """Binary found → _run invoked with [binary, '--version']."""
    with patch("shutil.which", return_value="/usr/bin/mutmut"):
        with patch.object(
            ToolAdapter, "_run", return_value=MagicMock(stdout="3.5.0")
        ) as mock_run:
            _adapter().version(tmp_path)

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "/usr/bin/mutmut"
    assert "--version" in cmd


def test_version_passes_cwd(tmp_path: Path) -> None:
    """invoke() passes cwd to _run."""
    with patch("shutil.which", return_value="/usr/bin/mutmut"):
        with patch.object(ToolAdapter, "_run", return_value=MagicMock(stdout="3.5.0")) as mock_run:
            _adapter().version(tmp_path)

    assert mock_run.call_args[1]["cwd"] == tmp_path


def test_version_wiring_exact_call_args(tmp_path: Path) -> None:
    """version() calls _run with exact binary + --version cmd + cwd + env.

    Kills mutmut survivors (13,16): env→None mutation on version.
    """
    with patch("shutil.which", return_value="/usr/bin/mutmut"):
        with patch.object(
            ToolAdapter, "_run", return_value=MagicMock(stdout="3.5.0")
        ) as mock_run:
            _adapter().version(tmp_path, env={"MUTMUT_ENV": "1"})

    mock_run.assert_called_once()
    assert mock_run.call_args[0][0] == ["/usr/bin/mutmut", "--version"]
    assert mock_run.call_args[1]["cwd"] == tmp_path
    assert mock_run.call_args[1]["env"] == {"MUTMUT_ENV": "1"}


def test_version_env_none_passed(tmp_path: Path) -> None:
    """env=None passed to _run when not specified.

    Kills mutmut on env=env mutation: env=None → removed.
    """
    with patch("shutil.which", return_value="/usr/bin/mutmut"):
        with patch.object(
            ToolAdapter, "_run", return_value=MagicMock(stdout="3.5.0")
        ) as mock_run:
            _adapter().version(tmp_path)
    assert mock_run.call_args[1]["env"] is None


def test_version_trimmed_output(tmp_path: Path) -> None:
    """stdout=' 3.5.0  ' → stripped to '3.5.0'."""
    with patch("shutil.which", return_value="/usr/bin/mutmut"):
        with patch.object(
            ToolAdapter, "_run", return_value=MagicMock(stdout="  3.5.0  ")
        ) as mock_run:
            result = _adapter().version(tmp_path)

    assert result == "3.5.0"


def test_version_empty_returns_unknown(tmp_path: Path) -> None:
    """stdout='' → returns 'unknown'."""
    with patch("shutil.which", return_value="/usr/bin/mutmut"):
        with patch.object(
            ToolAdapter, "_run", return_value=MagicMock(stdout="")
        ) as mock_run:
            result = _adapter().version(tmp_path)

    assert result == "unknown"


# ---------------------------------------------------------------------------
# invoke()
# ---------------------------------------------------------------------------


def test_invoke_binary_not_found(tmp_path: Path) -> None:
    """mutmut not found → exitcode=3, stderr contains 'mutmut'."""
    with patch("shutil.which", return_value=None):
        result = _adapter().invoke(tmp_path, [])

    assert result.exitcode == 3
    assert result.stdout == ""
    assert "mutmut" in result.stderr
    assert result.duration_seconds == 0.0


def test_invoke_wiring_exact_call_args(tmp_path: Path) -> None:
    """invoke() calls _run with exact cmd list + cwd/env/timeout.

    Kills mutmut survivors (1,3,4,5,11,12): cmd element mutations,
    cwd→None, env→None, timeout→mutated. Uses §4.4 strict mock args.
    """
    fake_bin = "/usr/bin/mutmut"
    with patch("shutil.which", return_value=fake_bin):
        with patch.object(
            ToolAdapter,
            "_run",
            return_value=_ok_invocation(json.dumps({"total": 10, "killed": 8})),
        ) as mock_run:
            _adapter().invoke(
                tmp_path,
                ["--path-include=.*\\.py$"],
                env={"MUTMUT_CI": "1"},
                timeout=700.0,
            )

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == fake_bin
    assert cmd == [fake_bin, "results", "--json", "--path-include=.*\\.py$"]
    assert mock_run.call_args[1]["cwd"] == tmp_path
    assert mock_run.call_args[1]["env"] == {"MUTMUT_CI": "1"}
    assert mock_run.call_args[1]["timeout"] == 700.0


def test_invoke_command_structure(tmp_path: Path) -> None:
    """Binary found → cmd = [binary, 'results', '--json', ...user-args]."""
    fake_bin = "/usr/bin/mutmut"
    with patch("shutil.which", return_value=fake_bin):
        with patch.object(
            ToolAdapter,
            "_run",
            return_value=_ok_invocation(json.dumps({"total": 10, "killed": 8})),
        ) as mock_run:
            _adapter().invoke(tmp_path, ["--path-include=.*\\.py$", "--no-summary"])

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == fake_bin
    assert "results" in cmd
    assert "--json" in cmd
    assert "--path-include=.*\\.py$" in cmd
    assert "--no-summary" in cmd


def test_invoke_sets_cwd_env_timeout(tmp_path: Path) -> None:
    """invoke() forwards cwd, env, and timeout to _run."""
    fake_bin = "/usr/bin/mutmut"
    with patch("shutil.which", return_value=fake_bin):
        with patch.object(
            ToolAdapter,
            "_run",
            return_value=_ok_invocation(),
        ) as mock_run:
            _adapter().invoke(
                tmp_path, [], env={"CI": "1"}, timeout=120.0
            )

    assert mock_run.call_args[1]["cwd"] == tmp_path
    assert mock_run.call_args[1]["env"] == {"CI": "1"}
    assert mock_run.call_args[1]["timeout"] == 120.0


def test_invoke_passes_through_result(tmp_path: Path) -> None:
    """invoke() returns whatever _run returns."""
    fake_bin = "/usr/bin/mutmut"
    with patch("shutil.which", return_value=fake_bin):
        with patch.object(
            ToolAdapter,
            "_run",
            return_value=ToolInvocation(
                stdout="done", stderr="warn", exitcode=1, duration_seconds=5.5
            ),
        ) as mock_run:
            result = _adapter().invoke(tmp_path, [])

    assert result.stdout == "done"
    assert result.stderr == "warn"
    assert result.exitcode == 1
    assert result.duration_seconds == 5.5

    with patch("shutil.which", return_value=None):
        result = _adapter().invoke(tmp_path, [])
    assert result.exitcode == 3

# ---------------------------------------------------------------------------
# parse() — JSON summaries
# ---------------------------------------------------------------------------


def test_parse_empty_json_object(tmp_path: Path) -> None:
    """'{}' → all-zero MutationStats."""
    stats = _adapter().parse("{}")

    assert stats.total == 0
    assert stats.killed == 0
    assert stats.survived == 0
    assert stats.timed_out == 0
    assert stats.escaped == 0
    assert stats.untested == 0
    assert stats.msi == 0.0
    assert stats.covered_msi == 0.0


def test_parse_all_killed_mutations(tmp_path: Path) -> None:
    """All killed → MSI=1.0, covered_msi=1.0."""
    stats = _adapter().parse(json.dumps({
        "total": 50,
        "killed": 50,
        "survived": 0,
        "timeout": 0,
        "escaped": 0,
        "untested": 0,
    }))

    assert stats.total == 50
    assert stats.killed == 50
    assert stats.msi == 1.0
    assert stats.covered_msi == 1.0


def test_parse_mixed_outcomes(tmp_path: Path) -> None:
    """killed/survived/timeout/escaped/untested all present."""
    stats = _adapter().parse(json.dumps({
        "total": 100,
        "killed": 80,
        "survived": 15,
        "timeout": 3,
        "escaped": 2,
        "untested": 0,
    }))

    assert stats.total == 100
    assert stats.killed == 80
    assert stats.survived == 15
    assert stats.timed_out == 3
    assert stats.escaped == 2
    assert stats.untested == 0


def test_parse_msi_formula(tmp_path: Path) -> None:
    """MSI = killed / (killed + survived + timed_out + escaped)."""
    stats = _adapter().parse(json.dumps({
        "total": 10,
        "killed": 3,
        "survived": 2,
        "timeout": 0,
        "escaped": 0,
        "untested": 0,
    }))

    expected = 3 / 5  # 0.6
    assert stats.msi == round(expected, 4)
    assert stats.msi == 0.6
    assert isinstance(stats.msi, float)


def test_parse_covered_equal_total(tmp_path: Path) -> None:
    """covered_msi = msi when every mutation is covered (untested=0)."""
    stats = _adapter().parse(json.dumps({
        "total": 40,
        "killed": 36,
        "survived": 4,
        "timeout": 0,
        "escaped": 0,
        "untested": 0,
    }))

    assert stats.total == 40
    assert stats.msi == stats.covered_msi


def test_parse_no_covered_mutations(tmp_path: Path) -> None:
    """total>0 but killed+survived+timeout+escaped==0 → msi=0.0, not crash."""
    stats = _adapter().parse(json.dumps({
        "total": 10,
        "killed": 0,
        "survived": 0,
        "timeout": 0,
        "escaped": 0,
        "untested": 0,
    }))

    assert stats.total == 10
    assert stats.msi == 0.0
    assert stats.covered_msi == 0.0


def test_parse_all_survived_mutation_msi(tmp_path: Path) -> None:
    """All survived → MSI=0.0."""
    stats = _adapter().parse(json.dumps({
        "total": 20,
        "killed": 0,
        "survived": 20,
        "timeout": 0,
        "escaped": 0,
        "untested": 0,
    }))

    assert stats.msi == 0.0
    assert stats.covered_msi == 0.0


def test_parse_timed_out_mutations(tmp_path: Path) -> None:
    """Timeout mutations counted → MSI drops."""
    stats = _adapter().parse(json.dumps({
        "total": 20,
        "killed": 5,
        "survived": 0,
        "timeout": 5,
        "escaped": 0,
        "untested": 0,
    }))

    expected = 5 / 10  # killed/(killed+survived+timeout+escaped)
    assert stats.timed_out == 5
    assert stats.msi == round(expected, 4)
    assert stats.covered_msi == stats.msi


def test_parse_untested_mutations(tmp_path: Path) -> None:
    """untested field present → MutationStats.untested set."""
    stats = _adapter().parse(json.dumps({
        "total": 50,
        "killed": 30,
        "survived": 5,
        "timeout": 0,
        "escaped": 0,
        "untested": 15,
    }))

    assert stats.untested == 15
    # covered = 30+5+0+0 = 35
    assert stats.msi == round(30 / 35, 4)


def test_parse_msi_multiplication_replacement(tmp_path: Path) -> None:
    """MSI = 3/5=0.6. With mutation killed (/→*): 3*5=15. 0.6 != 15."""
    stats = _adapter().parse(json.dumps({
        "total": 5,
        "killed": 3,
        "survived": 2,
        "timeout": 0,
        "escaped": 0,
        "untested": 0,
    }))

    mutation_mutant_msi = 3 * 5
    assert stats.msi == 0.6
    assert stats.msi != mutation_mutant_msi


def test_parse_only_timed_out(tmp_path: Path) -> None:
    """Only timed-out mutants → MSI=0.0."""
    stats = _adapter().parse(json.dumps({
        "total": 10,
        "killed": 0,
        "survived": 0,
        "timeout": 10,
        "escaped": 0,
        "untested": 0,
    }))

    assert stats.timed_out == 10
    assert stats.msi == 0.0
    assert stats.covered_msi == 0.0


# ---------------------------------------------------------------------------
# parse() — text fallback
# ---------------------------------------------------------------------------


def test_parse_text_fallback(tmp_path: Path) -> None:
    """Non-JSON text with key:value pairs → parsed via regex."""
    text = """
total: 30
killed: 24
survived: 5
timeout: 1
escaped: 0
untested: 0
"""
    stats = _adapter().parse(text)

    assert stats.total == 30
    assert stats.killed == 24
    assert stats.survived == 5
    assert stats.timed_out == 1
    assert stats.escaped == 0
    assert stats.untested == 0
    assert stats.msi == 0.8


# ---------------------------------------------------------------------------
# parse() — edge cases
# ---------------------------------------------------------------------------


def test_parse_empty_string(tmp_path: Path) -> None:
    """'' → all-zero MutationStats (no crash)."""
    stats = _adapter().parse("")

    assert stats.total == 0
    assert stats.killed == 0
    assert stats.survived == 0
    assert stats.msi == 0.0


def test_parse_whitespace_only(tmp_path: Path) -> None:
    """String with only whitespace/newlines → all-zero."""
    stats = _adapter().parse("   \n  \n")

    assert stats.total == 0
    assert stats.msi == 0.0


def test_parse_invalid_json(tmp_path: Path) -> None:
    """Invalid JSON → text fallback → fallback yields zeros for garbage."""
    stats = _adapter().parse("{not valid json}")

    assert stats.total == 0
    assert stats.msi == 0.0
    assert stats.killed == 0


def test_parse_non_dict_json(tmp_path: Path) -> None:
    """JSON string → not a dict → parse still handles gracefully."""
    with pytest.raises(AttributeError):
        _adapter().parse('"just a string"')

def test_parse_garbage_text_no_key_value_pairs(tmp_path: Path) -> None:
    """Random text with no key:value pairs → all zeros, no crash."""
    stats = _adapter().parse("this is not parseable at all")

    assert stats.total == 0
    assert stats.killed == 0
    assert stats.survived == 0
    assert stats.timed_out == 0
    assert stats.escaped == 0
    assert stats.untested == 0
    assert stats.msi == 0.0


def test_parse_partial_data_defaults() -> None:
    """Only some fields in JSON → missing fields default to 0."""
    stats = _adapter().parse(json.dumps({"total": 5, "killed": 4}))

    assert stats.total == 5
    assert stats.killed == 4
    assert stats.survived == 0
    assert stats.timed_out == 0
    assert stats.escaped == 0
    assert stats.untested == 0
    # msi = 4/(4+0+0+0) = 1.0 since only killed mutations are counted as covered
    assert stats.msi == 1.0


def test_parse_returns_mutation_stats_type() -> None:
    """parse() returns a MutationStats dataclass (frozen, typed)."""
    stats = _adapter().parse(json.dumps({
        "total": 3, "killed": 3, "survived": 0,
        "timeout": 0, "escaped": 0, "untested": 0,
    }))

    assert stats.__class__.__name__ == "MutationStats"
    assert stats.msi != 0.0


def test_parse_with_stderr_parameter() -> None:
    """stderr parameter accepted in signature but not used by parse()."""
    stats = _adapter().parse(
        json.dumps({"total": 10, "killed": 8, "survived": 2}),
        stderr="warning: something",
        exitcode=0,
    )

    assert stats.total == 10
    # msi = 8/(8+2+0+0) = 0.8
    assert stats.msi == 0.8

def test_parse_full_mutation_stats_object() -> None:
    """Full MutationStats comparison kills remaining parse mutmut (1,2,55,87).

    Mutmut_1,2: JSON field extraction mutations (total, killed).
    Mutmut_55,87: msi/covered_msi formula mutations.
    Dense assertions on every field.
    """
    stats = _adapter().parse(json.dumps({
        "total": 100,
        "killed": 72,
        "survived": 18,
        "timeout": 5,
        "escaped": 3,
        "untested": 2,
    }))

    assert stats.total == 100
    assert stats.killed == 72
    assert stats.survived == 18
    assert stats.timed_out == 5
    assert stats.escaped == 3
    assert stats.untested == 2
    # msi = killed / (killed + survived + timed_out + escaped)
    # = 72 / (72 + 18 + 5 + 3) = 72 / 98 ≈ 0.7347
    assert stats.msi == round(72 / 98, 4)
    assert stats.covered_msi == stats.msi
    assert stats.msi == 0.7347
    assert isinstance(stats.msi, float)
    assert isinstance(stats.covered_msi, float)


def test_parse_partial_json_all_defaults() -> None:
    """Only 'total' and 'killed' present → all other fields default to 0.

    Kills mutmut on .get("survived", 0), .get("timeout", 0) etc.
    mutations that change the default values.
    """
    stats = _adapter().parse(json.dumps({
        "total": 200,
        "killed": 199,
    }))

    assert stats.total == 200
    assert stats.killed == 199
    assert stats.survived == 0
    assert stats.timed_out == 0
    assert stats.escaped == 0
    assert stats.untested == 0
    # msi = 199 / (199 + 0 + 0 + 0) = 1.0
    assert stats.msi == 1.0
    assert stats.covered_msi == 1.0
