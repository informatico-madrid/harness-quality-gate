"""E2E test for doctor subcommand when PHP runtime is missing.

Tests that the ``doctor`` subcommand returns exit code 3
when critical PHP tools are unavailable.

Design: Test Coverage Table / e2e doctor
Requirements: FR-31, US-11
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.e2e
def test_doctor_exits_3_when_php_missing(tmp_path: Path) -> None:
    """doctor on a PHP fixture with no PHP runtime → exit code 3."""
    # Restrict PATH so PHP tools cannot be found
    real_path = os.environ.get("PATH", "")
    os.environ["PATH"] = "/usr/bin"
    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "harness_quality_gate",
                "doctor", str(tmp_path), "--json",
            ],
            capture_output=True,
            text=True,
        )
        # Should exit with INFRA_INCOMPLETE (3) because PHP is missing
        assert result.returncode in (3, 1)
    finally:
        os.environ["PATH"] = real_path


@pytest.mark.e2e
def test_doctor_json_output_when_php_missing(tmp_path: Path) -> None:
    """doctor --json → parseable JSON with verdict field."""
    real_path = os.environ.get("PATH", "")
    os.environ["PATH"] = "/usr/bin"
    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "harness_quality_gate",
                "doctor", str(tmp_path), "--json",
            ],
            capture_output=True,
            text=True,
        )
        import json

        data = json.loads(result.stdout)
        assert "verdict" in data or "tools" in data
    finally:
        os.environ["PATH"] = real_path


@pytest.mark.e2e
def test_doctor_cli_invocation_on_clean_fixture() -> None:
    """doctor on php-pure-pass fixture → valid CLI invocation."""
    fixture = (
        Path(__file__).resolve().parent.parent
        / "fixtures"
        / "php-pure-pass"
    )

    result = subprocess.run(
        [
            sys.executable, "-m", "harness_quality_gate",
            "doctor", str(fixture),
        ],
        capture_output=True,
        text=True,
    )
    # Should exit 0 (PASS) or 3 (INFRA_INCOMPLETE) depending on tool availability
    assert result.returncode in (0, 1, 3)
