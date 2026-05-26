"""Language-aware layer routing skeleton.

Routes detected language to the correct adapter module and orchestrates
per-layer execution (L3A/Tier-A AST, L1-L4, L3B/Tier-B BMAD).
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .adapters.php.php_adapter import PhpAdapter
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
    if language == "php" and layer == "L3A":
        return PhpAdapter().run_l3a(repo, env)

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

    For the L3A layer, runs PHP L3A first when the repo contains PHP
    (either as primary language or in a hybrid multi-language detection).
    """
    repo = Path(detection.repo_path)
    work_dir = Path(ctx.get("work_dir", "/tmp"))

    # Hybrid repos: run PHP L3A first if PHP is present
    if layer == "L3A" and detection.primary == "php":
        return PhpAdapter().run_l3a(repo, ctx)

    if layer == "L3A" and "php" in detection.languages_detected:
        return PhpAdapter().run_l3a(repo, ctx)

    return run_layer(
        language=detection.language,
        layer=layer,
        repo=repo,
        work_dir=work_dir,
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
