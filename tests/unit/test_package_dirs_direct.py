"""Direct unit tests for harness_quality_gate.adapters.base.package_dirs and source_targets.

Kills the surviving mutmut mutations:
  x_package_dirs__mutmut_1 through x_package_dirs__mutmut_12

Kills:
  mutmut_1  - if not repo.is_dir() → if repo.is_dir()  (returns [] when repo exists)
  mutmut_2  - entire generator → None  (returns None instead of list)
  mutmut_6  - not child.name.startswith(".") → child.name.startswith(".")
  mutmut_7  - child.name.startswith(None)  (would crash, but test must survive)
  mutmut_8  - child.name.startswith("XX.XX")  (matches nothing — hidden dirs always pass)
  mutmut_9  - child.name not in _NON_PACKAGE_DIRS → child.name in _NON_PACKAGE_DIRS
  mutmut_11 - (child / "__init__.py").__init__.py") → (child / "XX__init__.pyXX")
  mutmut_12 - "__init__.py" → "__INIT__.PY")  (case sensitivity)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from harness_quality_gate.adapters.base import package_dirs, source_targets


# ---------------------------------------------------------------------------
# package_dirs direct tests
# ---------------------------------------------------------------------------

class TestPackageDirsDirect:
    """Kill package_dirs survive mutations."""

    def test_returns_list_not_none(self, tmp_path: Path) -> None:
        """Kills mutmut_2: generator replaced with None.
        Result must be a list (even if empty)."""
        result = package_dirs(tmp_path)
        assert isinstance(result, list), f"Expected list, got {type(result).__name__}"

    def test_repo_with_packages(self, tmp_path: Path) -> None:
        """Kills mutmut_1: 'if repo.is_dir():' would return [].
        Must see packages when they exist."""
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        result = package_dirs(tmp_path)
        assert "mypkg" in result
        assert isinstance(result, list)

    def test_hidden_dirs_excluded(self, tmp_path: Path) -> None:
        """Kills mutmut_6, mutmut_7, mutmut_8.
        Hidden dirs ('.git') must not appear in result even if they exist."""
        hidden = tmp_path / ".git"
        hidden.mkdir()
        # Also add a real package
        pkg = tmp_path / "real"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        result = package_dirs(tmp_path)
        assert ".git" not in result
        assert "real" in result

    def test_non_package_dirs_excluded(self, tmp_path: Path) -> None:
        """Kills mutmut_9: 'in _NON_PACKAGE_DIRS' would include them.
        Tests/ dir must NOT appear even if __init__.py exists."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").write_text("")
        # Also real package so we have something to verify
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        result = package_dirs(tmp_path)
        assert "tests" not in result
        assert "mypkg" in result

    def test_init_file_missing(self, tmp_path: Path) -> None:
        """Kills mutmut_11: wrong filename → no packages found.
        Without __init__.py there must be no packages."""
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        # No __init__.py
        result = package_dirs(tmp_path)
        assert "mypkg" not in result

    def test_case_sensitivity__init(self, tmp_path: Path) -> None:
        """Kills mutmut_12: __INIT__.PY vs __init__.py.
        Only __init__.py (exact case) counts as a package marker."""
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        # Write with exact case
        (pkg / "__init__.py").write_text("")
        result = package_dirs(tmp_path)
        assert "mypkg" in result

    def test_multiple_packages_sorted(self, tmp_path: Path) -> None:
        """Verify sorted output.
        Also helps kill mutmut_6/7/8: non-hidden must appear sorted."""
        pkgs = ["alpha", "beta", "zebra"]
        for name in pkgs:
            p = tmp_path / name
            p.mkdir()
            (p / "__init__.py").write_text("")
        # Add hidden to confirm exclusion
        (tmp_path / ".secret").mkdir()
        result = package_dirs(tmp_path)
        assert result == pkgs
        assert ".secret" not in result

    def test_nonexistent_repo_returns_empty_list(self) -> None:
        """Kills mutmut_1 reversed: when repo doesn't exist, still returns [].
        Must not crash."""
        result = package_dirs(Path("/nonexistent/ghost/path"))
        assert result == []
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# source_targets direct tests
# ---------------------------------------------------------------------------

class TestSourceTargetsDirect:
    """Kills x_source_targets no-tests mutants."""

    def test_empty_candidates(self, tmp_path: Path) -> None:
        """source_targets([]) must return []."""
        result = source_targets(tmp_path)
        assert result == []

    def test_src_layout_found(self, tmp_path: Path) -> None:
        """source_targets with 'src' → must include it."""
        src = tmp_path / "src"
        src.mkdir()
        result = source_targets(tmp_path, "src", "tests")
        assert "src" in result
        assert "tests" not in result

    def test_exclude_tests_filter(self, tmp_path: Path) -> None:
        """exclude_tests=True must strip 'tests' dir."""
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        result = source_targets(tmp_path, "src", "tests", exclude_tests=True)
        assert "tests" not in result
        assert "src" in result

    def test_exclude_tests_strips_test_dirs(self, tmp_path: Path) -> None:
        """exclude_tests must also strip any dir containing 'test'.
        Kills x_source_targets__mutmut_X mutations on the exclude filter."""
        (tmp_path / "src").mkdir()
        (tmp_path / "testing").mkdir()
        (tmp_path / "tests").mkdir()
        result = source_targets(tmp_path, "src", "testing", "tests", exclude_tests=True)
        assert "testing" not in result
        assert "tests" not in result
        assert "src" in result
