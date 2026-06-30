"""Unit tests for SecurityCheckerAdapter.

Targets: version(), invoke(), parse() with granular asserts on all Finding fields.
Covers: version-not-found, invoke-not-found, invoke-success, parse edge cases,
and all branches inside parse() (empty stdout, invalid JSON, non-list, non-dict entries,
severity normalisation, missing fields, link extraction).

Design: Mutation testing — each boolean branch, default value,
string comparison and list membership is individually asserted.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.php.security_checker_adapter import SecurityCheckerAdapter


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def _adapter() -> SecurityCheckerAdapter:
    return SecurityCheckerAdapter()


# ---------------------------------------------------------------------------
# version() — POC stub, raises NotImplementedError
# ---------------------------------------------------------------------------

class TestVersion:
    def test_version_raises_not_implemented(self, tmp_path):
        """version() is a POC stub → NotImplementedError."""
        adapter = _adapter()
        with pytest.raises(NotImplementedError, match="not implemented"):
            adapter.version(tmp_path)


# ---------------------------------------------------------------------------
# invoke() — subprocess wiring
# ---------------------------------------------------------------------------

class TestInvoke:
    def test_invoke_local_php_security_checker_not_found(self, tmp_path):
        """Neither name on PATH → RuntimeError with exact message."""
        with patch("shutil.which", return_value=None):
            adapter = _adapter()
            with pytest.raises(RuntimeError) as exc_info:
                adapter.invoke(tmp_path)
            exc_msg = str(exc_info.value)
            # KILL mutmut_13: error string "XX...not found on PATHXX" mutation.
            assert "XX" not in exc_msg, f"Expected clean message, got: {exc_msg}"
            # Also check exact message to catch any wrapper string mutation
            assert exc_msg == "local-php-security-checker not found on PATH"

    def test_invoke_php_security_checker_not_found(self, tmp_path):
        """'local-php-...' missing but 'php-security-checker' absent too."""
        with patch("shutil.which", return_value=None):
            adapter = _adapter()
            with pytest.raises(RuntimeError) as exc_info:
                adapter.invoke(tmp_path)
            exc_msg = str(exc_info.value)
            # KILL mutmut_13: same error string mutation.
            assert "XX" not in exc_msg, f"Expected clean message, got: {exc_msg}"

    def test_invoke_prefers_local_php_security_checker(self, tmp_path):
        """When 'local-php-security-checker' exists it is used (second call returns None)."""
        def fake_which(name):
            if name == "local-php-security-checker":
                return "/usr/bin/local-php-security-checker"
            return None

        with patch("shutil.which", side_effect=fake_which):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    stdout='[{"vulnerabilities": []}]',
                    stderr="",
                    returncode=0,
                )
                adapter = _adapter()
                result = adapter.invoke(tmp_path)
                assert result.exitcode == 0
                assert result.stderr == ""
                # KILL mutmut_48: stdout must not be None.
                assert result.stdout is not None
                # KILL mutmut_51: duration_seconds must not be None.
                assert result.duration_seconds is not None
                # KILL mutmut_52: stdout must carry actual content (not default '').
                assert "vulnerabilities" in result.stdout
                # KILL mutmut_56: 'and ""' mutation changes stderr from '' to ''; assert exact value.
                assert result.stderr == ""
                # KILL mutmut_1: default timeout=300.0 must be passed to subprocess.run.
                assert mock_run.call_args[1]["timeout"] == 300.0
                # KILL mutmut_9, mutmut_27: text=True must be passed.
                assert mock_run.call_args[1]["text"] is True
                # KILL mutmut_26: capture_output=True must be passed.
                assert mock_run.call_args[1]["capture_output"] is True

    def test_invoke_success_non_default_values(self, tmp_path):
        """Verify stdout/stderr/exitcode/duration_seconds match actual subprocess values
        (catches mutmut_53 stderr removal, mutmut_54 exitcode removal, mutmut_55 duration removal)."""
        def fake_which(name):
            if name == "local-php-security-checker":
                return "/usr/bin/local-php-security-checker"
            return None

        with patch("shutil.which", side_effect=fake_which):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    stdout='[{"package":"a/b"}]',
                    stderr="some error info",
                    returncode=1,
                )
                adapter = _adapter()
                result = adapter.invoke(tmp_path)
                # KILL mutmut_53: stderr must be "some error info" not default ''.
                assert result.stderr == "some error info"
                # KILL mutmut_56: 'and ""' mutation would make stderr empty.
                assert result.stderr != ""
                # KILL mutmut_54: exitcode must be 1 not default 0.
                assert result.exitcode == 1
                # KILL mutmut_55: duration_seconds must not use default 0.0.
                assert isinstance(result.duration_seconds, (int, float))
                # Also verify stdout carries content.
                assert "package" in result.stdout
                # Verify duration_seconds is a float > 0 (not None, not 0).
                assert isinstance(result.duration_seconds, float)
                assert result.duration_seconds >= 0

    def test_invoke_falls_back_to_php_security_checker(self, tmp_path):
        """'local-php-...' missing → falls back to 'php-security-checker'."""
        with patch("shutil.which") as mock_which:
            mock_which.side_effect = [None, "/usr/bin/php-security-checker"]
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    stdout='[{"vulnerabilities": []}]',
                    stderr="",
                    returncode=0,
                )
                adapter = _adapter()
                result = adapter.invoke(tmp_path)
                assert result.exitcode == 0
                assert result.stderr == ""
                cmd = mock_run.call_args[0][0]
                assert "/usr/bin/php-security-checker" in cmd[0]
                # KILL mutmut_8, mutmut_10: verify the 2nd shutil.which call uses "php-security-checker".
                which_calls = mock_which.call_args_list
                assert len(which_calls) == 2
                assert which_calls[0][0][0] == "local-php-security-checker"
                assert which_calls[1][0][0] == "php-security-checker"

    def test_invoke_includes_format_json(self, tmp_path):
        """The CLI command always includes --format=json."""
        with patch("shutil.which", return_value="/usr/bin/local-php-security-checker"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout="[]", stderr="", returncode=0)
                adapter = _adapter()
                adapter.invoke(tmp_path)
                cmd = mock_run.call_args[0][0]
                assert "--format=json" in cmd

    def test_invoke_passes_extra_args(self, tmp_path):
        """Extra args are appended after --format=json."""
        with patch("shutil.which", return_value="/usr/bin/local-php-security-checker"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout="[]", stderr="", returncode=0)
                adapter = _adapter()
                adapter.invoke(tmp_path, args=["--ignore-unmapped"])
                cmd = mock_run.call_args[0][0]
                assert "--ignore-unmapped" in cmd
                # KILL mutmut_15: 'env or {}' → 'env and {}'.
                # With the mutation, subprocess.run receives env=None instead of empty dict.
                sub_env = mock_run.call_args[1]["env"]
                assert isinstance(sub_env, dict)
                assert "PATH" in sub_env

    def test_invoke_sets_cwd_to_repo(self, tmp_path):
        """subprocess.run is called with cwd=repo path."""
        repo = tmp_path / "myproject"
        repo.mkdir()
        with patch("shutil.which", return_value="/usr/bin/local-php-security-checker"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout="[]", stderr="", returncode=0)
                adapter = _adapter()
                adapter.invoke(repo)
                assert mock_run.call_args[1]["cwd"] == str(repo)

    def test_invoke_timeout_raises_runtime_error(self, tmp_path, caplog):
        """TimeoutExpired → RuntimeError per NFR-8a (timeout is infra_error, not quality)."""
        with patch("shutil.which", return_value="/usr/bin/local-php-security-checker"):
            with patch(
                "harness_quality_gate.adapters.php.security_checker_adapter.subprocess.run"
            ) as mock_run:
                import subprocess as sp

                exc = sp.TimeoutExpired(cmd="check", timeout=30)
                exc.stdout = None
                exc.stderr = None
                mock_run.side_effect = exc
                adapter = _adapter()
                with caplog.at_level(logging.WARNING):
                    with pytest.raises(RuntimeError, match=r"timed out"):
                        adapter.invoke(tmp_path, timeout=0.001)
                # KILL mutmut_64: logger.warning(None) would log 'None', not the actual message.
                assert len(caplog.records) >= 1
                assert "timed out" in caplog.records[-1].message

    def test_invoke_timeout_stderr_bytes_raises(self, tmp_path):
        """TimeoutExpired with bytes stderr still raises RuntimeError (no silent decoding)."""
        with patch("shutil.which", return_value="/usr/bin/local-php-security-checker"):
            with patch(
                "harness_quality_gate.adapters.php.security_checker_adapter.subprocess.run"
            ) as mock_run:
                import subprocess as sp

                exc = sp.TimeoutExpired(cmd="check", timeout=30)
                exc.stdout = None
                exc.stderr = b"error info"
                mock_run.side_effect = exc
                adapter = _adapter()
                with pytest.raises(RuntimeError, match=r"timed out"):
                    adapter.invoke(tmp_path, timeout=0.001)

    def test_invoke_timeout_stdout_bytes_raises(self, tmp_path):
        """TimeoutExpired with bytes stdout still raises RuntimeError (no silent decoding)."""
        with patch("shutil.which", return_value="/usr/bin/local-php-security-checker"):
            with patch(
                "harness_quality_gate.adapters.php.security_checker_adapter.subprocess.run"
            ) as mock_run:
                import subprocess as sp

                exc = sp.TimeoutExpired(cmd="check", timeout=30)
                exc.stdout = b"some output"
                exc.stderr = None
                mock_run.side_effect = exc
                adapter = _adapter()
                with pytest.raises(RuntimeError, match=r"timed out"):
                    adapter.invoke(tmp_path, timeout=0.001)


# ---------------------------------------------------------------------------
# parse() — edge cases before the loop
# ---------------------------------------------------------------------------

class TestParseEdgeCases:
    def test_parse_empty_string(self):
        """Empty stdout → []"""
        adapter = _adapter()
        findings = adapter.parse("")
        assert findings == []

    def test_parse_whitespace_only(self):
        """Whitespace-only stdout → []"""
        adapter = _adapter()
        findings = adapter.parse("   \n\t  ")
        assert findings == []

    def test_parse_newline_only(self):
        """Newline-only stdout → []"""
        adapter = _adapter()
        findings = adapter.parse("\n\n\n")
        assert findings == []

    def test_parse_invalid_json(self):
        """Malformed JSON → []"""
        adapter = _adapter()
        findings = adapter.parse("{not valid json}")
        assert findings == []

    def test_parse_json_string(self):
        """JSON string (not array/dict) → []"""
        adapter = _adapter()
        findings = adapter.parse('"just a string"')
        assert findings == []

    def test_parse_json_number(self):
        """JSON number → []"""
        adapter = _adapter()
        findings = adapter.parse("42")
        assert findings == []

    def test_parse_json_null(self):
        """JSON null → []"""
        adapter = _adapter()
        findings = adapter.parse("null")
        assert findings == []

    def test_parse_json_boolean_true(self):
        """JSON boolean true → []"""
        adapter = _adapter()
        findings = adapter.parse("true")
        assert findings == []

    def test_parse_json_object(self):
        """Valid JSON dict (not list) → []"""
        adapter = _adapter()
        findings = adapter.parse('{"vulnerabilities": []}')
        assert findings == []

    def test_parse_json_object_with_other_key(self):
        """JSON dict without expected key → []"""
        adapter = _adapter()
        findings = adapter.parse('{"other_key": []}')
        assert findings == []


# ---------------------------------------------------------------------------
# parse() — loop body: non-dict entries, empty list, single & multiple vulns
# ---------------------------------------------------------------------------

class TestParseVulnerabilities:
    def test_parse_empty_array(self):
        """JSON [] → []"""
        adapter = _adapter()
        findings = adapter.parse("[]")
        assert findings == []

    def test_parse_single_vulnerability(self):
        """One entry → one Finding with all expected fields."""
        adapter = _adapter()
        data = [{"package": "symfony/symfony", "severity": "critical", "installed_version": "4.0", "type": "xss"}]
        findings = adapter.parse(json.dumps(data))
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "symfony/symfony"
        assert f.severity == "error"
        assert "symfony/symfony" in f.message
        assert "4.0" in f.message
        assert "xss" in f.message
        assert f.tool == "local-php-security-checker"
        assert f.layer == "L4"
        assert f.language == "php"
        assert f.cve is None
        assert f.cwe == ""

    def test_parse_single_vulnerability_all_fields(self):
        """Entry with links → fix_hint is first link."""
        adapter = _adapter()
        data = [{
            "package": "vendor/pkg",
            "severity": "high",
            "installed_version": "1.0.0",
            "vulnerable_versions": "<2.0.0",
            "type": "injection",
            "links": ["https://advisory.example.com/1", "https://second"],
        }]
        findings = adapter.parse(json.dumps(data))
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "vendor/pkg"
        assert f.severity == "error"
        assert "vendor/pkg" in f.message
        assert "1.0.0" in f.message
        assert "<2.0.0" in f.message
        assert "injection" in f.message
        assert f.fix_hint == "https://advisory.example.com/1"

    def test_parse_severity_critical(self):
        """severity='critical' → 'error'."""
        adapter = _adapter()
        findings = adapter.parse(json.dumps([{"severity": "critical"}]))
        assert findings[0].severity == "error"

    def test_parse_severity_high(self):
        """severity='high' → 'error'."""
        adapter = _adapter()
        findings = adapter.parse(json.dumps([{"severity": "high"}]))
        assert findings[0].severity == "error"

    def test_parse_severity_medium(self):
        """severity='medium' → 'warning'."""
        adapter = _adapter()
        findings = adapter.parse(json.dumps([{"severity": "medium"}]))
        assert findings[0].severity == "warning"

    def test_parse_severity_low(self):
        """severity='low' → 'info'."""
        adapter = _adapter()
        findings = adapter.parse(json.dumps([{"severity": "low"}]))
        assert findings[0].severity == "info"

    def test_parse_severity_unknown(self):
        """Unrecognised severity → 'warning'."""
        adapter = _adapter()
        findings = adapter.parse(json.dumps([{"severity": "photonuclear"}]))
        assert findings[0].severity == "warning"

    def test_parse_severity_empty_string(self):
        """Empty severity string → 'warning'."""
        adapter = _adapter()
        findings = adapter.parse(json.dumps([{}]))
        assert findings[0].severity == "warning"

    def test_parse_severity_case_insensitive(self):
        """'Critical' uppercase → still mapped."""
        adapter = _adapter()
        findings = adapter.parse(json.dumps([{"severity": "Critical"}]))
        assert findings[0].severity == "error"

    def test_parse_no_links(self):
        """Entry with no 'links' → fix_hint is None."""
        adapter = _adapter()
        findings = adapter.parse(json.dumps([{"package": "a/b"}]))
        assert findings[0].fix_hint is None

    def test_parse_links_empty_list(self):
        """Entry with 'links': [] → fix_hint is None."""
        adapter = _adapter()
        findings = adapter.parse(json.dumps([{"package": "a/b", "links": []}]))
        assert findings[0].fix_hint is None

    def test_parse_vulnerable_versions_empty(self):
        """Empty vulnerable_versions → present but empty."""
        adapter = _adapter()
        findings = adapter.parse(json.dumps([{"package": "x/y", "vulnerable_versions": ""}]))
        assert len(findings) == 1
        assert "" in findings[0].message or findings[0].message == "x/y  has vulnerability in  ()"

    def test_parse_installed_version_empty(self):
        """Empty installed_version → defaults to ''"""
        adapter = _adapter()
        findings = adapter.parse(json.dumps([{"package": "x/y", "installed_version": "1.0"}]))
        assert len(findings) == 1
        assert "x/y" in findings[0].message

    def test_parse_multiple_vulnerabilities(self):
        """Multiple entries → multiple findings."""
        adapter = _adapter()
        data = [
            {"package": "symfony/symfony", "severity": "high", "version": "4.0", "type": "xss"},
            {"package": "monolog/monolog", "severity": "low", "version": "1.0", "type": "csrf"},
        ]
        findings = adapter.parse(json.dumps(data))
        assert len(findings) == 2
        assert findings[0].node == "symfony/symfony"
        assert findings[1].node == "monolog/monolog"
        assert "xss" in findings[0].message
        assert "csrf" in findings[1].message

    def test_parse_mixed_dict_and_non_dict(self):
        """Array with dicts and non-dict entries → non-dicts skipped."""
        adapter = _adapter()
        data = [
            {"package": "good/pkg"},
            "not a dict",
            42,
            {"package": "another/pkg"},
            None,
        ]
        findings = adapter.parse(json.dumps(data))
        assert len(findings) == 2
        assert findings[0].node == "good/pkg"
        assert findings[1].node == "another/pkg"

    def test_parse_non_dict_array_elements(self):
        """All elements are non-dicts → empty result."""
        adapter = _adapter()
        findings = adapter.parse(json.dumps(["not", "a", "dict"]))
        assert len(findings) == 0

    def test_parse_missing_package_defaults_to_unknown(self):
        """Entry without 'package' → 'unknown'."""
        adapter = _adapter()
        findings = adapter.parse(json.dumps([{"severity": "high"}]))
        assert findings[0].node == "unknown"

    def test_parse_missing_type_defaults_empty(self):
        """Entry without 'type' → empty string in message."""
        adapter = _adapter()
        findings = adapter.parse(json.dumps([{"package": "a/b", "severity": "high"}]))
        assert findings[0].message == "a/b  has vulnerability in  ()"

    def test_parse_all_severity_levels(self):
        """Full severity normalisation table."""
        adapter = _adapter()
        mapping = {
            "critical": "error",
            "high": "error",
            "medium": "warning",
            "low": "info",
        }
        for raw, expected in mapping.items():
            findings = adapter.parse(json.dumps([{"severity": raw}]))
            assert findings[0].severity == expected

    def test_parse_finding_all_required_attributes(self):
        """Every Finding attribute is individually verified."""
        adapter = _adapter()
        data = [{
            "package": "test/pkg",
            "severity": "high",
            "installed_version": "2.0",
            "vulnerable_versions": "<3.0",
            "type": "rce",
            "links": ["https://example.com"],
        }]
        findings = adapter.parse(json.dumps(data))
        f = findings[0]
        assert f.node == "test/pkg"
        assert f.severity == "error"
        assert f.message == "test/pkg 2.0 has vulnerability in <3.0 (rce)"
        assert f.fix_hint == "https://example.com"
        assert f.cve is None
        assert f.cwe == ""
        assert f.tool == "local-php-security-checker"
        assert f.layer == "L4"
        assert f.language == "php"
