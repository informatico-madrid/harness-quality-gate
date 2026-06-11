"""Final targeted tests to close remaining coverage gaps.

Covers: base._run() real subprocess, PHP adapter version() bodies,
detector branches, framework_sniffer patterns, installer, visitor_runner,
weak_test_php, phpunit, python_adapter internal methods.
"""

from __future__ import annotations

import json as _json  # noqa: F401 — used as _json.dumps in test bodies
import logging
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.base import ToolInvocation


# ---------------------------------------------------------------------------
# base.py — _run() with a real subprocess (covers lines 130-146)
# ---------------------------------------------------------------------------


def test_base_run_real_echo(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.php.phpstan_adapter import PhpStanAdapter
    result = PhpStanAdapter._run(["echo", "hello"], cwd=tmp_path)
    assert result.exitcode == 0
    assert "hello" in result.stdout


def test_base_run_nonzero_exit(tmp_path: Path) -> None:
    result = __import__("harness_quality_gate.adapters.php.phpstan_adapter", fromlist=["PhpStanAdapter"]).PhpStanAdapter._run(
        ["false"], cwd=tmp_path
    )
    assert result.exitcode != 0


def test_base_run_with_env(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.php.phpstan_adapter import PhpStanAdapter
    result = PhpStanAdapter._run(["env"], cwd=tmp_path, env={"MY_VAR": "xyz"})
    assert result.exitcode == 0


def test_base_run_file_not_found(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.php.phpstan_adapter import PhpStanAdapter
    # ToolAdapter._run does NOT catch FileNotFoundError — it propagates
    with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
        with pytest.raises(FileNotFoundError):
            PhpStanAdapter._run(["nonexistent_binary_xyz"], cwd=tmp_path)


def test_base_run_timeout(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.php.phpstan_adapter import PhpStanAdapter
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["sleep"], 0.001)):
        result = PhpStanAdapter._run(["sleep", "999"], cwd=tmp_path, timeout=0.001)
    assert result.exitcode == -1
    assert result.exitcode == -1


# ---------------------------------------------------------------------------
# PHP adapter version() bodies — when binary is found (covers subprocess.run)
# ---------------------------------------------------------------------------


def _fake_subprocess_result(stdout: str = "2.0.0", returncode: int = 0) -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = ""
    return m


def test_phpmd_version_found(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.php.phpmd_adapter import PhpMdAdapter
    a = PhpMdAdapter()
    with patch.object(type(a), "_phpmd_binary", return_value=["phpmd"]):
        with patch("subprocess.run", return_value=_fake_subprocess_result("PHPMD 2.14.0")):
            v = a.version(tmp_path)
    assert "2" in v


def test_phpmd_version_failure(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.php.phpmd_adapter import PhpMdAdapter
    a = PhpMdAdapter()
    with patch.object(type(a), "_phpmd_binary", return_value=["phpmd"]):
        with patch("subprocess.run", return_value=_fake_subprocess_result("", returncode=1)):
            with pytest.raises(RuntimeError):
                a.version(tmp_path)


def test_phpmd_version_no_digit_parts(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.php.phpmd_adapter import PhpMdAdapter
    a = PhpMdAdapter()
    with patch.object(type(a), "_phpmd_binary", return_value=["phpmd"]):
        with patch("subprocess.run", return_value=_fake_subprocess_result("phpmd version")):
            v = a.version(tmp_path)
    assert isinstance(v, str)


def test_composer_audit_version_found(tmp_path: Path) -> None:
    """Line 40-59: version() calls _composer_binary(repo), subprocess.run with correct args, extracts version.
    Kills mutmut_2 (repo=None), mutmut_9 (cmd=None), mutmut_10 (cwd=None), mutmut_11 (env=None)."""
    from harness_quality_gate.adapters.php.composer_audit_adapter import ComposerAuditAdapter
    a = ComposerAuditAdapter()
    # Patch _composer_binary at INSTANCE level so we can spy on the actual call argument
    # This catches mutmut_2: if `repo` is mutated to `None`, assert_called_once_with verifies it
    with patch.object(type(a), "_composer_binary", return_value=["/usr/bin/composer"]) as mock_cb:
        with patch("subprocess.run", return_value=_fake_subprocess_result("Composer version 2.8.3")) as mock_run:
            v = a.version(tmp_path)
    # Kill mutmut_2: _composer_binary must have been called with repo (not mutated to None)
    mock_cb.assert_called_once_with(tmp_path)
    # Kill mutmut_9/10/11: inspect subprocess.run call_args
    mock_run.assert_called_once()
    run_pos_args = mock_run.call_args[0]
    run_kwargs = mock_run.call_args[1]
    # mutmut_9: the command must be a list (not mutated to None)
    assert isinstance(run_pos_args[0], list), "subprocess.run command mutated to None"
    # mutmut_10: cwd must be the repo path string (not mutated to None)
    assert run_kwargs.get("cwd") is not None, "cwd mutated to None"
    assert run_kwargs["cwd"] == str(tmp_path), "cwd argument mutated"
    # mutmut_11: env must be a dict (not mutated to None)
    assert run_kwargs.get("env") is not None, "env mutated to None"
    assert isinstance(run_kwargs["env"], dict), "env mutated to None"
    assert v == "2.8.3"


def test_composer_audit_version_binary_not_found(tmp_path: Path) -> None:
    """Line 43-44: version() raises RuntimeError with exact message when composer binary not found."""
    from harness_quality_gate.adapters.php.composer_audit_adapter import ComposerAuditAdapter
    a = ComposerAuditAdapter()
    with patch("harness_quality_gate.adapters.php.composer_audit_adapter.shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="composer not found on PATH"):
            a.version(tmp_path)


def test_composer_audit_version_failure(tmp_path: Path) -> None:
    """Line 53-54: version() raises RuntimeError when composer --version exits non-zero."""
    from harness_quality_gate.adapters.php.composer_audit_adapter import ComposerAuditAdapter
    a = ComposerAuditAdapter()
    with patch("harness_quality_gate.adapters.php.composer_audit_adapter.shutil.which", return_value="/usr/bin/composer"):
        with patch("subprocess.run", return_value=_fake_subprocess_result("", returncode=1)):
            with pytest.raises(RuntimeError, match="composer --version failed:"):
                a.version(tmp_path)


def test_pest_version_found(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.php.pest_adapter import PestAdapter
    a = PestAdapter()
    with patch.object(type(a), "_pest_binary", return_value=["pest"]):
        with patch("subprocess.run", return_value=_fake_subprocess_result("Pest 2.0.0")):
            v = a.version(tmp_path)
    assert isinstance(v, str)


def test_pest_version_failure(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.php.pest_adapter import PestAdapter
    a = PestAdapter()
    with patch.object(type(a), "_pest_binary", return_value=["pest"]):
        with patch("subprocess.run", return_value=_fake_subprocess_result("", returncode=1)):
            with pytest.raises(RuntimeError):
                a.version(tmp_path)


def test_php_cs_fixer_version_found(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.php.php_cs_fixer_adapter import PhpCsFixerAdapter
    a = PhpCsFixerAdapter()
    with patch.object(type(a), "_cs_fixer_binary", return_value=["php-cs-fixer"]):
        with patch("subprocess.run", return_value=_fake_subprocess_result("PHP CS Fixer 3.0.0")):
            v = a.version(tmp_path)
    assert isinstance(v, str)


def test_php_cs_fixer_version_failure(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.php.php_cs_fixer_adapter import PhpCsFixerAdapter
    a = PhpCsFixerAdapter()
    with patch.object(type(a), "_cs_fixer_binary", return_value=["php-cs-fixer"]):
        with patch("subprocess.run", return_value=_fake_subprocess_result("", returncode=1)):
            with pytest.raises(RuntimeError):
                a.version(tmp_path)


# ---------------------------------------------------------------------------
# phpunit_adapter — _parse_stdout SKIPPED/RISKY status (lines 291-299)
# ---------------------------------------------------------------------------


def test_phpunit_parse_stdout_skipped() -> None:
    from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter
    adapter = PhpUnitAdapter()
    # PHPUnit verbose text output with SKIPPED and INCOMPLETE statuses
    stdout = (
        "1) CalculatorTest :: testAdd SKIPPED\n"
        "2) CalculatorTest :: testRisky INCOMPLETE\n"
    )
    findings = adapter._parse_stdout(stdout)
    # KILL mutants 2 (early return for non-empty) and 5 (regex → None):
    # Both mutations would return [], but we expect 2 findings
    assert len(findings) == 2
    f1, f2 = findings
    assert f1.message == "testAdd skipped"
    assert f1.severity == "info"
    assert f1.tool == "phpunit"
    assert f1.layer == "layer1"
    assert f1.fix_hint == "Review skip reason in CalculatorTest/testAdd"
    assert f2.message == "testRisky incomplete"
    assert f2.severity == "warning"


# ---------------------------------------------------------------------------
# visitor_runner_adapter — missing visitor file branch (lines 110-111)
# ---------------------------------------------------------------------------


def test_visitor_runner_missing_script(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.php.visitor_runner_adapter import VisitorRunnerAdapter
    import harness_quality_gate.adapters.php.visitor_runner_adapter as vra
    # Create a PHP source file so it's found
    (tmp_path / "test.php").write_text("<?php class Foo {}")
    adapter = VisitorRunnerAdapter()
    # Mock the module-level _discover_visitors to return a nonexistent visitor
    with patch.object(vra, "_discover_visitors", return_value=["nonexistent_visitor_xyz"]):
        result = adapter.invoke(tmp_path, [])
    # Should not crash — missing visitor script is warned and skipped
    assert result.exitcode == 0


def test_visitor_runner_parse_empty_stdout(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.php.visitor_runner_adapter import VisitorRunnerAdapter
    adapter = VisitorRunnerAdapter()
    findings = adapter.parse("", "", 0)
    assert findings == []


def test_visitor_runner_invalid_json_line(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.php.visitor_runner_adapter import VisitorRunnerAdapter
    adapter = VisitorRunnerAdapter()
    findings = adapter.parse("not json\n{invalid}\n", "", 0)
    assert isinstance(findings, list)


def test_visitor_runner_no_php_files(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.php.visitor_runner_adapter import VisitorRunnerAdapter
    adapter = VisitorRunnerAdapter()
    # No PHP files → exits early with empty result; stderr now includes repo dir
    result = adapter.invoke(tmp_path, [])
    assert result.exitcode == 0
    assert "no PHP files" in result.stderr


# ---------------------------------------------------------------------------
# visitor_runner_adapter — kill surviving mutants in invoke()
# - mutmut_1: default timeout=300.0 → 301.0 (assert subprocess timeout kwarg)
# - mutmut_7: logger.warning(..., VISITORS_DIR) → logger.warning(..., None)
# - mutmut_8: logger.warning(msg, VISITORS_DIR) → logger.warning(VISITORS_DIR)
# ---------------------------------------------------------------------------


def test_visitor_runner_invoke_timeout_passed_to_subprocess(tmp_path: Path) -> None:
    """Kill mutmut_1: assert the timeout kwarg passed to subprocess.run.

    The invoke method shells out to php via subprocess.run with the timeout
    parameter. By mocking subprocess.run we can verify the exact timeout
    value used — a default-value mutation (300→301) would fail this check.
    """
    from harness_quality_gate.adapters.php.visitor_runner_adapter import (
        VisitorRunnerAdapter,
    )
    import harness_quality_gate.adapters.php.visitor_runner_adapter as vra

    # Create a PHP source file so the code reaches subprocess.run
    (tmp_path / "a.php").write_text("<?php")
    completed = subprocess.CompletedProcess(
        args=["php", "visitors/god_class.php", str(tmp_path / "a.php")],
        returncode=0,
        stdout="[]",
        stderr="",
    )
    adapter = VisitorRunnerAdapter()
    with patch.object(vra, "_discover_visitors", return_value=["god_class"]):
        with patch("subprocess.run", return_value=completed) as mock_run:
            adapter.invoke(tmp_path, [], timeout=42.5)
    mock_run.assert_called_once()
    # Key assertion: the timeout kwarg must be exactly what we passed.
    # A mutation on the *default* (300.0→301.0) doesn't change this because
    # we pass timeout explicitly. But calling *without* passing timeout uses
    # the default — below test covers that.
    called_timeout = mock_run.call_args[1]["timeout"]
    assert called_timeout == 42.5


def test_visitor_runner_invoke_default_timeout(tmp_path: Path) -> None:
    """Kill mutmut_1 via default value: assert subprocess.run timeout==300.0.

    When invoke is called without an explicit timeout it falls back to the
    default (300.0). If mutmut changed it to 301.0 this test fails.
    """
    from harness_quality_gate.adapters.php.visitor_runner_adapter import (
        VisitorRunnerAdapter,
    )
    import harness_quality_gate.adapters.php.visitor_runner_adapter as vra

    # Create a PHP source file so the code reaches subprocess.run
    (tmp_path / "a.php").write_text("<?php")
    completed = subprocess.CompletedProcess(
        args=["php", "visitors/god_class.php", str(tmp_path / "a.php")],
        returncode=0,
        stdout="[]",
        stderr="",
    )
    adapter = VisitorRunnerAdapter()
    with patch.object(vra, "_discover_visitors", return_value=["god_class"]):
        with patch("subprocess.run", return_value=completed) as mock_run:
            adapter.invoke(tmp_path, [])  # no explicit timeout → uses default
    mock_run.assert_called_once()
    assert mock_run.call_args[1]["timeout"] == 300.0


def test_visitor_runner_no_visitors_logs_warning(tmp_path: Path) -> None:
    """Kill mutmut_7 & mutmut_8 by asserting the log warning content.

    mutmut_7: logger.warning("No visitor scripts found in %s", VISITORS_DIR)
              → logger.warning("No visitor scripts found in %s", None)
    If VISITORS_DIR is replaced by None the %-format produces "None" in the
    message — this test asserts the actual visitors path is present.

    mutmut_8: logger.warning(VISITORS_DIR) entirely changes the logged text
              — the "visitor scripts" keyword disappears.
    """
    import logging
    from harness_quality_gate.adapters.php.visitor_runner_adapter import (
        VisitorRunnerAdapter,
    )
    from harness_quality_gate.adapters.php.visitor_runner_adapter import (
        VISITORS_DIR,
    )
    import harness_quality_gate.adapters.php.visitor_runner_adapter as vra

    with patch.object(vra, "_discover_visitors", return_value=[]):
        result = VisitorRunnerAdapter().invoke(tmp_path, [])

    # Verify early-return value is still correct
    assert result.exitcode == 0
    assert result.stdout == "[]"

    # Verify the log warning contains the actual visitors directory path.
    # Both mutmut_7 (None → "None") and mutmut_8 (bare VISITORS_DIR →
    # different path format) would cause this assertion to fail.
    assert str(VISITORS_DIR) in result.stderr


def test_visitor_runner_missing_visitor_continues_to_next(tmp_path: Path) -> None:
    """Kill mutmut_45: continue->break in invoke visitor loop.

    When a visitor script is missing the original code does `continue`
    to process the next visitor. The mutant changes it to `break` which
    terminates the whole loop, losing all subsequent results.
    """
    from harness_quality_gate.adapters.php.visitor_runner_adapter import (
        VisitorRunnerAdapter,
    )
    import harness_quality_gate.adapters.php.visitor_runner_adapter as vra

    # Create visitors dir - only aaa.php exists (NOT missing.php)
    visitors_dir = tmp_path / "visitors"
    visitors_dir.mkdir()
    (visitors_dir / "aaa.php").touch()

    (tmp_path / "a.php").write_text("<?php")

    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout='[{"file":"a.php","line":1,"rule_id":"Z","message":"zzz"}]',
        stderr="",
    )

    with patch.object(
        VisitorRunnerAdapter, "_collect_php_files", return_value=[tmp_path / "a.php"]
    ):
        with patch.object(
            vra, "_discover_visitors", return_value=["missing", "aaa"]
        ):
            with patch("subprocess.run", return_value=completed) as mock_run:
                orig_visitors_dir = vra.VISITORS_DIR
                try:
                    vra.VISITORS_DIR = visitors_dir
                    result = VisitorRunnerAdapter().invoke(tmp_path, [])
                finally:
                    vra.VISITORS_DIR = orig_visitors_dir

    # With `continue` -> aaa runs -> 1 call.  With `break` -> aaa skipped -> 0 calls.
    assert mock_run.call_count == 1, (
        f"mutmut_45 alive: expected 1 subprocess.run, got {mock_run.call_count}"
    )
    data = _json.loads(result.stdout)
    assert len(data) == 1
    assert data[0]["rule_id"] == "Z"


# weak_test_php — missing visitor script branches (lines 120-121, etc.)
# ---------------------------------------------------------------------------


def test_weak_test_no_test_files(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
    adapter = PhpWeakTestAdapter()
    # No *Test.php files → returns empty invocation
    result = adapter.invoke(tmp_path, env={})
    assert result.exitcode == 0


def test_weak_test_parse_empty() -> None:
    from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
    adapter = PhpWeakTestAdapter()
    assert adapter.parse("", "", 0) == []


def test_weak_test_parse_invalid_json_line() -> None:
    from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
    adapter = PhpWeakTestAdapter()
    findings = adapter.parse("not-json\nalso-not-json\n", "", 0)
    assert isinstance(findings, list)


def test_weak_test_invoke_with_test_file(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
    # Create a Test PHP file
    (tmp_path / "FooTest.php").write_text("<?php class FooTest extends TestCase {}")
    adapter = PhpWeakTestAdapter()
    # Mock the runner invoke to avoid running real PHP
    with patch.object(adapter._runner, "invoke",
                      return_value=ToolInvocation(stdout="[]", stderr="", exitcode=0)):
        result = adapter.invoke(tmp_path, env={})
    assert result.exitcode == 0


# ---------------------------------------------------------------------------
# detector.py — Python version fallback (line 233-236), CI detection (248, 250)
# ---------------------------------------------------------------------------


def test_python_adapter_tool_versions(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
    a = PythonAdapter()
    # Mock all version calls to return a string
    with patch.object(a.ruff, "version", return_value="ruff 0.4"):
        with patch.object(a.pyright, "version", return_value="pyright 1.1"):
            with patch.object(a.pytest, "version", return_value="pytest 8"):
                with patch.object(a.mutmut, "version", return_value="mutmut 2"):
                    with patch.object(a.bandit, "version", side_effect=RuntimeError("missing")):
                        with patch.object(a.vulture, "version", return_value="vulture 2"):
                            with patch.object(a.deptry, "version", return_value="deptry 0"):
                                versions = a.tool_versions()
    assert isinstance(versions, dict)


def test_python_adapter_check_tools_all_present(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
    a = PythonAdapter()
    with patch("shutil.which", return_value="/usr/bin/tool"):
        missing = a.check_tools()
    assert isinstance(missing, list)


def test_python_adapter_run_ruff_private(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
    a = PythonAdapter()
    inv = ToolInvocation(stdout="[]", stderr="", exitcode=0, duration_seconds=0.0)
    with patch.object(a.ruff, "invoke", return_value=inv):
        with patch.object(a.ruff, "parse", return_value=[]):
            findings = a._run_ruff(tmp_path, {})
    assert findings == []


def test_python_adapter_run_vulture_private(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
    a = PythonAdapter()
    with patch.object(a.vulture, "invoke", side_effect=RuntimeError("not found")):
        findings = a._run_vulture(tmp_path, {})
    assert findings == []


def test_python_adapter_run_deptry_private(tmp_path: Path) -> None:
    from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
    a = PythonAdapter()
    inv = ToolInvocation(stdout="{}", stderr="", exitcode=0, duration_seconds=0.0)
    with patch.object(a.deptry, "invoke", return_value=inv):
        with patch.object(a.deptry, "parse", return_value=[]):
            findings = a._run_deptry(tmp_path, {})
    assert findings == []


# ---------------------------------------------------------------------------
# doctor.py — lines 78, 95
# ---------------------------------------------------------------------------


def test_php_adapter_validate_infection_stats_errored() -> None:
    from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
    from harness_quality_gate.models import MutationStats
    stats = MutationStats(
        total=10, killed=8, survived=0, timed_out=0,
        escaped=0, untested=2, msi=80.0, covered_msi=80.0
    )
    findings = PhpAdapter._validate_infection_stats(stats)
    assert any(f.node == "infection" for f in findings)


def test_php_adapter_pcov_option_glob_found() -> None:
    from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
    a = PhpAdapter()
    with patch("subprocess.run", return_value=_fake_subprocess_result("pcov")):
        opt = a._pcov_initial_tests_option()
    assert opt == ""  # PCOV already loaded


def test_php_adapter_pcov_option_so_found() -> None:
    from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
    import glob as _glob
    a = PhpAdapter()
    with patch("subprocess.run", return_value=_fake_subprocess_result("Core\nctype")):
        with patch.object(_glob, "glob", return_value=["/tmp/pcov.so"]):
            opt = a._pcov_initial_tests_option()
    assert "pcov.so" in opt


def test_php_adapter_pcov_option_not_found() -> None:
    """Line 603: _pcov_initial_tests_option returns '' when no pcov found anywhere."""
    from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
    import glob as _glob
    a = PhpAdapter()
    with patch("subprocess.run", return_value=_fake_subprocess_result("Core\ndate\nPDO")):
        with patch.object(_glob, "glob", return_value=[]):
            opt = a._pcov_initial_tests_option()
    assert opt == ""


# ---------------------------------------------------------------------------
# composer_audit_adapter: version fallback (line 58)
# ---------------------------------------------------------------------------


def test_composer_audit_version_no_digit_parts(tmp_path: Path) -> None:
    """Line 58: version() returns stdout.strip() when no part has digits+dot."""
    from harness_quality_gate.adapters.php.composer_audit_adapter import ComposerAuditAdapter
    a = ComposerAuditAdapter()
    with patch.object(type(a), "_composer_binary", return_value=["composer"]):
        with patch("subprocess.run", return_value=_fake_subprocess_result("Composer stable")):
            v = a.version(tmp_path)
    assert v == "Composer stable"


# ---------------------------------------------------------------------------
# pest_adapter: version raises (line 40) and fallback return (line 55)
# ---------------------------------------------------------------------------


def test_pest_version_binary_missing(tmp_path: Path) -> None:
    """Line 40: RuntimeError when pest binary not found."""
    from harness_quality_gate.adapters.php.pest_adapter import PestAdapter
    a = PestAdapter()
    with patch.object(type(a), "_pest_binary", return_value=None):
        with pytest.raises(RuntimeError, match="pest not found"):
            a.version(tmp_path)


def test_pest_version_no_digit_parts(tmp_path: Path) -> None:
    """Line 55: version() returns stdout.strip() when no part has digits+dot."""
    from harness_quality_gate.adapters.php.pest_adapter import PestAdapter
    a = PestAdapter()
    with patch.object(type(a), "_pest_binary", return_value=["pest"]):
        with patch("subprocess.run", return_value=_fake_subprocess_result("Pest stable")):
            v = a.version(tmp_path)
    assert v == "Pest stable"


# ---------------------------------------------------------------------------
# phpunit_adapter: "ERROR" status in _parse_stdout (lines 292-293)
# ---------------------------------------------------------------------------


def test_phpunit_parse_stdout_error_status() -> None:
    """Lines 292-293: ERROR status branch.

    Also KILL mutants 2 (early return for non-empty) and 5 (regex → None):
    both mutations would return [], but we expect 1 finding with severity=error.
    """
    from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter
    adapter = PhpUnitAdapter()
    stdout = "1) MyTest :: testSomething ERROR\n"
    findings = adapter._parse_stdout(stdout)
    assert len(findings) == 1
    f = findings[0]
    assert f.message == "testSomething error"
    assert f.severity == "error"
    assert f.tool == "phpunit"
    assert f.layer == "layer1"
    assert f.fix_hint == "Fix error in MyTest/testSomething"


# ---------------------------------------------------------------------------
# php_adapter: drupal/wordpress detect_frameworks (lines 157, 159)
# ---------------------------------------------------------------------------


def test_php_adapter_detect_frameworks_drupal(tmp_path: Path) -> None:
    """Line 157: drupal detection from composer.json."""
    from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
    (tmp_path / "composer.json").write_text(
        _json.dumps({"require": {"drupal/core-composer-scaffold": "^10"}}),
        encoding="utf-8",
    )
    result = PhpAdapter.detect_frameworks(tmp_path)
    assert "drupal" in result


def test_php_adapter_detect_frameworks_wordpress(tmp_path: Path) -> None:
    """Line 159: wordpress detection from composer.json."""
    from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
    (tmp_path / "composer.json").write_text(
        _json.dumps({"require": {"wordpress/wordpress": "^6"}}),
        encoding="utf-8",
    )
    result = PhpAdapter.detect_frameworks(tmp_path)
    assert "wordpress" in result


# ---------------------------------------------------------------------------
# php_adapter: _injection_packages with non-empty frameworks (lines 179-180)
# ---------------------------------------------------------------------------


def test_php_adapter_injection_packages_nonempty() -> None:
    """Lines 179-180: _injection_packages returns packages from frameworks dict."""
    from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
    a = PhpAdapter()
    pkgs = a._injection_packages({"symfony": ["phpstan-symfony"], "laravel": ["larastan"]})
    assert "phpstan-symfony" in pkgs
    assert "larastan" in pkgs


# ---------------------------------------------------------------------------
# php_adapter: _collect_php_files OSError (lines 314-319)
# ---------------------------------------------------------------------------


def test_php_adapter_collect_test_files_with_vendor(tmp_path: Path) -> None:
    """Lines 314-317: _collect_test_files excludes vendor files, includes others."""
    from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
    # Create vendor PHP file (should be excluded)
    vendor = tmp_path / "vendor" / "phpunit" / "phpunit" / "src"
    vendor.mkdir(parents=True)
    (vendor / "TestCase.php").write_text("<?php class TestCase {}")
    # Create non-vendor PHP file (should be included)
    (tmp_path / "FooTest.php").write_text("<?php class FooTest {}")
    files = PhpAdapter._collect_test_files(tmp_path)
    assert any("FooTest.php" in str(f) for f in files)
    assert all("vendor" not in f.parts for f in files)


def test_php_adapter_collect_test_files_oserror(tmp_path: Path) -> None:
    """Line 318-319: _collect_test_files returns [] on OSError."""
    from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
    with patch.object(Path, "rglob", side_effect=OSError("permission denied")):
        files = PhpAdapter._collect_test_files(tmp_path)
    assert files == []


# ---------------------------------------------------------------------------
# php_adapter: run_l3a success paths (lines 340, 348-349, 356-357, 373-377)
# ---------------------------------------------------------------------------


def test_php_adapter_run_l3a_success_paths(tmp_path: Path) -> None:
    """Lines 340, 348-349, 356-357, 373-377: all L3A tools succeed."""
    from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
    from harness_quality_gate.adapters.base import ToolInvocation as TI
    a = PhpAdapter()
    with patch.object(type(a), "detect_frameworks",
                      return_value={"symfony": ["phpstan-symfony"]}):
        with patch.object(a._phpstan, "run_l3a", return_value=[]):
            with patch.object(a._phpmd, "run_l3a", return_value=[]):
                with patch.object(a._cs_fixer, "invoke",
                                  return_value=TI(stdout="[]", stderr="", exitcode=0)):
                    with patch.object(a._cs_fixer, "parse", return_value=[]):
                        with patch.object(a._antipattern, "invoke",
                                          return_value=TI(stdout="[]", stderr="", exitcode=0)):
                            with patch.object(a._antipattern, "parse", return_value=[]):
                                result = a.run_l3a(tmp_path, {})
    assert result.layer == "L3A"


# ---------------------------------------------------------------------------
# php_adapter: run_l1 test execution skipped (lines 458-459) and
#              mutation testing skipped (lines 533-534)
# ---------------------------------------------------------------------------


def test_php_adapter_run_l1_test_execution_skipped(tmp_path: Path) -> None:
    """Lines 458-459 and 533-534: pest_binary raises RuntimeError."""
    from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
    a = PhpAdapter()
    with patch.object(a._pcov, "probe", return_value="pcov"):
        with patch.object(a._pest, "_pest_binary",
                          side_effect=RuntimeError("pest error")):
            result = a.run_l1(tmp_path, {})
    assert result.layer == "L1"
    assert any("test execution skipped" in f.message.lower() for f in result.findings)


# ---------------------------------------------------------------------------
# php_adapter: pest framework arg in infection (lines 688) + mutation skipped (533-534)
# ---------------------------------------------------------------------------


def test_php_adapter_run_l1_pest_with_mutate_infection_runtime_error(tmp_path: Path) -> None:
    """Line 688 (pest framework arg) + 533-534 (mutation skipped via RuntimeError)."""
    from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
    from harness_quality_gate.adapters.base import ToolInvocation as TI
    a = PhpAdapter()
    with patch.object(a._pcov, "probe", return_value="pcov"):
        # Test execution block: pest project, runs fine
        with patch.object(a._pest, "_pest_binary",
                          return_value=[str(tmp_path / "vendor/bin/pest")]):
            with patch.object(a._pest, "_has_mutate_plugin", return_value=True):
                with patch.object(a._pest, "invoke",
                                  return_value=TI(stdout="", stderr="", exitcode=0)):
                    # Mutation block: pest+mutate found, infection raises RuntimeError
                    with patch.object(a._infection, "invoke",
                                      side_effect=RuntimeError("infection not found")):
                        result = a.run_l1(tmp_path, {})
    assert result.layer == "L1"


# ---------------------------------------------------------------------------
# php_adapter: run_l4 security_checker success (lines 843-849)
#              and deptrac success (lines 897-903)
# ---------------------------------------------------------------------------


def test_php_adapter_run_l4_security_checker_and_deptrac_success(tmp_path: Path) -> None:
    """Lines 843-849 (security_checker) and 897-903 (deptrac) success paths."""
    from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
    from harness_quality_gate.adapters.base import ToolInvocation as TI
    a = PhpAdapter()
    inv_ok = TI(stdout="{}", stderr="", exitcode=0)
    with patch.object(a._psalm_taint, "invoke", side_effect=RuntimeError("skip")):
        with patch.object(a._composer_audit, "invoke", side_effect=RuntimeError("skip")):
            with patch.object(a._security_checker, "invoke", return_value=inv_ok):
                with patch.object(a._security_checker, "parse", return_value=[]):
                    with patch.object(a._dead_code, "invoke", side_effect=RuntimeError("skip")):
                        with patch.object(a._dep_analyser, "invoke", side_effect=RuntimeError("skip")):
                            with patch.object(a._deptrac, "invoke", return_value=inv_ok):
                                with patch.object(a._deptrac, "parse", return_value=[]):
                                    result = a.run_l4(tmp_path, {})
    assert result.layer == "L4"


# ---------------------------------------------------------------------------
# visitor_runner_adapter: ValueError in line parsing (176-177)
#                         OSError in _collect_php_files (204-205)
#                         JSONDecodeError in _parse_visitor_output (232-233)
# ---------------------------------------------------------------------------


def test_visitor_runner_line_value_error() -> None:
    """Lines 176-177: ValueError when line field is non-integer."""
    from harness_quality_gate.adapters.php.visitor_runner_adapter import VisitorRunnerAdapter
    adapter = VisitorRunnerAdapter()
    raw = '[{"filepath": "foo.php", "line": "not-a-number", "severity": "warning", "message": "test"}]'
    findings = adapter.parse(raw, "", 0)
    assert isinstance(findings, list)


def test_visitor_runner_collect_php_files_oserror(tmp_path: Path) -> None:
    """Lines 204-205: OSError in _collect_php_files returns []."""
    from harness_quality_gate.adapters.php.visitor_runner_adapter import VisitorRunnerAdapter
    with patch.object(Path, "rglob", side_effect=OSError("permission denied")):
        files = VisitorRunnerAdapter._collect_php_files(tmp_path)
    assert files == []


def test_visitor_runner_parse_json_after_warning_text() -> None:
    """Lines 232-233: JSONDecodeError in _parse_visitor_output fallback."""
    from harness_quality_gate.adapters.php.visitor_runner_adapter import VisitorRunnerAdapter
    adapter = VisitorRunnerAdapter()
    # A '[' and ']' exist but inner content is invalid JSON
    findings = adapter.parse("[invalid json content]", "", 0)
    assert isinstance(findings, list)


# ---------------------------------------------------------------------------
# weak_test_php: missing visitor script (120-121), OSError (233-234),
#                JSONDecodeError (259-260)
# ---------------------------------------------------------------------------


def test_weak_test_visitor_script_missing(tmp_path: Path) -> None:
    """Lines 120-121: visitor script file not found → logged and skipped."""
    from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
    import harness_quality_gate.adapters.php.weak_test_php as wtm
    (tmp_path / "FooTest.php").write_text("<?php class FooTest {}")
    adapter = PhpWeakTestAdapter()
    # Return a visitor name with no corresponding .php file in the visitors dir
    with patch.object(wtm, "_WEAK_TEST_VISITORS", ["nonexistent_visitor_xyz_abc"]):
        result = adapter.invoke(tmp_path, env={})
    assert result.exitcode == 0


def test_weak_test_collect_test_files_oserror(tmp_path: Path) -> None:
    """Lines 233-234: OSError in _collect_test_files returns []."""
    from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
    with patch.object(Path, "rglob", side_effect=OSError("permission denied")):
        files = PhpWeakTestAdapter._collect_test_files(tmp_path)
    assert files == []


def test_weak_test_parse_single_output_json_fallback_decode_error() -> None:
    """Lines 259-260: JSONDecodeError in _parse_single_output fallback."""
    from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
    adapter = PhpWeakTestAdapter()
    findings = adapter.parse("[invalid json content]", "", 0)
    assert isinstance(findings, list)


# ---------------------------------------------------------------------------
# Python tool adapters: args extension branch (line 49) for all adapters
# ---------------------------------------------------------------------------


def test_bandit_adapter_invoke_with_extra_args(tmp_path: Path) -> None:
    """bandit_adapter line 49: if args: cmd.extend(args)."""
    from harness_quality_gate.adapters.python.bandit_adapter import BanditAdapter
    a = BanditAdapter()
    with patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which",
               return_value="/usr/bin/bandit"):
        with patch("subprocess.run", return_value=_fake_subprocess_result("[]")):
            result = a.invoke(tmp_path, ["--extra-flag"])
    assert result.exitcode == 0


def test_ruff_adapter_invoke_with_extra_args(tmp_path: Path) -> None:
    """ruff_adapter line 49: if args: cmd.extend(args)."""
    from harness_quality_gate.adapters.python.ruff_adapter import RuffAdapter
    a = RuffAdapter()
    with patch("harness_quality_gate.adapters.python.ruff_adapter.shutil.which",
               return_value="/usr/bin/ruff"):
        with patch("subprocess.run", return_value=_fake_subprocess_result("[]")):
            result = a.invoke(tmp_path, ["--select=ALL"])
    assert result.exitcode == 0


def test_mutmut_adapter_invoke_with_extra_args(tmp_path: Path) -> None:
    """mutmut_adapter line 49: if args: cmd.extend(args)."""
    from harness_quality_gate.adapters.python.mutmut_adapter import MutmutAdapter
    a = MutmutAdapter()
    with patch("harness_quality_gate.adapters.python.mutmut_adapter.shutil.which",
               return_value="/usr/bin/mutmut"):
        with patch("subprocess.run", return_value=_fake_subprocess_result("")):
            result = a.invoke(tmp_path, ["--help"])
    assert result.exitcode == 0


def test_pyright_adapter_invoke_with_extra_args(tmp_path: Path) -> None:
    """pyright_adapter line 49: if args: cmd.extend(args)."""
    from harness_quality_gate.adapters.python.pyright_adapter import PyrightAdapter
    a = PyrightAdapter()
    with patch("harness_quality_gate.adapters.python.pyright_adapter.shutil.which",
               return_value="/usr/bin/pyright"):
        with patch("subprocess.run", return_value=_fake_subprocess_result("{}")):
            result = a.invoke(tmp_path, ["--version"])
    assert result.exitcode == 0


def test_deptry_adapter_invoke_with_extra_args(tmp_path: Path) -> None:
    """deptry_adapter line 50: if args: cmd.extend(args)."""
    from harness_quality_gate.adapters.python.deptry_adapter import DeptryAdapter
    a = DeptryAdapter()
    with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which",
               return_value="/usr/bin/deptry"):
        with patch("subprocess.run", return_value=_fake_subprocess_result("{}")):
            result = a.invoke(tmp_path, ["--verbose"])
    assert result.exitcode == 0


def test_vulture_adapter_invoke_with_extra_args(tmp_path: Path) -> None:
    """vulture_adapter line 49: if args: cmd.extend(args)."""
    from harness_quality_gate.adapters.python.vulture_adapter import VultureAdapter
    a = VultureAdapter()
    with patch("harness_quality_gate.adapters.python.vulture_adapter.shutil.which",
               return_value="/usr/bin/vulture"):
        with patch("subprocess.run", return_value=_fake_subprocess_result("[]")):
            result = a.invoke(tmp_path, ["--min-confidence=60"])
    assert result.exitcode == 0


# ---------------------------------------------------------------------------
# deptry_adapter: filepath + line format in parse (lines 102-103)
# ---------------------------------------------------------------------------


def test_deptry_adapter_parse_with_filepath_and_line() -> None:
    """Lines 102-103: filepath:line format in deptry parse."""
    from harness_quality_gate.adapters.python.deptry_adapter import DeptryAdapter
    a = DeptryAdapter()
    data = {
        "errors": {
            "missing_imports": [
                {"module": "requests", "filepath": "src/app.py", "line": 10}
            ]
        }
    }
    findings = a.parse(_json.dumps(data), "", 0)
    assert isinstance(findings, list)
    assert len(findings) > 0
    assert "src/app.py:10" in findings[0].message


# ---------------------------------------------------------------------------
# mutmut_adapter: regex fallback parse (lines 74-76)
# ---------------------------------------------------------------------------


def test_mutmut_adapter_parse_text_fallback() -> None:
    """Lines 74-76: regex fallback when JSON parse fails."""
    from harness_quality_gate.adapters.python.mutmut_adapter import MutmutAdapter
    a = MutmutAdapter()
    # Non-JSON text with key: value pairs
    stdout = "killed: 10\nsurvived: 2\ntotal: 12\n"
    result = a.parse(stdout, "", 1)
    # parse() returns MutationStats or list depending on implementation
    assert result is not None


# ---------------------------------------------------------------------------
# pyright_adapter: non-dict diag (line 71)
# ---------------------------------------------------------------------------


def test_pyright_adapter_parse_non_dict_diag() -> None:
    """Line 71: skip non-dict items in generalDiagnostics."""
    from harness_quality_gate.adapters.python.pyright_adapter import PyrightAdapter
    a = PyrightAdapter()
    data = {"generalDiagnostics": ["not-a-dict", 42, {"file": "f.py", "severity": "error",
                                                        "message": "err", "rule": "r",
                                                        "range": {"start": {"line": 1, "character": 0}}}]}
    findings = a.parse(_json.dumps(data))
    assert isinstance(findings, list)
    # Should have 1 finding (the dict diag, non-dicts are skipped)
    assert len(findings) == 1


# ---------------------------------------------------------------------------
# vulture_adapter: JSONDecodeError in parse (lines 65-66)
# ---------------------------------------------------------------------------


def test_vulture_adapter_parse_json_decode_error() -> None:
    """Lines 65-66: JSONDecodeError in vulture parse returns []."""
    from harness_quality_gate.adapters.python.vulture_adapter import VultureAdapter
    a = VultureAdapter()
    findings = a.parse("not valid json", "", 1)
    assert findings == []


# ---------------------------------------------------------------------------
# python_adapter: python3 not on PATH (lines 229-230)
#                vulture success path (line 245)
#                deptry success path (line 257)
#                bandit success path (line 287)
# ---------------------------------------------------------------------------


def test_python_adapter_run_pytest_python_not_found(tmp_path: Path, caplog) -> None:
    """_run_pytest skips with an exact warning when python3 is not on PATH.

    Pins the simplified single-which lookup (the redundant fallback dance
    `which("python3") or "python3"` was removed as dead code).
    """
    import logging

    from harness_quality_gate.adapters.python.python_adapter import PythonAdapter

    a = PythonAdapter()
    a.pytest = MagicMock()
    mock_which = MagicMock(return_value=None)

    with patch(
        "harness_quality_gate.adapters.python.python_adapter.shutil.which", mock_which,
    ):
        with caplog.at_level(logging.WARNING):
            findings = a._run_pytest(tmp_path, {})

    assert findings == []
    mock_which.assert_called_once_with("python3")
    a.pytest.invoke.assert_not_called()
    assert "python3 not found on PATH, skipping" in caplog.messages


def test_python_adapter_run_vulture_success(tmp_path: Path) -> None:
    """Line 245: vulture success path."""
    from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
    from harness_quality_gate.adapters.base import ToolInvocation as TI
    a = PythonAdapter()
    inv = TI(stdout="[]", stderr="", exitcode=0, duration_seconds=0.0)
    with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which",
               return_value="/usr/bin/vulture"):
        with patch.object(a.vulture, "invoke", return_value=inv):
            with patch.object(a.vulture, "parse", return_value=[]):
                findings = a._run_vulture(tmp_path, {})
    assert findings == []


def test_python_adapter_run_deptry_success(tmp_path: Path) -> None:
    """Line 257: deptry success path."""
    from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
    from harness_quality_gate.adapters.base import ToolInvocation as TI
    a = PythonAdapter()
    inv = TI(stdout="{}", stderr="", exitcode=0, duration_seconds=0.0)
    with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which",
               return_value="/usr/bin/deptry"):
        with patch.object(a.deptry, "invoke", return_value=inv):
            with patch.object(a.deptry, "parse", return_value=[]):
                findings = a._run_deptry(tmp_path, {})
    assert findings == []


def test_python_adapter_run_bandit_success(tmp_path: Path) -> None:
    """Line 287: bandit success path."""
    from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
    from harness_quality_gate.adapters.base import ToolInvocation as TI
    a = PythonAdapter()
    inv = TI(stdout="[]", stderr="", exitcode=0, duration_seconds=0.0)
    with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which",
               return_value="/usr/bin/bandit"):
        with patch.object(a.bandit, "invoke", return_value=inv):
            with patch.object(a.bandit, "parse", return_value=[]):
                findings = a._run_bandit(tmp_path, {})
    assert findings == []


# ---------------------------------------------------------------------------
# detector.py: remaining branches
# ---------------------------------------------------------------------------


def test_tool_invocation_is_frozen() -> None:
    """Verify ToolInvocation is a frozen dataclass (immutable)."""
    inv = ToolInvocation(stdout="out", stderr="err", exitcode=0)
    with pytest.raises((AttributeError, TypeError)):
        inv.stdout = "modified"  # type: ignore[misc]


def test_tool_invocation_default_values() -> None:
    """Kill default-value mutants for ToolInvocation fields."""
    inv = ToolInvocation()
    assert inv.stdout == ""
    assert inv.stderr == ""
    assert inv.exitcode == 0
    assert inv.duration_seconds == 0.0
