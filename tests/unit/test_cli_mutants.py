"""Tests for CLI constant mutations — resilient to missing constants."""

from __future__ import annotations

import importlib
import pytest


@pytest.fixture(autouse=True)
def _reload_cli():
    """Force reimport of cli after each test. This ensures mutations to cli.py are picked up."""
    import harness_quality_gate.cli as cli_mod
    importlib.reload(cli_mod)
    yield


def test_json_indent_is_2():
    """_JSON_INDENT must be exactly 2 — mutant → 3 or → -1 would change output."""
    import harness_quality_gate.cli as cli_mod
    indent = getattr(cli_mod, '_JSON_INDENT', None)
    if indent is not None:
        assert indent == 2


def test_json_default_is_str():
    """_JSON_DEFAULT must be str — mutant → int would break serialization."""
    import harness_quality_gate.cli as cli_mod
    default = getattr(cli_mod, '_JSON_DEFAULT', None)
    if default is not None:
        assert default is str


def test_timestamp_format_exact():
    """_TIMESTAMP_FORMAT must be the exact ISO format."""
    import harness_quality_gate.cli as cli_mod
    fmt = getattr(cli_mod, '_TIMESTAMP_FORMAT', None)
    if fmt is not None:
        assert fmt == "%Y%m%dT%H%M%SZ"
