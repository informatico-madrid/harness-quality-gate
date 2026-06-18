"""Unit tests for the config loader and validator.

Covers v1 hard-reject; v2 valid; threshold-lowered hard-reject;
${VAR} expansion; new Phase 5 top-level keys; config file precedence;
and load_with_defaults() merging.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from harness_quality_gate.config import (
    ConfigInvalid,
    _expand_env_vars,
    _find_config_path,
    load,
    load_with_defaults,
    validate,
    _deep_merge,
)

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
    # Ensure the target var is absent without clearing os.environ wholesale —
    # a full clear strips mutmut's MUTANT_UNDER_TEST and crashes the mutation
    # baseline. clear=False restores any change on exit.
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MISSING_VAR", None)
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


def test_validate_passthrough_fields() -> None:
    """Kill raw.get('gates'→'XXgatesXX'), raw.get('shared_tools'→...) etc.

    These fields are passed through verbatim; mutating their keys causes the
    wrong (empty) dict to land in Config.
    """
    cfg = _make_v2_config({
        "gates": {"layer1": {"coverage": 85}},
        "detection": {"language": "php"},
        "language_profiles": {"php": {"min_msi": 100}},
        "shared_tools": {"ruff": {"enabled": True}},
        "layer4": {"severity": "high"},
    })
    config = validate(cfg)
    assert config.gates == {"layer1": {"coverage": 85}}
    assert config.detection == {"language": "php"}
    assert config.language_profiles == {"php": {"min_msi": 100}}
    assert config.shared_tools == {"ruff": {"enabled": True}}
    assert config.layer4 == {"severity": "high"}


def test_validate_threshold_defaults_exact() -> None:
    """Kill default value mutations in _Thresholds constructor.

    timeouts_as_escaped default True, max_timeouts default 0,
    allow_ramp_flag_required default True — each asserted by name.
    """
    config = validate(_make_v2_config())
    assert config.infection.timeouts_as_escaped is True
    assert config.infection.max_timeouts == 0
    assert config.infection.allow_ramp_flag_required is True


def test_validate_max_timeouts_absent_defaults_to_zero() -> None:
    """Kill `or 0` mutation on max_timeouts.

    When 'max_timeouts' key is absent from the dict, `get()` returns None.
    Original: int(None or 0) → int(0) → 0.  Mutant: int(None) → TypeError.
    """
    cfg = _make_v2_config({
        "infection": {
            "thresholds": {
                "min_msi": 100.0,
                "min_covered_msi": 100.0,
                # No "max_timeouts" key at all
            },
        },
    })
    result = validate(cfg)
    assert result.infection.max_timeouts == 0


def test_validate_max_timeouts_null_defaults_to_zero() -> None:
    """Kill `or 0` when the key is present but explicitly null.

    YAML with 'max_timeouts: null' → get() returns None, `or 0` catches it.
    Mutant without `or 0` would raise TypeError on int(None).
    """
    cfg = _make_v2_config({
        "infection": {
            "thresholds": {
                "min_msi": 100.0,
                "min_covered_msi": 100.0,
                "max_timeouts": None,
            },
        },
    })
    result = validate(cfg)
    assert result.infection.max_timeouts == 0


def test_validate_concurrency_defaults_exact() -> None:
    """Kill max_workers_local=4, max_workers_ci=1 default mutations.
    When concurrency section exists, ci_env_vars comes from config; when absent, default is [].
    """
    config = validate(_make_v2_config())
    assert config.concurrency.max_workers_local == 4
    assert config.concurrency.max_workers_ci == 1

    # With explicit ci_env_vars in config — kills ci_env_vars key mutation
    cfg = _make_v2_config({"concurrency": {"ci_env_vars": ["CI", "GITHUB_ACTIONS"]}})
    config2 = validate(cfg)
    assert "CI" in config2.concurrency.ci_env_vars
    assert "GITHUB_ACTIONS" in config2.concurrency.ci_env_vars


def test_validate_min_msi_int_input_coerced_to_float() -> None:
    """YAML integers in min_msi must end up as Python float (kills mutmut_51
    which removes the float() cast on min_msi).

    Uses min_msi=200 (not the dataclass default 100.0) so the mutant —
    which OMITS min_msi from the _Thresholds() call and falls back to the
    default 100.0 — is forced to a different value.
    """
    cfg = _make_v2_config({
        "infection": {"thresholds": {"min_msi": 200, "min_covered_msi": 200}},
    })
    result = validate(cfg)
    # Mutant omits min_msi from the call → default 100.0 instead of 200.0
    assert result.infection.min_msi == 200.0
    assert isinstance(result.infection.min_msi, float)
    assert result.infection.min_covered_msi == 200.0
    assert isinstance(result.infection.min_covered_msi, float)

    # Pass explicit non-default values — kills 'max_workers_local' key mutation
    # (if key becomes 'XXmax_workers_localXX', the value 8 won't be found → default 4 used)
    cfg3 = _make_v2_config({
        "concurrency": {"max_workers_local": 8, "max_workers_ci": 2}
    })
    config3 = validate(cfg3)
    assert config3.concurrency.max_workers_local == 8
    assert config3.concurrency.max_workers_ci == 2


def test_validate_threshold_from_config() -> None:
    """Kill float(min_msi) → int(min_msi) and similar type-cast mutations."""
    cfg = _make_v2_config({
        "infection": {
            "thresholds": {
                "min_msi": 100,  # int in YAML → must be floated
                "min_covered_msi": 100,
                "timeouts_as_escaped": False,
                "max_timeouts": 3,
                "allow_ramp_flag_required": False,
            }
        }
    })
    config = validate(cfg)
    assert isinstance(config.infection.min_msi, float)
    assert config.infection.min_msi == 100.0
    assert config.infection.timeouts_as_escaped is False
    assert config.infection.max_timeouts == 3
    assert config.infection.allow_ramp_flag_required is False


def test_load_from_config_subdir(tmp_path: Path) -> None:
    """Kill repo/'config'/'quality-gate.yaml' path mutation.
    Config in config/ subdirectory must be found and loaded.
    """
    cfg = {"schema_version": 2}
    _write_yaml(tmp_path, "config/quality-gate.yaml", cfg)
    loaded = load(tmp_path)
    assert loaded.schema_version == 2


def test_load_lowered_threshold_always_rejects(tmp_path: Path) -> None:
    """Lowered thresholds raise ConfigInvalid unconditionally, with the exact
    Spanish message (kills t()-key and val-kwarg mutations)."""
    cfg = _make_v2_config({"infection": {"thresholds": {"min_msi": 80.0}}})
    _write_yaml(tmp_path, ".quality-gate.yaml", cfg)
    with pytest.raises(ConfigInvalid, match=r"min_msi=80\.0 < 100 — permitido solo con --allow-ramp y override"):
        load(tmp_path)


def test_shipped_skill_config_is_v2_valid() -> None:
    """Self-application guard (self-eval F14).

    The skill ships config/quality-gate.yaml; running ``all`` on the skill
    repo itself picks it up via load() — without ``schema_version: 2`` the
    skill rejects its own config as v1 and exits 4.
    """
    from harness_quality_gate.config import load

    repo_root = Path(__file__).resolve().parents[2]
    cfg = load(repo_root)
    assert cfg.schema_version == 2


# ---------------------------------------------------------------------------
# Phase 5: New Config fields — defaults
# ---------------------------------------------------------------------------


def test_validate_phase5_fields_defaults() -> None:
    """Config with only schema_version gets correct defaults for new fields."""
    config = validate(_make_v2_config())
    assert config.source_dir is None
    assert config.vulture_confidence == 80
    assert config.ruff_exclude == ["tests/"]
    assert config.mutmut_max_children is None
    assert config.mutation_threshold == 100.0
    assert config.coverage_threshold == 100.0


def test_validate_phase5_fields_from_raw() -> None:
    """validate() reads new keys from the raw dict."""
    cfg = _make_v2_config({
        "source_dir": "lib",
        "vulture_confidence": 90,
        "ruff_exclude": ["tests/", "vendor/"],
        "mutmut_max_children": 8,
        "mutation_threshold": 90.0,
        "coverage_threshold": 95.0,
    })
    config = validate(cfg)
    assert config.source_dir == "lib"
    assert config.vulture_confidence == 90
    assert config.ruff_exclude == ["tests/", "vendor/"]
    assert config.mutmut_max_children == 8
    assert config.mutation_threshold == 90.0
    assert config.coverage_threshold == 95.0


def test_validate_phase5_null_values_handled() -> None:
    """None/null values map to Python None for optional fields."""
    cfg = _make_v2_config({
        "source_dir": None,
        "mutmut_max_children": None,
    })
    config = validate(cfg)
    assert config.source_dir is None
    assert config.mutmut_max_children is None


# ---------------------------------------------------------------------------
# Phase 5: Config location precedence — _find_config_path
# ---------------------------------------------------------------------------


def test_find_config_path_prefers_quality_gate_dir(tmp_path: Path) -> None:
    """_quality-gate/quality-gate.yaml wins over .quality-gate.yaml."""
    _write_yaml(tmp_path, "_quality-gate/quality-gate.yaml", _make_v2_config())
    _write_yaml(tmp_path, ".quality-gate.yaml", _make_v2_config())
    result = _find_config_path(tmp_path)
    assert result is not None
    assert result.parts[-2:] == ("_quality-gate", "quality-gate.yaml")


def test_find_config_path_falls_through_to_dot_yaml(tmp_path: Path) -> None:
    """Without _quality-gate dir, .quality-gate.yaml is found."""
    _write_yaml(tmp_path, ".quality-gate.yaml", _make_v2_config())
    result = _find_config_path(tmp_path)
    assert result is not None
    assert result.name == ".quality-gate.yaml"


def test_find_config_path_falls_through_to_config_subdir(tmp_path: Path) -> None:
    """Without _quality-gate or .quality-gate.yaml, config/quality-gate.yaml is found."""
    _write_yaml(tmp_path, "config/quality-gate.yaml", _make_v2_config())
    result = _find_config_path(tmp_path)
    assert result is not None
    assert result.name == "quality-gate.yaml"


def test_find_config_path_all_absent_returns_none(tmp_path: Path) -> None:
    """No config files → None."""
    result = _find_config_path(tmp_path)
    assert result is None


# ---------------------------------------------------------------------------
# Phase 5: load_with_defaults() — merging bundled + project config
# ---------------------------------------------------------------------------


def test_load_with_defaults_uses_bundled_when_no_project_config(tmp_path: Path) -> None:
    """No project config → bundled defaults are used."""
    bundled_path = tmp_path / "bundled"
    bundled_path.mkdir()
    bundled_cfg = _make_v2_config({"source_dir": "src"})
    _write_yaml(bundled_path, "config/quality-gate.yaml", bundled_cfg)
    config = load_with_defaults(tmp_path, skill_dir=bundled_path)
    assert config.source_dir == "src"
    assert config.vulture_confidence == 80


def test_load_with_defaults_project_overrides_bundled(tmp_path: Path) -> None:
    """Project-level overrides take precedence over bundled defaults."""
    bundled_path = tmp_path / "bundled"
    bundled_path.mkdir()
    bundled_cfg = _make_v2_config({"source_dir": "src", "vulture_confidence": 60})
    _write_yaml(bundled_path, "config/quality-gate.yaml", bundled_cfg)

    project_path = tmp_path / "project"
    project_cfg = {"schema_version": 2, "source_dir": "lib"}
    _write_yaml(project_path, "_quality-gate/quality-gate.yaml", project_cfg)

    config = load_with_defaults(project_path, skill_dir=bundled_path)
    assert config.source_dir == "lib"  # project override
    assert config.vulture_confidence == 60  # bundled default


def test_load_with_defaults_list_replacement(tmp_path: Path) -> None:
    """Project ruff_exclude replaces (not appends to) bundled ruff_exclude."""
    bundled_path = tmp_path / "bundled"
    bundled_path.mkdir()
    bundled_cfg = _make_v2_config({"ruff_exclude": ["tests/", "vendor/"]})
    _write_yaml(bundled_path, "config/quality-gate.yaml", bundled_cfg)

    project_path = tmp_path / "project"
    project_cfg = {"schema_version": 2, "ruff_exclude": ["tests/"]}
    _write_yaml(project_path, "_quality-gate/quality-gate.yaml", project_cfg)

    config = load_with_defaults(project_path, skill_dir=bundled_path)
    assert config.ruff_exclude == ["tests/"]


def test_load_with_defaults_rejects_v1_schema(tmp_path: Path) -> None:
    """Project config with v1 schema → ConfigInvalid."""
    bundled_path = tmp_path / "bundled"
    bundled_path.mkdir()
    bundled_cfg = _make_v2_config()
    _write_yaml(bundled_path, "config/quality-gate.yaml", bundled_cfg)

    project_path = tmp_path / "project"
    _write_yaml(project_path, "_quality-gate/quality-gate.yaml", {"schema_version": 1})

    with pytest.raises(ConfigInvalid, match="v1"):
        load_with_defaults(project_path, skill_dir=bundled_path)


def test_load_with_defaults_no_bundled_no_project(tmp_path: Path) -> None:
    """No bundled defaults and no project config → FileNotFoundError."""
    project_path = tmp_path / "project"
    project_path.mkdir()
    with pytest.raises(FileNotFoundError):
        load_with_defaults(project_path, skill_dir=tmp_path / "nonexistent")


# ---------------------------------------------------------------------------
# _deep_merge function tests
# ---------------------------------------------------------------------------


def test_deep_merge_dict_simple() -> None:
    """Non-overlapping keys from override are added."""
    result = _deep_merge({"a": 1}, {"b": 2})
    assert result == {"a": 1, "b": 2}


def test_deep_merge_dict_overwrite() -> None:
    """Scalar override replaces base value."""
    result = _deep_merge({"a": 1}, {"a": 2})
    assert result == {"a": 2}


def test_deep_merge_list_replacement() -> None:
    """List override replaces (not merges) with base."""
    result = _deep_merge({"a": [1, 2]}, {"a": [3]})
    assert result == {"a": [3]}


def test_deep_merge_nested_dict_merge() -> None:
    """Nested dicts are merged, not replaced."""
    result = _deep_merge(
        {"x": {"a": 1, "b": 2}},
        {"x": {"b": 3, "c": 4}},
    )
    assert result == {"x": {"a": 1, "b": 3, "c": 4}}


# ---------------------------------------------------------------------------
# TestBoundsValidation — security fixes #2 and #7 bounds checks
# ---------------------------------------------------------------------------


class TestBoundsValidation:
    """Validate bounds checks for configurable parameters."""

    # ── vulture_confidence ────────────────────────────────────────────

    def test_vulture_confidence_negative_raises(self) -> None:
        """vulture_confidence: -1 → ConfigInvalid."""
        cfg = _make_v2_config({"vulture_confidence": -1})
        with pytest.raises(ConfigInvalid, match="vulture_confidence must be between 0 and 100"):
            validate(cfg)

    def test_vulture_confidence_101_raises(self) -> None:
        """vulture_confidence: 101 → ConfigInvalid."""
        cfg = _make_v2_config({"vulture_confidence": 101})
        with pytest.raises(ConfigInvalid, match="vulture_confidence must be between 0 and 100"):
            validate(cfg)

    def test_vulture_confidence_0_ok(self) -> None:
        """vulture_confidence: 0 is accepted (within bounds, no ConfigInvalid)."""
        cfg = _make_v2_config({"vulture_confidence": 0})
        config = validate(cfg)
        # 0 is within bounds so validation passes.
        # (it maps to the configured default 80 via `or 80` pattern — separate from bounds check)
        assert config.vulture_confidence == 80

    def test_vulture_confidence_100_ok(self) -> None:
        """vulture_confidence: 100 is accepted at boundary."""
        cfg = _make_v2_config({"vulture_confidence": 100})
        config = validate(cfg)
        assert config.vulture_confidence == 100

    def test_vulture_confidence_float_non_integer_raises(self) -> None:
        """vulture_confidence: 50.5 → ConfigInvalid."""
        cfg = _make_v2_config({"vulture_confidence": 50.5})
        with pytest.raises(ConfigInvalid, match="must be an integer, got float"):
            validate(cfg)

    def test_vulture_confidence_bool_true_raises(self) -> None:
        """vulture_confidence: True (YAML `true`) → ConfigInvalid."""
        cfg = _make_v2_config({"vulture_confidence": True})
        with pytest.raises(ConfigInvalid, match="must be an integer, got bool"):
            validate(cfg)

    def test_vulture_confidence_default_80_ok(self) -> None:
        """Default vulture_confidence (80) is accepted."""
        config = validate(_make_v2_config())
        assert config.vulture_confidence == 80

    # ── mutation_threshold ────────────────────────────────────────────

    def test_mutation_threshold_negative_raises(self) -> None:
        """mutation_threshold: -1 → ConfigInvalid."""
        cfg = _make_v2_config({"mutation_threshold": -1})
        with pytest.raises(ConfigInvalid, match="mutation_threshold must be between 0 and 100"):
            validate(cfg)

    def test_mutation_threshold_101_raises(self) -> None:
        """mutation_threshold: 101 → ConfigInvalid."""
        cfg = _make_v2_config({"mutation_threshold": 101})
        with pytest.raises(ConfigInvalid, match="mutation_threshold must be between 0 and 100"):
            validate(cfg)

    def test_mutation_threshold_0_ok(self) -> None:
        """mutation_threshold: 0 is accepted (within bounds, no ConfigInvalid)."""
        cfg = _make_v2_config({"mutation_threshold": 0})
        config = validate(cfg)
        # 0 is within bounds so validation passes.
        # (it maps to the configured default 100.0 via `or 100.0` pattern)
        assert config.mutation_threshold == 100.0

    def test_mutation_threshold_100_ok(self) -> None:
        """mutation_threshold: 100 is accepted at boundary."""
        cfg = _make_v2_config({"mutation_threshold": 100})
        config = validate(cfg)
        assert config.mutation_threshold == 100.0

    # ── coverage_threshold ────────────────────────────────────────────

    def test_coverage_threshold_negative_raises(self) -> None:
        """coverage_threshold: -1 → ConfigInvalid."""
        cfg = _make_v2_config({"coverage_threshold": -1})
        with pytest.raises(ConfigInvalid, match="coverage_threshold must be between 0 and 100"):
            validate(cfg)

    def test_coverage_threshold_101_raises(self) -> None:
        """coverage_threshold: 101 → ConfigInvalid."""
        cfg = _make_v2_config({"coverage_threshold": 101})
        with pytest.raises(ConfigInvalid, match="coverage_threshold must be between 0 and 100"):
            validate(cfg)

    def test_coverage_threshold_0_ok(self) -> None:
        """coverage_threshold: 0 is accepted (within bounds, no ConfigInvalid)."""
        cfg = _make_v2_config({"coverage_threshold": 0})
        config = validate(cfg)
        # 0 is within bounds so validation passes.
        # (it maps to the configured default 100.0 via `or 100.0` pattern)
        assert config.coverage_threshold == 100.0

    def test_coverage_threshold_100_ok(self) -> None:
        """coverage_threshold: 100 is accepted at boundary."""
        cfg = _make_v2_config({"coverage_threshold": 100})
        config = validate(cfg)
        assert config.coverage_threshold == 100.0

    # ── mutmut_max_children ───────────────────────────────────────────

    def test_mutmut_max_children_exceeds_cpu_limit_raises(self) -> None:
        """mutmut_max_children > cpu_count * 2 → ConfigInvalid."""
        cpu = os.cpu_count() or 1
        bad_value = cpu * 2 + 1
        cfg = _make_v2_config({"mutmut_max_children": bad_value})
        with pytest.raises(ConfigInvalid, match="mutmut_max_children.*exceeds safe maximum"):
            validate(cfg)

    def test_mutmut_max_children_none_ok(self) -> None:
        """mutmut_max_children: None (no override) is accepted."""
        cfg = _make_v2_config({"mutmut_max_children": None})
        config = validate(cfg)
        assert config.mutmut_max_children is None

    def test_mutmut_max_children_within_limit_ok(self) -> None:
        """mutmut_max_children within cpu_count * 2 is accepted."""
        cpu = os.cpu_count() or 1
        safe_value = max(1, (cpu * 2) // 2)  # half the limit
        cfg = _make_v2_config({"mutmut_max_children": safe_value})
        config = validate(cfg)
        assert config.mutmut_max_children == safe_value

    def test_mutmut_max_children_at_limit_ok(self) -> None:
        """mutmut_max_children exactly at cpu_count * 2 is accepted."""
        cpu = os.cpu_count() or 1
        at_limit = cpu * 2
        cfg = _make_v2_config({"mutmut_max_children": at_limit})
        config = validate(cfg)
        assert config.mutmut_max_children == at_limit


# ---------------------------------------------------------------------------
# TestDeepMerge — integration tests for load_with_defaults merging
# ---------------------------------------------------------------------------


class TestDeepMerge:
    """Tests for _deep_merge in load_with_defaults."""

    def test_deep_merge_nested_dicts(self, tmp_path: Path) -> None:
        """Project override merges into (not replaces) nested layer4 dict."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        bundled_cfg = bundled / "config" / "quality-gate.yaml"
        bundled_cfg.parent.mkdir(parents=True, exist_ok=True)
        bundled_cfg.write_text(yaml.dump({
            "schema_version": 2,
            "layer4": {
                "tools": {"bandit": {"priority": "required"}},
                "safety": {"fallback": True},
            },
        }), encoding="utf-8")

        project_cfg_path = tmp_path / "project" / "_quality-gate" / "quality-gate.yaml"
        project_cfg_path.parent.mkdir(parents=True, exist_ok=True)
        project_cfg_path.write_text(yaml.dump({
            "schema_version": 2,
            "layer4": {
                "safety": {"fallback": False},
            },
        }), encoding="utf-8")

        with patch.dict(os.environ, {"CLAUDE_SKILL_DIR": str(bundled)}):
            cfg = load_with_defaults(tmp_path / "project")

        # bandit priority from defaults preserved, safety fallback from project used
        assert cfg.layer4["tools"]["bandit"]["priority"] == "required"
        assert cfg.layer4["safety"]["fallback"] is False

    def test_deep_merge_empty_project_config(self, tmp_path: Path) -> None:
        """Empty project config ({}) should use bundled defaults as-is."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        bundled_cfg = bundled / "config" / "quality-gate.yaml"
        bundled_cfg.parent.mkdir(parents=True, exist_ok=True)
        bundled_cfg.write_text(yaml.dump({
            "schema_version": 2,
            "vulture_confidence": 60,
            "ruff_exclude": ["tests/", "examples/"],
        }), encoding="utf-8")

        project_cfg_path = tmp_path / "project" / "_quality-gate" / "quality-gate.yaml"
        project_cfg_path.parent.mkdir(parents=True, exist_ok=True)
        project_cfg_path.write_text(yaml.dump({"schema_version": 2}), encoding="utf-8")

        with patch.dict(os.environ, {"CLAUDE_SKILL_DIR": str(bundled)}):
            cfg = load_with_defaults(tmp_path / "project")

        assert cfg.vulture_confidence == 60
        assert cfg.ruff_exclude == ["tests/", "examples/"]
