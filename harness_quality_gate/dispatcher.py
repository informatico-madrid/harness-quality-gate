"""Language-aware layer routing skeleton.

Routes detected language to the correct adapter module and orchestrates
per-layer execution (L3A/Tier-A AST, L1-L4, L3B/Tier-B BMAD).
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .models import Finding, LayerResult

# Layer mapping: language slug -> adapter module name
_ROUTE_TABLE: Mapping[str, str] = {
    "php": "php_adapter",
    "python": "python_adapter",
}


def route(language: str) -> str | None:
    """Return the adapter module name for *language*, or ``None``.

    Example: ``route("php") -> "php_adapter"``.
    """
    return _ROUTE_TABLE.get(language)


def run_layer(
    language: str,
    layer: str,
    repo: Path,
    work_dir: Path,
    env: Mapping,
) -> LayerResult:
    """Execute a single quality gate *layer* for *language*.

    L3A = Tier A (AST). L3B = Tier B (BMAD).

    Returns a ``LayerResult`` summarising pass/fail and any findings.
    """
    return LayerResult(
        layer=layer,
        language=language,
        passed=True,
        findings=[],
        duration_sec=0.0,
    )
