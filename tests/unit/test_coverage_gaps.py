"""Unit tests targeting coverage gaps in new/changed modules.

Covers: dispatcher._extract_mutation_stats, dispatcher.dispatch_full,
        dispatcher._build_adapter, messages_fr, exit_codes, state,
        checkpoint.build/write path (tool_specific, per_language).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness_quality_gate import exit_codes
from harness_quality_gate.checkpoint import build, validate, write
from harness_quality_gate.dispatcher import (
    _build_adapter,
    _extract_mutation_stats,
    dispatch_full,
)
from harness_quality_gate.messages_fr import MESSAGES, msg
from harness_quality_gate.models import LayerResult, MutationStats
from harness_quality_gate.state import scratch_dir
from tests.factories import build_detection, build_layer_result


# ---------------------------------------------------------------------------
# exit_codes
# ---------------------------------------------------------------------------


def test_exit_codes_values() -> None:
    assert exit_codes.PASS == 0
    assert exit_codes.FAIL == 1
    assert exit_codes.UNSUPPORTED == 2
    assert exit_codes.INFRA_INCOMPLETE == 3
    assert exit_codes.CONFIG_INVALID == 4
    assert exit_codes.INTERNAL_ERROR == 5


# ---------------------------------------------------------------------------
# messages_fr
# ---------------------------------------------------------------------------


def test_messages_fr_known_key() -> None:
    result = msg("TOOL_MISSING", tool="phpunit")
    assert "phpunit" in result


def test_messages_fr_infra_ok() -> None:
    assert msg("INFRA_OK") == MESSAGES["INFRA_OK"]


def test_messages_fr_detect_success() -> None:
    result = msg("DETECT_SUCCESS", language="php", confidence=0.95)
    assert "php" in result
    assert "95" in result


def test_messages_fr_detect_hybrid() -> None:
    result = msg("DETECT_HYBRID", languages=["php", "python"])
    assert "DETECT_HYBRID" not in result  # expanded


def test_messages_fr_layer_complete() -> None:
    result = msg("LAYER_COMPLETE", layer="L3A", result="pass")
    assert "L3A" in result


def test_messages_fr_layer_failed() -> None:
    result = msg("LAYER_FAILED", layer="L1", count=3)
    assert "3" in result


def test_messages_fr_unknown_key() -> None:
    result = msg("NONEXISTENT_KEY")
    assert result == "NONEXISTENT_KEY"


# ---------------------------------------------------------------------------
# state.scratch_dir
# ---------------------------------------------------------------------------


def test_scratch_dir_creates_path(tmp_path: Path) -> None:
    d = scratch_dir(tmp_path, "python", "ruff")
    assert d.is_dir()
    assert d == tmp_path / "_quality-gate" / "work" / "python" / "ruff"


def test_scratch_dir_idempotent(tmp_path: Path) -> None:
    d1 = scratch_dir(tmp_path, "php", "phpstan")
    d2 = scratch_dir(tmp_path, "php", "phpstan")
    assert d1 == d2


# ---------------------------------------------------------------------------
# dispatcher._build_adapter
# ---------------------------------------------------------------------------


def test_build_adapter_php() -> None:
    from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
    adapter = _build_adapter("php")
    assert isinstance(adapter, PhpAdapter)


def test_build_adapter_python() -> None:
    from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
    adapter = _build_adapter("python")
    assert isinstance(adapter, PythonAdapter)


def test_build_adapter_unknown() -> None:
    assert _build_adapter("rust") is None


# ---------------------------------------------------------------------------
# dispatcher._extract_mutation_stats
# ---------------------------------------------------------------------------


def test_extract_mutation_stats_none_when_empty() -> None:
    assert _extract_mutation_stats([]) is None


def test_extract_mutation_stats_none_when_no_tool_specific() -> None:
    lr = build_layer_result(layer="L3B", language="python", passed=True)
    assert lr.tool_specific is None
    assert _extract_mutation_stats([lr]) is None


def test_extract_mutation_stats_from_python_l3b() -> None:
    stats = MutationStats(
        total=10, killed=8, survived=2, timed_out=0,
        escaped=0, untested=0, msi=80.0, covered_msi=80.0,
    )
    lr = LayerResult(
        layer="L3B", language="python", passed=False,
        findings=[], duration_sec=1.0,
        tool_specific={"mutation_stats": stats},
    )
    result = _extract_mutation_stats([lr])
    assert result is stats


def test_extract_mutation_stats_from_php_l1() -> None:
    lr = LayerResult(
        layer="L1", language="php", passed=True,
        findings=[], duration_sec=1.0,
        tool_specific={
            "mutation": {
                "killed": 5, "survived": 1, "timed_out": 0,
                "escaped": 0, "untested": 2, "msi": 83.33, "covered_msi": 83.33,
            }
        },
    )
    result = _extract_mutation_stats([lr])
    assert result is not None
    assert result.killed == 5
    assert result.survived == 1
    assert result.total == 8  # 5+1+0+0+2


def test_extract_mutation_stats_skips_non_mutation_tool_specific() -> None:
    lr = LayerResult(
        layer="L1", language="php", passed=True,
        findings=[], duration_sec=1.0,
        tool_specific={"coverage_driver": "pcov"},
    )
    assert _extract_mutation_stats([lr]) is None


def test_extract_mutation_stats_ignores_non_dataclass_l3b() -> None:
    lr = LayerResult(
        layer="L3B", language="python", passed=True,
        findings=[], duration_sec=1.0,
        tool_specific={"mutation_stats": {"not": "a dataclass"}},
    )
    assert _extract_mutation_stats([lr]) is None


# ---------------------------------------------------------------------------
# dispatcher.dispatch_full (mocked adapters)
# ---------------------------------------------------------------------------


def _make_mock_adapter(passing: bool = True) -> MagicMock:
    adapter = MagicMock()
    for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
        layer = method.replace("run_", "").upper().replace("3A", "3A").replace("3B", "3B")
        getattr(adapter, method).return_value = build_layer_result(
            layer=layer, language="python", passed=passing
        )
    return adapter


def test_dispatch_full_python_only(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _make_mock_adapter()
    monkeypatch.setattr("harness_quality_gate.dispatcher.PythonAdapter", lambda: mock)
    det = build_detection(language="python")
    checkpoint = dispatch_full(det, {})
    assert checkpoint.version == "v2"
    assert checkpoint.language == "python"
    assert len(checkpoint.layers) == 5  # L3A, L1, L2, L3B, L4


def test_dispatch_full_php_only(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _make_mock_adapter()
    monkeypatch.setattr("harness_quality_gate.dispatcher.PhpAdapter", lambda: mock)
    det = build_detection(language="php")
    checkpoint = dispatch_full(det, {})
    assert checkpoint.language == "php"
    assert len(checkpoint.layers) == 5


def test_dispatch_full_hybrid_appends_php_l3a(monkeypatch: pytest.MonkeyPatch) -> None:
    py_mock = _make_mock_adapter()
    php_mock = MagicMock()
    php_mock.run_l3a.return_value = build_layer_result(layer="L3A", language="php", passed=True)
    monkeypatch.setattr("harness_quality_gate.dispatcher.PythonAdapter", lambda: py_mock)
    monkeypatch.setattr("harness_quality_gate.dispatcher.PhpAdapter", lambda: php_mock)
    det = build_detection(language="python", languages_detected=["python", "php"])
    checkpoint = dispatch_full(det, {})
    assert len(checkpoint.layers) == 6  # 5 python + 1 php L3A
    languages = [lr.language for lr in checkpoint.layers]
    assert "php" in languages


def test_dispatch_full_filters_non_string_ctx(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-string ctx values (e.g. ConcurrencyPlan) must not reach adapters as env."""
    mock = _make_mock_adapter()
    monkeypatch.setattr("harness_quality_gate.dispatcher.PythonAdapter", lambda: mock)
    det = build_detection(language="python")
    from harness_quality_gate.concurrency import resolve
    ctx = {"work_dir": "/tmp", "concurrency": resolve("sequential", {})}
    dispatch_full(det, ctx)
    # Adapter methods called with string-only env
    call_args = mock.run_l3a.call_args
    env_arg = call_args[0][1]  # second positional arg
    assert all(isinstance(v, str) for v in env_arg.values())


def test_dispatch_full_unknown_language() -> None:
    det = build_detection(language="rust")
    checkpoint = dispatch_full(det, {})
    assert checkpoint.language == "rust"
    assert checkpoint.layers == []  # no adapter for rust


def test_dispatch_full_adapter_exception_produces_error_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = MagicMock()
    mock.run_l3a.side_effect = RuntimeError("phpstan exploded")
    for method in ("run_l1", "run_l2", "run_l3b", "run_l4"):
        getattr(mock, method).return_value = build_layer_result(
            layer=method.upper(), language="php", passed=True
        )
    monkeypatch.setattr("harness_quality_gate.dispatcher.PhpAdapter", lambda: mock)
    det = build_detection(language="php")
    checkpoint = dispatch_full(det, {})
    error_layers = [lr for lr in checkpoint.layers if lr.passed is False]
    assert len(error_layers) >= 1


def test_dispatch_full_hybrid_php_l3a_exception_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hybrid: PHP L3A error → appends error LayerResult, doesn't propagate."""
    py_mock = _make_mock_adapter()
    php_mock = MagicMock()
    php_mock.run_l3a.side_effect = RuntimeError("php visitor crashed")
    monkeypatch.setattr("harness_quality_gate.dispatcher.PythonAdapter", lambda: py_mock)
    monkeypatch.setattr("harness_quality_gate.dispatcher.PhpAdapter", lambda: php_mock)
    det = build_detection(language="python", languages_detected=["python", "php"])
    checkpoint = dispatch_full(det, {})
    php_layers = [lr for lr in checkpoint.layers if lr.language == "php"]
    assert len(php_layers) == 1
    assert php_layers[0].passed is False
    assert "error" in (php_layers[0].tool_specific or {})


def test_dispatch_non_l3a_layer_falls_through_to_run_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dispatch() with non-L3A layer falls through to run_layer."""
    from harness_quality_gate.dispatcher import dispatch
    mock = MagicMock()
    mock.run_l1.return_value = build_layer_result(layer="L1", language="python", passed=True)
    monkeypatch.setattr("harness_quality_gate.dispatcher.PythonAdapter", lambda: mock)
    det = build_detection(language="python")
    result = dispatch(detection=det, layer="L1", concurrency_plan=MagicMock(), ctx={})
    assert result.layer == "L1"


# ---------------------------------------------------------------------------
# checkpoint.build — tool_specific and per_language paths
# ---------------------------------------------------------------------------


def test_checkpoint_build_includes_tool_specific() -> None:
    lr = {
        "layer": "L1",
        "language": "python",
        "passed": True,
        "findings": [],
        "duration_sec": 1.0,
        "tool_specific": {"coverage_driver": "pcov"},
    }
    data = build([lr], {}, {"repo_path": "/tmp", "language": "python"})
    assert data["layers"][0]["tool_specific"] == {"coverage_driver": "pcov"}


def test_checkpoint_build_omits_none_tool_specific() -> None:
    lr = {
        "layer": "L3A",
        "language": "python",
        "passed": True,
        "findings": [],
        "duration_sec": 0.5,
    }
    data = build([lr], {}, {"repo_path": "/tmp", "language": "python"})
    assert "tool_specific" not in data["layers"][0]


def test_checkpoint_build_includes_per_language() -> None:
    lr = {
        "layer": "L3A",
        "language": "python",
        "passed": True,
        "findings": [],
        "duration_sec": 0.5,
        "per_language": {
            "php": {"layer": "L3A", "language": "php", "passed": True, "findings": []}
        },
    }
    data = build([lr], {}, {"repo_path": "/tmp", "language": "python"})
    assert "per_language" in data["layers"][0]


def test_checkpoint_build_serializes_finding_dataclasses() -> None:
    from harness_quality_gate.models import Finding
    finding = Finding(
        node="src/foo.py", severity="error", message="bad code",
        tool="ruff", layer="L3A", language="python",
    )
    lr = {
        "layer": "L3A",
        "language": "python",
        "passed": False,
        "findings": [finding],
        "duration_sec": 0.1,
    }
    data = build([lr], {}, {"repo_path": "/tmp", "language": "python"})
    f = data["layers"][0]["findings"][0]
    assert isinstance(f, dict)
    assert f["node"] == "src/foo.py"
    assert "cve" not in f  # None values stripped


def test_checkpoint_write_to_disk(tmp_path: Path) -> None:
    data = build([], {}, {"repo_path": "/tmp", "language": "python"})
    out = tmp_path / "quality-gate-latest.json"
    write(out, data)
    assert out.exists()
    loaded = json.loads(out.read_text())
    assert loaded["version"] == "v2"


def test_checkpoint_write_cleanup_on_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """write() unlinks tmp file and re-raises on BaseException."""
    data = build([], {}, {"repo_path": "/tmp", "language": "python"})
    import os as _os

    def boom(*_args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(_os, "replace", boom)
    out = tmp_path / "quality-gate-latest.json"
    with pytest.raises(OSError, match="disk full"):
        write(out, data)
    # Temp file should be cleaned up
    tmp_files = list(tmp_path.glob(".quality-gate-*.tmp"))
    assert len(tmp_files) == 0


def test_checkpoint_validate_accepts_null_tool_specific() -> None:
    data = {
        "version": "v2",
        "timestamp": "2026-05-31T00:00:00Z",
        "repository": "/tmp",
        "language": "python",
        "layers": [
            {
                "layer": "L4",
                "language": "python",
                "passed": True,
                "findings": [],
                "duration_sec": 0.0,
                "tool_specific": None,
            }
        ],
    }
    validate(data)  # should not raise


# ---------------------------------------------------------------------------
# allow_list_auditor — pattern match, audit(), unknown language
# ---------------------------------------------------------------------------


def test_allow_list_entry_pattern_match() -> None:
    from harness_quality_gate.allow_list_auditor import AllowListEntry
    entry = AllowListEntry(rule_id="X", pattern=r"B\d+")
    assert entry.matches("B101") is True
    assert entry.matches("E501") is False


def test_allow_list_entry_rule_id_match() -> None:
    from harness_quality_gate.allow_list_auditor import AllowListEntry
    entry = AllowListEntry(rule_id="E501")
    assert entry.matches("E501") is True
    assert entry.matches("E502") is False


def test_audit_filters_matching_rule_ids() -> None:
    from harness_quality_gate.allow_list_auditor import audit
    from harness_quality_gate.models import Finding
    findings = [
        Finding(node="f.py", severity="error", message="m", rule_id="B101", cwe="", tool="bandit", layer="L4", language="python"),
        Finding(node="f.py", severity="warning", message="m2", rule_id="E501", cwe="", tool="ruff", layer="L3A", language="python"),
    ]
    result = audit(findings, ["B101"])
    assert len(result) == 1
    assert result[0].rule_id == "E501"


def test_audit_keeps_findings_without_rule_id() -> None:
    from harness_quality_gate.allow_list_auditor import audit
    from harness_quality_gate.models import Finding
    findings = [
        Finding(node="f.py", severity="error", message="m", rule_id=None, cwe="", tool="t", layer="L4", language="python"),
    ]
    result = audit(findings, ["B101"])
    assert len(result) == 1


def test_allow_list_auditor_unknown_language(tmp_path: Path) -> None:
    from harness_quality_gate.allow_list_auditor import AllowListAuditor
    auditor = AllowListAuditor(language="rust")
    report = auditor.audit(tmp_path)
    assert report.exit_code == 0
    assert "Unknown" in report.summary
