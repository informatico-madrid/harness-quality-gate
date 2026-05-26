"""Language-aware layer routing skeleton.

Routes detected language to the correct adapter module and orchestrates
per-layer execution (L3A/Tier-A AST, L1-L4, L3B/Tier-B BMAD).
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .models import CheckpointV2, ConcurrencyPlan, Detection, LayerResult

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


def dispatch(
    detection: Detection,
    layer: str,
    concurrency_plan: ConcurrencyPlan,
    ctx: Mapping,
) -> LayerResult:
    """Run one quality-gate layer for the detected language.

    Stub: delegates to ``run_layer`` with the detected language.
    """
    return run_layer(
        language=detection.language,
        layer=layer,
        repo=Path(detection.repo_path),
        work_dir=Path(ctx.get("work_dir", "/tmp")),
        env=ctx,
    )


def dispatch_full(detection: Detection, ctx: Mapping) -> CheckpointV2:
    """Run all layers and emit a Checkpoint v2 summary.

    Stub: returns a checkpoint with one passing L3A layer.
    """
    return CheckpointV2(
        version="2.0.0",
        timestamp="",
        repository=detection.repo_path,  # type: ignore[attr-defined]
        language=detection.language,  # type: ignore[attr-defined]
        layers=[
            run_layer(
                language=detection.language,  # type: ignore[attr-defined]
                layer="L3A",
                repo=Path(detection.repo_path),  # type: ignore[attr-defined]
                work_dir=Path(ctx.get("work_dir", "/tmp")),
                env=ctx,
            )
        ],
        mutation=None,
    )
