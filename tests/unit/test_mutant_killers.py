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

def test_exit_codes_exact_values() -> None:
    from harness_quality_gate import exit_codes
    assert exit_codes.PASS == 0
    assert exit_codes.FAIL == 1
    assert exit_codes.UNSUPPORTED == 2
    assert exit_codes.INFRA_INCOMPLETE == 3
    assert exit_codes.CONFIG_INVALID == 4
    assert exit_codes.INTERNAL_ERROR == 5


# ---------------------------------------------------------------------------
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


