"""Tests specifically designed to kill mutmut survivors.

Targets patterns that survive with weak assertion tests:
- frozen=True on dataclasses
- Default field values
- CI env var strings
- Mode and numeric value checks
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# models.py — frozen dataclass tests (kill frozen=False mutants)
# ---------------------------------------------------------------------------

def _assert_frozen(cls, *args, **kwargs) -> None:
    """Assert that a dataclass instance is frozen (FrozenInstanceError on assignment)."""
    obj = cls(*args, **kwargs)
    first_field = list(obj.__dataclass_fields__)[0]
    with pytest.raises((AttributeError, TypeError)):
        setattr(obj, first_field, None)


def test_runtime_is_frozen() -> None:
    from harness_quality_gate.models import Runtime
    _assert_frozen(Runtime, python_version="3.12", concurrency="parallel", ci=False)


def test_detection_is_frozen() -> None:
    from harness_quality_gate.models import Detection, Runtime
    rt = Runtime(python_version="3.12", concurrency="parallel", ci=False)
    _assert_frozen(Detection, repo_path="/tmp", language="python", framework=None,
                   confidence=1.0, runtime=rt)


def test_finding_is_frozen() -> None:
    from harness_quality_gate.models import Finding
    _assert_frozen(Finding, node="f.py", severity="error", message="test")


def test_mutation_stats_is_frozen() -> None:
    from harness_quality_gate.models import MutationStats
    _assert_frozen(MutationStats, total=10, killed=10, survived=0, timed_out=0,
                   escaped=0, untested=0, msi=100.0, covered_msi=100.0)


def test_ignore_entry_is_frozen() -> None:
    from harness_quality_gate.models import IgnoreEntry
    _assert_frozen(IgnoreEntry, tool="ruff", hash="abc", reason="test",
                   date_added="2026-01-01", expiry=None)


def test_audit_report_is_frozen() -> None:
    from harness_quality_gate.models import AuditReport
    _assert_frozen(AuditReport, findings=[], summary="ok")


def test_tool_check_report_is_frozen() -> None:
    from harness_quality_gate.models import ToolCheckReport
    _assert_frozen(ToolCheckReport, tool="ruff", exit_code=0, output="v0.4", error=None)


def test_layer_result_is_frozen() -> None:
    from harness_quality_gate.models import LayerResult
    _assert_frozen(LayerResult, layer="L1", language="python", passed=True,
                   findings=[], duration_sec=1.0)


def test_concurrency_plan_is_frozen() -> None:
    from harness_quality_gate.models import ConcurrencyPlan
    _assert_frozen(ConcurrencyPlan, mode="parallel", ci_detected=False, max_threads=1)


def test_doctor_report_is_frozen() -> None:
    from harness_quality_gate.models import DoctorReport
    _assert_frozen(DoctorReport, verdict="INFRA_OK", python_version="3.12",
                   php_version="8.3", composer_version="2.7",
                   tools=[], warnings=[])


def test_install_report_is_frozen() -> None:
    from harness_quality_gate.models import InstallReport
    _assert_frozen(InstallReport, status="ok", tools_installed=[],
                   tools_failed=[], errors=[])


def test_checkpoint_v2_is_frozen() -> None:
    from harness_quality_gate.models import CheckpointV2, LayerResult
    lr = LayerResult(layer="L1", language="python", passed=True,
                     findings=[], duration_sec=1.0)
    _assert_frozen(CheckpointV2, version="v2", timestamp="2026-01-01T00:00:00Z",
                   repository="/tmp", language="python", layers=[lr], mutation=None)


def test_tool_taxonomy_entry_is_frozen() -> None:
    from harness_quality_gate.models import ToolTaxonomyEntry
    _assert_frozen(ToolTaxonomyEntry, tool="phpstan", layer="L3A",
                   tier="A", language="php")


# ---------------------------------------------------------------------------
# models.py — default field values (kill default string/int mutations)
# ---------------------------------------------------------------------------

def test_finding_default_fields() -> None:
    from harness_quality_gate.models import Finding
    f = Finding(node="f.py", severity="error", message="test")
    assert f.fix_hint is None
    assert f.cve is None
    assert f.cwe == ""
    assert f.tool is None
    assert f.layer is None
    assert f.language is None
    assert f.rule_id is None


def test_audit_report_default_fields() -> None:
    from harness_quality_gate.models import AuditReport
    r = AuditReport(findings=[], summary="ok")
    assert r.exit_code == 0
    assert r.ignored_count == 0


def test_layer_result_default_tool_specific() -> None:
    from harness_quality_gate.models import LayerResult
    r = LayerResult(layer="L1", language="python", passed=True,
                    findings=[], duration_sec=1.0)
    assert r.tool_specific is None


def test_detection_default_fields() -> None:
    from harness_quality_gate.models import Detection, Runtime
    rt = Runtime(python_version="3.12", concurrency="parallel", ci=False)
    d = Detection(repo_path="/tmp", language="python", framework=None,
                  confidence=1.0, runtime=rt)
    assert d.languages_detected == []
    assert d.frameworks == {}
    assert d.file_counts == {}


# ---------------------------------------------------------------------------
# concurrency.py — CI env var names, mode strings, max_threads values
# ---------------------------------------------------------------------------

def test_concurrency_resolve_parallel_exact() -> None:
    from harness_quality_gate.concurrency import resolve
    plan = resolve("parallel", {})
    assert plan.mode == "parallel"
    assert plan.ci_detected is False
    assert plan.max_threads == 1


def test_concurrency_resolve_sequential_exact() -> None:
    from harness_quality_gate.concurrency import resolve
    plan = resolve("sequential", {})
    assert plan.mode == "sequential"
    assert plan.ci_detected is False
    assert plan.max_threads == 1


def test_concurrency_auto_ci_sequential_exact() -> None:
    from harness_quality_gate.concurrency import resolve
    plan = resolve("auto", {"CI": "true"})
    assert plan.mode == "sequential"
    assert plan.ci_detected is True
    assert plan.max_threads == 1


def test_concurrency_auto_no_ci_parallel_exact() -> None:
    from harness_quality_gate.concurrency import resolve
    plan = resolve("auto", {})
    assert plan.mode == "parallel"
    assert plan.ci_detected is False
    assert plan.max_threads == 1


def test_concurrency_all_ci_env_vars() -> None:
    """Kill mutations that change each CI env var name."""
    from harness_quality_gate.concurrency import resolve
    for var in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "BUILDKITE", "CIRCLECI"):
        plan = resolve("auto", {var: "true"})
        assert plan.mode == "sequential", f"{var} should trigger sequential"
        assert plan.ci_detected is True, f"{var} should be detected as CI"


def test_concurrency_ci_env_vars_unknown_does_not_trigger() -> None:
    """Ensure unknown env vars don't trigger CI detection."""
    from harness_quality_gate.concurrency import resolve
    plan = resolve("auto", {"XXGITLAB_CIXX": "true", "UNKNOWN_CI": "true"})
    assert plan.mode == "parallel"
    assert plan.ci_detected is False


def test_concurrency_explicit_parallel_overrides_ci() -> None:
    """Kill mode=='XXparallelXX' mutant: explicit parallel ignores CI env vars."""
    from harness_quality_gate.concurrency import resolve
    # With CI detected, explicit parallel still returns parallel (not sequential)
    plan = resolve("parallel", {"CI": "true"})
    assert plan.mode == "parallel"
    assert plan.ci_detected is False  # explicit mode, not auto


def test_concurrency_explicit_sequential_overrides_no_ci() -> None:
    """Kill mode=='XXsequentialXX' mutant: explicit sequential always sequential."""
    from harness_quality_gate.concurrency import resolve
    plan = resolve("sequential", {"NO_CI": "false"})
    assert plan.mode == "sequential"


# ---------------------------------------------------------------------------
# exit_codes.py — exact values (kill numeric mutations)
# ---------------------------------------------------------------------------

def test_exit_codes_exact_values() -> None:
    from harness_quality_gate import exit_codes
    assert exit_codes.PASS == 0
    assert exit_codes.FAIL == 1
    assert exit_codes.UNSUPPORTED == 2
    assert exit_codes.INFRA_INCOMPLETE == 3
    assert exit_codes.CONFIG_INVALID == 4
    assert exit_codes.INTERNAL_ERROR == 5


# ---------------------------------------------------------------------------
# state.py — check exact structure
# ---------------------------------------------------------------------------

def test_state_scratch_dir_path() -> None:
    """Kill state.py mutations by verifying scratch_dir path structure."""
    from harness_quality_gate.state import scratch_dir
    from pathlib import Path
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = scratch_dir(Path(tmp), "python", "ruff")
        assert p == Path(tmp) / "_quality-gate" / "work" / "python" / "ruff"
        assert p.is_dir()


# ---------------------------------------------------------------------------
# dispatcher.py — _LAYER_METHOD dict keys/values + _extract_mutation_stats
# ---------------------------------------------------------------------------

def test_dispatcher_layer_method_exact_values() -> None:
    """Kill string mutations in _LAYER_METHOD dict."""
    from harness_quality_gate.dispatcher import _LAYER_METHOD
    assert _LAYER_METHOD["L1"] == "run_l1"
    assert _LAYER_METHOD["L2"] == "run_l2"
    assert _LAYER_METHOD["L3A"] == "run_l3a"
    assert _LAYER_METHOD["L3B"] == "run_l3b"
    assert _LAYER_METHOD["L4"] == "run_l4"


def test_dispatcher_extract_mutation_stats_php_l1() -> None:
    """Kill dict key + default value mutations in _extract_mutation_stats."""
    from harness_quality_gate.dispatcher import _extract_mutation_stats
    from harness_quality_gate.models import LayerResult, MutationStats, Finding

    m_dict = {
        "killed": 5, "survived": 1, "timed_out": 0, "escaped": 0,
        "untested": 0, "msi": 83.3, "covered_msi": 83.3,
    }
    lr = LayerResult(
        layer="L1", language="php", passed=True, findings=[],
        duration_sec=1.0, tool_specific={"mutation": m_dict}
    )
    stats = _extract_mutation_stats([lr])
    assert stats is not None
    assert stats.killed == 5
    assert stats.survived == 1
    assert stats.timed_out == 0
    assert stats.escaped == 0
    assert stats.untested == 0
    assert stats.total == 6


def test_dispatcher_extract_mutation_stats_defaults_are_zero() -> None:
    """Kill default value mutations (0 → 1) in _extract_mutation_stats."""
    from harness_quality_gate.dispatcher import _extract_mutation_stats
    from harness_quality_gate.models import LayerResult

    # Empty mutation dict — all fields should default to 0
    lr = LayerResult(
        layer="L1", language="php", passed=True, findings=[],
        duration_sec=1.0, tool_specific={"mutation": {}}
    )
    stats = _extract_mutation_stats([lr])
    assert stats is not None
    assert stats.killed == 0
    assert stats.survived == 0
    assert stats.timed_out == 0
    assert stats.escaped == 0
    assert stats.untested == 0
    assert stats.total == 0


def test_dispatcher_extract_mutation_stats_total_calculation() -> None:
    """Kill arithmetic mutation in total = killed + survived + timed_out + ..."""
    from harness_quality_gate.dispatcher import _extract_mutation_stats
    from harness_quality_gate.models import LayerResult

    m_dict = {
        "killed": 2, "survived": 3, "timed_out": 1, "escaped": 1,
        "untested": 2, "msi": 40.0, "covered_msi": 50.0,
    }
    lr = LayerResult(
        layer="L1", language="php", passed=True, findings=[],
        duration_sec=1.0, tool_specific={"mutation": m_dict}
    )
    stats = _extract_mutation_stats([lr])
    assert stats is not None
    assert stats.total == 2 + 3 + 1 + 1 + 2  # = 9


def test_dispatcher_extract_mutation_stats_l3b_mutation_stats() -> None:
    """Kill 'L3B' and 'or' mutations in Python L3B extraction."""
    from harness_quality_gate.dispatcher import _extract_mutation_stats
    from harness_quality_gate.models import LayerResult, MutationStats

    ms = MutationStats(total=10, killed=10, survived=0, timed_out=0,
                       escaped=0, untested=0, msi=100.0, covered_msi=100.0)
    lr = LayerResult(
        layer="L3B", language="python", passed=True, findings=[],
        duration_sec=1.0, tool_specific={"mutation_stats": ms}
    )
    stats = _extract_mutation_stats([lr])
    assert stats is not None
    assert stats.total == 10
    assert stats.msi == 100.0


def test_dispatcher_extract_mutation_stats_l3b_not_l1() -> None:
    """Kill 'and' → 'or' mutation: L3B match should NOT trigger for L1 layer."""
    from harness_quality_gate.dispatcher import _extract_mutation_stats
    from harness_quality_gate.models import LayerResult, MutationStats

    ms = MutationStats(total=5, killed=5, survived=0, timed_out=0,
                       escaped=0, untested=0, msi=100.0, covered_msi=100.0)
    # L1 layer with mutation_stats key (wrong key for L1 — should NOT be returned)
    lr = LayerResult(
        layer="L1", language="python", passed=True, findings=[],
        duration_sec=1.0, tool_specific={"mutation_stats": ms}
    )
    stats = _extract_mutation_stats([lr])
    assert stats is None  # L1 doesn't have mutation_stats key, only L3B does


def test_dispatcher_repo_path_from_detection() -> None:
    """Kill repo = None mutation: verify repo path is extracted correctly from detection."""
    from harness_quality_gate.dispatcher import dispatch_full
    from harness_quality_gate.models import Detection, Runtime, LayerResult
    from unittest.mock import patch, MagicMock
    from pathlib import Path

    rt = Runtime(python_version="3.12", concurrency="parallel", ci=False)
    detection = Detection(
        repo_path="/tmp/test_repo_path_xyz",
        language="python",
        framework=None,
        confidence=1.0,
        runtime=rt,
        languages_detected=["python"],
    )

    captured_repo = []

    def make_mock_adapter():
        mock_adapter = MagicMock()
        layer_result = LayerResult(layer="L3A", language="python", passed=True,
                                   findings=[], duration_sec=0.1)
        l1_result = LayerResult(layer="L1", language="python", passed=True,
                                findings=[], duration_sec=0.1)
        l2_result = LayerResult(layer="L2", language="python", passed=True,
                                findings=[], duration_sec=0.1)
        l3b_result = LayerResult(layer="L3B", language="python", passed=True,
                                 findings=[], duration_sec=0.1)
        l4_result = LayerResult(layer="L4", language="python", passed=True,
                                findings=[], duration_sec=0.1)

        def capture_run_l3a(repo, env):
            captured_repo.append(repo)
            return layer_result

        mock_adapter.run_l3a.side_effect = capture_run_l3a
        mock_adapter.run_l1.return_value = l1_result
        mock_adapter.run_l2.return_value = l2_result
        mock_adapter.run_l3b.return_value = l3b_result
        mock_adapter.run_l4.return_value = l4_result
        return mock_adapter

    with patch("harness_quality_gate.dispatcher.PythonAdapter", side_effect=make_mock_adapter):
        dispatch_full(detection, {})

    assert len(captured_repo) == 1
    assert captured_repo[0] == Path("/tmp/test_repo_path_xyz")




# ---------------------------------------------------------------------------
# checkpoint.py — critical logic mutations
# ---------------------------------------------------------------------------

def _det(**kw: object) -> dict:
    return {"repo_path": "/tmp", "language": "python", "framework": None,
            "confidence": 1.0, "languages_detected": [], "frameworks": {}, **kw}


def _rt() -> dict:
    return {"python_version": "3.12", "concurrency": "parallel", "ci": False}


def test_checkpoint_version_field() -> None:
    """Kill version='v2' string mutation."""
    from harness_quality_gate.checkpoint import build
    result = build([], _rt(), _det())
    assert result["version"] == "v2"


def test_checkpoint_mutation_not_none_included() -> None:
    """Kill 'is not None' → 'is None': mutation included when not None."""
    from harness_quality_gate.checkpoint import build
    mut = {"killed": 5, "total": 5, "msi": 100.0}
    result = build([], _rt(), _det(mutation=mut))
    assert "mutation" in result
    assert result["mutation"]["msi"] == 100.0


def test_checkpoint_mutation_none_excluded() -> None:
    """Complementary: mutation not included when absent."""
    from harness_quality_gate.checkpoint import build
    result = build([], _rt(), _det())
    assert "mutation" not in result


def test_checkpoint_build_excludes_none_fields() -> None:
    """Kill 'and not isinstance' → 'or not isinstance': _to_dict strips None fields."""
    from harness_quality_gate.checkpoint import build
    from harness_quality_gate.models import Finding
    f = Finding(node="f.py", severity="error", message="test")  # fix_hint=None
    lr = {"layer": "L1", "language": "python", "passed": True,
          "findings": [f], "duration_sec": 1.0}
    result = build([lr], _rt(), _det())
    f_dict = result["layers"][0]["findings"][0]
    assert "node" in f_dict
    assert "fix_hint" not in f_dict  # None field stripped


def test_checkpoint_write_creates_parents(tmp_path) -> None:
    """Kill parents=False: write must create parent dirs."""
    from harness_quality_gate.checkpoint import write, build
    import json
    nested = tmp_path / "deep" / "nested" / "quality-gate-latest.json"
    data = build([], _rt(), _det())
    write(nested, data)
    assert nested.exists()
    assert json.loads(nested.read_text())["version"] == "v2"


# ---------------------------------------------------------------------------
# config.py — frozen dataclasses and default values
# ---------------------------------------------------------------------------

def test_config_thresholds_defaults() -> None:
    """Kill default value mutations in _Thresholds (direct dataclass instantiation)."""
    from harness_quality_gate.config import _Thresholds
    t = _Thresholds()
    assert t.min_msi == 100.0
    assert t.min_covered_msi == 100.0
    assert t.timeouts_as_escaped is True
    assert t.max_timeouts == 0


def test_config_concurrency_default() -> None:
    """Kill 'auto' → 'XXautoXX' mutation."""
    from harness_quality_gate.config import _Concurrency
    c = _Concurrency()
    assert c.default == "auto"


def test_config_ci_env_vars_all_present() -> None:
    """Kill CI env var string mutations in _Concurrency default."""
    from harness_quality_gate.config import _Concurrency
    c = _Concurrency()
    for expected in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "BUILDKITE", "CIRCLECI"):
        assert expected in c.ci_env_vars, f"{expected} missing from ci_env_vars"


# ---------------------------------------------------------------------------
# allow_list_auditor.py — key constant values
# ---------------------------------------------------------------------------

def test_allow_list_metadata_window() -> None:
    """Kill _METADATA_WINDOW = 5 → 6 mutation."""
    from harness_quality_gate.allow_list_auditor import _METADATA_WINDOW
    assert _METADATA_WINDOW == 5


def test_allow_list_php_selector_lang_name() -> None:
    """Kill lang_name='php' → 'XXphpXX' mutation."""
    from harness_quality_gate.allow_list_auditor import _PHP_SELECTOR
    assert _PHP_SELECTOR.lang_name == "php"


def test_allow_list_php_selector_marker() -> None:
    """Kill marker string mutations."""
    from harness_quality_gate.allow_list_auditor import _PHP_SELECTOR
    assert "@infection-ignore-all" in _PHP_SELECTOR.marker_label


def test_allow_list_audit_report_info_severity(tmp_path) -> None:
    """Kill severity='info' → 'XXinfoXX' mutation."""
    from harness_quality_gate.allow_list_auditor import AllowListAuditor
    import os

    # Create a justified ignore in a PHP file
    php_file = tmp_path / "test.php"
    php_file.write_text(
        "<?php\n"
        "# reason: equivalent mutant\n"
        "# audited: user 2026-01-01\n"
        "@infection-ignore-all\n"
        "function foo() { return 1; }\n"
    )
    report = AllowListAuditor(language="php").audit(tmp_path)
    # If there are any "info" findings, verify severity
    for f in report.findings:
        if "justified" in f.message.lower():
            assert f.severity == "info"




# ---------------------------------------------------------------------------
# base.py _run — stderr default value and timeout stdout/stderr (kill "" → "XXXX")
# ---------------------------------------------------------------------------

def test_base_run_stderr_default_empty() -> None:
    """Kill stderr='' → 'XXXX': verify stderr is empty string when process has no stderr."""
    from harness_quality_gate.adapters.php.phpstan_adapter import PhpStanAdapter
    import subprocess
    from unittest.mock import patch
    completed = subprocess.CompletedProcess(['echo', 'hi'], 0, stdout='hi\n', stderr=None)
    with patch('subprocess.run', return_value=completed):
        result = PhpStanAdapter._run(['echo', 'hi'])
    assert result.stderr == ""  # None → "" via "stderr or ''"


def test_base_run_timeout_stdout_empty() -> None:
    """Kill else '' → else 'XXXX': timeout stdout empty when no partial output."""
    from harness_quality_gate.adapters.php.phpstan_adapter import PhpStanAdapter
    import subprocess
    from unittest.mock import patch
    exc = subprocess.TimeoutExpired(['sleep'], 1)
    exc.stdout = None  # No partial output
    exc.stderr = None
    with patch('subprocess.run', side_effect=exc):
        result = PhpStanAdapter._run(['sleep', '999'], timeout=0.001)
    assert result.stdout == ""


# ---------------------------------------------------------------------------
# dispatcher.py — msi/covered_msi key names + timestamp + error duration
# ---------------------------------------------------------------------------

def test_dispatcher_extract_mutation_stats_msi_and_covered_msi() -> None:
    """Kill 'msi' → 'XXmsiXX' and 'covered_msi' → 'XXcovered_msiXX' mutations."""
    from harness_quality_gate.dispatcher import _extract_mutation_stats
    from harness_quality_gate.models import LayerResult

    m_dict = {
        "killed": 10, "survived": 0, "timed_out": 0, "escaped": 0,
        "untested": 0, "msi": 100.0, "covered_msi": 95.5,
    }
    lr = LayerResult(
        layer="L1", language="php", passed=True, findings=[],
        duration_sec=1.0, tool_specific={"mutation": m_dict}
    )
    stats = _extract_mutation_stats([lr])
    assert stats is not None
    assert stats.msi == 100.0
    assert stats.covered_msi == 95.5


def test_dispatcher_checkpoint_version() -> None:
    """Kill 'v2' version string mutation in dispatch_full checkpoint."""
    from harness_quality_gate.dispatcher import dispatch_full
    from harness_quality_gate.models import Detection, Runtime, LayerResult
    from unittest.mock import patch, MagicMock

    rt = Runtime(python_version="3.12", concurrency="parallel", ci=False)
    detection = Detection(
        repo_path="/tmp", language="python", framework=None,
        confidence=1.0, runtime=rt, languages_detected=["python"],
    )

    layer_result = LayerResult(layer="L3A", language="python", passed=True,
                               findings=[], duration_sec=0.1)
    l1_result = LayerResult(layer="L1", language="python", passed=True,
                            findings=[], duration_sec=0.1)
    l2_result = LayerResult(layer="L2", language="python", passed=True,
                            findings=[], duration_sec=0.1)
    l3b_result = LayerResult(layer="L3B", language="python", passed=True,
                             findings=[], duration_sec=0.1)
    l4_result = LayerResult(layer="L4", language="python", passed=True,
                            findings=[], duration_sec=0.1)

    mock_adapter = MagicMock()
    mock_adapter.run_l3a.return_value = layer_result
    mock_adapter.run_l1.return_value = l1_result
    mock_adapter.run_l2.return_value = l2_result
    mock_adapter.run_l3b.return_value = l3b_result
    mock_adapter.run_l4.return_value = l4_result

    with patch("harness_quality_gate.dispatcher.PythonAdapter", side_effect=lambda: mock_adapter):
        checkpoint = dispatch_full(detection, {})

    assert checkpoint.version == "v2"


def test_dispatcher_error_layer_duration_zero() -> None:
    """Kill duration_sec=0.0 → 1.0: error layer duration should be 0."""
    from harness_quality_gate.dispatcher import dispatch_full
    from harness_quality_gate.models import Detection, Runtime
    from unittest.mock import patch

    rt = Runtime(python_version="3.12", concurrency="parallel", ci=False)
    det = Detection(repo_path="/tmp", language="python", framework=None,
                    confidence=1.0, runtime=rt, languages_detected=["python"])

    def raise_error(repo, env):
        raise RuntimeError("test error")

    mock_adapter = object.__new__(__import__('harness_quality_gate.adapters.python.python_adapter', 
                                              fromlist=['PythonAdapter']).PythonAdapter)

    with patch("harness_quality_gate.dispatcher.PythonAdapter") as MockAdapter:
        instance = MockAdapter.return_value
        instance.run_l3a.side_effect = raise_error
        instance.run_l1.side_effect = raise_error
        instance.run_l2.side_effect = raise_error
        instance.run_l3b.side_effect = raise_error
        instance.run_l4.side_effect = raise_error
        checkpoint = dispatch_full(det, {})

    # Layers with errors should have duration_sec = 0.0
    error_layers = [l for l in checkpoint.layers if l.tool_specific and "error" in l.tool_specific]
    for el in error_layers:
        assert el.duration_sec == 0.0, f"Error layer {el.layer} duration should be 0.0"




# ---------------------------------------------------------------------------
# dispatcher.py — dispatch() function logic mutations
# ---------------------------------------------------------------------------

def test_dispatch_repo_path_from_detection(monkeypatch) -> None:
    """Kill repo = None mutation in dispatch(): verify correct repo path."""
    import pytest
    from harness_quality_gate.dispatcher import dispatch
    from harness_quality_gate.models import ConcurrencyPlan
    from tests.factories import build_detection, build_layer_result
    from unittest.mock import MagicMock
    from pathlib import Path

    captured = []
    mock_adapter = MagicMock()

    def capture_run_l3a(repo, ctx):
        captured.append(repo)
        return build_layer_result(layer="L3A", language="php", passed=True)

    mock_adapter.run_l3a.side_effect = capture_run_l3a
    monkeypatch.setattr("harness_quality_gate.dispatcher.PhpAdapter", lambda: mock_adapter)

    det = build_detection(language="php")
    dispatch(detection=det, layer="L3A", concurrency_plan=MagicMock(), ctx={})
    assert len(captured) == 1
    assert captured[0] == Path(det.repo_path)


def test_dispatch_l3a_and_not_or_php_primary(monkeypatch) -> None:
    """Kill 'and' → 'or' mutation: L3A+php check.
    
    dispatch(layer='L1', php) should NOT use PHP L3A path.
    If 'and' is changed to 'or', primary==php would trigger L3A for L1 calls.
    """
    from harness_quality_gate.dispatcher import dispatch
    from harness_quality_gate.models import ConcurrencyPlan
    from tests.factories import build_detection, build_layer_result
    from unittest.mock import MagicMock

    php_l3a_called = []
    php_mock = MagicMock()
    php_mock.run_l3a.side_effect = lambda r, c: php_l3a_called.append(1) or build_layer_result(layer="L3A", language="php", passed=True)
    php_mock.run_l1.return_value = build_layer_result(layer="L1", language="php", passed=True)
    monkeypatch.setattr("harness_quality_gate.dispatcher.PhpAdapter", lambda: php_mock)

    det = build_detection(language="php")
    dispatch(detection=det, layer="L1", concurrency_plan=MagicMock(), ctx={})
    # L1 dispatch should NOT call run_l3a on PHP adapter
    assert len(php_l3a_called) == 0, "dispatch(L1, php) should not call PHP L3A path"


def test_dispatch_l3a_languages_detected_and_not_or(monkeypatch) -> None:
    """Kill 'and' → 'or' mutation in second L3A check.
    
    dispatch(layer='L1', python_with_php) should NOT use PHP L3A path.
    """
    from harness_quality_gate.dispatcher import dispatch
    from harness_quality_gate.models import ConcurrencyPlan
    from tests.factories import build_detection, build_layer_result
    from unittest.mock import MagicMock

    php_l3a_called = []
    php_mock = MagicMock()
    php_mock.run_l3a.side_effect = lambda r, c: php_l3a_called.append(1) or build_layer_result(layer="L3A", language="php", passed=True)
    py_mock = MagicMock()
    py_mock.run_l1.return_value = build_layer_result(layer="L1", language="python", passed=True)
    monkeypatch.setattr("harness_quality_gate.dispatcher.PhpAdapter", lambda: php_mock)
    monkeypatch.setattr("harness_quality_gate.dispatcher.PythonAdapter", lambda: py_mock)

    det = build_detection(language="python", languages_detected=["python", "php"])
    dispatch(detection=det, layer="L1", concurrency_plan=MagicMock(), ctx={})
    # L1 with python+php should NOT call PHP run_l3a
    assert len(php_l3a_called) == 0


# ---------------------------------------------------------------------------
# base.py _run — default timeout and duration_seconds rounding
# ---------------------------------------------------------------------------

def test_base_run_default_timeout_is_300(tmp_path) -> None:
    """Kill timeout=300.0 → 301.0 in _run default parameter (call without timeout)."""
    from harness_quality_gate.adapters.php.phpstan_adapter import PhpStanAdapter
    import subprocess
    from unittest.mock import patch

    captured_timeout = []
    original_run = subprocess.run

    def capture_run(*args, **kwargs):
        captured_timeout.append(kwargs.get('timeout'))
        return original_run(*args, **kwargs)

    # Call WITHOUT explicit timeout — uses default 300.0
    with patch('subprocess.run', side_effect=capture_run):
        PhpStanAdapter._run(['echo', 'test'], cwd=tmp_path)

    assert captured_timeout[0] == 300.0


def test_base_run_duration_rounded_to_3_places(tmp_path) -> None:
    """Kill round(duration, 3) → round(duration, 4): verify 3-decimal rounding."""
    from harness_quality_gate.adapters.php.phpstan_adapter import PhpStanAdapter
    import subprocess
    from unittest.mock import patch

    completed = subprocess.CompletedProcess(['echo'], 0, stdout='', stderr='')
    with patch('subprocess.run', return_value=completed):
        result = PhpStanAdapter._run(['echo', 'hi'], cwd=tmp_path)
    # round(x, 3) == round(x, 3) is trivially true,
    # but round(x, 3) != round(x, 4) only if x has 4+ decimal places
    # We verify the stored value IS what round(x, 3) would produce
    assert result.duration_seconds == round(result.duration_seconds, 3)


def test_base_run_timeout_duration_rounded_to_3_places() -> None:
    """Kill round(duration, 3) → round(duration, 4) in timeout handler."""
    from harness_quality_gate.adapters.php.phpstan_adapter import PhpStanAdapter
    import subprocess
    from unittest.mock import patch

    exc = subprocess.TimeoutExpired(['echo'], 1)
    exc.stdout = None
    exc.stderr = None
    with patch('subprocess.run', side_effect=exc):
        result = PhpStanAdapter._run(['echo'], timeout=0.001)
    assert result.duration_seconds == round(result.duration_seconds, 3)
    assert result.exitcode == -1


