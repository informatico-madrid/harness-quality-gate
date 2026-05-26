"""Unit tests for the three-tier language detector.

Covers python-only, php-only, hybrid, empty, override-file,
cache-hit, mtime-invalidation, and git-HEAD-invalidation per
Coverage Table.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from harness_quality_gate.detector import (
    _load_cache,  # pyright: ignore[reportMissingImports]
    detect,
)
from tests.factories import build_detection  # pyright: ignore[reportMissingImports]


# ---------------------------------------------------------------------------
# Fixtures: repo helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def py_repo(tmp_path: Path) -> Path:
    """Create a minimal Python-only repo."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test-py"\n', encoding="utf-8"
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_mod.py").write_text("def test_one(): pass\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def php_repo(tmp_path: Path) -> Path:
    """Create a minimal PHP-only repo."""
    (tmp_path / "composer.json").write_text(
        '{"name":"test-php"}', encoding="utf-8"
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "App.php").write_text("<?php\nclass App {}\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "AppTest.php").write_text(
        "<?php\nclass AppTest {}\n", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture()
def hybrid_repo(tmp_path: Path) -> Path:
    """Create a repo with both Python and PHP sources."""
    (tmp_path / "composer.json").write_text(
        '{"name":"hybrid"}', encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "hybrid-py"\n', encoding="utf-8"
    )
    php_src = tmp_path / "src" / "php"
    php_src.mkdir(parents=True)
    (php_src / "app.php").write_text("<?php\nclass App {}\n", encoding="utf-8")
    py_src = tmp_path / "src" / "python"
    py_src.mkdir(parents=True)
    (py_src / "app.py").write_text("class App:\n    pass\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def override_repo(tmp_path: Path) -> Path:
    """Create a PHP repo with an explicit Python override."""
    (tmp_path / "composer.json").write_text(
        '{"name":"forced-py"}', encoding="utf-8"
    )
    (tmp_path / ".quality-gate-lang").write_text(
        "python\n", encoding="utf-8"
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Tests per Coverage Table
# ---------------------------------------------------------------------------

def test_python_only(py_repo: Path) -> None:
    """Tier 2+3: Python manifest + files → primary=python, confidence≈1.0."""
    result = detect(py_repo)
    assert result.primary == "python"
    assert result.language == "python"
    assert "python" in result.languages_detected
    assert "php" not in result.languages_detected
    assert result.confidence >= 0.9


def test_php_only(php_repo: Path) -> None:
    """Tier 2+3: PHP manifest + files → primary=php."""
    result = detect(php_repo)
    assert result.primary == "php"
    assert result.language == "php"
    assert "php" in result.languages_detected
    assert "python" not in result.languages_detected


def test_hybrid(py_repo: Path, hybrid_repo: Path) -> None:
    """Tier 2+3: Both languages detected → primary=python (tie-break)."""
    result = detect(hybrid_repo)
    assert "python" in result.languages_detected
    assert "php" in result.languages_detected
    # Tie-break prefers python
    assert result.primary == "python"


def test_empty_repo(tmp_path: Path) -> None:
    """Empty repo → falls back to python with low confidence."""
    result = detect(tmp_path)
    assert result.primary == "python"  # default tie-break


def test_override_file(override_repo: Path) -> None:
    """Tier 1: .quality-gate-lang overrides manifest detection."""
    result = detect(override_repo)
    assert result.primary == "python"
    assert result.confidence == 1.0


def test_cache_hit(py_repo: Path) -> None:
    """Cache exists and is fresh → returns cached Detection without recomputing."""
    # First call populates the cache
    detect(py_repo, force=False)
    cache_path = py_repo / "_quality-gate" / "detection.json"
    assert cache_path.exists()

    # Second call should return cached result
    result = detect(py_repo, force=False)
    # Cache file was created during first call, reuse is transparent
    assert result.primary == "python"

    # Force bypasses cache
    result_force = detect(py_repo, force=True)
    assert result_force.primary == result.primary


def test_mtime_invalidation(py_repo: Path) -> None:
    """When a manifest is modified after cache was written, cache is invalidated."""
    cache_path = py_repo / "_quality-gate" / "detection.json"
    _fingerprint_path = py_repo / "_quality-gate" / ".detection-fingerprint"

    # Create a fresh detection (populates cache)
    detect(py_repo, force=False)
    assert cache_path.exists()

    # Manually modify the manifest's mtime to be newer than cache
    pyproject = py_repo / "pyproject.toml"
    cache_path.touch()  # set cache mtime to now
    time.sleep(0.05)
    pyproject.touch()  # set manifest mtime after cache

    # Loading cache should return None due to mtime mismatch
    cached = _load_cache(py_repo)
    assert cached is None


def test_git_head_invalidation(py_repo: Path) -> None:
    """When git HEAD changes after cache was written, cache is invalidated."""
    fp_path = py_repo / "_quality-gate" / ".detection-fingerprint"

    # Create a git repo and detect (populates cache with HEAD sha)
    import subprocess
    subprocess.run(["git", "init"], cwd=str(py_repo), capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(py_repo), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(py_repo), capture_output=True, check=True,
    )
    (py_repo / "README.md").write_text("# test\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=str(py_repo), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=str(py_repo), capture_output=True, check=True,
    )
    detect(py_repo, force=False)

    # Stale HEAD stored in fingerprint
    assert fp_path.exists()
    _stored_head = fp_path.read_text(encoding="utf-8").strip()

    # Now stub _current_git_head to return a different sha
    with patch("harness_quality_gate.detector._current_git_head", return_value="fake-sha-diff"):
        cached = _load_cache(py_repo)
        assert cached is None  # HEAD changed, cache invalidated


def test_detection_model_structure() -> None:
    """The Detection model has the expected fields and primary alias."""
    det = build_detection(language="php", framework="laravel")
    assert det.language == "php"
    assert det.primary == "php"  # alias
    assert det.framework == "laravel"


def test_detect_nonexistent_repo(tmp_path: Path) -> None:
    """detect() still returns a Detection for non-existent dirs (resolves to existing parent)."""
    sub = tmp_path / "does-not-exist"
    result = detect(sub)
    assert result is not None
    assert isinstance(result.primary, str)
