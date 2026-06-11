"""E2E smoke: full pipeline against the python-pure-pass fixture.

Exercises the real CLI process end to end, catching contract bugs that
mocked unit tests cannot see (parse() signature mismatches, dataclasses
leaking into JSON, schema-invalid checkpoints).

The fixture is copied to a temp dir so the in-tree fixture is never
polluted with ``_quality-gate/`` output.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "python-pure-pass"
_EXPECTED_LAYERS = ["L3A", "L1", "L2", "L3B", "L4"]


@pytest.fixture()
def python_repo(tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    shutil.copytree(_FIXTURE, target)
    return target


def _run_all(repo: Path, *extra: str, env: dict[str, str] | None = None,
             ) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness_quality_gate", "all", str(repo), *extra],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        env=env,
        timeout=300,
    )


@pytest.mark.e2e
def test_all_python_pure_pass_structure(python_repo: Path) -> None:
    """'all' completes without crashing and emits the 5-layer checkpoint."""
    result = _run_all(python_repo, "--json")
    assert result.returncode in (0, 1), (
        f"Expected PASS/FAIL, got {result.returncode}. stderr: {result.stderr[:800]}"
    )
    assert "Traceback" not in result.stderr, result.stderr[:800]

    data = json.loads(result.stdout)
    assert data["language"] == "python"
    assert data["version"] == "v2"
    assert [layer["layer"] for layer in data["layers"]] == _EXPECTED_LAYERS
    for layer in data["layers"]:
        assert layer["language"] == "python"
        assert isinstance(layer["passed"], bool)
        assert isinstance(layer["duration_sec"], (int, float))
        assert isinstance(layer["findings"], list)

    # P7 regression: MutationStats must arrive as a plain serialised dict.
    l1 = data["layers"][1]
    stats = l1["tool_specific"]["mutation_stats"]
    for field in ("total", "killed", "survived", "timed_out",
                  "escaped", "untested", "msi", "covered_msi"):
        assert isinstance(stats[field], (int, float)), f"{field} not numeric: {stats}"

    # L2 carries the diversity report.
    l2 = data["layers"][2]
    assert "diversity" in l2["tool_specific"]


@pytest.mark.e2e
def test_no_null_optional_fields_in_findings(python_repo: Path) -> None:
    """P8 regression: no finding may carry null optional fields."""
    result = _run_all(python_repo, "--json")
    data = json.loads(result.stdout)
    for layer in data["layers"]:
        for finding in layer["findings"]:
            for key, value in finding.items():
                assert value is not None, (
                    f"null {key!r} in finding of layer {layer['layer']}: {finding}"
                )


@pytest.mark.e2e
def test_checkpoint_written_and_schema_valid(python_repo: Path) -> None:
    """The latest checkpoint lands on disk and validates against the schema."""
    result = _run_all(python_repo, "--quiet")
    assert result.returncode in (0, 1), result.stderr[:800]

    latest = python_repo / "_quality-gate" / "quality-gate-latest.json"
    assert latest.is_file(), "quality-gate-latest.json was not written"
    data = json.loads(latest.read_text(encoding="utf-8"))

    # P9 regression: the timestamped checkpoint must also survive write().
    work = python_repo / "_quality-gate" / "work"
    timestamped = list(work.glob("quality-gate-*.json"))
    assert timestamped, "timestamped checkpoint was silently lost"

    sys.path.insert(0, str(_REPO_ROOT))
    try:
        from harness_quality_gate.checkpoint import validate
        validate(data)  # must not raise
    finally:
        sys.path.remove(str(_REPO_ROOT))


@pytest.mark.e2e
def test_restricted_path_degrades_gracefully(python_repo: Path) -> None:
    """With a minimal PATH the optional tools skip with warnings, no crash."""
    env = {**os.environ, "PATH": "/usr/bin:/bin"}
    result = _run_all(python_repo, "--json", env=env)
    assert result.returncode in (0, 1), (
        f"Expected graceful degradation, got {result.returncode}. "
        f"stderr: {result.stderr[:800]}"
    )
    data = json.loads(result.stdout)
    assert data["language"] == "python"
    assert [layer["layer"] for layer in data["layers"]] == _EXPECTED_LAYERS
