"""Shared fixtures for PHP adapter unit tests.

Provides a fixture that seeds `infection.json5` into `tmp_path` so
the HRM-E5 scope guard (Story 5.3) does not block existing tests
that rely on `tmp_path` as a repo root.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _seed_infection_config(tmp_path: Path) -> None:
    """Create a minimal ``infection.json5`` in ``tmp_path`` so that the
    HRM-E5 Infection scope guard passes for tests targeting ``run_l1``.

    This fixture runs automatically for every test in this directory.
    Tests that want to test the scope guard directly should override
    this fixture or write their own config.
    """
    config = {
        "source": {"directories": ["src"]},
        "minMsi": 100,
        "minCoveredMsi": 100,
    }
    (tmp_path / "infection.json5").write_text(
        json.dumps(config, indent=4) + "\n",
        encoding="utf-8",
    )
