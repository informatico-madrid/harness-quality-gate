"""E2E test for the full quality gate pipeline on PHP.

Runs the full L3A→L4 pipeline against the ``symfony-mini`` fixture
and asserts that the detection + dispatch path works end-to-end.

Requires PHP tools (phpstan, phpmd, php-cs-fixer) installed on PATH.
Skipped when ``needs-php`` marker is filtered out.

Design: Test Coverage Table / e2e full-gate-php
Requirements: FR-6, FR-22, NFR-15
"""

from __future__ import annotations

import dataclasses
import shutil
import tempfile
from pathlib import Path

import pytest

from harness_quality_gate.checkpoint import write as write_checkpoint
from harness_quality_gate.detector import detect

FIXTURE_DIR = (
    Path(__file__).resolve().parent / "repos" / "symfony-mini"
)

# Fixture also available as the php-pure-pass fixture
PHP_PURE_PASS = Path(__file__).resolve().parent.parent / "fixtures" / "php-pure-pass"


def _php_tools_available() -> bool:
    """Return True if all three L3A PHP tools are on PATH."""
    return all(
        shutil.which(t) is not None for t in ("phpstan", "phpmd", "php-cs-fixer")
    )


@pytest.mark.e2e
@pytest.mark.needs_php
def test_full_gate_php_detects_symfony() -> None:
    """symfony-mini fixture → detected language='php', framework='symfony'."""
    if not _php_tools_available():
        pytest.skip("PHP tools not on PATH")

    detection = detect(FIXTURE_DIR, force=True)
    assert detection.primary == "php"
    assert "symfony" in detection.frameworks


@pytest.mark.e2e
@pytest.mark.needs_php
def test_full_gate_php_emits_valid_checkpoint() -> None:
    """dispatch_full on symfony-mini → valid checkpoint v2."""
    if not _php_tools_available():
        pytest.skip("PHP tools not on PATH")

    from harness_quality_gate.dispatcher import dispatch_full

    detection = detect(FIXTURE_DIR, force=True)
    ctx: dict = {
        "work_dir": str(FIXTURE_DIR / "_quality-gate" / "work"),
    }
    checkpoint = dispatch_full(detection, ctx)

    assert checkpoint.version == "v2"
    assert checkpoint.language == "php"
    assert len(checkpoint.layers) >= 1


@pytest.mark.e2e
@pytest.mark.needs_php
def test_full_gate_php_checkpoint_file_written() -> None:
    """dispatch_full → checkpoint written to disk and valid."""
    if not _php_tools_available():
        pytest.skip("PHP tools not on PATH")

    from harness_quality_gate.dispatcher import dispatch_full

    detection = detect(FIXTURE_DIR, force=True)
    ctx: dict = {
        "work_dir": str(FIXTURE_DIR / "_quality-gate" / "work"),
    }
    checkpoint = dispatch_full(detection, ctx)

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "quality-gate-latest.json"
        write_checkpoint(out_path, dataclasses.asdict(checkpoint))
        import json

        raw = json.loads(out_path.read_text())
        assert raw["version"] == "v2"
        assert raw["language"] == "php"
