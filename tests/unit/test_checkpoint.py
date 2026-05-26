"""Unit tests for checkpoint v2 builder + writer.

Covers build(), JSON Schema validation, and rejection on validation failure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import jsonschema

from harness_quality_gate.checkpoint import build, validate, write
from tests.factories import build_layer_result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def good_detection() -> dict:
    return {
        "repo_path": "/tmp/test",
        "language": "python",
        "framework": None,
        "confidence": 0.95,
    }


@pytest.fixture()
def layer_dicts() -> list[dict]:
    return [
        build_layer_result(layer="L3A", language="python", passed=True).__dict__,
        build_layer_result(layer="L1", language="python", passed=True).__dict__,
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_build_basic(good_detection: dict) -> None:
    """build() produces a dict with required top-level keys."""
    result = build([], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    assert result["version"] == "v2"
    assert result["repository"] == "/tmp/test"
    assert result["language"] == "python"
    assert isinstance(result["layers"], list)


def test_build_with_layers(good_detection: dict, layer_dicts: list[dict]) -> None:
    """build() includes layer result entries."""
    runtime = {"python_version": "3.12", "concurrency": "auto", "ci": False}
    result = build(layer_dicts, runtime, good_detection)
    assert len(result["layers"]) == 2
    assert result["layers"][0]["layer"] == "L3A"
    assert result["layers"][0]["passed"] is True


def test_build_validates_through_schema(good_detection: dict) -> None:
    """build() output passes JSON Schema validation."""
    data = build([], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    validate(data)  # should not raise


def test_build_rejects_invalid_schema() -> None:
    """validate() raises ValidationError for missing required fields."""
    invalid_data: dict = {"version": "v2"}  # missing repository, language, layers
    with pytest.raises(jsonschema.ValidationError):
        validate(invalid_data)


def test_write_creates_file(good_detection: dict, tmp_path: Path) -> None:
    """write() creates the checkpoint file at the target path."""
    data = build([], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    target = tmp_path / "checkpoint.json"
    write(target, data)
    assert target.exists()
    # File is valid JSON
    json.loads(target.read_text(encoding="utf-8"))


def test_write_timestamped_copy(good_detection: dict, tmp_path: Path) -> None:
    """write() creates a timestamped copy when basename is quality-gate-latest.json."""
    data = build([], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    target = tmp_path / "quality-gate-latest.json"
    write(target, data)
    assert target.exists()
    # Timestamped copies should also exist
    children = list(tmp_path.glob("quality-gate-*.json"))
    assert len(children) >= 2  # latest + at least one timestamped
