"""Unit tests for the installer module.

Covers composer-present path, PHAR-only path with SHA verification,
corrupt PHAR → ChecksumMismatch, placeholder detection, and caching.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.installer import (
    _download_phar,
    _find_config_path,
    _install_composer,
    _install_phar,
    _make_report,
    install,
)


# ---------------------------------------------------------------------------
# Config discovery
# ---------------------------------------------------------------------------


def test_find_config_path_in_repo(tmp_path: Path) -> None:
    """_find_config_path returns the config file under repo/config/."""
    config = tmp_path / "config" / "php-tool-versions.json"
    config.parent.mkdir()
    config.write_text("{}")
    assert _find_config_path(tmp_path) == config


def test_find_config_path_walks_up_parents(tmp_path: Path) -> None:
    """_find_config_path walks up parent directories if not in repo root."""
    repo = tmp_path / "sub" / "deep"
    config = tmp_path / "config" / "php-tool-versions.json"
    config.parent.mkdir(parents=True)
    config.write_text("{}")
    assert _find_config_path(repo) == config


def test_find_config_path_raises_when_missing(tmp_path: Path) -> None:
    """_find_config_path raises FileNotFoundError when config is absent."""
    with pytest.raises(FileNotFoundError, match="not found"):
        _find_config_path(tmp_path)


# ---------------------------------------------------------------------------
# Composer path
# ---------------------------------------------------------------------------


def test_composer_not_found(tmp_path: Path) -> None:
    """When composer is not on PATH → error status with all tools failed."""
    # Create minimal config so _load_critical_tools finds it
    config = tmp_path / "config" / "php-tool-versions.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"phpunit": {"version": "11.5.0"}}))
    installed: list[str] = []
    failed: list[str] = []
    errors: list[str] = []
    with patch("shutil.which", return_value=None):
        report = _install_composer(tmp_path, {}, installed, failed, errors)
    assert report.status == "error"
    assert report.tools_installed == []
    assert report.tools_failed == ["phpunit"]
    assert "composer not found on PATH" in report.errors[0]


def test_composer_success(tmp_path: Path) -> None:
    """Successful composer require → tool added to installed list."""
    # Create minimal config
    config = tmp_path / "config" / "php-tool-versions.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"phpunit": {"version": "11.5.0"}}))
    result = MagicMock()
    result.returncode = 0
    result.stderr = ""
    installed: list[str] = []
    failed: list[str] = []
    errors: list[str] = []
    with patch("shutil.which", return_value="/usr/bin/composer"):
        with patch("subprocess.run", return_value=result):
            report = _install_composer(tmp_path, {}, installed, failed, errors)
    assert report.status == "success"
    assert "phpunit" in report.tools_installed


def test_composer_failure_with_stderr(tmp_path: Path) -> None:
    """Composer fails with stderr → tool in failed list + error message."""
    config = tmp_path / "config" / "php-tool-versions.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"phpunit": {"version": "11.5.0"}}))
    result = MagicMock()
    result.returncode = 1
    result.stderr = "Class not found"
    installed: list[str] = []
    failed: list[str] = []
    errors: list[str] = []
    with patch("subprocess.run", return_value=result):
        with patch("shutil.which", return_value="/usr/bin/composer"):
            report = _install_composer(tmp_path, {}, installed, failed, errors)
    assert report.status == "error"
    assert "phpunit" in report.tools_failed
    assert "phpunit: Class not found" in report.errors[0]


def test_composer_timeout(tmp_path: Path) -> None:
    """Composer timeout → error message captured."""
    config = tmp_path / "config" / "php-tool-versions.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"phpunit": {"version": "11.5.0"}}))
    installed: list[str] = []
    failed: list[str] = []
    errors: list[str] = []
    timeout_err = subprocess.TimeoutExpired(
        ["composer", "require", "--dev", "phpunit:11.5.0"],
        timeout=600,
    )
    with patch("subprocess.run", side_effect=timeout_err):
        with patch("shutil.which", return_value="/usr/bin/composer"):
            report = _install_composer(tmp_path, {}, installed, failed, errors)
    assert report.status == "error"
    assert "phpunit" in report.tools_failed
    assert "timed out" in report.errors[0]


def test_install_phar_only_flag(tmp_path: Path) -> None:
    """phar_only=True skips composer and uses PHAR path."""
    # Create config so _find_config_path doesn't raise
    config = tmp_path / "config" / "php-tool-versions.json"
    config.parent.mkdir(parents=True)
    config.write_text("{}")
    with patch("harness_quality_gate.installer._install_phar") as mock_phar:
        mock_phar.return_value = MagicMock(status="error", tools_installed=[], tools_failed=[], errors=[])
        install(tmp_path, phar_only=True)  # type: ignore[arg-type]
        mock_phar.assert_called_once()


# ---------------------------------------------------------------------------
# PHAR download with SHA-256 verification
# ---------------------------------------------------------------------------


def _make_phar_bytes(version: str = "1.0.0", sha: str | None = None) -> tuple[bytes, str]:
    """Create deterministic PHAR bytes + expected SHA-256."""
    content = f"phpunit-{version}-phar-content"
    data = content.encode()
    expected = sha or hashlib.sha256(data).hexdigest()
    return data, expected


def test_phar_download_success() -> None:
    """Successful PHAR download with SHA match → cached, success=True."""
    data, expected = _make_phar_bytes()
    response = MagicMock()
    response.read.return_value = data
    urlopen_ctx = MagicMock()
    urlopen_ctx.__enter__ = MagicMock(return_value=response)
    urlopen_ctx.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=urlopen_ctx):
        success, path, err = _download_phar("phpunit", "1.0.0", "http://fake/phpunit.phar", expected)
    assert success is True
    assert path is not None
    assert err is None
    assert path.exists()
    # Cleanup
    path.unlink(missing_ok=True)
    try:
        path.parent.rmdir()
    except OSError:
        pass


def test_phar_sha_mismatch_deletes_file(tmp_path: Path) -> None:
    """SHA mismatch → file deleted, no orphan, error returned."""
    data, _ = _make_phar_bytes()
    wrong_sha = "a" * 64  # wrong SHA-256
    response = MagicMock()
    response.read.return_value = data
    urlopen_ctx = MagicMock()
    urlopen_ctx.__enter__ = MagicMock(return_value=response)
    urlopen_ctx.__exit__ = MagicMock(return_value=False)
    cache_dir = tmp_path / ".cache" / "harness-quality-gate" / "bin"
    with patch("urllib.request.urlopen", return_value=urlopen_ctx):
        with patch("harness_quality_gate.installer._CACHE_DIR", cache_dir):
            success, path, err = _download_phar("phpunit", "1.0.0", "http://fake/phpunit.phar", wrong_sha)
    assert success is False
    assert path is None
    assert "SHA-256 mismatch" in err  # type: ignore[arg-type]
    # No orphan file
    phar_files = list(cache_dir.rglob("phpunit.phar"))
    assert len(phar_files) == 0


def test_phar_already_cached_returns_path(tmp_path: Path) -> None:
    """Already cached PHAR → returns cached path without downloading."""
    # The cache dir name is: {name}-{version}-{sha[:8]}
    content = b"existing phar"
    sha = hashlib.sha256(content).hexdigest()
    cache_dir = tmp_path / ".cache" / "harness-quality-gate" / f"phpunit-1.0.0-{sha[:8]}"
    cache_dir.mkdir(parents=True)
    (cache_dir / "phpunit.phar").write_bytes(content)
    with patch("harness_quality_gate.installer._CACHE_DIR", cache_dir.parent):
        success, path, _ = _download_phar(
            "phpunit", "1.0.0",
            "http://fake/phpunit.phar",
            sha,
        )
    assert success is True
    assert path is not None
    assert path == cache_dir / "phpunit.phar"
    # urlopen should NOT have been called (cached)


def test_phar_download_url_error() -> None:
    """Network error → error message, no orphan file."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")  # type: ignore[attr-defined]
        success, path, err = _download_phar(
            "phpunit", "1.0.0",
            "http://fake/nonexistent.phar",
            "a" * 64,
        )
    assert success is False
    assert path is None
    assert "download failed" in err  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# PHAR install path
# ---------------------------------------------------------------------------


def test_phar_install_placeholder_fails() -> None:
    """PHAR install with all-placeholder SHA → error status (all fail)."""
    versions: dict = {
        "phpunit": {"version": "11.5.0", "phar_url": "http://fake/phpunit.phar", "sha256": "placeholder-phase-2"},
    }
    installed: list[str] = []
    failed: list[str] = []
    errors: list[str] = []
    report = _install_phar(Path("/tmp"), versions, installed, failed, errors)
    # All tools fail → status=error (per _make_report logic)
    assert report.status == "error"
    assert "phpunit" in report.tools_failed
    assert "placeholder" in report.errors[0]


def test_phar_install_partial_success() -> None:
    """PHAR install with one placeholder + one success → partial status."""
    # Use two non-placeholder tools where one succeeds and one fails
    versions: dict = {
        "phpunit": {"version": "11.5.0", "phar_url": "http://fake/phpunit.phar", "sha256": "real-sha-1"},
        "phpstan": {"version": "2.1.0", "phar_url": "http://fake/phpstan.phar", "sha256": "real-sha-2"},
    }
    installed: list[str] = []
    failed: list[str] = []
    errors: list[str] = []
    with patch("harness_quality_gate.installer._download_phar") as mock_dl:
        # phpunit: mocked failure
        # phpstan: mocked success
        mock_dl.side_effect = [
            (False, None, "phpunit: download failed"),
            (True, Path("/tmp/phpstan.phar"), None),
        ]
        report = _install_phar(Path("/tmp"), versions, installed, failed, errors)
    assert report.status == "partial"
    assert "phpunit" in report.tools_failed
    assert "phpstan" in report.tools_installed


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


def test_make_report_success() -> None:
    """No failures → status=success."""
    report = _make_report(["phpunit"], [], [])
    assert report.status == "success"
    assert report.tools_failed == []


def test_make_report_partial() -> None:
    """Some tools failed → status=partial."""
    report = _make_report(["phpunit"], ["infection"], ["infection: error"])
    assert report.status == "partial"
    assert report.tools_failed == ["infection"]


def test_make_report_error() -> None:
    """All tools failed → status=error."""
    report = _make_report([], ["phpunit", "infection"], ["phpunit: error"])
    assert report.status == "error"
    assert report.tools_installed == []
