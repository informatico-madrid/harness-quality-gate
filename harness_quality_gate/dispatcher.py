"""Language-aware layer routing.

Routes detected language to the correct adapter and orchestrates
per-layer execution (L3A/Tier-A AST, L1-L4, L3B/Tier-B BMAD).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .adapters.php.php_adapter import PhpAdapter
from .adapters.python.python_adapter import PythonAdapter
from .models import CheckpointV2, ConcurrencyPlan, Detection, LayerResult, MutationStats

# Language slug → adapter module name
_ROUTE_TABLE: Mapping[str, str] = {
    "php": "php_adapter",
    "python": "python_adapter",
}

# Layer id → BaseAdapter method name
_LAYER_METHOD: Mapping[str, str] = {
    "L1": "run_l1",
    "L2": "run_l2",
    "L3A": "run_l3a",
    "L3B": "run_l3b",
    "L4": "run_l4",
}

# Design doc (§2): run order per language
_LAYERS_SEQUENCE = ("L3A", "L1", "L2", "L3B", "L4")


def route(language: str) -> str | None:
    """Return the adapter module name for *language*, or ``None``.

    Example: ``route("php") -> "php_adapter"``.
    """
    return _ROUTE_TABLE.get(language)


def _build_adapter(language: str) -> PhpAdapter | PythonAdapter | None:
    if language == "php":
        return PhpAdapter()
    if language == "python":
        return PythonAdapter()
    return None


def run_layer(
    language: str,
    layer: str,
    repo: Path,
    work_dir: Path,
    env: Mapping,
) -> LayerResult:
    """Execute a single quality gate *layer* for *language*.

    L3A = Tier A (AST/static). L3B = Tier B (mutation/weak-test).
    Delegates to the language adapter when one is known; returns a passing
    stub for unsupported language/layer combinations.
    """
    adapter = _build_adapter(language)
    method_name = _LAYER_METHOD.get(layer)

    if adapter is not None and method_name is not None:
        return getattr(adapter, method_name)(repo, env)

    # Unsupported language or layer: return passing stub
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

    # Hybrid repos: PHP L3A takes precedence when PHP is present
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


def _extract_mutation_stats(layers: list[LayerResult]) -> MutationStats | None:
    """Extract MutationStats from L3B (Python) or L1 (PHP) tool_specific."""
    for lr in layers:
        if lr.tool_specific is None:
            continue
        # Python L3B: MutationStats stored directly
        if lr.layer == "L3B" and "mutation_stats" in lr.tool_specific:
            val = lr.tool_specific["mutation_stats"]
            if isinstance(val, MutationStats):
                return val
        # PHP L1: mutation stored as a plain dict
        if lr.layer == "L1" and "mutation" in lr.tool_specific:
            m = lr.tool_specific["mutation"]
            if isinstance(m, dict):
                killed = int(m.get("killed", 0))
                survived = int(m.get("survived", 0))
                timed_out = int(m.get("timed_out", 0))
                escaped = int(m.get("escaped", 0))
                untested = int(m.get("untested", 0))
                return MutationStats(
                    total=killed + survived + timed_out + escaped + untested,
                    killed=killed,
                    survived=survived,
                    timed_out=timed_out,
                    escaped=escaped,
                    untested=untested,
                    msi=float(m.get("msi", 0.0)),
                    covered_msi=float(m.get("covered_msi", 0.0)),
                )
    return None


def dispatch_full(detection: Detection, ctx: Mapping) -> CheckpointV2:
    """Run all layers (L3A→L1→L2→L3B→L4) and emit a Checkpoint v2.

    For hybrid repos where PHP is a secondary language, PHP L3A is appended
    after the primary language's full layer sequence.

    Only string-valued entries in *ctx* are forwarded as the env mapping to
    adapters; non-string values (e.g. ConcurrencyPlan) are silently excluded.
    Adapter exceptions are caught and surfaced as INTERNAL_ERROR findings so
    a single broken tool cannot abort the entire gate run.
    """
    repo = Path(detection.repo_path)
    primary_language = detection.language
    # Forward only string-typed context values as env (adapters expect Mapping[str, str])
    env: dict[str, str] = {k: v for k, v in ctx.items() if isinstance(v, str)}
    layers: list[LayerResult] = []

    adapter = _build_adapter(primary_language)
    if adapter is not None:
        for layer in _LAYERS_SEQUENCE:
            method = getattr(adapter, _LAYER_METHOD[layer])
            try:
                layers.append(method(repo, env))
            except Exception as exc:  # noqa: BLE001
                layers.append(LayerResult(
                    layer=layer,
                    language=primary_language,
                    passed=False,
                    findings=[],
                    duration_sec=0.0,
                    tool_specific={"error": str(exc)},
                ))

    # Hybrid: also run PHP L3A when PHP is a secondary language
    if primary_language != "php" and "php" in detection.languages_detected:
        try:
            layers.append(PhpAdapter().run_l3a(repo, env))
        except Exception as exc:  # noqa: BLE001
            layers.append(LayerResult(
                layer="L3A",
                language="php",
                passed=False,
                findings=[],
                duration_sec=0.0,
                tool_specific={"error": str(exc)},
            ))

    return CheckpointV2(
        version="v2",
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        repository=detection.repo_path,
        language=primary_language,
        layers=layers,
        mutation=_extract_mutation_stats(layers),
    )
