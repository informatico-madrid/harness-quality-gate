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

import json
import os
import subprocess
from dataclasses import asdict
from pathlib import Path

from .framework_sniffer import sniff_framework
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
# Cache helpers (FR-3, NFR-3, TD-5, TD-16)
# ------------------------------------------------------------------

CACHE_DIR = "_quality-gate"
CACHE_FILE = "detection.json"
FINGERPRINT_FILE = ".detection-fingerprint"

_MANIFEST_NAMES = PYTHON_MANIFESTS | PHP_MANIFESTS


def _cache_path(repo: Path) -> Path:
    """Return the path to the cache JSON file inside the repo."""
    return repo / CACHE_DIR / CACHE_FILE


def _fingerprint_path(repo: Path) -> Path:
    """Return the path to the git-HEAD fingerprint file inside the repo."""
    return repo / CACHE_DIR / FINGERPRINT_FILE


def _current_git_head(repo: Path) -> str | None:
    """Return the current git HEAD sha, or None if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, cwd=str(repo),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _any_manifest_stale(repo: Path, cache_mtime: float) -> bool:
    """Return True if any manifest file was modified after the cache was written."""
    for name in _MANIFEST_NAMES:
        p = repo / name
        if p.is_file():
            try:
                if p.stat().st_mtime > cache_mtime:
                    return True
            except OSError:
                pass
    return False


def _load_cache(repo: Path) -> Detection | None:
    """Load a cached Detection from ``_quality-gate/detection.json``.

    Returns ``None`` when the cache is absent, corrupted, or stale
    (manifest mtime changed or git HEAD diverged).
    """
    cache = _cache_path(repo)
    if not cache.is_file():
        return None

    try:
        cache_mtime = cache.stat().st_mtime
    except OSError:
        return None

    # Stale-manifest check
    if _any_manifest_stale(repo, cache_mtime):
        return None

    # Stale-git-HEAD check
    fingerprint = _fingerprint_path(repo)
    if fingerprint.is_file():
        try:
            stored_head = fingerprint.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        # Skip comparison when either side is non-git
        if stored_head != "<no-git>":
            current_head = _current_git_head(repo)
            if current_head is not None and stored_head != current_head:
                return None

    # Read + reconstruct
    try:
        raw = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    # The cache stores all fields except the read-only `primary` alias.
    try:
        return Detection(**raw)
    except TypeError:
        return None


def _save_cache(repo: Path, detection: Detection) -> None:
    """Write *detection* and the current git HEAD to the cache files."""
    cache_dir = repo / CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache = _cache_path(repo)
    cache.write_text(
        json.dumps(asdict(detection), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    fingerprint = _fingerprint_path(repo)
    head = _current_git_head(repo)
    fingerprint.write_text((head or "<no-git>") + "\n", encoding="utf-8")


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
# Framework signal sniffing (FR-22, US-14, US-7)
# ------------------------------------------------------------------

def framework_signals(repo: Path) -> dict[str, list[str]]:
    """Detect framework signals in *repo*.

    Returns a dict mapping language (``"php"`` / ``"python"``) to a list
    of canonical framework names (lowercase).

    PHP signals
    -----------
    - Composer ``require`` / ``require-dev`` keys for framework packages:

      ``symfony/framework-bundle`` → ``["symfony"]``
      ``laravel/framework`` → ``["laravel"]``
      ``drupal/core`` → ``["drupal"]``
      ``roots/wordpress`` → ``["wordpress"]``

    - Pest test runner co-presence: both ``pestphp/pest`` AND
      ``pestphp/pest-plugin-mutate`` in composer.json ``require-dev``
      emits ``["pest"]``.

    Python signals
    --------------
    Delegates to :func:`sniff_framework <harness_quality_gate.framework_sniffer.sniff_framework>`.
    """
    repo = repo.resolve()
    result: dict[str, list[str]] = {}

    # PHP — sniff via existing sniffer
    php_fw = sniff_framework(repo, "php")
    if php_fw is not None:
        result["php"] = [php_fw]

    # PHP — Pest test runner co-presence (require + require-dev)
    composer = repo / "composer.json"
    if composer.is_file():
        try:
            data = json.loads(composer.read_text(encoding="utf-8"))
            dev = data.get("require-dev", {})
            has_pest = "pestphp/pest" in dev
            has_mutate = "pestphp/pest-plugin-mutate" in dev
            if has_pest and has_mutate:
                result.setdefault("php", []).append("pest")
        except (json.JSONDecodeError, OSError):
            pass

    # Python — sniff via existing sniffer
    py_fw = sniff_framework(repo, "python")
    if py_fw is not None:
        result["python"] = [py_fw]

    return result


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
        If ``True``, bypass the cache and always re-run detection.

    Returns
    -------
    Detection
        A :class:`~harness_quality_gate.models.Detection` describing the
        detected language(s), framework signals, and source-file counts.
    """
    repo = repo.resolve()

    # ---- Cache lookup (skip when --force) ----
    if not force:
        cached = _load_cache(repo)
        if cached is not None:
            return cached

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
            frameworks=framework_signals(repo),
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

    result = Detection(
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
        frameworks=framework_signals(repo),
        file_counts=file_counts,
    )

    _save_cache(repo, result)
    return result
