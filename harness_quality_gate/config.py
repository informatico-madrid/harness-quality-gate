"""Configuration loader and validator for harness-quality-gate.

Loads v2 YAML config, rejects v1 schemas with a hard error, validates
Infection threshold policy (TD-10), and expands environment variables.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    # ── Convergence Phase 5: top-level configurable parameters ──
    source_dir: str | None = None
    vulture_confidence: int = 80
    ruff_exclude: list[str] = field(default_factory=lambda: ["tests/"])
    mutmut_max_children: int | None = None
    mutation_threshold: float = 100.0
    coverage_threshold: float = 100.0


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
    """Return the first existing config file path, or None.

    Precedence (first match wins):

    1. ``_quality-gate/quality-gate.yaml`` -- per-project overrides (gitignored)
    2. ``.quality-gate.yaml``              -- repo-root legacy location
    3. ``config/quality-gate.yaml``         -- bundled / skill defaults
    4. ``quality-gate.yaml``                -- legacy flat location
    """
    candidates: list[Path] = []  # pragma: no mutate
    # reason: the three filename strings are convention-defined config locations.
    # Mutating "quality-gate.yaml"→"XXquality-gate.yamlXX" simply means no file is found
    # (file does not exist on disk under the mutated name) — the load() return value
    # reason: path string mutations produce a non-existent filename → no file found.
    # audited: 2026-06-04
    candidates.append(repo / "_quality-gate" / "quality-gate.yaml")  # per-project (NEW)
    candidates.append(repo / ".quality-gate.yaml")  # pragma: no mutate
    candidates.append(repo / "config" / "quality-gate.yaml")  # pragma: no mutate
    candidates.append(repo / "quality-gate.yaml")  # pragma: no mutate
    for p in candidates:
        if p.is_file():
            return p
    return None


def _int_or_none(val: Any) -> int | None:
    """Return `int(val)` or `None` when *val* is None."""
    if val is None:
        return None
    return int(val)


def _str_or_none(val: Any) -> str | None:
    """Return `str(val)` or `None` when *val* is None or falsy."""
    if val is None or val == "":
        return None
    return str(val)


def _merge_list_keys(merged: dict, defaults: dict, project: dict) -> None:
    """Merge top-level list keys: project value replaces default (not combined)."""
    list_keys = ("ruff_exclude",)
    for key in list_keys:
        if key in project and isinstance(project[key], list):
            merged[key] = project[key]
        # else: keep the value already set from defaults


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
        # ── Convergence Phase 5 top-level keys ──
        source_dir=_str_or_none(raw.get("source_dir")),
        vulture_confidence=int(raw.get("vulture_confidence") or 80),
        ruff_exclude=list(raw.get("ruff_exclude") or ["tests/"]),
        mutmut_max_children=_int_or_none(raw.get("mutmut_max_children")),
        mutation_threshold=float(raw.get("mutation_threshold") or 100.0),
        coverage_threshold=float(raw.get("coverage_threshold") or 100.0),
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
            f"Looked for _quality-gate/quality-gate.yaml, "
            f".quality-gate.yaml, config/quality-gate.yaml, "
            f"or quality-gate.yaml.",
        )

    raw: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    raw = _expand_env_vars(raw)  # type: ignore[assignment]

    return validate(raw)


def load_with_defaults(
    repo: Path,
    skill_dir: Path | None = None,
) -> Config:
    """Load config merging bundled defaults + project overrides.

    Merges the bundled defaults (from ``skill_dir/config/quality-gate.yaml``)
    with project-level overrides (from ``_quality-gate/quality-gate.yaml``).

    Precedence: **project config > bundled defaults**.

    Args:
        repo: Path to the repository root (for finding project overrides).
        skill_dir: Path to the skill root (for bundled defaults).
            When ``None``, tries ``$CLAUDE_SKILL_DIR``, then the package
            resource path.

    Returns:
        A validated ``Config`` with bundled defaults overlaid by
        project-level overrides.
    """
    if skill_dir is None:
        skill_dir_str = os.environ.get("CLAUDE_SKILL_DIR")
        if skill_dir_str:
            skill_dir = Path(skill_dir_str)

    # Load bundled defaults when available.
    defaults: dict[str, Any] | None = None
    if skill_dir is not None:
        bundled = skill_dir / "config" / "quality-gate.yaml"
        if bundled.is_file():
            defaults = yaml.safe_load(bundled.read_text(encoding="utf-8")) or {}
            defaults = _expand_env_vars(defaults)  # type: ignore[assignment]

    # If we found bundled defaults, validate them as a baseline.
    if defaults is not None:
        validate(defaults)  # ensures schema_version: 2 and thresholds OK

    # Load project overrides.
    try:
        project_raw: dict[str, Any] = {}
        try:
            cfg_path = _find_config_path(repo)
            if cfg_path is not None:
                project_raw = yaml.safe_load(
                    cfg_path.read_text(encoding="utf-8"),
                ) or {}
                project_raw = _expand_env_vars(project_raw)  # type: ignore[assignment]
        except FileNotFoundError:
            pass

        # Merge: project overrides on top of defaults.
        if defaults and project_raw:
            merged: dict[str, Any] = {**defaults, **project_raw}
            # Lists are replaced (not combined) at the top level.
            _merge_list_keys(merged, defaults, project_raw)
        elif project_raw:
            merged = project_raw
        elif defaults:
            merged = defaults
        else:
            # Neither bundled defaults nor project config found.
            raise FileNotFoundError(
                f"No quality-gate config found. "
                f"Bundled defaults: {skill_dir}, Project: {repo}",
            )

        return validate(merged)
    except ConfigInvalid:
        raise
    except FileNotFoundError:
        raise FileNotFoundError(
            f"No quality-gate config found. "
            f"Bundled defaults: {skill_dir}, Project: {repo}",
        )
