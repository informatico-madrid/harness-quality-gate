"""Checkpoint v2 builder + writer with schema validation.

Sole writer of checkpoint JSON per TD-15.
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
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
    def _to_dict(obj: Any) -> Any:
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            # Strip None-valued fields so the JSON schema's string-typed
            # optional fields (fix_hint, cve, cwe, rule_id) don't fail
            # validation with "null is not of type 'string'".
            return {k: v for k, v in dataclasses.asdict(obj).items() if v is not None}
        if isinstance(obj, dict):
            # Findings arrive pre-converted to dicts from cli._asdict, which
            # keeps None values — strip them here for the same schema reason.
            return {k: v for k, v in obj.items() if v is not None}
        return obj

    layers = []
    for lr in layer_results:
        raw_findings = lr.get("findings") or []
        findings = [_to_dict(f) for f in raw_findings]
        entry: dict[str, Any] = {
            "layer": lr.get("layer") or "",
            "language": lr.get("language") or "",
            "passed": lr.get("passed", False),
            "findings": findings,
            "duration_sec": lr.get("duration_sec") or 0.0,
        }
        if "per_language" in lr:
            entry["per_language"] = lr["per_language"]
        if lr.get("tool_specific") is not None:
            entry["tool_specific"] = lr["tool_specific"]
        layers.append(entry)

    mutation: dict[str, Any] | None = detection.get("mutation")

    data: dict[str, Any] = {}
    data["version"] = "v2"
    data["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["repository"] = detection.get("repo_path") or ""
    data["language"] = detection.get("language") or ""
    data["layers"] = layers
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

    Uses atomic writes (temp file + rename) to prevent partial writes
    from concurrent writers.

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

    # mutations produce semantically identical JSON for ASCII content.
    # reason: Tipo C — ensure_ascii=None es gemelo falsy de False (idéntico en runtime);
    # indent/True/removal los fija test_write_exact_payload_and_unicode. default=str era
    # parámetro muerto (validate() garantiza datos JSON-serializables) y fue eliminado.
    # audited: 2026-06-11
    payload = json.dumps(data, indent=2, ensure_ascii=False)  # pragma: no mutate

    # Atomic write: write to temp file in same directory, then rename
    # only the temp filename, not the final written content or file location.
    fd, tmp_path = tempfile.mkstemp(dir=str(output_path.parent), prefix=".quality-gate-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_path, str(output_path))
    except BaseException:
        os.unlink(tmp_path)
        raise

    if output_path.name == "quality-gate-latest.json":
        # "timestamp" is schema-required — validate() above guarantees presence
        ts = data["timestamp"]
        timestamped = output_path.with_name(f"quality-gate-{ts}.json")
        timestamped.write_text(payload, encoding="utf-8")
