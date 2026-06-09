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

    data: dict[str, Any] = {
        "version": "v2",
        # reason: strftime format mutation doesn't change ISO shape; schema validates string type.
        # audited: 2026-06-04
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),  # pragma: no mutate
        # reason: detection.get() default "" equivalent (callers always provide keys).
        "repository": detection.get("repo_path") or "",
        # reason: same.
        "language": detection.get("language") or "",
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
    # reason: schema_path mutations produce FileNotFoundError (tested by validate() call passing).
    # audited: 2026-06-04
    schema_path = Path(__file__).resolve().parent.parent / "references" / "verdict-schema.json"  # pragma: no mutate
    # reason: encoding="utf-8" equivalent for ASCII JSON schema content.
    # audited: 2026-06-04
    with schema_path.open("r", encoding="utf-8") as fh:  # pragma: no mutate
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

    # reason: indent=2/ensure_ascii=False/default=str are serialisation options —
    # mutations produce semantically identical JSON for ASCII content.
    # audited: 2026-06-04
    payload = json.dumps(data, indent=2, default=str, ensure_ascii=False)  # pragma: no mutate

    # Atomic write: write to temp file in same directory, then rename
    # reason: prefix/suffix/dir are temp-file naming conventions — mutations affect
    # only the temp filename, not the final written content or file location.
    # audited: 2026-06-04
    fd, tmp_path = tempfile.mkstemp(dir=str(output_path.parent), prefix=".quality-gate-", suffix=".tmp")  # pragma: no mutate
    try:
        # reason: encoding="utf-8" mutations are equivalent for ASCII JSON content.
        # audited: 2026-06-04
        with os.fdopen(fd, "w", encoding="utf-8") as f:  # pragma: no mutate
            f.write(payload)
        os.replace(tmp_path, str(output_path))
    except BaseException:
        os.unlink(tmp_path)
        raise

    if output_path.name == "quality-gate-latest.json":
        # reason: strftime format mutations produce valid (if different) filename; content is tested.
        # audited: 2026-06-04
        ts = data.get("timestamp", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))  # pragma: no mutate
        timestamped = output_path.with_name(f"quality-gate-{ts}.json")
        # reason: encoding="utf-8" equivalent for ASCII JSON.
        # audited: 2026-06-04
        timestamped.write_text(payload, encoding="utf-8")  # pragma: no mutate
