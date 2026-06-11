"""E2E smoke: full pipeline against the php-pure-pass fixture.

Requires the PHP toolchain (php + composer); skips cleanly when absent.
The fixture is copied to a temp dir and provisioned via ``composer install``
when its bin dir is incomplete, so the in-tree fixture stays pristine.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.needs_php, pytest.mark.needs_composer]

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "php-pure-pass"
_EXPECTED_LAYERS = ["L3A", "L1", "L2", "L3B", "L4"]
#: php-pure-pass uses composer config.bin-dir=bin
_CRITICAL_BINARIES = ("phpunit", "phpstan", "infection")


@pytest.fixture(scope="module")
def php_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("php") is None:
        pytest.skip("php not available on PATH")
    if shutil.which("composer") is None:
        pytest.skip("composer not available on PATH")

    target = tmp_path_factory.mktemp("php-smoke") / "repo"
    shutil.copytree(_FIXTURE, target)

    if not all((target / "bin" / tool).exists() for tool in _CRITICAL_BINARIES):
        install = subprocess.run(
            ["composer", "install", "--no-interaction", "--no-progress"],
            cwd=str(target),
            capture_output=True,
            text=True,
            timeout=600,
        )
        if install.returncode != 0:
            pytest.skip(
                f"composer install failed (offline?): {install.stderr[:300]}"
            )
    return target


def _run_all(repo: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness_quality_gate", "all", str(repo), *extra],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=600,
    )


def test_all_php_pure_pass_structure(php_repo: Path) -> None:
    """'all' on a provisioned PHP repo completes with the 5-layer checkpoint."""
    result = _run_all(php_repo, "--json")
    assert result.returncode in (0, 1), (
        f"Expected PASS/FAIL, got {result.returncode}. stderr: {result.stderr[:800]}"
    )
    assert "Traceback" not in result.stderr, result.stderr[:800]

    data = json.loads(result.stdout)
    assert data["language"] == "php"
    assert data["version"] == "v2"
    assert [layer["layer"] for layer in data["layers"]] == _EXPECTED_LAYERS
    for layer in data["layers"]:
        assert layer["language"] == "php"
        assert isinstance(layer["passed"], bool)
        assert isinstance(layer["duration_sec"], (int, float))
        assert isinstance(layer["findings"], list)


def test_layer_semantics_after_remap(php_repo: Path) -> None:
    """L2 findings come from weak-test; L3B from antipatterns/deptrac."""
    result = _run_all(php_repo, "--json")
    data = json.loads(result.stdout)
    layers = {layer["layer"]: layer for layer in data["layers"]}

    for finding in layers["L2"]["findings"]:
        assert finding.get("tool") == "weak-test-php", finding
    for finding in layers["L3B"]["findings"]:
        assert finding.get("tool") in ("antipattern-tier-a", "deptrac"), finding

    # L1 runs the Infection mutation gate; when stats are produced they are
    # plain serialised values (P7 regression guard).
    tool_specific = layers["L1"].get("tool_specific")
    if tool_specific is not None:
        json.dumps(tool_specific)


def test_checkpoint_written_and_schema_valid(php_repo: Path) -> None:
    result = _run_all(php_repo, "--quiet")
    assert result.returncode in (0, 1), result.stderr[:800]

    latest = php_repo / "_quality-gate" / "quality-gate-latest.json"
    assert latest.is_file(), "quality-gate-latest.json was not written"
    data = json.loads(latest.read_text(encoding="utf-8"))
    assert data["language"] == "php"

    sys.path.insert(0, str(_REPO_ROOT))
    try:
        from harness_quality_gate.checkpoint import validate
        validate(data)  # must not raise
    finally:
        sys.path.remove(str(_REPO_ROOT))
