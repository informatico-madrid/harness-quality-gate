"""Unit tests for checkpoint v2 builder + writer.

Covers build(), JSON Schema validation, and rejection on validation failure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import jsonschema

from unittest.mock import patch

from harness_quality_gate.checkpoint import build, validate, write
from tests.factories import build_layer_result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def good_detection() -> dict:
    return {
        "repo_path": "/tmp/test",
        "language": "python",
        "framework": None,
        "confidence": 0.95,
    }


@pytest.fixture()
def layer_dicts() -> list[dict]:
    return [
        build_layer_result(layer="L3A", language="python", passed=True).__dict__,
        build_layer_result(layer="L1", language="python", passed=True).__dict__,
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_build_basic(good_detection: dict) -> None:
    """build() produces a dict with required top-level keys."""
    result = build([], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    assert result["version"] == "v2"
    assert result["repository"] == "/tmp/test"
    assert result["language"] == "python"
    assert isinstance(result["layers"], list)


def test_build_with_layers(good_detection: dict, layer_dicts: list[dict]) -> None:
    """build() includes layer result entries."""
    runtime = {"python_version": "3.12", "concurrency": "auto", "ci": False}
    result = build(layer_dicts, runtime, good_detection)
    assert len(result["layers"]) == 2
    assert result["layers"][0]["layer"] == "L3A"
    assert result["layers"][0]["passed"] is True


def test_build_validates_through_schema(good_detection: dict) -> None:
    """build() output passes JSON Schema validation."""
    data = build([], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    validate(data)  # should not raise


def test_build_rejects_invalid_schema() -> None:
    """validate() raises ValidationError for missing required fields."""
    invalid_data: dict = {"version": "v2"}  # missing repository, language, layers
    with pytest.raises(jsonschema.ValidationError):
        validate(invalid_data)


def test_write_creates_file(good_detection: dict, tmp_path: Path) -> None:
    """write() creates the checkpoint file at the target path."""
    data = build([], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    target = tmp_path / "checkpoint.json"
    write(target, data)
    assert target.exists()
    # File is valid JSON
    json.loads(target.read_text(encoding="utf-8"))


def test_write_timestamped_copy(good_detection: dict, tmp_path: Path) -> None:
    """write() creates a timestamped copy when basename is quality-gate-latest.json."""
    data = build([], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    target = tmp_path / "quality-gate-latest.json"
    write(target, data)
    assert target.exists()
    # Timestamped copies should also exist
    children = list(tmp_path.glob("quality-gate-*.json"))
    assert len(children) >= 2  # latest + at least one timestamped


def test_build_layer_entry_keys_exact(good_detection: dict) -> None:
    """Kill lr.get('layer'→'XXlayerXX'), lr.get('language'→'XXlanguageXX'), etc.

    Pass a layer dict with non-empty findings and assert each key by name so
    any string-mutation of the key produces a wrong result.
    """
    from harness_quality_gate.models import Finding
    finding = Finding(node="src/Foo.php", severity="error", message="SRP violation")
    layer_dict = {
        "layer": "L3A",
        "language": "php",
        "passed": False,
        "findings": [finding],
        "duration_sec": 1.5,
    }
    result = build(
        [layer_dict],
        {"python_version": "3.12", "concurrency": "sequential", "ci": True},
        good_detection,
    )
    entry = result["layers"][0]
    # Each key must be exactly the expected string — kills key-mutation survivors
    assert entry["layer"] == "L3A"
    assert entry["language"] == "php"
    assert entry["passed"] is False
    assert entry["duration_sec"] == 1.5
    # findings must be populated from the "findings" key, not empty default
    assert len(entry["findings"]) == 1
    assert entry["findings"][0]["node"] == "src/Foo.php"
    assert entry["findings"][0]["severity"] == "error"


def test_build_detection_keys_used(good_detection: dict) -> None:
    """Kill detection.get('language'→'XXlanguageXX') and detection.get('repo_path'→...) mutations."""
    detection = {
        "repo_path": "/app/myproject",
        "language": "php",
        "framework": "symfony",
        "confidence": 0.99,
    }
    result = build([], {"python_version": "3.12", "concurrency": "auto", "ci": False}, detection)
    # These must come from the "language" and "repo_path" keys — not defaults
    assert result["language"] == "php"
    assert result["repository"] == "/app/myproject"


def test_build_to_dict_dataclass_vs_type(good_detection: dict) -> None:
    """Kill is_dataclass(obj) && not isinstance(obj, type) → isinstance(obj, type) mutation.

    Passing a dataclass instance as a finding must produce a dict;
    passing the dataclass class itself must NOT be treated as a dataclass instance.
    """
    from harness_quality_gate.models import Finding
    instance = Finding(node="src/A.php", severity="warning", message="msg")
    layer_dict = {
        "layer": "L3A",
        "language": "python",
        "passed": True,
        "findings": [instance],
        "duration_sec": 0.0,
    }
    result = build(
        [layer_dict],
        {"python_version": "3.12", "concurrency": "auto", "ci": False},
        good_detection,
    )
    f = result["layers"][0]["findings"][0]
    # Must be a plain dict (dataclass converted), not the dataclass object itself
    assert isinstance(f, dict)
    assert f["node"] == "src/A.php"
    assert f["severity"] == "warning"


def test_build_passed_default_false(good_detection: dict) -> None:
    """Kill lr.get('passed', False) → lr.get('passed', True) mutation."""
    # Layer dict missing 'passed' key — must default to False, not True
    layer_dict = {"layer": "L3A", "language": "python", "findings": [], "duration_sec": 0.0}
    result = build(
        [layer_dict],
        {"python_version": "3.12", "concurrency": "auto", "ci": False},
        good_detection,
    )
    assert result["layers"][0]["passed"] is False


def test_build_to_dict_filters_none_fields(good_detection: dict) -> None:
    """Kill 'v is not None' → 'v is None' mutation in _to_dict.

    Finding has optional fields (fix_hint, cve, etc.) that are None by default.
    When _to_dict filters 'if v is not None', None fields are excluded from output.
    When mutated to 'if v is None', only None fields appear — non-None fields vanish.
    """
    from harness_quality_gate.models import Finding
    # Create Finding with all required fields non-None, optional fields left as None
    f = Finding(node="src/Foo.php", severity="error", message="SRP violation")
    assert f.fix_hint is None  # optional field
    assert f.cve is None        # optional field

    layer_dict = {
        "layer": "L3A", "language": "php", "passed": False,
        "findings": [f], "duration_sec": 0.1,
    }
    result = build([layer_dict], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    finding_out = result["layers"][0]["findings"][0]

    # Required fields MUST be present (not filtered by is_not_None)
    assert finding_out["node"] == "src/Foo.php"
    assert finding_out["severity"] == "error"
    assert finding_out["message"] == "SRP violation"
    # Optional None fields must NOT be present (filtered out)
    assert "fix_hint" not in finding_out, "None fields should be excluded by _to_dict"
    assert "cve" not in finding_out


def test_build_to_dict_is_dataclass_and_not_type(good_detection: dict) -> None:
    """Kill 'is_dataclass(obj) and not isinstance(obj,type)' → 'or' mutation.

    With `and`: is_dataclass(FindingClass) AND not isinstance(FindingClass,type) = True AND False = False
      → _to_dict returns the class unchanged (correct).
    With `or`: is_dataclass(FindingClass) OR not isinstance(FindingClass,type) = True OR False = True
      → _to_dict tries dataclasses.asdict(FindingClass) which raises TypeError.

    So the mutant crashes; the test must assert no exception is raised.
    """
    from harness_quality_gate.models import Finding
    layer_dict = {
        "layer": "L3A", "language": "python", "passed": True,
        "findings": [Finding],  # class, not instance
        "duration_sec": 0.0,
    }
    # Must not raise — the class is passed through unchanged
    result = build([layer_dict], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    finding_out = result["layers"][0]["findings"][0]
    # The class itself is returned (not converted), which is a type object
    assert finding_out is Finding


def test_write_calls_validate_with_data(good_detection: dict, tmp_path: Path) -> None:
    """Kill validate(data) → validate(None) mutation in write().

    write() must call validate() with the actual data, not None.
    """
    data = build([], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    target = tmp_path / "out.json"
    # Should not raise (valid data passed)
    write(target, data)
    assert target.exists()
    # Content must be valid JSON matching the built data
    import json as json_mod
    loaded = json_mod.loads(target.read_text())
    assert loaded["language"] == data["language"]
    assert loaded["version"] == "v2"


def test_validate_schema_path_resolves(good_detection: dict) -> None:
    """Kill schema_path=None mutation in validate().

    validate() must successfully load the schema file (not None).
    If schema_path=None, schema_path.open() would raise AttributeError.
    """
    data = build([], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    # Should not raise — schema file must be found and loaded
    validate(data)


def test_build_layer_with_per_language(good_detection: dict) -> None:
    """Kill 'per_language' key mutation and cover the branch (line 62)."""
    layer_dict = {
        "layer": "L3A",
        "language": "python",
        "passed": True,
        "findings": [],
        "duration_sec": 0.5,
        "per_language": {"python": {"passed": True}, "php": {"passed": False}},
    }
    result = build([layer_dict], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    entry = result["layers"][0]
    assert "per_language" in entry
    assert entry["per_language"]["python"]["passed"] is True


def test_build_layer_with_tool_specific(good_detection: dict) -> None:
    """Kill tool_specific key mutation and cover the branch (line 64)."""
    layer_dict = {
        "layer": "L1",
        "language": "php",
        "passed": True,
        "findings": [],
        "duration_sec": 1.0,
        "tool_specific": {"phpunit_version": "10.5.0", "infection_msi": 100.0},
    }
    result = build([layer_dict], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    entry = result["layers"][0]
    assert "tool_specific" in entry
    assert entry["tool_specific"]["phpunit_version"] == "10.5.0"


def test_build_layer_without_tool_specific_absent(good_detection: dict) -> None:
    """Kill tool_specific is not None → is None mutation (line 63).
    When tool_specific is None, it must NOT appear in the output entry."""
    layer_dict = {
        "layer": "L3A",
        "language": "python",
        "passed": True,
        "findings": [],
        "duration_sec": 0.1,
        "tool_specific": None,
    }
    result = build([layer_dict], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    assert "tool_specific" not in result["layers"][0]


def test_build_findings_default_empty_list(good_detection: dict) -> None:
    """Kill lr.get('findings', []) → lr.get('XXfindingsXX', []) mutation.

    When the dict has no 'findings' key, the result must be an empty list (not
    come from a wrong key). When it does have 'findings', they must be preserved.
    """
    # With key present — must use the key value, not the default
    from harness_quality_gate.models import Finding
    f = Finding(node="X.php", severity="error", message="err")
    with_findings = {"layer": "L1", "language": "php", "passed": False, "findings": [f], "duration_sec": 0.5}
    result = build(
        [with_findings],
        {"python_version": "3.12", "concurrency": "auto", "ci": False},
        good_detection,
    )
    assert len(result["layers"][0]["findings"]) == 1

    # Without key present — must fall back to [] (not error)
    without_findings = {"layer": "L1", "language": "php", "passed": True, "duration_sec": 0.5}
    result2 = build(
        [without_findings],
        {"python_version": "3.12", "concurrency": "auto", "ci": False},
        good_detection,
    )
    assert result2["layers"][0]["findings"] == []


def test_write_atomic_cleanup_on_fdopen_failure(good_detection: dict, tmp_path: Path) -> None:
    """Kill the 'BaseException after mkstemp → no cleanup' mutation in write().

    When os.fdopen raises, the except block must call os.unlink(tmp_path)
    to clean up the orphaned temp file.  If os.unlink is removed or the
    exception is swallowed without cleanup, the mutant survives.
    """
    data = build([], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    target = tmp_path / "checkpoint.json"

    with patch("harness_quality_gate.checkpoint.os.fdopen", side_effect=IOError("write failed")):
        with pytest.raises(IOError, match="write failed"):
            write(target, data)

    # The target must NOT exist (write never completed)
    assert not target.exists()
    # Temp file must be cleaned up — no .quality-gate-*.tmp leftovers
    assert list(tmp_path.glob(".quality-gate-*.tmp")) == []
