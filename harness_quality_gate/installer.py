"""Tool installer for PHP gate.

Implements composer-local installation of PHP tools (POC path).
PHAR download path deferred to Phase 2.

Per design.md installer component:
- Reads config/php-tool-versions.json for pinned versions
- Runs `composer require --dev <package>:<version>` per critical tool
- Returns InstallReport with status
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from harness_quality_gate.models import InstallReport


def _find_config_path(repo: Path) -> Path:
    """Locate config/php-tool-versions.json relative to repo."""
    candidate = repo / "config" / "php-tool-versions.json"
    if candidate.exists():
        return candidate
    # Fallback: look in common ancestor locations
    for parent in repo.parents:
        candidate = parent / "config" / "php-tool-versions.json"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "config/php-tool-versions.json not found near repo"
    )


def _load_tool_versions(config_path: Path) -> dict[str, dict]:
    """Load and parse php-tool-versions.json."""
    with open(config_path, "r") as f:
        return json.load(f)


def _load_critical_tools(repo: Path) -> list[tuple[str, str, str]]:
    """Return list of (name, package, version) for critical tools.

    Reads config/php-tool-taxonomy.json to filter critical tools,
    then matches against config/php-tool-versions.json for versions.
    """
    taxonomy_path = repo / "config" / "php-tool-taxonomy.json"
    if not taxonomy_path.exists():
        # Search upward if not at repo root
        for parent in repo.parents:
            taxonomy_path = parent / "config" / "php-tool-taxonomy.json"
            if taxonomy_path.exists():
                break

    versions_path = _find_config_path(repo)

    # Load taxonomy
    with open(taxonomy_path, "r") as f:
        taxonomy = json.load(f)

    # Load versions
    versions = _load_tool_versions(versions_path)

    # Filter critical + install_via=composer + has package
    result = []
    for entry in taxonomy:
        if entry.get("criticality") != "critical":
            continue
        if entry.get("install_via") != "composer":
            continue
        package = entry.get("package")
        if not package:
            continue
        name = entry["name"]
        ver = versions.get(name, {}).get("version", "")
        if ver:
            result.append((name, package, ver))

    return result


def _run_composer_require(repo: Path, package: str, version: str) -> tuple[bool, str | None]:
    """Run `composer require --dev <package>:<version>`.

    Returns (success, error_message_or_none).
    """
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


def install(repo: Path, plan: object | None = None) -> InstallReport:
    """Install PHP gate tools via composer (POC path).

    Reads config/php-tool-versions.json and config/php-tool-taxonomy.json,
    then runs `composer require --dev <package>:<version>` for each
    critical tool with a pinned version.

    Args:
        repo: Path to the PHP repository.
        plan: Optional install plan (reserved for Phase 2 PHAR path).

    Returns:
        InstallReport with installation status.

    Raises:
        FileNotFoundError: If tool version config is missing.
    """
    tools = _load_critical_tools(repo)
    installed: list[str] = []
    failed: list[str] = []
    errors: list[str] = []

    # Check composer availability first
    if not shutil.which("composer"):
        return InstallReport(
            status="error",
            tools_installed=[],
            tools_failed=[t[0] for t in tools],
            errors=["composer not found on PATH"],
        )

    for name, package, version in tools:
        success, err = _run_composer_require(repo, package, version)
        if success:
            installed.append(name)
        else:
            failed.append(name)
            if err:
                errors.append(f"{name}: {err[:200]}")

    if failed:
        status = "partial"
    else:
        status = "success"

    return InstallReport(
        status=status,
        tools_installed=installed,
        tools_failed=failed,
        errors=errors,
    )
