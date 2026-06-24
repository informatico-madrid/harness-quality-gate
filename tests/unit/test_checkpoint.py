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
    validate(data)  # must not raise
    assert isinstance(data, dict)
    assert data["version"] == "v2"
    assert "repository" in data
    assert "language" in data
    assert "layers" in data


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
    from pathlib import Path
    data = build([], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    validate(data)  # must not raise — schema file must be found and loaded
    schema_path = Path(__file__).resolve().parent.parent.parent / "references" / "verdict-schema.json"
    assert schema_path.exists(), f"schema file not found at {schema_path}"


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


def test_build_duration_default_zero_when_absent(good_detection: dict) -> None:
    """A layer dict without 'duration_sec' defaults to exactly 0.0.

    Kills the ``.get('duration_sec', 0.0)`` default mutations (None / removed /
    1.0): only an absent-key test exercises that default.
    """
    without_duration = {"layer": "L1", "language": "php", "passed": True, "findings": []}
    result = build(
        [without_duration],
        {"python_version": "3.12", "concurrency": "auto", "ci": False},
        good_detection,
    )
    assert result["layers"][0]["duration_sec"] == 0.0


def test_build_with_layer_per_language_exact_value(good_detection: dict) -> None:
    """Kill 'per_language' key mutation (mutmut_21).
    The exact key name must be preserved; otherwise the layer entry won't have
    the expected per_language data."""
    layer_dict = {
        "layer": "L3A",
        "language": "python",
        "passed": True,
        "findings": [],
        "duration_sec": 0.5,
        "per_language": {"python": {"passed": True, "msi": 95.5}},
    }
    result = build([layer_dict], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    entry = result["layers"][0]
    # Assert per_language exact value and exact key — kills key-mutation mutants
    assert "per_language" in entry
    assert entry["per_language"]["python"]["passed"] is True
    assert entry["per_language"]["python"]["msi"] == 95.5


def test_build_with_layer_tool_specific_exact_value(good_detection: dict) -> None:
    """Kill 'tool_specific' key mutation (mutmut_28).
    The exact key name must be preserved."""
    layer_dict = {
        "layer": "L1",
        "language": "python",
        "passed": True,
        "findings": [],
        "duration_sec": 1.0,
        "tool_specific": {"version": "2.0", "flags": ["--strict"]},
    }
    result = build([layer_dict], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    entry = result["layers"][0]
    assert "tool_specific" in entry
    assert entry["tool_specific"]["version"] == "2.0"
    assert entry["tool_specific"]["flags"] == ["--strict"]


def test_detection_has_no_optional_mutation_field(good_detection: dict) -> None:
    """Kill 'mutation' key mutation in detection (mutmut_46, 77, 78, 79, 87, 94).
    These mutations affect detection.get("mutation") or if mutation is not None.
    When no mutation is provided, output should NOT have 'mutation' key.
    """
    result = build(
        [{"layer": "L3A", "language": "python", "passed": True, "findings": [], "duration_sec": 0.0}],
        {"python_version": "3.12", "concurrency": "auto", "ci": False},
        good_detection,
    )
    # No mutation in detection → no 'mutation' in output
    assert "mutation" not in result


def test_detection_with_mutation_field(good_detection: dict) -> None:
    """Kill 'mutation' key mutation (mutmut_46).
    When mutation IS in detection, output must have 'mutation' with correct value."""
    detection_with_mutation = {
        "repo_path": "/tmp/test",
        "language": "python",
        "framework": None,
        "confidence": 0.95,
        "mutation": {"total": 100, "killed": 95, "msi": 95.0},
    }
    result = build(
        [{"layer": "L3A", "language": "python", "passed": True, "findings": [], "duration_sec": 0.0}],
        {"python_version": "3.12", "concurrency": "auto", "ci": False},
        detection_with_mutation,
    )
    # mutation IS in detection → must appear in output
    assert "mutation" in result
    assert result["mutation"]["total"] == 100
    assert result["mutation"]["msi"] == 95.0


def test_build_duration_sec_zero_keeps_zero(good_detection: dict) -> None:
    """Kill 'duration_sec or 0.0 → 1.0' mutation (mutmut_46).

    When a layer dict provides duration_sec=0.0, the 'or 0.0' clause
    would evaluate to the mutated value (1.0). Assert exact value to kill it.
    """
    layer_dict = {
        "layer": "L1",
        "language": "php",
        "passed": True,
        "findings": [],
        "duration_sec": 0.0,
    }
    result = build([layer_dict], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    assert result["layers"][0]["duration_sec"] == 0.0, (
        f"Duration sec must be 0.0, got: {result['layers'][0]['duration_sec']}"
    )


def test_build_timestamp_is_valid_iso8601(good_detection: dict) -> None:
    """Kill 'timezone.utc → None' and strftime format mutations (mutmut_77, 78, 79).

    The timestamp must be a valid ISO 8601 date-time string. Changes to the format
    ('XX...', '%y-%m-%dt%h:%m:%sz') or timezone (None) would produce an invalid
    or different ISO string that this assertion catches.
    """
    result = build([], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    ts = result["timestamp"]
    # Must be a non-empty string matching ISO 8601 format YYYY-MM-DDTHH:MM:SSZ
    assert isinstance(ts, str)
    assert len(ts) == 20  # "2026-06-09T12:00:00Z"
    # Must match ISO 8601 pattern: YYYY-MM-DDTHH:MM:SSZ
    import re
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", ts), (
        f"Expected ISO 8601 timestamp, got: {ts}"
    )


def test_write_uses_indent_2_pretty_print(good_detection: dict, tmp_path: Path) -> None:
    """write() must use json.dumps(indent=2) — kills mutmut_12 (indent=None compact).

    Pretty-printed JSON with indent=2 contains '\\n  ' (newline + 2 spaces + key).
    Compact JSON (indent=None) is a single line with no '\\n  ' patterns.
    Uses a dict with an inner key to make the indented pattern observable.
    """
    # Use a data dict with nested structure so indent pattern is clear
    data: dict = {
        "version": "v2",
        "timestamp": "2026-06-11T00:00:00Z",
        "repository": "/tmp/test",
        "language": "python",
        "layers": [{"layer": "L1", "language": "python", "passed": True, "findings": [], "duration_sec": 0.5}],
        "mutation": {
            "total": 100, "killed": 95, "survived": 3, "timed_out": 1,
            "escaped": 0, "untested": 1, "msi": 95.0,
        },
    }
    target = tmp_path / "checkpoint.json"
    write(target, data)

    content = target.read_text(encoding="utf-8")

    # Pretty-printed JSON with indent=2 has '\\n  "key"' (newline + 2 spaces indent + key).
    # Compact JSON (indent=None) produces '{"version": "v2", ...}' — no newline-inside.
    assert '\n  "version"' in content
    assert '\n  "mutation"' in content

    # Also verify multi-line: must have at least as many newlines as top-level keys (5+)
    assert content.count("\n") >= 6, (
        f"Expected at least 6 newlines in pretty-printed JSON, got {content.count(chr(10))}. "
        "This suggests indent=None (compact JSON) was used instead of indent=2."
    )


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


def test_build_layer_missing_layer_key_uses_empty_string(good_detection: dict) -> None:
    """Kill lr.get('layer') → lr.get('layer') or 'XXXX' fallback mutation (mutmut_21).

    When the layer dict is missing the 'layer' key entirely, lr.get() returns None,
    and the fallback '' vs 'XXXX' is exercised. Assert it must be exactly ''."""
    layer_dict = {
        "language": "python",  # 'layer' intentionally omitted
        "passed": True,
        "findings": [],
        "duration_sec": 0.0,
    }
    result = build([layer_dict], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)
    assert result["layers"][0]["layer"] == "", (
        f"Missing 'layer' should default to empty string, got: {result['layers'][0]['layer']!r}"
    )


def test_validate_opens_schema_with_mode_r_explicit() -> None:
    """validate() must open the schema file with mode='r' explicitly.

    Kills mutmut_11 which removes the 'r' mode argument from
    `schema_path.open("r", encoding="utf-8")`.

    Technique H2 (spy): mock Path.open and assert the call args.
    Under the mutated code, open() has no positional "r" arg — the
    positional-arg ``is`` check fails the mutant.
    """
    from unittest.mock import mock_open

    m_open = mock_open(read_data='{"type": "object"}')
    with patch("pathlib.Path.open", m_open):
        validate({"any": "data"})
    # Pin: open() was called with "r" as the first positional arg
    assert m_open.call_args.args[0] == "r"


def test_build_layer_missing_language_key_uses_empty_string(good_detection: dict) -> None:
    """Kill lr.get('language') → lr.get('language') or 'XXXX' fallback mutation (mutmut_28).

    When the layer dict is missing the 'language' key entirely, lr.get() returns None,
    and the fallback '' vs 'XXXX' is exercised. Assert it must be exactly ''."""
    layer_dict = {
        "layer": "L3A",
        "passed": True,  # 'language' intentionally omitted
        "findings": [],
        "duration_sec": 0.0,
    }
    result = build(
        [layer_dict],
        {"python_version": "3.12", "concurrency": "auto", "ci": False},
        good_detection,
    )
    assert result["layers"][0]["language"] == "", (
        f"Missing 'language' should default to empty string, got: {result['layers'][0]['language']!r}"
    )


def test_validate_opens_schema_with_utf8_encoding_explicit(good_detection: dict) -> None:
    """validate() must open the schema file with encoding='utf-8' explicitly.

    Kills mutmut_10 (encoding=None). mutmut wraps strings as XXfooXX — even
    `assertIn 'utf-8' in encoding` would pass; we use kwargs pin instead.
    """
    from unittest.mock import mock_open

    data = build([], {"python_version": "3.12", "concurrency": "auto", "ci": False}, good_detection)

    m_open = mock_open(read_data='{"type": "object"}')
    with patch("pathlib.Path.open", m_open):
        validate(data)

    # The code calls schema_path.open("r", encoding="utf-8")
    # Under the mutant, encoding becomes None — this assert catches it.
    call_kwargs = m_open.call_args.kwargs
    assert call_kwargs.get("encoding") == "utf-8"


def test_build_calls_datetime_now_with_timezone_utc() -> None:
    """Kill 'datetime.now(timezone.utc) → datetime.now(None)' mutation (mutmut_79).

    When mutated to datetime.now(None), the call uses the local timezone instead
    of UTC — producing a DIFFERENT instant though the strftime format is identical.
    This spy verifies the argument to datetime.now() is timezone.utc.

    Technique: H2 (spy on dependency call args) + H1 (assertEqual exact).
    """
    from datetime import datetime, timezone as tz

    fixed_dt = datetime(2026, 6, 11, 12, 0, 0, tzinfo=tz.utc)

    with patch("harness_quality_gate.checkpoint.datetime") as dt_mock:
        dt_mock.now.return_value = fixed_dt
        dt_mock.timezone = tz  # module attribute, preserved for the build path

        result = build(
            [],
            {"python_version": "3.13", "concurrency": "seq", "ci": False},
            {"repo_path": "/x", "language": "python"},
        )

    # The spy must see datetime.now called with timezone.utc, NOT None.
    # Mutant calls datetime.now(None) — assert_called_with(timezone.utc) fails.
    dt_mock.now.assert_called_with(tz.utc)
    assert result["timestamp"] == "2026-06-11T12:00:00Z"


def test_build_repository_defaults_to_empty_string_when_repo_path_absent() -> None:
    """Kill mutmut_90: detection.get('repo_path') or '' → 'XXXX'.

    When 'repo_path' is absent from detection, data['repository'] must be ''
    (not 'XXXX'). The good_detection fixture always includes repo_path, so
    the fallback branch is currently untested.
    """
    result = build(
        [],
        {"python_version": "3.12", "concurrency": "auto", "ci": False},
        {"language": "python", "confidence": 0.9},  # no 'repo_path'
    )
    assert result["repository"] == "", (
        f"Missing 'repo_path' should default to empty string, got: {result['repository']!r}"
    )
