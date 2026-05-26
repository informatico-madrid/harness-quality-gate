"""Checkpoint v2 writer — serializes CheckpointV2 dataclass to JSON.

Writes to `<repo>/_quality-gate/checkpoint.json` when `output` is None.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def _find_repo(path: Path) -> Path:
    """Walk up from *path* to the repo root (contains harness_quality_gate/)."""
    current = path.resolve()
    candidate = current
    while candidate != candidate.parent:
        if (candidate / "harness_quality_gate").is_dir():
            return candidate
        candidate = candidate.parent
    return current


def _dataclass_to_dict(obj: Any) -> Any:
    """Recursively serialize a dataclass tree to a plain dict."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _dataclass_to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_dataclass_to_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _dataclass_to_dict(v) for k, v in obj.items()}
    return obj


def write_checkpoint(result: Any, output: str | None = None) -> None:
    """Write *result* (a CheckpointV2 dataclass) as JSON to disk.

    Parameters
    ----------
    result:
        A :class:`~harness_quality_gate.models.CheckpointV2` instance.
    output:
        Absolute or relative file path.  When *None* the default
        location is ``<repo>/_quality-gate/checkpoint.json``.
    """
    if output is None:
        repo = _find_repo(Path.cwd())
        qg = repo / "_quality-gate"
        qg.mkdir(parents=True, exist_ok=True)
        output = str(qg / "checkpoint.json")

    payload: dict[str, Any] = _dataclass_to_dict(result)

    with open(output, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str, ensure_ascii=False)
