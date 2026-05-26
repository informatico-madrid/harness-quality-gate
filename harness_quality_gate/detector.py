"""Three-tier language detection for polyglot repos.

Tier 1 — explicit override via ``.quality-gate-lang``.
Tier 2 — manifest scan (``pyproject.toml`` vs ``composer.json``).
Tier 3 — source-file count tie-breaker (``*.py`` vs ``*.php``).

Scoring
-------
score = (10 if manifest_hits else 0) + min(file_count, 100)

Returns a :class:`~harness_quality_gate.models.Detection`.
"""

from __future__ import annotations

import os
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

from .models import Detection, Runtime

# Directories skipped during file scanning.
EXCLUDE_DIRS: set[str] = {
    ".git",
    "node_modules",
    "vendor",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".tox",
    "_quality-gate",
    "_bmad-output",
}

# File extensions that count as "source code" per language.
PY_EXTENSIONS: set[str] = {
    ".py",
    ".pyi",
    ".pyx",
}

PHP_EXTENSIONS: set[str] = {
    ".php",
    ".php4",
    ".php5",
    ".phtml",
    ".inc",
}

# Manifest file names that strongly indicate each language.
PYTHON_MANIFESTS: set[str] = {
    "pyproject.toml",
    "setup.py",
    "Pipfile",
    "poetry.lock",
    "uv.lock",
}

PHP_MANIFESTS: set[str] = {
    "composer.json",
    "composer.lock",
}


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _find_manifests(repo: Path, manifests: set[str]) -> list[str]:
    """Return manifest file paths found at the repository root."""
    found: list[str] = []
    for name in manifests:
        if (repo / name).is_file():
            found.append(name)
    return found


def _count_source_files(repo: Path, extensions: set[str]) -> int:
    """Count source-code files under *repo*, excluding *EXCLUDE_DIRS*."""
    count = 0
    for dirpath, dirnames, filenames in os.walk(repo):
        # Prune excluded directories in-place.
        dirnames[:] = [
            d for d in dirnames
            if d not in EXCLUDE_DIRS and not Path(dirpath, d).is_symlink()
        ]
        for fn in filenames:
            if any(fn.endswith(ext) for ext in extensions):
                count += 1
    return count


def _detect_python_version(repo: Path) -> str:
    """Best-effort Python version from pyproject.toml or system."""
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        try:
            content = pyproject.read_text(encoding="utf-8")
            for line in content.splitlines():
                if "requires-python" in line:
                    import re
                    m = re.search(r'">=([\d.]+)"', line)
                    if m:
                        return m.group(1)
        except (OSError, UnicodeDecodeError):
            pass

    # Fallback: detect from system Python.
    try:
        result = subprocess.run(
            ["python3", "--version"], capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip().split()[-1]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return "3.x"


def _detect_ci_environment() -> bool:
    """Return True if any CI environment variable is set."""
    ci_vars = {"CI", "GITHUB_ACTIONS", "GITLAB_CI", "BUILDKITE", "CIRCLECI"}
    return bool(ci_vars & set(os.environ))


def _detect_concurrency_mode() -> str:
    """Return 'parallel' or 'sequential' based on CLI flag / CI env."""
    if os.environ.get("CLAUDE_CODE_CONCURRENCY"):
        return os.environ["CLAUDE_CODE_CONCURRENCY"]
    if _detect_ci_environment():
        return "sequential"
    return "parallel"


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def detect(repo: Path, force: bool = False) -> Detection:
    """Perform three-tier language detection on *repo*.

    Parameters
    ----------
    repo:
        Path to the repository root.
    force:
        If ``True``, skip any caching layer (reserved for future use).

    Returns
    -------
    Detection
        A :class:`~harness_quality_gate.models.Detection` describing the
        detected language(s), framework signals, and source-file counts.
    """
    repo = repo.resolve()

    # ---- Tier 1: explicit override ----
    override_file = repo / ".quality-gate-lang"
    if override_file.is_file():
        primary = override_file.read_text(encoding="utf-8").strip().lower()
        # Resolve alias
        lang_map = {"py": "python", "python": "python", "php": "php"}
        language = lang_map.get(primary, primary)
        return Detection(
            repo_path=str(repo),
            language=language,
            framework=None,
            confidence=1.0,
            runtime=Runtime(
                python_version=_detect_python_version(repo),
                concurrency=_detect_concurrency_mode(),
                ci=_detect_ci_environment(),
            ),
            languages_detected=[language],
            frameworks={},
            file_counts={language: 0},
        )

    # ---- Tier 2: manifest scan ----
    py_manifests = _find_manifests(repo, PYTHON_MANIFESTS)
    php_manifests = _find_manifests(repo, PHP_MANIFESTS)
    py_manifest_score = 10 if py_manifests else 0
    php_manifest_score = 10 if php_manifests else 0

    # ---- Tier 3: source-file count ----
    py_file_count = _count_source_files(repo, PY_EXTENSIONS)
    php_file_count = _count_source_files(repo, PHP_EXTENSIONS)

    # Hybrid scoring: (10 if manifest_hits else 0) + min(file_count, 100)
    py_score = py_manifest_score + min(py_file_count, 100)
    php_score = php_manifest_score + min(php_file_count, 100)

    # Collect all detected languages (score > 0 or manifest found)
    languages_detected: list[str] = []
    if py_manifests or py_file_count > 0:
        languages_detected.append("python")
    if php_manifests or php_file_count > 0:
        languages_detected.append("php")

    file_counts: dict[str, int] = {}
    if py_file_count > 0:
        file_counts["python"] = py_file_count
    if php_file_count > 0:
        file_counts["php"] = php_file_count

    # Determine primary language (tie-break: first found, then python)
    if php_score > py_score:
        primary = "php"
    elif py_score > php_score:
        primary = "python"
    elif languages_detected:
        # Tie: prefer python if both scores are 0 (no manifests)
        primary = "python"
    else:
        # Neither language detected at all
        primary = "python"

    # Confidence: 1.0 if manifest hit, 0.7 if file-count based
    manifest_hit = bool(py_manifests or php_manifests)
    confidence = 1.0 if manifest_hit else min(0.9, 0.5 + min(py_file_count + php_file_count, 50) / 50)

    return Detection(
        repo_path=str(repo),
        language=primary,
        framework=None,
        confidence=round(confidence, 2),
        runtime=Runtime(
            python_version=_detect_python_version(repo),
            concurrency=_detect_concurrency_mode(),
            ci=_detect_ci_environment(),
        ),
        languages_detected=languages_detected,
        frameworks={},
        file_counts=file_counts,
    )
