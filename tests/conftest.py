"""Shared test fixtures for harness-quality-gate.

Provides PATH stubbing, HTTP responses cleanup, tmp_path git-init helper.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
import pytest


@pytest.fixture()
def patch_path(tmp_path: Path):  # type: ignore[return]
    """Return a temporary directory that is prepended to PATH for the test.

    Tools resolved via shutil.which will find stubs inside this directory
    before the system PATH, allowing safe mocking of external binaries.
    """
    original = os.environ.get("PATH", "")
    patch = tmp_path / "path_override"
    patch.mkdir(exist_ok=True)
    os.environ["PATH"] = str(patch) + os.pathsep + original
    try:
        yield patch
    finally:
        os.environ["PATH"] = original


@pytest.fixture()
def tmp_git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repository inside tmp_path and return its path.

    Initialises git, sets a dummy user, and creates an initial commit so
    that the detector / installer components that inspect the git working
    tree do not fail with ``NotGitError``.
    """
    subprocess.run(
        ["git", "init"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    # Create an initial commit
    (tmp_path / "README.md").write_text("# Test", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    return tmp_path


@pytest.fixture()
def isolated_tmpdir():  # type: ignore[return]
    """Create a unique temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
