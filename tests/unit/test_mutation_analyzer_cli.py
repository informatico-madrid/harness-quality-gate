"""Contract tests for the mutation_analyzer CLI used by the skill steps.

step-02-layer1 invokes ``--gate`` (exit 0/1); step-03-layer2 consumes the
kill-map JSON. bmad/ is coverage-omitted, but the CLI contract these steps
document must not regress silently.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from harness_quality_gate.bmad.mutation_analyzer import (
    ModuleMutStats,
    MutationStats,
    main,
)


def _stats(survived: int) -> MutationStats:
    return MutationStats(
        tool="mutmut",
        modules={
            "calc": ModuleMutStats(
                module="calc", total=10, killed=10 - survived, survived=survived,
            ),
        },
    )


def test_kill_map_json_default(capsys, tmp_path):
    with patch(
        "harness_quality_gate.bmad.mutation_analyzer.analyze",
        return_value=_stats(survived=0),
    ):
        code = main([str(tmp_path)])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool"] == "mutmut"
    assert payload["mutation_kill_map"] == {
        "calc": {"killed": 10, "total": 10, "rate": 1.0},
    }
    assert payload["overall_kill_rate"] == 1.0
    assert "gate" not in payload


def test_gate_ok_exit_0(capsys, tmp_path):
    with patch(
        "harness_quality_gate.bmad.mutation_analyzer.analyze",
        return_value=_stats(survived=0),
    ):
        code = main([str(tmp_path), "--gate"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["gate"] == "OK"


def test_gate_nok_exit_1_on_survivors(capsys, tmp_path):
    with patch(
        "harness_quality_gate.bmad.mutation_analyzer.analyze",
        return_value=_stats(survived=2),
    ):
        code = main([str(tmp_path), "--gate"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["gate"] == "NOK"
    assert payload["mutation_kill_map"]["calc"]["rate"] == 0.8


def test_tool_flag_forwarded(tmp_path, capsys):
    with patch(
        "harness_quality_gate.bmad.mutation_analyzer.analyze",
        return_value=MutationStats(tool="infection", modules={}),
    ) as analyze:
        code = main([str(tmp_path), "--tool", "infection"])
    assert code == 0
    assert analyze.call_args.kwargs["tool"] == "infection"
    assert json.loads(capsys.readouterr().out)["overall_kill_rate"] == 1.0


def test_usage_error_exit_2(capsys):
    assert main([]) == 2
    assert "Usage:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Simulation regression (H13): Infection 0.29 writes status LISTS
# (killed/escaped/timeouted/uncovered/...), not the legacy "mutators"
# mapping — parse_infection returned {} for every real log and the PHP
# kill-map gate was vacuously OK.
# ---------------------------------------------------------------------------

def _mutant(path: str, line: int = 5) -> dict:
    return {
        "mutator": {
            "mutatorName": "PublicVisibility",
            "originalFilePath": path,
            "originalStartLine": line,
        },
        "diff": "@@ @@",
    }


class TestParseInfection029Format:
    def _write_log(self, tmp_path, payload):
        (tmp_path / "infection-log.json").write_text(
            json.dumps(payload), encoding="utf-8",
        )

    def test_kill_map_groups_by_module_and_status(self, tmp_path):
        from harness_quality_gate.bmad.mutation_analyzer import parse_infection
        self._write_log(tmp_path, {
            "stats": {"totalMutantsCount": 6},
            "killed": [
                _mutant("/repo/src/Greeter.php"),
                _mutant("/repo/src/Greeter.php", 9),
                _mutant("/repo/src/Mailer.php"),
            ],
            "escaped": [_mutant("/repo/src/Greeter.php", 12)],
            "timeouted": [_mutant("/repo/src/Mailer.php", 20)],
            "uncovered": [_mutant("/repo/src/Mailer.php", 30)],
        })
        stats = parse_infection(tmp_path)
        assert set(stats) == {"Greeter", "Mailer"}
        g = stats["Greeter"]
        assert (g.total, g.killed, g.survived, g.timeout, g.skipped) == (3, 2, 1, 0, 0)
        m = stats["Mailer"]
        assert (m.total, m.killed, m.survived, m.timeout, m.skipped) == (3, 1, 0, 1, 1)

    def test_clean_log_all_killed_gates_ok(self, tmp_path):
        from harness_quality_gate.bmad.mutation_analyzer import analyze
        self._write_log(tmp_path, {
            "stats": {"totalMutantsCount": 2},
            "killed": [_mutant("/repo/src/Greeter.php"),
                       _mutant("/repo/src/Greeter.php", 9)],
            "escaped": [],
        })
        result = analyze(tmp_path, tool="infection")
        assert result.modules["Greeter"].killed == 2
        assert result.kill_rate == 1.0

    def test_escaped_mutants_fail_the_gate(self, tmp_path):
        from harness_quality_gate.bmad.mutation_analyzer import main
        self._write_log(tmp_path, {
            "stats": {"totalMutantsCount": 2},
            "killed": [_mutant("/repo/src/Greeter.php")],
            "escaped": [_mutant("/repo/src/Greeter.php", 9)],
        })
        assert main([str(tmp_path), "--gate", "--tool", "infection"]) == 1

    def test_malformed_log_returns_empty(self, tmp_path):
        from harness_quality_gate.bmad.mutation_analyzer import parse_infection
        self._write_log(tmp_path, {"stats": "nope", "killed": "not-a-list"})
        assert parse_infection(tmp_path) == {}

    def test_mutant_without_file_path_is_ignored(self, tmp_path):
        from harness_quality_gate.bmad.mutation_analyzer import parse_infection
        self._write_log(tmp_path, {
            "killed": [{"mutator": {"mutatorName": "X"}},
                       _mutant("/repo/src/Greeter.php")],
        })
        stats = parse_infection(tmp_path)
        assert set(stats) == {"Greeter"}
        assert stats["Greeter"].total == 1
