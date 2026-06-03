"""Unit tests for the language-aware dispatcher.

Covers php-only routing, hybrid repos, and zero-tool edge cases
per Coverage Table and FR-41 / FR-42.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness_quality_gate.dispatcher import dispatch, route, run_layer
from tests.factories import build_detection, build_layer_result


# ---------------------------------------------------------------------------
# Tests per Coverage Table
# ---------------------------------------------------------------------------


def test_route_php() -> None:
    """php language → php_adapter module."""
    assert route("php") == "php_adapter"


def test_route_python() -> None:
    """python language → python_adapter module."""
    assert route("python") == "python_adapter"


def test_route_unknown() -> None:
    """Unknown language → None."""
    assert route("rust") is None


def test_run_layer_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """python+L3A → delegates to PythonAdapter.run_l3a."""
    mock_adapter = MagicMock()
    mock_adapter.run_l3a.return_value = build_layer_result(
        layer="L3A", language="python", passed=True
    )
    monkeypatch.setattr(
        "harness_quality_gate.dispatcher.PythonAdapter", lambda: mock_adapter
    )
    result = run_layer(
        language="python",
        layer="L3A",
        repo=Path("/tmp"),
        work_dir=Path("/tmp/work"),
        env={},
    )
    assert result.passed is True
    mock_adapter.run_l3a.assert_called_once()


def test_run_layer_unknown_language() -> None:
    """Unknown language → stub LayerResult with passed=True."""
    result = run_layer(
        language="rust",
        layer="L3A",
        repo=Path("/tmp"),
        work_dir=Path("/tmp/work"),
        env={},
    )
    assert result.passed is True
    assert result.findings == []
    assert result.duration_sec == 0.0


def test_run_layer_php_l3a(monkeypatch: pytest.MonkeyPatch) -> None:
    """PHP L3A delegates to PhpAdapter."""
    mock_adapter = MagicMock()
    mock_adapter.run_l3a.return_value = build_layer_result(
        layer="L3A", language="php", passed=True
    )
    monkeypatch.setattr(
        "harness_quality_gate.dispatcher.PhpAdapter", lambda: mock_adapter
    )
    result = run_layer(
        language="php",
        layer="L3A",
        repo=Path("/tmp"),
        work_dir=Path("/tmp/work"),
        env={},
    )
    assert result.passed is True


def test_dispatch_php_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    """PHP as primary language → PhpAdapter.run_l3a."""
    mock_adapter = MagicMock()
    mock_adapter.run_l3a.return_value = build_layer_result(
        layer="L3A", language="php", passed=True
    )
    monkeypatch.setattr(
        "harness_quality_gate.dispatcher.PhpAdapter", lambda: mock_adapter
    )
    det = build_detection(language="php", framework="symfony")
    result = dispatch(
        detection=det,
        layer="L3A",
        concurrency_plan=MagicMock(),
        ctx={},
    )
    assert result.passed is True


def test_dispatch_hybrid_l3a(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hybrid repo with PHP present → PhpAdapter.run_l3a."""
    mock_adapter = MagicMock()
    mock_adapter.run_l3a.return_value = build_layer_result(
        layer="L3A", language="php", passed=False
    )
    monkeypatch.setattr(
        "harness_quality_gate.dispatcher.PhpAdapter", lambda: mock_adapter
    )
    det = build_detection(
        language="python",
        languages_detected=["python", "php"],
    )
    result = dispatch(
        detection=det,
        layer="L3A",
        concurrency_plan=MagicMock(),
        ctx={},
    )
    assert result.passed is False
