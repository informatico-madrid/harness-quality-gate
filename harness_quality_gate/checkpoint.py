"""Checkpoint v2 builder + writer with schema validation.

Sole writer of checkpoint JSON per TD-15.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema


def build(
    layer_results: list[dict[str, Any]],
    runtime: dict[str, Any],
    detection: dict[str, Any],
) -> dict[str, Any]:
    """Build a CheckpointV2 dict matching the v2 schema.

    Parameters
    ----------
    layer_results:
        List of layer result dicts (each with keys: layer, language, passed,
        findings, duration_sec — matching LayerResult shape).
    runtime:
        Runtime info dict (python_version, concurrency, ci).
    detection:
        Detection info dict (repo_path, language, framework, confidence,
        languages_detected, frameworks, file_counts).

    Returns
    -------
    dict
        CheckpointV2-shaped dict ready for schema validation + serialization.
    """
    layers = []
    for lr in layer_results:
        entry: dict[str, Any] = {
            "layer": lr.get("layer", ""),
            "language": lr.get("language", ""),
            "passed": lr.get("passed", False),
            "findings": lr.get("findings", []),
            "duration_sec": lr.get("duration_sec", 0.0),
        }
        if "per_language" in lr:
            entry["per_language"] = lr["per_language"]
        layers.append(entry)

    mutation: dict[str, Any] | None = detection.get("mutation")

    data: dict[str, Any] = {
        "version": "v2",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repository": detection.get("repo_path", ""),
        "language": detection.get("language", ""),
        "layers": layers,
    }
    if mutation is not None:
        data["mutation"] = mutation

    return data


def validate(data: dict[str, Any]) -> None:
    """Validate *data* against references/verdict-schema.json.

    Raises
    ------
    jsonschema.ValidationError
        If the data does not conform to the schema.
    """
    schema_path = Path(__file__).resolve().parent.parent / "references" / "verdict-schema.json"
    with schema_path.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    jsonschema.validate(instance=data, schema=schema)


def write(path: str | Path, data: dict[str, Any]) -> None:
    """Write checkpoint data to *path*, validating first.

    Parameters
    ----------
    path:
        Target file path. If the path basename is ``quality-gate-latest.json``,
        also write a timestamped copy alongside it.
    data:
        CheckpointV2-shaped dict.

    Raises
    ------
    jsonschema.ValidationError
        If validation fails.
    """
    validate(data)

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps(data, indent=2, default=str, ensure_ascii=False)
    output_path.write_text(payload, encoding="utf-8")

    if output_path.name == "quality-gate-latest.json":
        ts = data.get("timestamp", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        timestamped = output_path.with_name(f"quality-gate-{ts}.json")
        timestamped.write_text(payload, encoding="utf-8")
