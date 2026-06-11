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
