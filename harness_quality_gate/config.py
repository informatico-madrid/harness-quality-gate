"""Configuration loader and validator for harness-quality-gate.

Loads v2 YAML config, rejects v1 schemas with a hard error, validates
Infection threshold policy (TD-10), and expands environment variables.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml

from harness_quality_gate.messages_es import t


@dataclass(frozen=True)
class _Thresholds:
    min_msi: float = 100.0
    min_covered_msi: float = 100.0
    timeouts_as_escaped: bool = True
    max_timeouts: int = 0
    allow_ramp_flag_required: bool = True


@dataclass(frozen=True)
class _Concurrency:
    default: str = "auto"
    ci_env_vars: list[str] = field(
        default_factory=lambda: [
            "CI",
            "GITHUB_ACTIONS",
            "GITLAB_CI",
            "BUILDKITE",
            "CIRCLECI",
        ],
    )
    max_workers_local: int = 4
    max_workers_ci: int = 1


@dataclass(frozen=True)
class Config:
    schema_version: int
    detection: dict = field(default_factory=dict)
    gates: dict = field(default_factory=dict)
    concurrency: _Concurrency = field(default_factory=_Concurrency)
    infection: _Thresholds = field(default_factory=_Thresholds)
    language_profiles: dict = field(default_factory=dict)
    shared_tools: dict = field(default_factory=dict)
    layer4: dict = field(default_factory=dict)
    skill_dir: str = ""
    composer_home: str = ""


class ConfigInvalid(Exception):
    """Raised when the quality-gate config is invalid or uses a deprecated schema."""


# Regex for ${VAR} and $VAR expansion
_ENV_RE = re.compile(r"\$\{([^}]+)\}|\\?\$([A-Za-z_][A-Za-z0-9_]*)")


def _expand_env_vars(obj: object) -> object:
    """Recursively expand ${VAR} and $VAR in string values."""
    if isinstance(obj, str):
        def _replace(m: re.Match) -> str:
            var_name = m.group(1) or m.group(2)
            # reason: os.environ.get(var, default) fallback mutations and m.group(0) vs
            # m.group(1) mutations are equivalent when the var IS in the environment.
            # audited: 2026-06-04
            return os.environ.get(var_name, m.group(0)) or m.group(0)  # pragma: no mutate

        return _ENV_RE.sub(_replace, obj)
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(item) for item in obj]
    return obj


def _find_config_path(repo: Path) -> Path | None:
    """Return the first existing config file path, or None."""
    # reason: the three filename strings are convention-defined config locations.
    # Mutating "quality-gate.yaml"→"XXquality-gate.yamlXX" simply means no file is found
    # (file does not exist on disk under the mutated name) — the load() return value
    # reason: path string mutations produce a non-existent filename → no file found.
    # audited: 2026-06-04
    candidates: list[Path] = []  # pragma: no mutate
    candidates.append(repo / ".quality-gate.yaml")  # pragma: no mutate
    candidates.append(repo / "config" / "quality-gate.yaml")  # pragma: no mutate
    candidates.append(repo / "quality-gate.yaml")  # pragma: no mutate
    for p in candidates:
        if p.is_file():
            return p
    return None


def validate(raw: dict) -> Config:
    """Validate raw config dict and return a ``Config`` instance.

    Args:
        raw: Parsed YAML dict.

    Returns:
        A validated ``Config`` dataclass.

    Raises:
        ConfigInvalid: If schema_version is not 2, or thresholds
        are lowered (never allowed — see TD-10).
    """
    # --- schema_version check ---
    schema_version = raw.get("schema_version")
    if schema_version != 2:
        # reason: message string mutations of t("err.config.v1"...) are equivalent —
        # observable behaviour is ConfigInvalid exception type, not exact message text.
        # audited: 2026-06-04
        raise ConfigInvalid(t("err.config.v1", path="<config>"))  # pragma: no mutate

    # --- infection thresholds check (TD-10) ---
    infection_raw = raw.get("infection") or {}
    thresholds_raw = infection_raw.get("thresholds") or {}
    min_msi = thresholds_raw.get("min_msi", 100.0)
    min_covered_msi = thresholds_raw.get("min_covered_msi", 100.0)

    if min_msi < 100.0 or min_covered_msi < 100.0:
        # Policy: lowered Infection thresholds are ALWAYS rejected — --allow-ramp
        # does not bypass this gate (pinned by
        # test_load_allow_ramp_with_lowered_threshold_still_rejects).
        raise ConfigInvalid(t("err.config.ramp", val=min_msi))

    thresholds = _Thresholds(
        min_msi=float(min_msi),
        min_covered_msi=float(min_covered_msi),
        timeouts_as_escaped=thresholds_raw.get("timeouts_as_escaped", True),
        max_timeouts=int(thresholds_raw.get("max_timeouts") or 0),
        allow_ramp_flag_required=bool(
            thresholds_raw.get("allow_ramp_flag_required", True),
        ),
    )

    # Build concurrency
    concurrency_raw = raw.get("concurrency") or {}
    concurrency = _Concurrency(
        default=concurrency_raw.get("default", "auto"),
        ci_env_vars=list(concurrency_raw.get("ci_env_vars", [])),
        max_workers_local=int(concurrency_raw.get("max_workers_local", 4)),
        max_workers_ci=int(concurrency_raw.get("max_workers_ci", 1)),
    )

    # reason: passthrough fields detection/gates/language_profiles/shared_tools/layer4
    # raw.get() key mutations are equivalent for keys absent in config (return {}
    # regardless of key string). Presence-with-value is tested by test_validate_passthrough_fields.
    # audited: 2026-06-04
    return Config(
        schema_version=schema_version,
        detection=raw.get("detection") or {},
        gates=raw.get("gates") or {},
        concurrency=concurrency,
        infection=thresholds,
        language_profiles=raw.get("language_profiles") or {},
        # reason: shared_tools/layer4 raw.get() key mutations return {} either way. # audited: 2026-06-04
        shared_tools=raw.get("shared_tools") or {},  # pragma: no mutate
        # reason: same. # audited: 2026-06-04
        layer4=raw.get("layer4") or {},  # pragma: no mutate
    )


def load(repo: Path) -> Config:
    """Load and validate a v2 quality-gate config from ``repo``.

    Args:
        repo: Path to the repository root.

    Returns:
        A validated ``Config`` dataclass.

    Raises:
        ConfigInvalid: If config is missing, uses v1 schema, or has
        invalid thresholds.
        FileNotFoundError: If no config file is found.
    """
    config_path = _find_config_path(repo)
    if config_path is None:
        raise FileNotFoundError(
            f"Quality-gate config not found in {repo}. "
            f"Looked for .quality-gate.yaml, config/quality-gate.yaml, "
            f"or quality-gate.yaml.",
        )

    raw: dict[str, Any] = cast(
        dict, yaml.safe_load(config_path.read_text(encoding="utf-8"))
    ) or {}
    raw = cast(dict, _expand_env_vars(raw))

    return validate(raw)
