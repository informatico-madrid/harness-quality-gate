"""Integration tests for checkpoint schema validation.

Ensures that checkpoint builder output conforms to
``references/verdict-schema.json``.

Design: Test Coverage Table / integration schema rows
Requirements: FR-24, NFR-16, US-10
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_quality_gate.checkpoint import build as build_checkpoint
from harness_quality_gate.checkpoint import validate

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.mark.integration
def test_builder_emits_schema_compliant_dict() -> None:
    """build() output passes jsonschema.validate against the schema."""
    layer_dict = {
        "layer": "L3A",
        "language": "php",
        "passed": True,
        "findings": [],
        "duration_sec": 0.5,
    }
    runtime = {"python_version": "3.12", "concurrency": "sequential", "ci": False}
    detection = {
        "repo_path": "/tmp/test-repo",
        "language": "php",
        "framework": "",
        "confidence": 1.0,
        "mutation": None,
    }
    checkpoint = build_checkpoint([layer_dict], runtime, detection)

    # Should not raise
    validate(checkpoint)
    assert checkpoint["version"] == "v2"
    assert checkpoint["language"] == "php"


@pytest.mark.integration
def test_builder_with_mutation_data() -> None:
    """build() with mutation stats → valid checkpoint."""
    layer_dict = {
        "layer": "L1",
        "language": "php",
        "passed": True,
        "findings": [],
        "duration_sec": 1.2,
    }
    runtime = {"python_version": "3.12", "concurrency": "sequential", "ci": False}
    detection = {
        "repo_path": "/tmp/test-repo",
        "language": "php",
        "framework": "",
        "confidence": 1.0,
        "mutation": {
            "msi": 100.0,
            "covered_msi": 100.0,
            "total": 10,
            "killed": 10,
            "survived": 0,
            "escaped": 0,
            "timed_out": 0,
            "untested": 0,
        },
    }
    checkpoint = build_checkpoint([layer_dict], runtime, detection)

    validate(checkpoint)
    assert checkpoint["mutation"]["msi"] == 100.0


@pytest.mark.integration
def test_builder_python_checkpoint() -> None:
    """build() with language='python' → valid checkpoint."""
    layer_dict = {
        "layer": "L3A",
        "language": "python",
        "passed": True,
        "findings": [],
        "duration_sec": 0.3,
    }
    runtime = {"python_version": "3.12", "concurrency": "parallel", "ci": True}
    detection = {
        "repo_path": "/tmp/py-repo",
        "language": "python",
        "framework": "fastapi",
        "confidence": 0.95,
        "mutation": None,
    }
    checkpoint = build_checkpoint([layer_dict], runtime, detection)

    validate(checkpoint)
    assert checkpoint["language"] == "python"


@pytest.mark.integration
def test_schema_version_field() -> None:
    """The checkpoint must include a version field."""
    layer_dict = {
        "layer": "L3A",
        "language": "php",
        "passed": True,
        "findings": [],
        "duration_sec": 0.1,
    }
    detection = {
        "repo_path": "/tmp/test",
        "language": "php",
        "framework": "",
        "confidence": 1.0,
        "mutation": None,
    }
    checkpoint = build_checkpoint(
        [layer_dict],
        {"python_version": "", "concurrency": "auto", "ci": False},
        detection,
    )

    assert "version" in checkpoint
    assert checkpoint["version"] == "v2"


@pytest.mark.integration
def test_schema_layers_field() -> None:
    """The checkpoint must include a layers array."""
    layer_dict = {
        "layer": "L1",
        "language": "php",
        "passed": False,
        "findings": [{"node": "x.php", "severity": "error", "message": "test"}],
        "duration_sec": 2.0,
    }
    detection = {
        "repo_path": "/tmp/test",
        "language": "php",
        "framework": "",
        "confidence": 1.0,
        "mutation": None,
    }
    checkpoint = build_checkpoint(
        [layer_dict],
        {"python_version": "", "concurrency": "auto", "ci": False},
        detection,
    )

    assert "layers" in checkpoint
    assert len(checkpoint["layers"]) == 1
    assert checkpoint["layers"][0]["layer"] == "L1"
