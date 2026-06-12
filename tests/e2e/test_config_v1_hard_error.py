"""E2E: v1 config files are a hard error (exit 4 CONFIG_INVALID).

FR-34 is wired inside ``_cmd_all()``: a config file with a deprecated v1
schema aborts the gate before any layer runs.

Design: Test Coverage Table / e2e config-v1
Requirements: FR-34, NFR-15
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture()
def legacy_config_fixture() -> Path:
    """Return path to the legacy v1 config fixture."""
    return _REPO_ROOT / "tests" / "fixtures" / "legacy-config-v1"


def _run_all(repo: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness_quality_gate", "all", str(repo), *extra],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=120,
    )


@pytest.mark.e2e
def test_v1_config_hard_errors_with_exit_4(legacy_config_fixture: Path) -> None:
    """Running 'all' on a repo with a v1 config → exit 4, no layers run."""
    result = _run_all(legacy_config_fixture)
    assert result.returncode == 4, (
        f"Expected exit 4 (CONFIG_INVALID), got {result.returncode}. "
        f"stderr: {result.stderr[:500]}"
    )


@pytest.mark.e2e
def test_v1_config_json_payload(legacy_config_fixture: Path) -> None:
    """The error payload is machine-readable JSON with exit_code 4."""
    result = _run_all(legacy_config_fixture, "--json")
    assert result.returncode == 4
    data = json.loads(result.stdout)
    assert data["exit_code"] == 4
    assert "v1" in data["error"]


@pytest.mark.e2e
def test_v1_config_quiet_suppresses_output(legacy_config_fixture: Path) -> None:
    result = _run_all(legacy_config_fixture, "--quiet")
    assert result.returncode == 4
    assert result.stdout == ""
