"""Integration tests for hybrid language dispatch.

Verifies that ``dispatch_full`` correctly routes both Python and PHP repos
through their respective adapters and that the checkpoint captures per-language
results.

Design: Test Coverage Table / integration hybrid rows
Requirements: FR-4, FR-5, FR-6, US-10
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_quality_gate.detector import detect
from harness_quality_gate.dispatcher import dispatch_full
from harness_quality_gate.concurrency import resolve

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.mark.integration
def test_hybrid_repo_detected() -> None:
    """hybrid-py-php fixture → primary='python' + 'php' in languages_detected."""
    repo = FIXTURE_DIR / "hybrid-py-php"
    detection = detect(repo, force=True)

    assert detection.primary == "python"
    assert "php" in detection.languages_detected
    assert "python" in detection.languages_detected


@pytest.mark.integration
def test_hybrid_dispatch_completes() -> None:
    """dispatch_full on hybrid repo → CheckpointV2 with layers."""
    repo = FIXTURE_DIR / "hybrid-py-php"
    detection = detect(repo, force=True)
    ctx: dict = {
        "work_dir": str(repo / "_quality-gate" / "work"),
        "concurrency": resolve("sequential", {}),
    }
    checkpoint = dispatch_full(detection, ctx)

    assert checkpoint.version == "v2"
    assert checkpoint.language == "python"
    assert len(checkpoint.layers) >= 1


@pytest.mark.integration
def test_python_adapter_l3a_completes() -> None:
    """PythonAdapter.run_l3a on python-pure-pass → passing result."""
    from harness_quality_gate.adapters.python.python_adapter import (
        PythonAdapter,
    )

    repo = FIXTURE_DIR / "python-pure-pass"
    adapter = PythonAdapter()
    result = adapter.run_l3a(repo, {})

    assert result.layer == "L3A"
    assert result.language == "python"


@pytest.mark.integration
def test_python_adapter_passes_on_clean_fixture() -> None:
    """PythonAdapter.run_l3a on python-pure-pass → passed=True."""
    from harness_quality_gate.adapters.python.python_adapter import (
        PythonAdapter,
    )

    repo = FIXTURE_DIR / "python-pure-pass"
    adapter = PythonAdapter()
    result = adapter.run_l3a(repo, {})

    assert result.passed is True
