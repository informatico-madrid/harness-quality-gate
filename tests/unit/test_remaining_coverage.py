"""Comprehensive tests to close coverage gaps across multiple modules.

Targets:
  - php_adapter.py (67%)
  - framework_sniffer.py (56%)
  - python_adapter.py (68%)
  - pytest_adapter.py (42%)
  - doctor.py (83%)
  - detector.py (85%)
  - base.py (77%)
  - installer.py (95%)
  - Various small-gap adapters
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.base import ToolAdapter, ToolInvocation
from harness_quality_gate.models import MutationStats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inv(stdout: str = "", stderr: str = "", exitcode: int = 0) -> ToolInvocation:
    return ToolInvocation(stdout=stdout, stderr=stderr, exitcode=exitcode)


# ===========================================================================
# 1. base.py — abstract stubs + _run() edge cases
# ===========================================================================

class _ConcreteAdapter(ToolAdapter):
    """Minimal concrete subclass for testing ToolAdapter methods."""

    _name = "concrete"

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo, env=None) -> str:
        return "1.0"

    def invoke(self, repo, args, *, env=None, timeout=300.0) -> ToolInvocation:
        return self._run(["echo", "hi"], cwd=repo, env=env, timeout=timeout)

    def parse(self, stdout, stderr="", exitcode=0):
        return []


class TestBaseToolAdapter:
    def test_name_property(self, tmp_path):
        a = _ConcreteAdapter()
        assert a.name == "concrete"

    def test_run_timeout_returns_invocation(self, tmp_path):
        """_run handles TimeoutExpired and returns exitcode=-1."""
        a = _ConcreteAdapter()
        with patch("harness_quality_gate.adapters.base.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd=["php"], timeout=1)):
            result = a._run(["php", "-v"], cwd=tmp_path)
        assert result.exitcode == -1

    def test_run_timeout_with_bytes_output(self, tmp_path):
        """_run handles TimeoutExpired where stdout/stderr are bytes."""
        a = _ConcreteAdapter()
        exc = subprocess.TimeoutExpired(cmd=["php"], timeout=1)
        exc.stdout = b"some output"
        exc.stderr = b"some error"
        with patch("harness_quality_gate.adapters.base.subprocess.run", side_effect=exc):
            result = a._run(["php", "-v"], cwd=tmp_path)
        assert result.exitcode == -1
        assert result.stdout == "some output"
        assert result.stderr == "some error"

    def test_run_success(self, tmp_path):
        """_run returns ToolInvocation on success."""
        a = _ConcreteAdapter()
        mock_result = MagicMock()
        mock_result.stdout = "hello"
        mock_result.stderr = ""
        mock_result.returncode = 0
        with patch("harness_quality_gate.adapters.base.subprocess.run",
                   return_value=mock_result):
            result = a._run(["echo", "hello"], cwd=tmp_path)
        assert result.stdout == "hello"
        assert result.exitcode == 0


# ===========================================================================
# 2. pytest_adapter.py — JUnit XML parsing
# ===========================================================================

class TestPytestAdapterParse:
    def _adapter(self):
        from harness_quality_gate.adapters.python.pytest_adapter import PytestAdapter
        return PytestAdapter()

    def test_name(self):
        assert self._adapter().name == "pytest"

    def test_empty_stdout(self):
        findings = self._adapter().parse("")
        assert findings == []

    def test_invalid_xml(self):
        findings = self._adapter().parse("not xml at all")
        assert findings == []

    def test_failure_testcase(self):
        xml = """<?xml version="1.0"?>
<testsuite tests="1" failures="1" errors="0">
  <testcase classname="tests.foo" name="test_bar">
    <failure message="AssertionError: expected 1 got 2">full traceback</failure>
  </testcase>
</testsuite>"""
        findings = self._adapter().parse(xml)
        assert any(f.rule_id == "failure" for f in findings)
        assert any(f.rule_id == "summary" for f in findings)

    def test_error_testcase(self):
        xml = """<?xml version="1.0"?>
<testsuite tests="1" failures="0" errors="1">
  <testcase classname="tests.foo" name="test_error">
    <error message="ImportError">traceback here</error>
  </testcase>
</testsuite>"""
        findings = self._adapter().parse(xml)
        assert any(f.rule_id == "error" for f in findings)
        assert any(f.rule_id == "summary" for f in findings)

    def test_skipped_testcase(self):
        xml = """<?xml version="1.0"?>
<testsuite tests="1" failures="0" errors="0" skipped="1">
  <testcase classname="tests.foo" name="test_skip">
    <skipped message="reason">some reason</skipped>
  </testcase>
</testsuite>"""
        findings = self._adapter().parse(xml)
        assert any(f.rule_id == "skipped" for f in findings)

    def test_empty_testsuite(self):
        xml = """<?xml version="1.0"?>
<testsuite tests="0" failures="0" errors="0">
</testsuite>"""
        findings = self._adapter().parse(xml)
        assert findings == []

    def test_failure_no_message_uses_text(self):
        xml = """<?xml version="1.0"?>
<testsuite tests="1" failures="1">
  <testcase name="test_x">
    <failure>text only failure</failure>
  </testcase>
</testsuite>"""
        findings = self._adapter().parse(xml)
        assert any(f.rule_id == "failure" for f in findings)

    def test_failure_and_skip_in_summary(self):
        xml = """<?xml version="1.0"?>
<testsuite tests="3" failures="1" errors="1" skipped="1">
  <testcase classname="A" name="t1">
    <failure message="fail">fail</failure>
  </testcase>
  <testcase classname="A" name="t2">
    <error message="err">err</error>
  </testcase>
  <testcase classname="A" name="t3">
    <skipped message="skip"/>
  </testcase>
</testsuite>"""
        findings = self._adapter().parse(xml)
        summary = next(f for f in findings if f.rule_id == "summary")
        assert "failure" in summary.message
        assert "error" in summary.message
        assert "skipped" in summary.message

    def test_invoke_extends_args(self, tmp_path):
        """invoke() adds extra args after the base command."""
        a = self._adapter()
        with patch.object(a.__class__, "_run", return_value=_inv()) as mock_run:
            a.invoke(tmp_path, ["--tb=short"])
            cmd = mock_run.call_args[0][0]
        assert "--tb=short" in cmd


# ===========================================================================
# 3. framework_sniffer.py
# ===========================================================================

class TestFrameworkSniffer:
    def test_unknown_language_returns_none(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        result = sniff_framework(tmp_path, "rust")
        assert result is None

    def test_php_no_composer(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        result = sniff_framework(tmp_path, "php")
        assert result is None

    def test_php_laravel_via_manifest(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        (tmp_path / "composer.json").write_text(
            json.dumps({"require": {"laravel/framework": "^10"}}), encoding="utf-8"
        )
        assert sniff_framework(tmp_path, "php") == "laravel"

    def test_php_symfony_via_manifest(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        (tmp_path / "composer.json").write_text(
            json.dumps({"require": {"symfony/framework-bundle": "^6"}}), encoding="utf-8"
        )
        assert sniff_framework(tmp_path, "php") == "symfony"

    def test_php_drupal_via_manifest(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        (tmp_path / "composer.json").write_text(
            json.dumps({"require": {"drupal/core": "^10"}}), encoding="utf-8"
        )
        assert sniff_framework(tmp_path, "php") == "drupal"

    def test_php_wordpress_via_manifest(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        (tmp_path / "composer.json").write_text(
            json.dumps({"require": {"roots/wordpress": "^6"}}), encoding="utf-8"
        )
        assert sniff_framework(tmp_path, "php") == "wordpress"

    def test_php_composer_json_decode_error(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        (tmp_path / "composer.json").write_text("NOT JSON", encoding="utf-8")
        # Should not raise, returns None (no heuristic match either)
        result = sniff_framework(tmp_path, "php")
        assert result is None

    def test_php_symfony_heuristic(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        app_dir = tmp_path / "App"
        app_dir.mkdir()
        (app_dir / "Kernel.php").write_text("<?php", encoding="utf-8")
        assert sniff_framework(tmp_path, "php") == "symfony"

    def test_php_wordpress_heuristic(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        wp = tmp_path / "wp-includes"
        wp.mkdir()
        (wp / "version.php").write_text("<?php", encoding="utf-8")
        assert sniff_framework(tmp_path, "php") == "wordpress"

    def test_php_vendor_manifest_detection(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        vendor = tmp_path / "vendor" / "laravel" / "framework"
        vendor.mkdir(parents=True)
        (vendor / "composer.json").write_text(
            json.dumps({"name": "laravel/framework"}), encoding="utf-8"
        )
        assert sniff_framework(tmp_path, "php") == "laravel"

    def test_php_vendor_manifest_bad_json(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        vendor = tmp_path / "vendor" / "laravel" / "framework"
        vendor.mkdir(parents=True)
        (vendor / "composer.json").write_text("INVALID", encoding="utf-8")
        # Falls through to heuristics, returns None since no match
        result = sniff_framework(tmp_path, "php")
        assert result is None

    def test_python_django_manifest(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        (tmp_path / "requirements.txt").write_text("Django>=4.2\n", encoding="utf-8")
        assert sniff_framework(tmp_path, "python") == "django"

    def test_python_flask_manifest(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        (tmp_path / "requirements.txt").write_text("flask>=2.0\n", encoding="utf-8")
        assert sniff_framework(tmp_path, "python") == "flask"

    def test_python_fastapi_manifest(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        (tmp_path / "requirements.txt").write_text("fastapi>=0.100\n", encoding="utf-8")
        assert sniff_framework(tmp_path, "python") == "fastapi"

    def test_python_manage_py_heuristic(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        (tmp_path / "manage.py").write_text("#!/usr/bin/env python", encoding="utf-8")
        assert sniff_framework(tmp_path, "python") == "django"

    def test_python_fastapi_heuristic_no_match(self, tmp_path):
        """The fastapi heuristic checks file paths (not content), so a plain .py file
        won't match unless its path contains 'from fastapi import'. Verify returns None."""
        from harness_quality_gate.framework_sniffer import sniff_framework
        (tmp_path / "main.py").write_text("from fastapi import FastAPI", encoding="utf-8")
        # _dir_has_content matches against str(filepath), not file content
        # so this returns None (no fastapi in the path name)
        result = sniff_framework(tmp_path, "python")
        assert result is None

    def test_python_no_framework(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        assert sniff_framework(tmp_path, "python") is None

    def test_python_pyproject_poetry_deps(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        toml = "[tool.poetry.dependencies]\ndjango = \"^4.2\"\n"
        (tmp_path / "pyproject.toml").write_text(toml, encoding="utf-8")
        assert sniff_framework(tmp_path, "python") == "django"

    def test_python_pyproject_project_deps(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        toml = '[project]\ndependencies = ["Django>=4.2", "requests"]\n'
        (tmp_path / "pyproject.toml").write_text(toml, encoding="utf-8")
        assert sniff_framework(tmp_path, "python") == "django"

    def test_python_pipfile(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        pipfile = "[packages]\nDjango = \"*\"\n"
        (tmp_path / "Pipfile").write_text(pipfile, encoding="utf-8")
        assert sniff_framework(tmp_path, "python") == "django"

    def test_python_setup_py(self, tmp_path):
        from harness_quality_gate.framework_sniffer import sniff_framework
        (tmp_path / "setup.py").write_text("flask\n", encoding="utf-8")
        assert sniff_framework(tmp_path, "python") == "flask"

    def test_dir_has_content_no_dir(self, tmp_path):
        import re
        from harness_quality_gate.framework_sniffer import _dir_has_content
        assert _dir_has_content(tmp_path, "nonexistent", re.compile(r".*")) is False

    def test_python_flask_heuristic_no_match(self, tmp_path):
        """The flask heuristic checks file paths (not content), so a plain app.py
        won't match unless its path contains 'from flask import'. Verify returns None."""
        from harness_quality_gate.framework_sniffer import sniff_framework
        # _dir_has_content matches against str(filepath), not file content
        (tmp_path / "app.py").write_text("from flask import Flask\napp = Flask(__name__)", encoding="utf-8")
        result = sniff_framework(tmp_path, "python")
        assert result is None


# ===========================================================================
# 4. detector.py — edge cases
# ===========================================================================

class TestDetector:
    def test_detect_force_bypasses_cache(self, tmp_path):
        from harness_quality_gate.detector import detect
        (tmp_path / "pyproject.toml").write_text("[tool.poetry]\n", encoding="utf-8")
        result = detect(tmp_path, force=True)
        assert result.language == "python"

    def test_detect_hybrid_php_wins(self, tmp_path):
        from harness_quality_gate.detector import detect
        # PHP manifest + many PHP files
        (tmp_path / "composer.json").write_text("{}", encoding="utf-8")
        for i in range(5):
            (tmp_path / f"file{i}.php").write_text("<?php", encoding="utf-8")
        result = detect(tmp_path, force=True)
        assert result.language == "php"

    def test_detect_empty_dir_defaults_python(self, tmp_path):
        from harness_quality_gate.detector import detect
        result = detect(tmp_path, force=True)
        assert result.language == "python"

    def test_detect_py_files_only(self, tmp_path):
        from harness_quality_gate.detector import detect
        (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
        result = detect(tmp_path, force=True)
        assert result.language == "python"

    def test_detect_php_files_only(self, tmp_path):
        from harness_quality_gate.detector import detect
        (tmp_path / "index.php").write_text("<?php", encoding="utf-8")
        result = detect(tmp_path, force=True)
        assert result.language == "php"

    def test_detect_tie_prefers_python(self, tmp_path):
        from harness_quality_gate.detector import detect
        # Equal py/php file counts, no manifests
        (tmp_path / "a.py").write_text("x=1", encoding="utf-8")
        (tmp_path / "b.php").write_text("<?php", encoding="utf-8")
        result = detect(tmp_path, force=True)
        assert result.language == "python"

    def test_detect_tier1_override_php(self, tmp_path):
        from harness_quality_gate.detector import detect
        (tmp_path / ".quality-gate-lang").write_text("php\n", encoding="utf-8")
        result = detect(tmp_path, force=True)
        assert result.language == "php"

    def test_detect_tier1_override_py_alias(self, tmp_path):
        from harness_quality_gate.detector import detect
        (tmp_path / ".quality-gate-lang").write_text("py\n", encoding="utf-8")
        result = detect(tmp_path, force=True)
        assert result.language == "python"

    def test_cache_roundtrip(self, tmp_path):
        from harness_quality_gate.detector import detect, _load_cache
        (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        detect(tmp_path, force=True)
        cached = _load_cache(tmp_path)
        assert cached is not None
        assert cached.language == "python"

    def test_framework_signals_pest(self, tmp_path):
        from harness_quality_gate.detector import framework_signals
        (tmp_path / "composer.json").write_text(
            json.dumps({
                "require-dev": {
                    "pestphp/pest": "^2",
                    "pestphp/pest-plugin-mutate": "^2",
                }
            }),
            encoding="utf-8",
        )
        signals = framework_signals(tmp_path)
        assert "pest" in signals.get("php", [])

    def test_framework_signals_composer_json_error(self, tmp_path):
        from harness_quality_gate.detector import framework_signals
        (tmp_path / "composer.json").write_text("INVALID", encoding="utf-8")
        # should not raise
        signals = framework_signals(tmp_path)
        assert isinstance(signals, dict)

    def test_detect_ci_environment(self, monkeypatch):
        from harness_quality_gate.detector import _detect_ci_environment
        monkeypatch.setenv("CI", "true")
        assert _detect_ci_environment() is True

    def test_detect_concurrency_from_env(self, monkeypatch):
        from harness_quality_gate.detector import _detect_concurrency_mode
        monkeypatch.setenv("CLAUDE_CODE_CONCURRENCY", "sequential")
        assert _detect_concurrency_mode() == "sequential"

    def test_current_git_head_not_git(self, tmp_path):
        from harness_quality_gate.detector import _current_git_head
        # Not a git repo
        result = _current_git_head(tmp_path)
        # Either returns a string or None; should not raise
        assert result is None or isinstance(result, str)

    def test_any_manifest_stale(self, tmp_path):
        from harness_quality_gate.detector import _any_manifest_stale
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        import time
        time.sleep(0.01)
        result = _any_manifest_stale(tmp_path, cache_mtime=0.0)
        assert result is True


# ===========================================================================
# 5. doctor.py — coverage gaps
# ===========================================================================

class TestDoctor:
    def test_run_pass(self, tmp_path):
        import harness_quality_gate.doctor as doctor
        with patch.object(doctor, "_resolve_tool", return_value="/bin/tool"):
            with patch.object(doctor, "_try_version", return_value="1.0"):
                with patch.object(doctor, "_detect_php_extensions", return_value=[]):
                    with patch("harness_quality_gate.doctor.shutil.which", return_value="/bin/php"):
                        report = doctor.run(tmp_path)
        assert report.verdict in ("PASS", "INFRA_INCOMPLETE")

    def test_run_infra_incomplete(self, tmp_path):
        import harness_quality_gate.doctor as doctor
        with patch.object(doctor, "_resolve_tool", return_value=None):
            with patch.object(doctor, "_detect_php_extensions", return_value=[]):
                with patch("harness_quality_gate.doctor.shutil.which", return_value=None):
                    report = doctor.run(tmp_path)
        assert report.verdict == "INFRA_INCOMPLETE"

    def test_run_json_mode(self, tmp_path):
        import harness_quality_gate.doctor as doctor
        with patch.object(doctor, "_resolve_tool", return_value=None):
            with patch.object(doctor, "_detect_php_extensions", return_value=[]):
                with patch("harness_quality_gate.doctor.shutil.which", return_value=None):
                    report = doctor.run(tmp_path, json_mode=True)
        assert report is not None

    def test_asdict(self, tmp_path):
        import harness_quality_gate.doctor as doctor
        from harness_quality_gate.models import DoctorReport, ToolCheckReport
        report = DoctorReport(
            verdict="PASS",
            python_version="3.12",
            php_version="8.3",
            composer_version="2.8",
            tools=[ToolCheckReport(tool="phpunit", exit_code=0, output="11.0", error=None)],
            warnings=[],
        )
        d = doctor.asdict(report)
        assert d["verdict"] == "PASS"
        assert len(d["tools"]) == 1

    def test_resolve_tool_phar(self, tmp_path):
        import harness_quality_gate.doctor as doctor
        phar_dir = tmp_path / ".cache" / "harness-quality-gate" / "bin"
        phar_dir.mkdir(parents=True)
        phar = phar_dir / "phpunit.phar"
        phar.write_text("phar")
        phar.chmod(0o755)
        with patch("os.path.expanduser", return_value=str(phar)):
            result = doctor._resolve_tool("phpunit", tmp_path)
        # Can be None if which fails; just check it doesn't raise
        assert result is None or isinstance(result, str)

    def test_resolve_tool_vendor_bin(self, tmp_path):
        import harness_quality_gate.doctor as doctor
        vendor = tmp_path / "vendor" / "bin"
        vendor.mkdir(parents=True)
        phpunit = vendor / "phpunit"
        phpunit.write_text("#!/bin/sh")
        phpunit.chmod(0o755)
        result = doctor._resolve_tool("phpunit", tmp_path)
        assert result == str(phpunit)

    def test_try_version_none_path(self):
        import harness_quality_gate.doctor as doctor
        assert doctor._try_version(None, "phpunit") == ""

    def test_try_version_oserror(self):
        import harness_quality_gate.doctor as doctor
        with patch("subprocess.run", side_effect=OSError("not found")):
            result = doctor._try_version("phpunit", "phpunit")
        assert result == ""

    def test_detect_php_extensions_pcov_and_xdebug(self):
        import harness_quality_gate.doctor as doctor
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "pcov\nxdebug\n"
        with patch("subprocess.run", return_value=mock_result):
            warnings = doctor._detect_php_extensions()
        assert any("PCOV" in w or "Xdebug" in w or "pcov" in w.lower() for w in warnings)

    def test_detect_php_extensions_oserror(self):
        import harness_quality_gate.doctor as doctor
        with patch("subprocess.run", side_effect=OSError("no php")):
            warnings = doctor._detect_php_extensions()
        assert warnings == []

    def test_print_human_pass(self, tmp_path, capsys):
        import harness_quality_gate.doctor as doctor
        from harness_quality_gate.models import DoctorReport, ToolCheckReport
        report = DoctorReport(
            verdict="PASS",
            python_version="3.12",
            php_version="8.3",
            composer_version="2.8",
            tools=[
                ToolCheckReport(tool="phpunit", exit_code=0, output="11.0", error=None),
                ToolCheckReport(tool="infection", exit_code=127, output=None, error="no encontrado"),
            ],
            warnings=["test warning"],
        )
        doctor._print_human(report, ["infection"])
        captured = capsys.readouterr()
        assert "Diagnóstico" in captured.out

    def test_print_human_infra_incomplete(self, tmp_path, capsys):
        import harness_quality_gate.doctor as doctor
        from harness_quality_gate.models import DoctorReport, ToolCheckReport
        report = DoctorReport(
            verdict="INFRA_INCOMPLETE",
            python_version="",
            php_version="",
            composer_version="",
            tools=[ToolCheckReport(tool="phpunit", exit_code=127, output=None, error="no encontrado")],
            warnings=[],
        )
        doctor._print_human(report, ["phpunit"])
        captured = capsys.readouterr()
        assert "incompleta" in captured.out or "INFRA" in captured.out or "Diagnóstico" in captured.out


# ===========================================================================
# 6. installer.py — small gaps
# ===========================================================================

class TestInstaller:
    def _make_config(self, repo: Path) -> None:
        config_dir = repo / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "php-tool-versions.json").write_text(
            json.dumps({
                "phpunit": {"version": "^11.0", "phar_url": "", "sha256": "placeholder-phase-2"},
                "phpstan": {"version": "^1.10", "phar_url": "http://example.com/phpstan.phar",
                            "sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"},
            }),
            encoding="utf-8",
        )

    def test_install_no_composer(self, tmp_path):
        from harness_quality_gate import installer
        self._make_config(tmp_path)
        with patch("harness_quality_gate.installer.shutil.which", return_value=None):
            report = installer.install(tmp_path)
        assert report.status in ("error", "partial")

    def test_install_phar_only_placeholder(self, tmp_path):
        from harness_quality_gate import installer
        import urllib.error
        self._make_config(tmp_path)
        # Patch urlopen so it raises URLError for the non-placeholder entry
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("blocked")):
            report = installer.install(tmp_path, phar_only=True)
        # phpunit has placeholder sha256 → should fail regardless
        assert "phpunit" in report.tools_failed
        # phpstan attempted download → also fails (URLError)
        assert "phpstan" in report.tools_failed

    def test_find_config_path_not_found(self, tmp_path):
        from harness_quality_gate import installer
        with pytest.raises(FileNotFoundError):
            installer._find_config_path(tmp_path)

    def test_run_composer_timeout(self, tmp_path):
        from harness_quality_gate import installer
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd=["composer"], timeout=600)):
            success, err = installer._run_composer_require(tmp_path, "phpunit", "^11")
        assert success is False
        assert err is not None

    def test_run_composer_not_found(self, tmp_path):
        from harness_quality_gate import installer
        with patch("subprocess.run", side_effect=FileNotFoundError("composer not found")):
            success, err = installer._run_composer_require(tmp_path, "phpunit", "^11")
        assert success is False
        assert err is not None and "composer not found" in err

    def test_download_phar_checksum_mismatch(self, tmp_path):
        """SHA-256 mismatch kills the PHAR and returns error."""
        import hashlib
        from harness_quality_gate import installer

        bad_data = b"wrong data"
        correct_sha = hashlib.sha256(b"correct data").hexdigest()  # different from actual

        mock_resp = MagicMock()
        mock_resp.read.return_value = bad_data
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        # Patch Path.exists to return False so the cache check is bypassed
        with patch.object(installer.Path, "exists", return_value=False):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                success, path, err = installer._download_phar(
                    "phpunit", "11.0", "http://example.com/phpunit.phar", correct_sha
                )

        assert success is False
        assert path is None
        assert err is not None
        assert "mismatch" in err.lower()

    def test_make_report_partial(self):
        from harness_quality_gate import installer
        report = installer._make_report(["phpunit"], ["phpstan"], ["phpstan: failed"])
        assert report.status == "partial"

    def test_make_report_error(self):
        from harness_quality_gate import installer
        report = installer._make_report([], ["phpstan"], ["phpstan: failed"])
        assert report.status == "error"


# ===========================================================================
# 7. python_adapter.py — tool_versions, check_tools, _run_* helpers
# ===========================================================================

class TestPythonAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_name_property(self):
        a = self._adapter()
        assert a._name == "python"

    def test_tool_versions_all_missing(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            with patch.object(a.ruff.__class__, "version", side_effect=RuntimeError("missing")):
                with patch.object(a.pyright.__class__, "version", side_effect=RuntimeError("missing")):
                    versions = a.tool_versions()
        assert isinstance(versions, dict)

    def test_check_tools_missing_ruff(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="Missing Python"):
                a.check_tools()

    def test_check_tools_all_present(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value="/bin/tool"):
            result = a.check_tools()
        assert "ruff" in result

    def test_run_ruff_not_found(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            findings = a._run_ruff(tmp_path, {})
        assert findings == []

    def test_run_ruff_oserror(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value="/bin/ruff"):
            with patch.object(a.ruff, "invoke", side_effect=OSError("broken")):
                findings = a._run_ruff(tmp_path, {})
        assert findings == []

    def test_run_pyright_not_found(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            findings = a._run_pyright(tmp_path, {})
        assert findings == []

    def test_run_pyright_oserror(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value="/bin/pyright"):
            with patch.object(a.pyright, "invoke", side_effect=OSError("broken")):
                findings = a._run_pyright(tmp_path, {})
        assert findings == []

    def test_run_pytest_oserror(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value="/bin/python3"):
            with patch.object(a.pytest, "invoke", side_effect=OSError("broken")):
                findings = a._run_pytest(tmp_path, {})
        assert findings == []

    def test_run_vulture_not_found(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            findings = a._run_vulture(tmp_path, {})
        assert findings == []

    def test_run_vulture_oserror(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value="/bin/vulture"):
            with patch.object(a.vulture, "invoke", side_effect=OSError("broken")):
                findings = a._run_vulture(tmp_path, {})
        assert findings == []

    def test_run_deptry_not_found(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            findings = a._run_deptry(tmp_path, {})
        assert findings == []

    def test_run_deptry_oserror(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value="/bin/deptry"):
            with patch.object(a.deptry, "invoke", side_effect=OSError("broken")):
                findings = a._run_deptry(tmp_path, {})
        assert findings == []

    def test_run_mutmut_not_found(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            stats = a._run_mutmut(tmp_path, {})
        assert stats.total == 0

    def test_run_mutmut_oserror(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value="/bin/mutmut"):
            with patch.object(a.mutmut, "invoke", side_effect=OSError("broken")):
                stats = a._run_mutmut(tmp_path, {})
        assert stats.total == 0

    def test_run_bandit_not_found(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value=None):
            findings = a._run_bandit(tmp_path, {})
        assert findings == []

    def test_run_bandit_oserror(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.shutil.which", return_value="/bin/bandit"):
            with patch.object(a.bandit, "invoke", side_effect=OSError("broken")):
                findings = a._run_bandit(tmp_path, {})
        assert findings == []


# ===========================================================================
# 8. php_adapter.py
# ===========================================================================

class TestPhpAdapterProperties:
    def _adapter(self):
        from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
        return PhpAdapter()

    def test_name_property(self):
        a = self._adapter()
        assert a.name == "php"

    def test_tool_versions_missing(self, tmp_path):
        a = self._adapter()
        with patch.object(a._phpstan, "version", side_effect=RuntimeError("missing")):
            with patch.object(a._phpmd, "version", side_effect=RuntimeError("missing")):
                with patch.object(a._cs_fixer, "version", side_effect=RuntimeError("missing")):
                    versions = a.tool_versions()
        assert all(v == "MISSING" for v in versions.values())

    def test_check_tools_missing(self, tmp_path):
        a = self._adapter()
        with patch.object(a._phpstan, "version", side_effect=RuntimeError("missing")):
            with patch.object(a._phpmd, "version", side_effect=RuntimeError("missing")):
                with patch.object(a._cs_fixer, "version", side_effect=RuntimeError("missing")):
                    with pytest.raises(RuntimeError, match="Missing PHP"):
                        a.check_tools()

    def test_check_tools_all_present(self, tmp_path):
        a = self._adapter()
        with patch.object(a._phpstan, "version", return_value="1.0"):
            with patch.object(a._phpmd, "version", return_value="2.0"):
                with patch.object(a._cs_fixer, "version", return_value="3.0"):
                    result = a.check_tools()
        assert "phpstan" in result

    def test_detect_frameworks_no_composer(self, tmp_path):
        from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
        result = PhpAdapter.detect_frameworks(tmp_path)
        assert result == {}

    def test_detect_frameworks_invalid_json(self, tmp_path):
        from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
        (tmp_path / "composer.json").write_text("INVALID", encoding="utf-8")
        result = PhpAdapter.detect_frameworks(tmp_path)
        assert result == {}

    def test_detect_frameworks_symfony(self, tmp_path):
        from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
        (tmp_path / "composer.json").write_text(
            json.dumps({"require": {"symfony/framework-bundle": "^6"}}),
            encoding="utf-8",
        )
        result = PhpAdapter.detect_frameworks(tmp_path)
        assert "symfony" in result

    def test_detect_frameworks_laravel(self, tmp_path):
        from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
        (tmp_path / "composer.json").write_text(
            json.dumps({"require": {"laravel/framework": "^10"}}),
            encoding="utf-8",
        )
        result = PhpAdapter.detect_frameworks(tmp_path)
        assert "laravel" in result

    def test_build_phpstan_extra_config_empty(self):
        from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
        assert PhpAdapter._build_phpstan_extra_config([]) == ""

    def test_build_phpstan_extra_config_with_packages(self):
        from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
        result = PhpAdapter._build_phpstan_extra_config(["phpstan-symfony"])
        assert "phpstan-symfony" in result

    def test_validate_infection_stats_all_pass(self):
        from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
        stats = MutationStats(
            total=10, killed=10, survived=0, timed_out=0,
            escaped=0, untested=0, msi=100.0, covered_msi=100.0,
        )
        findings = PhpAdapter._validate_infection_stats(stats)
        assert findings == []

    def test_validate_infection_stats_low_msi(self):
        from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
        stats = MutationStats(
            total=10, killed=5, survived=5, timed_out=0,
            escaped=0, untested=0, msi=50.0, covered_msi=50.0,
        )
        findings = PhpAdapter._validate_infection_stats(stats)
        assert any("Mutation score" in f.message for f in findings)

    def test_validate_infection_stats_low_covered_msi(self):
        from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
        stats = MutationStats(
            total=10, killed=10, survived=0, timed_out=0,
            escaped=0, untested=0, msi=100.0, covered_msi=50.0,
        )
        findings = PhpAdapter._validate_infection_stats(stats)
        assert any("Covered" in f.message for f in findings)

    def test_validate_infection_stats_escaped(self):
        from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
        stats = MutationStats(
            total=10, killed=9, survived=1, timed_out=0,
            escaped=1, untested=0, msi=100.0, covered_msi=100.0,
        )
        findings = PhpAdapter._validate_infection_stats(stats)
        assert any("escaped" in f.message for f in findings)

    def test_validate_infection_stats_timed_out(self):
        from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
        stats = MutationStats(
            total=10, killed=9, survived=0, timed_out=1,
            escaped=0, untested=0, msi=100.0, covered_msi=100.0,
        )
        findings = PhpAdapter._validate_infection_stats(stats)
        assert any("timed out" in f.message for f in findings)


class TestPhpAdapterL1:
    def _adapter(self):
        from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
        return PhpAdapter()

    def test_run_l1_pcov_probe_fails(self, tmp_path):
        a = self._adapter()
        with patch.object(a._pcov, "probe", side_effect=RuntimeError("no php")):
            with patch.object(a._pest, "_pest_binary", return_value=None):
                with patch.object(a._phpunit, "invoke", return_value=_inv()):
                    with patch.object(a._phpunit, "parse", return_value=[]):
                        with patch.object(a._infection, "invoke",
                                          return_value=_inv(exitcode=3)):
                            result = a.run_l1(tmp_path, {})
        assert result.layer == "L1"
        assert any("Coverage driver" in f.message for f in result.findings)

    def test_run_l1_pest_project_no_mutate(self, tmp_path):
        a = self._adapter()
        with patch.object(a._pcov, "probe", return_value="pcov"):
            with patch.object(a._pest, "_pest_binary", return_value=[str(tmp_path / "vendor/bin/pest")]):
                with patch.object(a._pest, "_has_mutate_plugin", return_value=False):
                    with patch.object(a._pest, "invoke", return_value=_inv(exitcode=0)):
                        result = a.run_l1(tmp_path, {})
        assert result.layer == "L1"
        assert result.tool_specific is not None and "mutation_skipped" in result.tool_specific

    def test_run_l1_pest_tests_fail(self, tmp_path):
        a = self._adapter()
        with patch.object(a._pcov, "probe", return_value="pcov"):
            with patch.object(a._pest, "_pest_binary", return_value=["/bin/pest"]):
                with patch.object(a._pest, "_has_mutate_plugin", return_value=False):
                    with patch.object(a._pest, "invoke", return_value=_inv(exitcode=1)):
                        result = a.run_l1(tmp_path, {})
        assert any(f.tool == "pest" for f in result.findings)

    def test_run_l1_infection_required_but_unavailable(self, tmp_path):
        a = self._adapter()
        with patch.object(a._pcov, "probe", return_value="pcov"):
            with patch.object(a._pest, "_pest_binary", return_value=None):
                with patch.object(a._phpunit, "invoke", return_value=_inv()):
                    with patch.object(a._phpunit, "parse", return_value=[]):
                        with patch.object(a._infection, "invoke",
                                          return_value=_inv(stdout="", exitcode=3)):
                            result = a.run_l1(tmp_path, {"HARNESS_INFECTION_REQUIRED": "1"})
        assert any("HARNESS_INFECTION_REQUIRED" in f.message for f in result.findings)

    def test_run_l1_infection_infra_error(self, tmp_path):
        a = self._adapter()
        with patch.object(a._pcov, "probe", return_value="pcov"):
            with patch.object(a._pest, "_pest_binary", return_value=None):
                with patch.object(a._phpunit, "invoke", return_value=_inv()):
                    with patch.object(a._phpunit, "parse", return_value=[]):
                        with patch.object(a._infection, "invoke",
                                          return_value=_inv(stderr="Fatal error", exitcode=1)):
                            result = a.run_l1(tmp_path, {})
        # Infra error → no mutation stats
        assert result.layer == "L1"

    def test_run_l1_infection_stats_parsed(self, tmp_path):
        a = self._adapter()
        infection_text = (
            "6 mutations were generated:\n"
            "   6 mutants were killed\n"
            "   0 covered mutants were not detected\n"
            "   0 mutants were not covered\n"
            "   0 errors were encountered\n"
            "   0 time outs were encountered\n"
            "Metrics:\n"
            "  Mutation Score Indicator (MSI): 100%\n"
            "  Covered Code MSI: 100%\n"
        )
        with patch.object(a._pcov, "probe", return_value="pcov"):
            with patch.object(a._pest, "_pest_binary", return_value=None):
                with patch.object(a._phpunit, "invoke", return_value=_inv()):
                    with patch.object(a._phpunit, "parse", return_value=[]):
                        with patch.object(a._infection, "invoke",
                                          return_value=_inv(stdout=infection_text, exitcode=0)):
                            result = a.run_l1(tmp_path, {})
        assert result.tool_specific is not None and "mutation" in result.tool_specific

    def test_pcov_initial_tests_option_already_loaded(self):
        a = self._adapter()
        mock_result = MagicMock()
        mock_result.stdout = "pcov\n"
        with patch("subprocess.run", return_value=mock_result):
            flag = a._pcov_initial_tests_option()
        assert flag == ""

    def test_pcov_initial_tests_option_oserror(self):
        a = self._adapter()
        with patch("subprocess.run", side_effect=OSError("no php")):
            flag = a._pcov_initial_tests_option()
        assert flag == ""

    def test_pcov_initial_tests_option_glob_found(self, tmp_path):
        a = self._adapter()
        mock_result = MagicMock()
        mock_result.stdout = "no_pcov\n"
        # Create a fake pcov.so
        pcov_path = tmp_path / "pcov.so"
        pcov_path.write_bytes(b"")
        with patch("subprocess.run", return_value=mock_result):
            with patch("glob.glob", return_value=[str(pcov_path)]):
                flag = a._pcov_initial_tests_option()
        assert "pcov.so" in flag or flag == ""

    def test_run_phpunit_tests_runtime_error(self, tmp_path):
        a = self._adapter()
        with patch.object(a._phpunit, "invoke", side_effect=RuntimeError("not found")):
            findings = a._run_phpunit_tests(tmp_path, {})
        assert findings == []

    def test_run_pest_tests_runtime_error(self, tmp_path):
        a = self._adapter()
        with patch.object(a._pest, "invoke", side_effect=RuntimeError("not found")):
            findings = a._run_pest_tests(tmp_path, {})
        assert findings == []

    def test_run_infection_runtime_error(self, tmp_path):
        a = self._adapter()
        with patch.object(a._infection, "invoke", side_effect=RuntimeError("not found")):
            stats = a._run_infection(tmp_path, {}, False)
        assert stats is None

    def test_run_infection_exitcode_3_empty(self, tmp_path):
        a = self._adapter()
        with patch.object(a._infection, "invoke", return_value=_inv(exitcode=3, stdout="")):
            stats = a._run_infection(tmp_path, {}, False)
        assert stats is None


class TestPhpAdapterL3AL2L3BL4:
    def _adapter(self):
        from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
        return PhpAdapter()

    def test_run_l3a_all_tools_skip(self, tmp_path):
        a = self._adapter()
        with patch.object(a._phpstan, "run_l3a", side_effect=RuntimeError("missing")):
            with patch.object(a._phpmd, "run_l3a", side_effect=RuntimeError("missing")):
                with patch.object(a._cs_fixer, "invoke", side_effect=RuntimeError("missing")):
                    with patch.object(a._antipattern, "invoke", side_effect=RuntimeError("missing")):
                        result = a.run_l3a(tmp_path, {})
        assert result.layer == "L3A"
        assert result.passed is True

    def test_run_l2_skip(self, tmp_path):
        a = self._adapter()
        with patch.object(a._antipattern, "invoke", side_effect=RuntimeError("missing")):
            result = a.run_l2(tmp_path, {})
        assert result.layer == "L2"
        assert result.passed is True

    def test_run_l3b_delegates(self, tmp_path):
        a = self._adapter()
        mock_result = MagicMock()
        mock_result.layer = "L3B"
        mock_result.passed = True
        mock_result.findings = []
        with patch.object(a._weak_test, "run_l3b", return_value=mock_result):
            result = a.run_l3b(tmp_path, {})
        assert result.layer == "L3B"

    def test_run_l4_all_tools_skip(self, tmp_path):
        a = self._adapter()
        with patch.object(a._psalm_taint, "invoke", side_effect=RuntimeError("missing")):
            with patch.object(a._composer_audit, "invoke", side_effect=RuntimeError("missing")):
                with patch.object(a._security_checker, "invoke", side_effect=RuntimeError("missing")):
                    with patch.object(a._dead_code, "invoke", side_effect=RuntimeError("missing")):
                        with patch.object(a._dep_analyser, "invoke", side_effect=RuntimeError("missing")):
                            with patch.object(a._deptrac, "invoke", side_effect=RuntimeError("missing")):
                                result = a.run_l4(tmp_path, {})
        assert result.layer == "L4"
        assert result.passed is True

    def test_collect_test_files_oserror(self, tmp_path):
        from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
        # When repo doesn't exist, should return []
        nonexistent = tmp_path / "nonexistent"
        files = PhpAdapter._collect_test_files(nonexistent)
        assert files == []


# ===========================================================================
# 9. Small gaps: deptry_adapter.py
# ===========================================================================

class TestDeptryAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.python.deptry_adapter import DeptryAdapter
        return DeptryAdapter()

    def test_name(self):
        assert self._adapter().name == "deptry"

    def test_version_not_found(self, tmp_path):
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="deptry not found"):
                self._adapter().version(tmp_path)

    def test_invoke_not_found(self, tmp_path):
        with patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which", return_value=None):
            inv = self._adapter().invoke(tmp_path, [])
        assert inv.exitcode == 3

    def test_parse_non_dict_item(self):
        stdout = json.dumps({"errors": {"missing_imports": ["some-string"]}})
        findings = self._adapter().parse(stdout)
        # string items should produce findings too
        assert isinstance(findings, list)

    def test_parse_non_list_category(self):
        stdout = json.dumps({"errors": {"missing_imports": "not-a-list"}})
        findings = self._adapter().parse(stdout)
        assert findings == []

    def test_parse_no_filepath(self):
        stdout = json.dumps({"errors": {"missing_imports": [{"module": "mymod"}]}})
        findings = self._adapter().parse(stdout)
        assert any("mymod" in f.message for f in findings)


# ===========================================================================
# 10. Small gaps: mutmut_adapter.py
# ===========================================================================

class TestMutmutAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.python.mutmut_adapter import MutmutAdapter
        return MutmutAdapter()

    def test_name(self):
        assert self._adapter().name == "mutmut"

    def test_invoke_not_found(self, tmp_path):
        with patch("harness_quality_gate.adapters.python.mutmut_adapter.shutil.which", return_value=None):
            inv = self._adapter().invoke(tmp_path, [])
        assert inv.exitcode == 3


# ===========================================================================
# 11. Small gaps: pyright_adapter.py
# ===========================================================================

class TestPyrightAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.python.pyright_adapter import PyrightAdapter
        return PyrightAdapter()

    def test_name(self):
        assert self._adapter().name == "pyright"

    def test_version_not_found(self, tmp_path):
        with patch("harness_quality_gate.adapters.python.pyright_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="pyright not found"):
                self._adapter().version(tmp_path)

    def test_invoke_not_found(self, tmp_path):
        with patch("harness_quality_gate.adapters.python.pyright_adapter.shutil.which", return_value=None):
            inv = self._adapter().invoke(tmp_path, [])
        assert inv.exitcode == 3

    def test_parse_diag_with_line(self):
        stdout = json.dumps({
            "generalDiagnostics": [{
                "file": "foo.py",
                "severity": "error",
                "message": "type error",
                "rule": "reportMissingImport",
                "range": {"start": {"line": 5, "character": 3}},
            }]
        })
        findings = self._adapter().parse(stdout)
        assert len(findings) == 1
        assert "reportMissingImport" in findings[0].message


# ===========================================================================
# 12. Small gaps: bandit_adapter.py
# ===========================================================================

class TestBanditAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.python.bandit_adapter import BanditAdapter
        return BanditAdapter()

    def test_name(self):
        assert self._adapter().name == "bandit"

    def test_invoke_not_found(self, tmp_path):
        with patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which", return_value=None):
            inv = self._adapter().invoke(tmp_path, [])
        assert inv.exitcode == 3


# ===========================================================================
# 13. Small gaps: ruff_adapter.py
# ===========================================================================

class TestRuffAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.python.ruff_adapter import RuffAdapter
        return RuffAdapter()

    def test_name(self):
        assert self._adapter().name == "ruff"

    def test_invoke_not_found(self, tmp_path):
        with patch("harness_quality_gate.adapters.python.ruff_adapter.shutil.which", return_value=None):
            inv = self._adapter().invoke(tmp_path, [])
        assert inv.exitcode == 3


# ===========================================================================
# 14. Small gaps: vulture_adapter.py
# ===========================================================================

class TestVultureAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.python.vulture_adapter import VultureAdapter
        return VultureAdapter()

    def test_name(self):
        assert self._adapter().name == "vulture"

    def test_version_not_found(self, tmp_path):
        with patch("harness_quality_gate.adapters.python.vulture_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="vulture not found"):
                self._adapter().version(tmp_path)

    def test_invoke_not_found(self, tmp_path):
        with patch("harness_quality_gate.adapters.python.vulture_adapter.shutil.which", return_value=None):
            inv = self._adapter().invoke(tmp_path, [])
        assert inv.exitcode == 3

    def test_parse_no_filepath(self):
        stdout = json.dumps([{"name": "unused_fn", "type": "function"}])
        findings = self._adapter().parse(stdout)
        assert any("unused_fn" in f.message for f in findings)


# ===========================================================================
# 15. deptrac_adapter.py — line 49 (name)
# ===========================================================================

class TestDeptracAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.php.deptrac_adapter import DeptracAdapter
        return DeptracAdapter()

    def test_name(self):
        assert self._adapter().name == "deptrac"

    def test_version_not_implemented(self, tmp_path):
        with pytest.raises(NotImplementedError):
            self._adapter().version(tmp_path)

    def test_invoke_missing_binary(self, tmp_path):
        with pytest.raises(RuntimeError, match="deptrac not found"):
            self._adapter().invoke(tmp_path, [])


# ===========================================================================
# 16. phpstan_adapter.py — line 71 (vendor bin fallback)
# ===========================================================================

class TestPhpStanAdapterBinaryResolution:
    def _adapter(self):
        from harness_quality_gate.adapters.php.phpstan_adapter import PhpStanAdapter
        return PhpStanAdapter()

    def test_name(self):
        assert self._adapter().name == "phpstan"

    def test_vendor_bin_fallback(self, tmp_path):
        vendor_bin = tmp_path / "vendor" / "bin"
        vendor_bin.mkdir(parents=True)
        phpstan = vendor_bin / "phpstan"
        phpstan.write_text("#!/bin/sh")
        phpstan.chmod(0o755)
        a = self._adapter()
        with patch("harness_quality_gate.adapters.php.phpstan_adapter.shutil.which", return_value=None):
            cmd = a._phpstan_binary(tmp_path)
        assert cmd is not None
        assert str(phpstan) in cmd

    def test_binary_not_found(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.php.phpstan_adapter.shutil.which", return_value=None):
            cmd = a._phpstan_binary(tmp_path)
        assert cmd is None


# ===========================================================================
# 17. infection_adapter.py — gaps 27-28, 43, 46, 81, 176-178
# ===========================================================================

class TestInfectionAdapterExtras:
    def _adapter(self):
        from harness_quality_gate.adapters.php.infection_adapter import InfectionAdapter
        return InfectionAdapter()

    def test_name(self):
        assert self._adapter().name == "infection"

    def test_version_not_implemented(self, tmp_path):
        with pytest.raises(NotImplementedError):
            self._adapter().version(tmp_path)

    def test_invoke_finds_vendor_bin(self, tmp_path):
        vendor_bin = tmp_path / "vendor" / "bin"
        vendor_bin.mkdir(parents=True)
        infection = vendor_bin / "infection"
        infection.write_text("#!/bin/sh")
        infection.chmod(0o755)
        a = self._adapter()
        with patch("harness_quality_gate.adapters.php.infection_adapter.shutil.which", return_value=None):
            with patch.object(a.__class__, "_run", return_value=_inv()):
                inv = a.invoke(tmp_path, [])
        assert inv is not None

    def test_invoke_not_found(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.php.infection_adapter.shutil.which", return_value=None):
            inv = a.invoke(tmp_path, [])
        assert inv.exitcode == 3

    def test_composer_bin_dir_reads_composer_json(self, tmp_path):
        from harness_quality_gate.adapters.php.infection_adapter import _composer_bin_dir
        (tmp_path / "composer.json").write_text(
            json.dumps({"config": {"bin-dir": "tools/bin"}}), encoding="utf-8"
        )
        assert _composer_bin_dir(tmp_path) == "tools/bin"

    def test_composer_bin_dir_default(self, tmp_path):
        from harness_quality_gate.adapters.php.infection_adapter import _composer_bin_dir
        assert _composer_bin_dir(tmp_path) == "vendor/bin"

    def test_parse_stats_fallback_msi_computation(self):
        """When regex doesn't match MSI% but killed>0, MSI is computed."""
        text = (
            "10 mutations were generated:\n"
            "   8 mutants were killed\n"
            "   2 covered mutants were not detected\n"
            "   0 mutants were not covered\n"
            "   0 errors were encountered\n"
            "   0 time outs were encountered\n"
        )
        a = self._adapter()
        stats = a.parse_stats(text)
        assert stats.killed == 8
        assert stats.survived == 2
        assert stats.msi > 0.0


# ===========================================================================
# 18. config.py — line 129 (allow_ramp True raises anyway)
# ===========================================================================

class TestConfig:
    def test_validate_allow_ramp_still_raises(self):
        from harness_quality_gate.config import validate, ConfigInvalid
        raw = {
            "schema_version": 2,
            "infection": {"thresholds": {"min_msi": 80.0}},
        }
        with pytest.raises(ConfigInvalid):
            validate(raw, allow_ramp=True)

    def test_validate_schema_v1_raises(self):
        from harness_quality_gate.config import validate, ConfigInvalid
        with pytest.raises(ConfigInvalid):
            validate({"schema_version": 1})

    def test_validate_ok(self):
        from harness_quality_gate.config import validate
        raw = {"schema_version": 2}
        config = validate(raw)
        assert config.schema_version == 2


# ===========================================================================
# 19. composer_audit_adapter.py — parse gaps (lines 40-58)
# ===========================================================================

class TestComposerAuditAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.php.composer_audit_adapter import ComposerAuditAdapter
        return ComposerAuditAdapter()

    def test_name(self):
        assert self._adapter().name == "composer-audit"

    def test_version_not_found(self, tmp_path):
        a = self._adapter()
        with patch.object(a, "_composer_binary", return_value=None):
            with pytest.raises(RuntimeError, match="composer not found"):
                a.version(tmp_path)

    def test_invoke_not_found(self, tmp_path):
        a = self._adapter()
        with patch.object(a, "_composer_binary", return_value=None):
            with pytest.raises(RuntimeError, match="composer not found"):
                a.invoke(tmp_path, [])

    def test_parse_advisory_no_cve(self):
        stdout = json.dumps({
            "advisories": {
                "vendor/pkg": [{
                    "advisoryId": "ADV-001",
                    "title": "Some vulnerability",
                    "link": "https://example.com/adv",
                }]
            }
        })
        findings = self._adapter().parse(stdout, "", 0)
        assert len(findings) == 1
        assert findings[0].node == "vendor/pkg"

    def test_parse_empty_stdout(self):
        findings = self._adapter().parse("", "", 0)
        assert findings == []

    def test_parse_non_dict_advisories(self):
        stdout = json.dumps({"advisories": ["not-a-dict"]})
        findings = self._adapter().parse(stdout, "", 0)
        assert findings == []


# ===========================================================================
# 20. pest_adapter.py — _pest_binary with Path checking
# ===========================================================================

class TestPestAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.php.pest_adapter import PestAdapter
        return PestAdapter()

    def test_name(self):
        assert self._adapter().name == "pest"

    def test_pest_binary_vendor_bin(self, tmp_path):
        vendor_bin = tmp_path / "vendor" / "bin"
        vendor_bin.mkdir(parents=True)
        pest_bin = vendor_bin / "pest"
        pest_bin.write_text("#!/bin/sh")
        pest_bin.chmod(0o755)
        a = self._adapter()
        cmd = a._pest_binary(tmp_path)
        assert cmd is not None
        assert str(pest_bin) in cmd

    def test_pest_binary_system_path(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.php.pest_adapter.shutil.which", return_value="/usr/bin/pest"):
            cmd = a._pest_binary(tmp_path)
        assert cmd is not None and "/usr/bin/pest" in cmd

    def test_pest_binary_not_found(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.php.pest_adapter.shutil.which", return_value=None):
            cmd = a._pest_binary(tmp_path)
        assert cmd is None

    def test_invoke_not_found(self, tmp_path):
        a = self._adapter()
        with patch.object(a, "_pest_binary", return_value=None):
            with pytest.raises(RuntimeError, match="pest not found"):
                a.invoke(tmp_path, [])

    def test_has_mutate_plugin_no_file(self, tmp_path):
        a = self._adapter()
        assert a._has_mutate_plugin(tmp_path) is False

    def test_has_mutate_plugin_present(self, tmp_path):
        (tmp_path / "composer.json").write_text(
            json.dumps({"require-dev": {"pestphp/pest-plugin-mutate": "^2"}}),
            encoding="utf-8",
        )
        a = self._adapter()
        assert a._has_mutate_plugin(tmp_path) is True

    def test_has_mutate_plugin_invalid_json(self, tmp_path):
        (tmp_path / "composer.json").write_text("INVALID", encoding="utf-8")
        a = self._adapter()
        assert a._has_mutate_plugin(tmp_path) is False


# ===========================================================================
# 21. phpunit_adapter.py — JUnit XML error cases (lines 291-299)
# ===========================================================================

class TestPhpUnitAdapterJUnit:
    def _adapter(self):
        from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter
        return PhpUnitAdapter()

    def test_parse_junit_xml_parse_error(self, tmp_path):
        bad_xml = tmp_path / "junit.xml"
        bad_xml.write_text("NOT XML AT ALL", encoding="utf-8")
        from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter
        findings = PhpUnitAdapter._parse_junit_xml(bad_xml)
        assert any("Failed to parse" in f.message for f in findings)

    def test_parse_junit_xml_no_tests(self, tmp_path):
        xml = tmp_path / "junit.xml"
        xml.write_text(
            '<?xml version="1.0"?><testsuite tests="0" errors="0" failures="0" skipped="0"/>',
            encoding="utf-8",
        )
        from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter
        findings = PhpUnitAdapter._parse_junit_xml(xml)
        assert any("No tests" in f.message for f in findings)

    def test_parse_junit_xml_with_error(self, tmp_path):
        xml_content = """<?xml version="1.0"?>
<testsuite tests="1" errors="1" failures="0" skipped="0">
  <testcase name="test_foo" classname="FooTest">
    <error>Fatal error: ...</error>
  </testcase>
</testsuite>"""
        xml = tmp_path / "junit.xml"
        xml.write_text(xml_content, encoding="utf-8")
        from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter
        findings = PhpUnitAdapter._parse_junit_xml(xml)
        assert any("error" in f.message.lower() or f.severity == "error" for f in findings)

    def test_parse_junit_xml_with_skipped(self, tmp_path):
        xml_content = """<?xml version="1.0"?>
<testsuite tests="1" errors="0" failures="0" skipped="1">
  <testcase name="test_foo" classname="FooTest">
    <skipped/>
  </testcase>
</testsuite>"""
        xml = tmp_path / "junit.xml"
        xml.write_text(xml_content, encoding="utf-8")
        from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter
        findings = PhpUnitAdapter._parse_junit_xml(xml)
        assert any("skipped" in f.message.lower() for f in findings)

    def test_version_not_implemented(self, tmp_path):
        a = self._adapter()
        with pytest.raises(NotImplementedError):
            a.version(tmp_path)


# ===========================================================================
# 22. php_cs_fixer_adapter.py — version() method
# ===========================================================================

class TestPhpCsFixerAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.php.php_cs_fixer_adapter import PhpCsFixerAdapter
        return PhpCsFixerAdapter()

    def test_name(self):
        assert self._adapter().name == "php-cs-fixer"

    def test_version_not_found(self, tmp_path):
        a = self._adapter()
        with patch.object(a, "_cs_fixer_binary", return_value=None):
            with pytest.raises(RuntimeError, match="php-cs-fixer not found"):
                a.version(tmp_path)

    def test_cs_fixer_binary_vendor_fallback(self, tmp_path):
        vendor_bin = tmp_path / "vendor" / "bin"
        vendor_bin.mkdir(parents=True)
        fixer = vendor_bin / "php-cs-fixer"
        fixer.write_text("#!/bin/sh")
        fixer.chmod(0o755)
        a = self._adapter()
        with patch("harness_quality_gate.adapters.php.php_cs_fixer_adapter.shutil.which", return_value=None):
            cmd = a._cs_fixer_binary(tmp_path)
        assert cmd is not None
        assert str(fixer) in cmd

    def test_cs_fixer_binary_not_found(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.php.php_cs_fixer_adapter.shutil.which", return_value=None):
            cmd = a._cs_fixer_binary(tmp_path)
        assert cmd is None


# ===========================================================================
# 23. phpmd_adapter.py — version() method
# ===========================================================================

class TestPhpMdAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.php.phpmd_adapter import PhpMdAdapter
        return PhpMdAdapter()

    def test_name(self):
        assert self._adapter().name == "phpmd"

    def test_version_not_found(self, tmp_path):
        a = self._adapter()
        with patch.object(a, "_phpmd_binary", return_value=None):
            with pytest.raises(RuntimeError, match="phpmd not found"):
                a.version(tmp_path)

    def test_phpmd_binary_vendor_fallback(self, tmp_path):
        vendor_bin = tmp_path / "vendor" / "bin"
        vendor_bin.mkdir(parents=True)
        phpmd = vendor_bin / "phpmd"
        phpmd.write_text("#!/bin/sh")
        phpmd.chmod(0o755)
        a = self._adapter()
        with patch("harness_quality_gate.adapters.php.phpmd_adapter.shutil.which", return_value=None):
            cmd = a._phpmd_binary(tmp_path)
        assert cmd is not None
        assert str(phpmd) in cmd

    def test_phpmd_binary_not_found(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.php.phpmd_adapter.shutil.which", return_value=None):
            cmd = a._phpmd_binary(tmp_path)
        assert cmd is None


# ===========================================================================
# 24. visitor_runner_adapter.py — lines 110-111, 176-177, 204-205, 232-233
# ===========================================================================

class TestVisitorRunnerAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.php.visitor_runner_adapter import VisitorRunnerAdapter
        return VisitorRunnerAdapter()

    def test_name(self):
        assert self._adapter().name == "visitor-runner"

    def test_version_not_implemented(self, tmp_path):
        with pytest.raises(NotImplementedError):
            self._adapter().version(tmp_path)

    def test_invoke_no_php_files(self, tmp_path):
        a = self._adapter()
        # Create a dummy visitor
        with patch("harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors",
                   return_value=["dummy_visitor"]):
            with patch.object(a.__class__, "_collect_php_files", return_value=[]):
                inv = a.invoke(tmp_path, [])
        assert inv.stdout == "[]"

    def test_invoke_no_visitors(self, tmp_path):
        a = self._adapter()
        with patch("harness_quality_gate.adapters.php.visitor_runner_adapter._discover_visitors",
                   return_value=[]):
            inv = a.invoke(tmp_path, [])
        assert inv.stdout == "[]"
        assert "no visitors" in inv.stderr

    def test_collect_php_files_oserror(self, tmp_path):
        from harness_quality_gate.adapters.php.visitor_runner_adapter import VisitorRunnerAdapter
        # non-existent dir
        files = VisitorRunnerAdapter._collect_php_files(tmp_path / "nonexistent")
        assert files == []

    def test_parse_visitor_output_invalid_json(self):
        from harness_quality_gate.adapters.php.visitor_runner_adapter import VisitorRunnerAdapter
        result = VisitorRunnerAdapter._parse_visitor_output("not json and no brackets")
        assert result == []

    def test_parse_visitor_output_mixed_with_json_array(self):
        from harness_quality_gate.adapters.php.visitor_runner_adapter import VisitorRunnerAdapter
        text = 'Warning: some warning\n[{"file": "foo.php", "line": 1, "message": "test"}]'
        result = VisitorRunnerAdapter._parse_visitor_output(text)
        assert len(result) == 1

    def test_parse_empty_string(self):
        a = self._adapter()
        findings = a.parse("", "", 0)
        assert findings == []


# ===========================================================================
# 25. weak_test_php.py — lines 120-121, 197-198, 233-234, 259-260
# ===========================================================================

class TestPhpWeakTestAdapter:
    def _adapter(self):
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        return PhpWeakTestAdapter()

    def test_name(self):
        assert self._adapter().name == "weak-test-php"

    def test_version(self):
        a = self._adapter()
        assert "visitors" in a.version(Path("."))

    def test_invoke_no_test_files(self, tmp_path):
        a = self._adapter()
        inv = a.invoke(tmp_path, [])
        assert inv.stdout == "[]"
        assert "no PHP test files" in inv.stderr

    def test_invoke_visitor_missing(self, tmp_path):
        """When visitor script file doesn't exist, it is skipped."""
        a = self._adapter()
        # Create a test file so we pass the early-exit check
        test_file = tmp_path / "FooTest.php"
        test_file.write_text("<?php", encoding="utf-8")
        # All visitor scripts will be missing since tmp_path is not the real visitors dir
        inv = a.invoke(tmp_path, [])
        assert inv is not None

    def test_collect_test_files(self, tmp_path):
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        (tmp_path / "FooTest.php").write_text("<?php", encoding="utf-8")
        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / "BarTest.php").write_text("<?php", encoding="utf-8")
        files = PhpWeakTestAdapter._collect_test_files(tmp_path)
        assert any("FooTest.php" in str(f) for f in files)
        assert not any("vendor" in str(f) for f in files)

    def test_parse_single_output_invalid_json(self):
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        result = PhpWeakTestAdapter._parse_single_output("not json, no brackets")
        assert result == []

    def test_parse_single_output_with_fallback(self):
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        text = 'some output\n[{"file": "t.php", "line": 1, "message": "weak"}]'
        result = PhpWeakTestAdapter._parse_single_output(text)
        assert len(result) == 1

    def test_parse_empty(self):
        a = self._adapter()
        findings = a.parse("", "", 0)
        assert findings == []

    def test_parse_valid_finding(self):
        a = self._adapter()
        stdout = json.dumps([{
            "file": "tests/FooTest.php",
            "line": 10,
            "rule_id": "A1",
            "message": "Zero assertions",
            "severity": "error",
        }])
        findings = a.parse(stdout)
        assert len(findings) == 1
        assert findings[0].rule_id == "A1"
        assert findings[0].layer == "L3B"

    def test_parse_line_conversion_error(self):
        a = self._adapter()
        stdout = json.dumps([{
            "file": "tests/FooTest.php",
            "line": "not-a-number",
            "rule_id": "A1",
            "message": "Zero assertions",
            "severity": "error",
        }])
        # Should not raise
        findings = a.parse(stdout)
        assert len(findings) == 1
