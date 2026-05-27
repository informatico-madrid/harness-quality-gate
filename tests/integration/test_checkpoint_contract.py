"""Contract validation tests for Checkpoint v2 JSON schema.

Loads worked-example JSONs from design.md (valid-php, valid-python,
valid-hybrid) and hand-crafted invalid examples, then validates each
against ``references/verdict-schema.json`` using ``jsonschema``.

Design: TD-8 (JSON Schema contract at references/verdict-schema.json)
Requirements: NFR-5, NFR-16, US-10
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "checkpoint-examples"
SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "references" / "verdict-schema.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    """Load and pre-validate the Checkpoint v2 JSON Schema."""
    s = json.load(SCHEMA_PATH.open())
    jsonschema.Draft202012Validator.check_schema(s)
    return s


@pytest.fixture(scope="module", params=["valid-php", "valid-python", "valid-hybrid"])
def valid_checkpoint(request, schema: dict) -> dict:
    """Parametrised fixture: load each worked-example from design.md."""
    path = FIXTURE_DIR / f"{request.param}.json"
    data = json.load(path.open())
    jsonschema.validate(data, schema)
    assert data["version"] == "v2"
    return data


# ---------------------------------------------------------------------------
# Positive: all valid examples must pass schema validation
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestValidExamples:
    """Each worked example from design.md validates against the schema."""

    def test_valid_php(self, schema: dict) -> None:
        """Worked example 1 (mono-PHP passing) validates."""
        data = json.load((FIXTURE_DIR / "valid-php.json").open())
        jsonschema.validate(data, schema)
        assert data["language"] == "php"
        assert data["version"] == "v2"

    def test_valid_python(self, schema: dict) -> None:
        """Worked example (mono-Python passing) validates."""
        data = json.load((FIXTURE_DIR / "valid-python.json").open())
        jsonschema.validate(data, schema)
        assert data["language"] == "python"
        assert data["version"] == "v2"

    def test_valid_hybrid(self, schema: dict) -> None:
        """Worked example 2 (hybrid repo) validates."""
        data = json.load((FIXTURE_DIR / "valid-hybrid.json").open())
        jsonschema.validate(data, schema)
        assert data["language"] == "hybrid"
        assert data["version"] == "v2"
        # per_language blocks present
        layer = data["layers"][0]
        assert "per_language" in layer
        assert "python" in layer["per_language"]
        assert "php" in layer["per_language"]


# ---------------------------------------------------------------------------
# Negative: each deliberately-invalid example must raise ValidationError
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestInvalidExamples:
    """Deliberately-invalid examples must fail validation."""

    def test_invalid_missing_language(self, schema: dict) -> None:
        """Missing required 'language' field → validation FAIL."""
        data = json.load((FIXTURE_DIR / "invalid-missing-language.json").open())
        assert "language" not in data
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, schema)

    def test_invalid_wrong_version(self, schema: dict) -> None:
        """schema_version must be const 'v2' — 'v1' is rejected."""
        data = json.load((FIXTURE_DIR / "invalid-wrong-version.json").open())
        assert data["version"] == "v1"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, schema)

    def test_invalid_malformed_per_language(self, schema: dict) -> None:
        """per_language values must be layerBlock objects, not strings."""
        data = json.load((FIXTURE_DIR / "invalid-malformed-perlang.json").open())
        py_block = data["layers"][0]["per_language"]["python"]
        assert isinstance(py_block, str), "fixture must have string (not object) for python block"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, schema)
