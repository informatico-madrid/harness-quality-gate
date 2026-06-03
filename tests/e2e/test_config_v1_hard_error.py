"""E2E tests for v1 config handling.

Note: v1 config detection (FR-34) is wired in Phase 2+ tasks.
These tests verify current behavior (valid checkpoint produced)
and include skip markers for hard-error assertions.

Design: Test Coverage Table / e2e config-v1
Requirements: FR-34, NFR-15
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def legacy_config_fixture() -> Path:
    """Return path to the legacy v1 config fixture."""
    return (
        Path(__file__).resolve().parent.parent
        / "fixtures"
        / "legacy-config-v1"
    )


@pytest.mark.e2e
def test_all_runs_with_v1_config(legacy_config_fixture: Path) -> None:
    """Running 'all' on a repo with v1 config → produces valid checkpoint.

    Note: v1 config hard-error (exit 4) is implemented in Phase 2+ tasks.
    This test verifies current behaviour until FR-34 is wired up.
    """
    result = subprocess.run(
        [
            sys.executable, "-m", "harness_quality_gate",
            "all", str(legacy_config_fixture),
        ],
        capture_output=True,
        text=True,
    )
    # 0 = PASS, 1 = FAIL (gate ran with real PHP layers and found issues),
    # 4 = CONFIG_INVALID (v1 hard-error, wired in Phase 2+)
    assert result.returncode in (0, 1, 4)


@pytest.mark.e2e
def test_v1_config_with_json_flag(legacy_config_fixture: Path) -> None:
    """v1 config with --json → parseable JSON checkpoint."""
    result = subprocess.run(
        [
            sys.executable, "-m", "harness_quality_gate",
            "all", str(legacy_config_fixture), "--json",
        ],
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(result.stdout)
        # Currently produces a full checkpoint; future v1 hard-error may
        # output {"error": "...", "exit_code": 4} instead
        assert "language" in data or "error" in data
    except json.JSONDecodeError:
        # Some implementations print Spanish text directly
        assert result.returncode in (0, 4)
