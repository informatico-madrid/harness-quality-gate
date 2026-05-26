"""Framework signal sniffer for polyglot repos.

Detects PHP and Python frameworks from manifest files and source-file
presence.  Returns the canonical framework name or ``None`` when no
signal is found.

Design: Component Responsibilities / framework_sniffer
Requirements: FR-4, US-2
"""

from __future__ import annotations

import json
import re
from pathlib import Path


# ------------------------------------------------------------------
# Manifest → framework map  (key is the package name in require/dev-require)
# ------------------------------------------------------------------

_PHP_FRAMEWORK_MANIFESTS: dict[str, str] = {
    "laravel/framework": "laravel",
    "symfony/framework-bundle": "symfony",
    "drupal/core": "drupal",
    "roots/wordpress": "wordpress",
}

_PYTHON_FRAMEWORK_MANIFESTS: dict[str, str] = {
    "django": "django",
    "flask": "flask",
    "fastapi": "fastapi",
    "starlette": "fastapi",
    "django-rest-framework": "django-rest",
    "djangorestframework": "django-rest",
}


def _parse_require_section(composer_text: str) -> dict[str, str]:
    """Extract ``"package": "version"`` pairs from a composer.json string."""
    data = json.loads(composer_text)
    sections = ("require", "require-dev")
    result: dict[str, str] = {}
    for section in sections:
        section_data = data.get(section, {})
        if isinstance(section_data, dict):
            result.update(section_data)
    return result


def _file_exists_at(repo: Path, rel: str) -> bool:
    """Return True when *rel* (relative to *repo*) exists as file or dir."""
    return (repo / rel).exists()


def _dir_has_content(repo: Path, rel: str, pattern: re.Pattern[str]) -> bool:
    """Return True when any file under *rel* matches *pattern*."""
    base = repo / rel
    if not base.is_dir():
        return False
    try:
        for entry in base.rglob("*"):
            if entry.is_file() and pattern.search(str(entry)):
                return True
    except OSError:
        pass
    return False


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def sniff_framework(repo: Path, language: str) -> str | None:
    """Detect framework signals in *repo* for the given *language*.

    Returns
    -------
    str | None
        The canonical framework name (lowercase), or ``None``.
    """
    repo = repo.resolve()
    lang = language.lower()

    if lang == "php":
        return _sniff_php(repo)
    if lang == "python":
        return _sniff_python(repo)
    return None


# ------------------------------------------------------------------
# PHP detection
# ------------------------------------------------------------------

def _sniff_php(repo: Path) -> str | None:
    composer = repo / "composer.json"
    require: dict[str, str] = {}
    if composer.is_file():
        try:
            require = _parse_require_section(composer.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            require = {}

    # 1. Manifest-based detection (require keys)
    for pkg, fw in _PHP_FRAMEWORK_MANIFESTS.items():
        if pkg in require:
            return fw

    # 2. Composer vendor manifest (e.g. vendor/laravel/framework/composer.json)
    vendor_dir = repo / "vendor"
    if vendor_dir.is_dir():
        for pkg, fw in _PHP_FRAMEWORK_MANIFESTS.items():
            vendor_path = vendor_dir
            for part in pkg.split("/"):
                vendor_path = vendor_path / part
            vendor_path = vendor_path / "composer.json"
            if vendor_path.is_file():
                try:
                    vendor_data = json.loads(vendor_path.read_text(encoding="utf-8"))
                    if vendor_data.get("name") == pkg:
                        return fw
                except (json.JSONDecodeError, OSError):
                    pass

    # 3. Source-file heuristics
    if _file_exists_at(repo, "App/Kernel.php"):
        return "symfony"
    if _file_exists_at(repo, "wp-includes/version.php"):
        return "wordpress"
    if _dir_has_content(repo, "core", re.compile(r"\\.info\\.ya?ml$", re.IGNORECASE)):
        return "drupal"
    if _dir_has_content(repo, "vendor/laravel", re.compile(r"Illuminate", re.IGNORECASE)):
        return "laravel"

    return None


# ------------------------------------------------------------------
# Python detection
# ------------------------------------------------------------------

def _sniff_python(repo: Path) -> str | None:
    pyproject = repo / "pyproject.toml"
    pipfile = repo / "Pipfile"
    requirements = repo / "requirements.txt"
    setup_py = repo / "setup.py"

    require: dict[str, str] = {}
    for manifest in (pyproject, pipfile, requirements, setup_py):
        if manifest.is_file():
            require.update(_parse_python_manifest(manifest))

    # 1. Manifest-based detection
    for pkg, fw in _PYTHON_FRAMEWORK_MANIFESTS.items():
        if pkg in require:
            return fw

    # 2. Source-file heuristics
    if _file_exists_at(repo, "manage.py"):
        return "django"
    if _file_exists_at(repo, "app.py") and _dir_has_content(repo, ".", re.compile(r"from flask import", re.IGNORECASE)):
        return "flask"
    if _dir_has_content(repo, ".", re.compile(r"from fastapi import", re.IGNORECASE)):
        return "fastapi"

    return None


def _parse_python_manifest(path: Path) -> dict[str, str]:
    """Best-effort extract package names from common Python manifests."""
    result: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return result

    if path.name == "pyproject.toml":
        # --- [tool.poetry.dependencies] ---
        in_poetry_deps = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped == "[tool.poetry.dependencies]":
                in_poetry_deps = True
                continue
            if stripped.startswith("[") and in_poetry_deps:
                in_poetry_deps = False
                continue
            if in_poetry_deps:
                m = re.match(r'^([A-Za-z0-9_][A-Za-z0-9._-]*)', stripped)
                if m:
                    result[m.group(1).lower()] = ""
        # --- [project] section: look for dependencies = [...] ---
        in_project = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("[project]") or stripped.startswith("[project."):
                if stripped == "[project]":
                    in_project = True
                else:
                    in_project = False
                continue
            if stripped.startswith("[") and in_project:
                in_project = False
                continue
            if in_project:
                # Match dependencies = ["pkg1", "pkg2"]
                m = re.match(r'^dependencies\s*=\s*\[', stripped)
                if m:
                    # Extract all quoted package specs from the list
                    for item in re.findall(r'"([^"]+)"|\'([^\']+)\'', stripped):
                        pkg = _extract_pip_package_name(item[0] or item[1])
                        if pkg:
                            result[pkg] = ""
                    # Handle multi-line lists: keep reading until ]
                    if ']' not in stripped:
                        for next_line in text.splitlines()[text.splitlines().index(line)+1:]:
                            ns = next_line.strip()
                            for item in re.findall(r'"([^"]+)"|\'([^\']+)\'', ns):
                                pkg = _extract_pip_package_name(item[0] or item[1])
                                if pkg:
                                    result[pkg] = ""
                            if ']' in ns:
                                break
    elif path.name == "Pipfile":
        in_requires = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped == "[packages]" or stripped == "[dev-packages]":
                in_requires = True
                continue
            if stripped.startswith("["):
                in_requires = False
                continue
            if in_requires:
                pkg = _extract_pip_package_name(stripped)
                if pkg:
                    result[pkg] = ""
    elif path.name in ("requirements.txt", "setup.py"):
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            pkg = _extract_pip_package_name(stripped)
            if pkg:
                result[pkg] = ""

    return result


def _extract_pip_package_name(spec: str) -> str | None:
    """Extract package name from a pip-style spec like ``django>=4.2``."""
    spec = spec.strip()
    # Remove extras, version specifiers
    m = re.match(r"([A-Za-z0-9_][A-Za-z0-9._-]*)", spec)
    if m:
        return m.group(1).lower().replace("-", "").replace("_", "")
    return None
