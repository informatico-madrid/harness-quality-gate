"""Unit tests for the config loader and validator.

Covers v1 hard-reject; v2 valid; threshold-lowered hard-reject;
${VAR} expansion; and missing config file.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from harness_quality_gate.config import ConfigInvalid, _expand_env_vars, load, validate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_v2_config(extra: dict | None = None) -> dict:
    """Build a minimal v2 config dict."""
    cfg: dict = {"schema_version": 2}
    if extra:
        cfg.update(extra)
    return cfg


def _write_yaml(repo: Path, filename: str, data: dict) -> Path:
    """Write YAML config and return its path."""
    path = repo / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# validate() — schema version
# ---------------------------------------------------------------------------


def test_validate_v1_hard_rejects() -> None:
    """Schema version 1 → ConfigInvalid."""
    with pytest.raises(ConfigInvalid, match="v1"):
        validate({"schema_version": 1})


def test_validate_v1_hard_rejects_missing_version() -> None:
    """Missing schema_version → ConfigInvalid (not 2)."""
    with pytest.raises(ConfigInvalid, match="v1"):
        validate({})


def test_validate_v2_valid() -> None:
    """Valid v2 config → Config instance."""
    config = validate(_make_v2_config())
    assert config.schema_version == 2
    assert config.infection.min_msi == 100.0
    assert config.infection.min_covered_msi == 100.0
    assert config.concurrency.default == "auto"


def test_validate_v2_with_custom_thresholds_defaults() -> None:
    """V2 config with infection section but thresholds at defaults."""
    cfg = _make_v2_config({
        "infection": {"thresholds": {"min_msi": 100.0, "min_covered_msi": 100.0}},
    })
    config = validate(cfg)
    assert config.infection.min_msi == 100.0
    assert config.infection.min_covered_msi == 100.0
    assert config.infection.timeouts_as_escaped is True
    assert config.infection.max_timeouts == 0


# ---------------------------------------------------------------------------
# validate() — threshold policy (TD-10)
# ---------------------------------------------------------------------------


def test_validate_threshold_lowered_rejects() -> None:
    """min_msi < 100 → ConfigInvalid."""
    cfg = _make_v2_config({
        "infection": {"thresholds": {"min_msi": 90.0}},
    })
    with pytest.raises(ConfigInvalid, match="ramp"):
        validate(cfg)


def test_validate_threshold_covered_lowered_rejects() -> None:
    """min_covered_msi < 100 → ConfigInvalid."""
    cfg = _make_v2_config({
        "infection": {"thresholds": {"min_covered_msi": 90.0}},
    })
    with pytest.raises(ConfigInvalid, match="ramp"):
        validate(cfg)


def test_validate_threshold_100_accepts() -> None:
    """Exactly 100.0 is accepted."""
    cfg = _make_v2_config({
        "infection": {"thresholds": {"min_msi": 100.0, "min_covered_msi": 100.0}},
    })
    config = validate(cfg)
    assert config.infection.min_msi == 100.0


def test_validate_concurrency_defaults() -> None:
    """Empty concurrency → defaults."""
    config = validate(_make_v2_config())
    assert config.concurrency.default == "auto"
    assert config.concurrency.max_workers_local == 4
    assert config.concurrency.max_workers_ci == 1


# ---------------------------------------------------------------------------
# _expand_env_vars()
# ---------------------------------------------------------------------------


def test_expand_env_vars_simple() -> None:
    """${VAR} is expanded from os.environ."""
    with patch.dict(os.environ, {"CLAUDE_SKILL_DIR": "/opt/skills"}):
        result = _expand_env_vars("${CLAUDE_SKILL_DIR}/path")
    assert result == "/opt/skills/path"


def test_expand_env_vars_dollar_no_braces() -> None:
    """$VAR (without braces) is expanded."""
    with patch.dict(os.environ, {"MY_PATH": "/usr/local"}):
        result = _expand_env_vars("path is $MY_PATH")
    assert result == "path is /usr/local"


def test_expand_env_vars_missing_unchanged() -> None:
    """Missing env var → original ${VAR} left unchanged."""
    with patch.dict(os.environ, {}, clear=True):
        result = _expand_env_vars("${MISSING_VAR}")
    assert result == "${MISSING_VAR}"


def test_expand_env_vars_dict_recursion() -> None:
    """Nested dict values are expanded."""
    with patch.dict(os.environ, {"SKILL_DIR": "/skills"}):
        data: dict[str, object] = {"skill_dir": "${SKILL_DIR}"}
        result = _expand_env_vars(data)  # type: ignore[assignment]
    assert result["skill_dir"] == "/skills"


def test_expand_env_vars_list_recursion() -> None:
    """List items are expanded."""
    with patch.dict(os.environ, {"ENV": "prod"}):
        data = ["${ENV}-1", "static"]
        result = _expand_env_vars(data)
    assert result == ["prod-1", "static"]


def test_expand_env_vars_non_string_unchanged() -> None:
    """Integers and other non-string types pass through."""
    assert _expand_env_vars(42) == 42
    assert _expand_env_vars(3.14) == 3.14
    assert _expand_env_vars(None) is None


# ---------------------------------------------------------------------------
# load() — file discovery
# ---------------------------------------------------------------------------


def test_load_missing_config(tmp_path: Path) -> None:
    """No config file → FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="Quality-gate config not found"):
        load(tmp_path)


def test_load_dot_yaml(tmp_path: Path) -> None:
    """Config at repo root (.quality-gate.yaml) is found."""
    cfg = _make_v2_config()
    _write_yaml(tmp_path, ".quality-gate.yaml", cfg)
    config = load(tmp_path)
    assert config.schema_version == 2


def test_load_config_subdir(tmp_path: Path) -> None:
    """Config at config/quality-gate.yaml is found."""
    cfg = _make_v2_config()
    _write_yaml(tmp_path, "config/quality-gate.yaml", cfg)
    config = load(tmp_path)
    assert config.schema_version == 2


def test_load_env_expansion(tmp_path: Path) -> None:
    """Config with ${VAR} is expanded before validation.
    Concurrency default env var expansion is a real path.
    """
    cfg: dict = {
        "schema_version": 2,
        "concurrency": {"default": "${GATE_CONCURRENCY}"},
    }
    _write_yaml(tmp_path, ".quality-gate.yaml", cfg)
    with patch.dict(os.environ, {"GATE_CONCURRENCY": "sequential"}):
        loaded = load(tmp_path)
    assert loaded.concurrency.default == "sequential"


def test_load_v1_rejects(tmp_path: Path) -> None:
    """V1 config → ConfigInvalid."""
    cfg = {"schema_version": 1}
    _write_yaml(tmp_path, ".quality-gate.yaml", cfg)
    with pytest.raises(ConfigInvalid, match="v1"):
        load(tmp_path)
