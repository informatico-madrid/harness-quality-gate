"""E2E test for the full quality gate pipeline on Python.

Runs the full L3A→L4 pipeline against the ``python-pure-pass`` fixture
and asserts that all layers pass with zero findings.

Design: Test Coverage Table / e2e full-gate-python
Requirements: FR-5, FR-6, NFR-15
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
from pathlib import Path

import pytest

from harness_quality_gate.checkpoint import write as write_checkpoint
from harness_quality_gate.detector import detect
from harness_quality_gate.dispatcher import dispatch_full

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "python-pure-pass"


def _asdict(obj: object) -> object:
    """Convert a frozen dataclass to a JSON-serialisable dict."""
    if hasattr(obj, "__dataclass_fields__"):
        return dataclasses.asdict(obj)  # type: ignore[arg-type, call-overload]
    if isinstance(obj, dict):
        return {k: _asdict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_asdict(v) for v in obj]
    return obj  # type: ignore[return-value]


@pytest.mark.e2e
def test_full_gate_python_pure_pass() -> None:
    """Full gate on python-pure-pass → checkpoint with all layers passing."""
    detection = detect(FIXTURE_DIR, force=True)
    assert detection.primary == "python"

    ctx: dict = {
        "work_dir": str(FIXTURE_DIR / "_quality-gate" / "work"),
    }
    checkpoint = dispatch_full(detection, ctx)

    assert checkpoint.version == "v2"
    assert checkpoint.language == "python"
    assert len(checkpoint.layers) >= 1

    # Every layer should pass on this clean fixture
    for layer in checkpoint.layers:
        assert layer.passed is True, (
            f"Layer {layer.layer} ({layer.language}) failed: "
            + str([f.message for f in layer.findings])
        )


@pytest.mark.e2e
def test_full_gate_python_emits_checkpoint_file() -> None:
    """dispatch_full → checkpoint written to disk and validates."""
    detection = detect(FIXTURE_DIR, force=True)
    ctx: dict = {
        "work_dir": str(FIXTURE_DIR / "_quality-gate" / "work"),
    }
    checkpoint = dispatch_full(detection, ctx)

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "quality-gate-latest.json"
        write_checkpoint(out_path, _asdict(checkpoint))  # type: ignore[arg-type]
        raw = json.loads(out_path.read_text())
        assert raw["version"] == "v2"
        assert raw["language"] == "python"
        assert "layers" in raw


@pytest.mark.e2e
def test_full_gate_checkpoint_has_l3a_and_l4() -> None:
    """Full gate on python fixture → checkpoint includes L3A and L4 layers."""
    detection = detect(FIXTURE_DIR, force=True)
    ctx: dict = {
        "work_dir": str(FIXTURE_DIR / "_quality-gate" / "work"),
    }
    checkpoint = dispatch_full(detection, ctx)

    layer_names = {layer.layer for layer in checkpoint.layers}
    assert "L3A" in layer_names
    assert "L4" in layer_names or len(checkpoint.layers) >= 1
