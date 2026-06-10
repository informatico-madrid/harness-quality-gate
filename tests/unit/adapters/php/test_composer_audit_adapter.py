"""Unit tests for ComposerAuditAdapter — targeted mutation killing.

Covers: version(), _composer_binary(), invoke(), parse().
Design: Dense assertions on ALL output fields, subprocess args, and edge cases.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.php.composer_audit_adapter import ComposerAuditAdapter
from harness_quality_gate.adapters.base import ToolAdapter, ToolInvocation
from harness_quality_gate.models import Finding


# ===========================================================================
# Helpers
# ===========================================================================


def _adapter() -> ComposerAuditAdapter:
    return ComposerAuditAdapter()


# ===========================================================================
# _composer_binary()
# ===========================================================================


class TestComposerBinary:
    """Tests for _composer_binary — kills subprocess binary resolution mutations."""

    def test_composer_binary_found(self) -> None:
        """Binary found on PATH → returns [path]."""
        with patch(
            "harness_quality_gate.adapters.php.composer_audit_adapter.shutil.which",
            return_value="/usr/bin/composer",
        ):
            result = _adapter()._composer_binary(Path("/repo"))
        assert result == ["/usr/bin/composer"]

    def test_composer_binary_not_found(self) -> None:
        """Composer not found → returns None."""
        with patch(
            "harness_quality_gate.adapters.php.composer_audit_adapter.shutil.which",
            return_value=None,
        ):
            result = _adapter()._composer_binary(Path("/repo"))
        assert result is None

    def test_composer_binary_returns_list_not_empty(self) -> None:
        """_composer_binary always returns either a list or None (not empty list)."""
        with patch(
            "harness_quality_gate.adapters.php.composer_audit_adapter.shutil.which",
            return_value="/usr/local/bin/composer",
        ):
            result = _adapter()._composer_binary(Path("/repo"))
        assert isinstance(result, list)
        assert len(result) >= 1
        # Kills mutation: return [path] → return [] (empty list)


# ===========================================================================
# version()
# ===========================================================================


class TestVersion:
    """Tests for version() — kills binary resolution, subprocess args, version parsing."""

    def test_version_raises_when_not_found(self) -> None:
        """When composer binary not found → RuntimeError."""
        with patch(
            "harness_quality_gate.adapters.php.composer_audit_adapter.shutil.which",
            return_value=None,
        ):
            with pytest.raises(RuntimeError, match="composer not found"):
                _adapter().version(Path("/repo"))

    def test_version_successful_extraction_from_output(self) -> None:
        """Version extracted from 'Composer version 2.8.3 ...' output.

        Kills mutmut on subprocess.cmd construction, env merging, timeout,
        return code check, version parsing.
        """
        with patch("harness_quality_gate.adapters.php.composer_audit_adapter.shutil.which", return_value="/usr/bin/composer"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="Composer version 2.8.3 (some hash)\n")
                version = _adapter().version(Path("/repo"))
        assert version == "2.8.3"

    def test_version_with_env_merged(self) -> None:
        """version() merges env with os.environ for subprocess."""
        with patch("harness_quality_gate.adapters.php.composer_audit_adapter.shutil.which", return_value="/usr/bin/composer"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="Composer version 2.8.3\n")
                _adapter().version(Path("/repo"), env={"CUSTOM_VAR": "xyz"})
        mock_run.assert_called_once()
        kw = mock_run.call_args[1]
        assert kw["env"]["CUSTOM_VAR"] == "xyz"
        assert "PATH" in kw["env"]

    def test_version_hardcoded_timeout_30(self) -> None:
        """version() uses hardcoded timeout=30 (NOT 300 from invoke default)."""
        with patch("harness_quality_gate.adapters.php.composer_audit_adapter.shutil.which", return_value="/usr/bin/composer"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="Composer version 2.8.3\n")
                _adapter().version(Path("/repo"))
        kw = mock_run.call_args[1]
        assert kw["timeout"] == 30

    def test_version_nonzero_exitcode_raises(self) -> None:
        """Non-zero returncode → RuntimeError with stderr."""
        with patch("harness_quality_gate.adapters.php.composer_audit_adapter.shutil.which", return_value="/usr/bin/composer"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="composer error")
                with pytest.raises(RuntimeError, match="composer --version failed"):
                    _adapter().version(Path("/repo"))

    def test_version_fallback_returns_stripped_output(self) -> None:
        """When no version number found in output → return stripped stdout."""
        with patch("harness_quality_gate.adapters.php.composer_audit_adapter.shutil.which", return_value="/usr/bin/composer"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="Composer dev\n")
                version = _adapter().version(Path("/repo"))
        assert version == "Composer dev"

    def test_version_subprocess_argv(self) -> None:
        """subprocess.run is called with [cmd, "--version"]."""
        with patch("harness_quality_gate.adapters.php.composer_audit_adapter.shutil.which", return_value="/usr/bin/composer"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="Composer version 2.8.3\n")
                _adapter().version(Path("/repo"))
        args = mock_run.call_args[0][0]
        assert args[0] == "/usr/bin/composer"
        assert args == ["/usr/bin/composer", "--version"]

    def test_version_cwd_is_repo(self) -> None:
        """subprocess.run cwd is str(repo)."""
        with patch("harness_quality_gate.adapters.php.composer_audit_adapter.shutil.which", return_value="/usr/bin/composer"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="Composer version 2.8.3\n")
                repo = Path("/custom/repo")
                _adapter().version(repo)
        assert mock_run.call_args[1]["cwd"] == "/custom/repo"


# ===========================================================================
# invoke()
# ===========================================================================


class TestInvoke:
    """Tests for invoke() — kills binary resolution, run construction, args."""

    def test_invoke_raises_when_no_binary(self) -> None:
        """When composer not found → RuntimeError."""
        with patch("harness_quality_gate.adapters.php.composer_audit_adapter.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="composer not found on PATH"):
                _adapter().invoke(Path("/repo"))

    def test_invoke_with_extra_args(self) -> None:
        """invoke calls _run with composer cmd + audit args."""
        with patch.object(ComposerAuditAdapter, "_composer_binary", return_value=["/usr/bin/composer"]):
            with patch.object(
                ComposerAuditAdapter, "_run",
                return_value=MagicMock(stdout="[]", stderr="", exitcode=0, duration_seconds=0.0),
            ) as mock_run:
                _adapter().invoke(Path("/repo"), ["--dry-run"])
        cmd = mock_run.call_args[0][0]
        assert cmd == ["/usr/bin/composer", "audit", "--format=json", "--no-dev"]

    def test_invoke_custom_timeout_passed(self) -> None:
        """invoke forwards timeout to _run."""
        with patch.object(ComposerAuditAdapter, "_composer_binary", return_value=["/usr/bin/composer"]):
            with patch.object(
                ComposerAuditAdapter, "_run",
                return_value=MagicMock(stdout="[]", stderr="", exitcode=0, duration_seconds=0.0),
            ) as mock_run:
                _adapter().invoke(Path("/repo"), timeout=120.0)
        assert mock_run.call_args[1]["timeout"] == 120.0

    def test_invoke_cwd_set_to_repo(self) -> None:
        """invoke sets cwd=repo in _run."""
        with patch.object(ComposerAuditAdapter, "_composer_binary", return_value=["/usr/bin/composer"]):
            with patch.object(
                ComposerAuditAdapter, "_run",
                return_value=MagicMock(stdout="[]", stderr="", exitcode=0, duration_seconds=0.0),
            ) as mock_run:
                repo = Path("/custom/repo")
                _adapter().invoke(repo)
        assert mock_run.call_args[1]["cwd"] == repo

    def test_invoke_env_passed_to_run(self) -> None:
        """invoke passes env dict to _run."""
        with patch.object(ComposerAuditAdapter, "_composer_binary", return_value=["/usr/bin/composer"]):
            with patch.object(
                ComposerAuditAdapter, "_run",
                return_value=MagicMock(stdout="[]", stderr="", exitcode=0, duration_seconds=0.0),
            ) as mock_run:
                _adapter().invoke(Path("/repo"), env={"COMPOSER_HOME": "/custom"})
        assert mock_run.call_args[1]["env"]["COMPOSER_HOME"] == "/custom"

    def test_invoke_default_args(self) -> None:
        """invoke with None args → only standard audit_args."""
        with patch.object(ComposerAuditAdapter, "_composer_binary", return_value=["/usr/bin/composer"]):
            with patch.object(
                ComposerAuditAdapter, "_run",
                return_value=MagicMock(stdout="[]", stderr="", exitcode=0, duration_seconds=0.0),
            ) as mock_run:
                _adapter().invoke(Path("/repo"))
        cmd = mock_run.call_args[0][0]
        assert len(cmd) == 4
        assert cmd == ["/usr/bin/composer", "audit", "--format=json", "--no-dev"]


# ===========================================================================
# parse()
# ===========================================================================


class TestParse:
    """Tests for parse() — kills JSON parsing, Finding construction, data.get() mutations."""

    def test_parse_empty_output(self) -> None:
        assert _adapter().parse("", "", 0) == []

    def test_parse_whitespace_only(self) -> None:
        assert _adapter().parse("   \n  ", "", 0) == []

    def test_parse_invalid_json(self) -> None:
        assert _adapter().parse("not json", "", 0) == []

    def test_parse_no_advisories_key(self) -> None:
        assert _adapter().parse('{"packages": []}', "", 0) == []

    def test_parse_advisories_not_dict(self) -> None:
        assert _adapter().parse('{"advisories": "string"}', "", 0) == []

    def test_parse_advisories_empty_dict(self) -> None:
        assert _adapter().parse('{"advisories": {}}', "", 0) == []

    def test_parse_single_advisory_all_fields(self) -> None:
        """Single advisory with all fields → each Finding field verified."""
        data = {
            "advisories": {
                "vendor/package": [
                    {
                        "advisoryId": "SEC-123",
                        "cve": "CVE-2024-1234",
                        "title": "SQL injection possible",
                        "link": "https://example.com/advisory/123",
                    }
                ]
            }
        }
        findings = _adapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "vendor/package"
        assert f.severity == "error"
        assert f.message == "SQL injection possible"
        assert f.fix_hint == "https://example.com/advisory/123"
        assert f.cve == "CVE-2024-1234"
        assert f.cwe == ""

    def test_parse_advisory_without_cve_uses_advisory_id(self) -> None:
        data = {
            "advisories": {
                "vendor/package": [
                    {"advisoryId": "SEC-456", "title": "XSS vulnerability"},
                ]
            }
        }
        findings = _adapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        assert findings[0].cve == "SEC-456"

    def test_parse_advisory_missing_title(self) -> None:
        data = {"advisories": {"vendor/package": [{"advisoryId": "SEC-789"}]}}
        findings = _adapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        assert findings[0].message == "Advisory for vendor/package"

    def test_parse_advisory_missing_all_optional_fields(self) -> None:
        data = {"advisories": {"acme/thing": [{"advisoryId": "ADV-1"}]}}
        findings = _adapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "acme/thing"
        assert f.severity == "error"
        assert f.message == "Advisory for acme/thing"
        assert f.fix_hint is None
        assert f.cve == "ADV-1"
        assert f.cwe == ""

    def test_parse_multiple_advisories(self) -> None:
        data = {
            "advisories": {
                "pkg/pkg-a": [
                    {"advisoryId": "SEC-1", "cve": "CVE-2024-001", "title": "Title 1"},
                    {"advisoryId": "SEC-2", "title": "Title 2"},
                ],
                "pkg/pkg-b": [{"advisoryId": "SEC-3"}],
            }
        }
        findings = _adapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 3
        nodes = {f.node for f in findings}
        assert nodes == {"pkg/pkg-a", "pkg/pkg-b"}
        for f in findings:
            assert f.severity == "error"
            assert f.cwe == ""

    def test_parse_adv_not_dict_skipped(self) -> None:
        data = {"advisories": {"pkg/x": ["not a dict", {"advisoryId": "SEC-1"}]}}
        findings = _adapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 1

    def test_parse_adv_list_not_list_skipped(self) -> None:
        data = {"advisories": {"pkg/x": "not a list"}}
        assert _adapter().parse(json.dumps(data), "", 0) == []

    def test_parse_return_is_list(self) -> None:
        """parse() always returns a list, never None/dict."""
        assert isinstance(_adapter().parse("", "", 0), list)
        assert isinstance(_adapter().parse('{"advisories":{}}', "", 0), list)

    def test_parse_exitcode_ignored_in_parse(self) -> None:
        """exitcode is ignored by parse() — always processes stdout."""
        data = {"advisories": {"vendor/pkg": [{"advisoryId": "SEC-0"}]}}
        findings = _adapter().parse(json.dumps(data), "", 1)
        assert len(findings) == 1

    def test_parse_node_is_package_path(self) -> None:
        assert _adapter().parse('{"advisories":{"exact/path/package":[{"advisoryId":"S"}]}}', "", 0)[0].node == "exact/path/package"

    def test_parse_severity_is_error(self) -> None:
        assert _adapter().parse('{"advisories":{"pkg/x":[{"advisoryId":"A"}]}}', "", 0)[0].severity == "error"

    def test_parse_cwe_is_empty_string(self) -> None:
        assert _adapter().parse('{"advisories":{"pkg/x":[{"advisoryId":"A"}]}}', "", 0)[0].cwe == ""

    def test_parse_multiple_packages_density(self) -> None:
        """Dense assertion: verify ALL fields for multiple findings."""
        data = {
            "advisories": {
                "vendor/pkg-a": [{"advisoryId": "S1", "title": "T1", "link": "h1", "cve": "C1"}],
                "vendor/pkg-b": [{"advisoryId": "S2", "title": "T2"}],
            }
        }
        findings = _adapter().parse(json.dumps(data), "", 0)
        assert len(findings) == 2
        f0, f1 = findings
        assert f0.node == "vendor/pkg-a"
        assert f0.severity == "error"
        assert f0.message == "T1"
        assert f0.fix_hint == "h1"
        assert f0.cve == "C1"
        assert f0.cwe == ""
        assert f1.node == "vendor/pkg-b"
        assert f1.severity == "error"
        assert f1.message == "T2"
        assert f1.fix_hint is None
        assert f1.cve == "S2"
        assert f1.cwe == ""


# ===========================================================================
# ToolAdapter base class compliance
# ===========================================================================


class TestToolAdapterCompliance:
    """Tests ensuring ComposerAuditAdapter implements ToolAdapter correctly."""

    def test_name_property(self) -> None:
        assert _adapter().name == "composer-audit"

    def test_name_type(self) -> None:
        assert isinstance(_adapter().name, str)

    def test_isinstance_tool_adapter(self) -> None:
        assert isinstance(_adapter(), ToolAdapter)
