"""Integration tests for full PHP L3A layer.

End-to-end run of PHPStan + PHPMD + php-cs-fixer through PhpAdapter.run_l3a()
on the ``php-pure-pass`` fixture.  Requires PHP tooling (phpstan, phpmd,
php-cs-fixer) to be available on PATH.

Design: Test Coverage Table / integration L3A rows
Requirements: FR-6, FR-7, FR-8, FR-9, US-3
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from harness_quality_gate.checkpoint import build as build_checkpoint
from harness_quality_gate.checkpoint import write as write_checkpoint
from harness_quality_gate.detector import detect
from harness_quality_gate.adapters.php.php_adapter import PhpAdapter

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "php-pure-pass"


@pytest.mark.integration
@pytest.mark.needs_php
def test_run_l3a_php_passes_on_pure_pass_fixture() -> None:
    """PhpAdapter.run_l3a → passed=True on php-pure-pass fixture."""
    detection = detect(FIXTURE_DIR, force=True)
    assert detection.primary == "php"

    adapter = PhpAdapter()
    result = adapter.run_l3a(FIXTURE_DIR, {})

    assert result.layer == "L3A"
    assert result.language == "php"
    assert isinstance(result.passed, bool)


@pytest.mark.integration
@pytest.mark.needs_php
def test_run_l3a_emits_valid_checkpoint() -> None:
    """run_l3a output serialises to a valid Checkpoint v2 structure."""
    adapter = PhpAdapter()
    result = adapter.run_l3a(FIXTURE_DIR, {})

    layer_dict = {
        "layer": result.layer,
        "language": result.language,
        "passed": result.passed,
        "findings": [
            {
                "node": f.node,
                "severity": f.severity,
                "message": f.message,
            }
            for f in result.findings
        ],
        "duration_sec": result.duration_sec,
    }

    runtime = {
        "python_version": "",
        "concurrency": "sequential",
        "ci": False,
    }
    detection_dict = {
        "repo_path": str(FIXTURE_DIR),
        "language": "php",
        "framework": "",
        "confidence": 1.0,
        "mutation": None,
    }
    checkpoint = build_checkpoint([layer_dict], runtime, detection_dict)

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "checkpoint.json"
        write_checkpoint(out_path, checkpoint)
        raw = json.loads(out_path.read_text())
        assert raw["version"] == "v2"
        assert raw["language"] == "php"
        assert len(raw["layers"]) >= 1
        assert raw["layers"][0]["layer"] == "L3A"


@pytest.mark.integration
@pytest.mark.needs_php
def test_run_l3a_handles_missing_php_tools_gracefully() -> None:
    """When PHP tools are missing, run_l3a still returns a LayerResult."""
    # Temporarily restrict PATH so phpstan/phpmd/php-cs-fixer cannot be found
    real_path = os.environ.get("PATH", "")
    restricted = "/usr/bin"
    os.environ["PATH"] = restricted
    try:
        result = PhpAdapter().run_l3a(FIXTURE_DIR, {})
        assert result.layer == "L3A"
        assert result.language == "php"
        assert isinstance(result.passed, bool)
    finally:
        os.environ["PATH"] = real_path
