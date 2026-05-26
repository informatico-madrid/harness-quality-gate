"""Tool installer for PHP gate.

Implements composer-local installation of PHP tools (primary path)
with PHAR download fallback (Phase 2).

Per design.md installer component:
- Reads config/php-tool-versions.json for pinned versions
- Runs `composer require --dev <package>:<version>` per critical tool
- Falls back to PHAR download with SHA-256 verification
- Returns InstallReport with status
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

from harness_quality_gate.models import InstallReport


class ChecksumMismatch(Exception):
    """Raised when PHAR SHA-256 does not match manifest."""


# Cache directory for PHAR files
_CACHE_DIR = Path.home() / ".cache" / "harness-quality-gate" / "bin"


def _find_config_path(repo: Path) -> Path:
    """Locate config/php-tool-versions.json relative to repo."""
    candidate = repo / "config" / "php-tool-versions.json"
    if candidate.exists():
        return candidate
    for parent in repo.parents:
        candidate = parent / "config" / "php-tool-versions.json"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("config/php-tool-versions.json not found near repo")


def _load_tool_versions(config_path: Path) -> dict[str, Any]:
    """Load and parse php-tool-versions.json."""
    with open(config_path, "r") as f:
        return json.load(f)


def _load_critical_tools(repo: Path) -> list[tuple[str, str, str]]:
    """Return list of (name, package, version) for critical tools."""
    taxonomy_path = repo / "config" / "php-tool-taxonomy.json"
    if not taxonomy_path.exists():
        for parent in repo.parents:
            taxonomy_path = parent / "config" / "php-tool-taxonomy.json"
            if taxonomy_path.exists():
                break

    versions_path = _find_config_path(repo)
    versions = _load_tool_versions(versions_path)

    # Use a minimal taxonomy inline for critical composer tools
    critical_tools: list[tuple[str, str, str]] = []
    for name, info in versions.items():
        if name in (
            "phpunit",
            "phpstan",
            "infection",
            "psalm",
            "deptrac",
            "php-cs-fixer",
            "phpmd",
        ):
            version = info.get("version", "")
            if version:
                critical_tools.append((name, name, version))

    return critical_tools


def _run_composer_require(repo: Path, package: str, version: str) -> tuple[bool, str | None]:
    """Run `composer require --dev <package>:<version>`."""
    try:
        result = subprocess.run(
            ["composer", "require", "--dev", f"{package}:{version}"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode == 0:
            return True, None
        return False, result.stderr or result.stdout
    except FileNotFoundError:
        return False, "composer not found on PATH"
    except subprocess.TimeoutExpired:
        return False, "composer timed out after 600s"


def _download_phar(
    name: str,
    version: str,
    phar_url: str,
    expected_sha256: str,
) -> tuple[bool, Path | None, str | None]:
    """Download a PHAR file and verify SHA-256.

    Returns (success, cached_path, error_message).
    On SHA-256 mismatch, deletes the partial file.
    """
    cache_dir = _CACHE_DIR / f"{name}-{version}-{expected_sha256[:8]}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    phar_path = cache_dir / f"{name}.phar"

    # Already cached?
    if phar_path.exists():
        return True, phar_path, None

    try:
        with urllib.request.urlopen(phar_url, timeout=120) as response:
            data = response.read()

        # Verify SHA-256
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if actual_sha256 != expected_sha256:
            phar_path.unlink(missing_ok=True)
            return False, None, (
                f"{name}: SHA-256 mismatch (expected={expected_sha256[:16]}..., "
                f"got={actual_sha256[:16]}...)"
            )

        # Write atomically
        temp_path = phar_path.with_suffix(".tmp")
        temp_path.write_bytes(data)
        temp_path.rename(phar_path)

        return True, phar_path, None
    except urllib.error.URLError as e:
        phar_path.unlink(missing_ok=True)
        return False, None, f"{name}: download failed — {e.reason}"
    except OSError as e:
        phar_path.unlink(missing_ok=True)
        return False, None, f"{name}: write failed — {e}"


def install(
    repo: Path,
    plan: object | None = None,
    phar_only: bool = False,
) -> InstallReport:
    """Install PHP gate tools.

    Primary path: composer-local.
    Fallback (if phar_only=True or composer fails): PHAR download.

    Args:
        repo: Path to the PHP repository.
        plan: Optional install plan (reserved).
        phar_only: If True, skip composer and use PHAR download.

    Returns:
        InstallReport with installation status.

    Raises:
        FileNotFoundError: If tool version config is missing.
    """
    versions = _load_tool_versions(_find_config_path(repo))

    installed: list[str] = []
    failed: list[str] = []
    errors: list[str] = []

    if phar_only:
        return _install_phar(repo, versions, installed, failed, errors)

    # Composer-local path
    return _install_composer(repo, versions, installed, failed, errors)


def _install_composer(
    repo: Path,
    versions: dict[str, Any],
    installed: list[str],
    failed: list[str],
    errors: list[str],
) -> InstallReport:
    """Install via composer (primary path)."""
    critical = _load_critical_tools(repo)

    if not shutil.which("composer"):
        return InstallReport(
            status="error",
            tools_installed=[],
            tools_failed=[t[0] for t in critical],
            errors=["composer not found on PATH"],
        )

    for name, package, version in critical:
        success, err = _run_composer_require(repo, package, version)
        if success:
            installed.append(name)
        else:
            failed.append(name)
            if err:
                errors.append(f"{name}: {err[:200]}")

    return _make_report(installed, failed, errors)


def _install_phar(
    repo: Path,
    versions: dict[str, Any],
    installed: list[str],
    failed: list[str],
    errors: list[str],
) -> InstallReport:
    """Install via PHAR download with SHA-256 verification."""
    for name, info in versions.items():
        phar_url = info.get("phar_url", "")
        expected_sha256 = info.get("sha256", "")
        version = info.get("version", "unknown")

        if not phar_url or expected_sha256 == "placeholder-phase-2":
            failed.append(name)
            errors.append(f"{name}: PHAR URL or SHA missing (placeholder)")
            continue

        success, _path, err = _download_phar(name, version, phar_url, expected_sha256)
        if success:
            installed.append(name)
        else:
            failed.append(name)
            if err:
                errors.append(err)

    return _make_report(installed, failed, errors)


def _make_report(installed: list[str], failed: list[str], errors: list[str]) -> InstallReport:
    """Create InstallReport from collected results."""
    if failed:
        status = "partial" if installed else "error"
    else:
        status = "success"

    return InstallReport(
        status=status,
        tools_installed=installed,
        tools_failed=failed,
        errors=errors,
    )
