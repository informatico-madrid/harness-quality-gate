"""E2E: PHP repos with missing critical tools exit 3 (INFRA_INCOMPLETE).

Replaces the old ``doctor``-subcommand tests: the infra-check now runs
inline in ``_cmd_all()`` (deliberate decision 69b05df — no doctor module).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _run_all(repo: Path, *extra: str, path: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PATH": path}
    return subprocess.run(
        [sys.executable, "-m", "harness_quality_gate", "all", str(repo), *extra],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        env=env,
        timeout=120,
    )


@pytest.fixture()
def bare_php_repo(tmp_path: Path) -> Path:
    """A composer.json-only repo: detected as PHP, no toolchain at all."""
    (tmp_path / "composer.json").write_text(
        '{"name": "test/infra-check"}', encoding="utf-8"
    )
    return tmp_path


@pytest.mark.e2e
def test_php_repo_without_toolchain_exits_3(bare_php_repo: Path) -> None:
    """No php/phpunit/phpstan/infection reachable → exit 3, not a crash."""
    result = _run_all(bare_php_repo, path="/nonexistent-bin")
    assert result.returncode == 3, (
        f"Expected exit 3 (INFRA_INCOMPLETE), got {result.returncode}. "
        f"stderr: {result.stderr[:500]}"
    )


@pytest.mark.e2e
def test_infra_payload_lists_missing_tools(bare_php_repo: Path) -> None:
    result = _run_all(bare_php_repo, "--json", path="/nonexistent-bin")
    assert result.returncode == 3
    data = json.loads(result.stdout)
    assert data["exit_code"] == 3
    assert data["missing_tools"] == ["php", "phpunit", "phpstan", "infection"]
    assert "Infraestructura PHP incompleta" in data["error"]


@pytest.mark.e2e
def test_php_runtime_present_but_tools_missing(bare_php_repo: Path) -> None:
    """With only the system PATH (php present, project tools absent) the
    missing list names the project toolchain, not the runtime."""
    if not Path("/usr/bin/php").exists():
        pytest.skip("system php not present at /usr/bin/php")
    result = _run_all(bare_php_repo, "--json", path="/usr/bin:/bin")
    assert result.returncode == 3
    data = json.loads(result.stdout)
    assert "php" not in data["missing_tools"]
    assert set(data["missing_tools"]) <= {"phpunit", "phpstan", "infection"}
    assert data["missing_tools"], "expected at least one missing project tool"


@pytest.mark.e2e
def test_python_repo_is_not_infra_gated(tmp_path: Path) -> None:
    """Python repos keep graceful degradation — never exit 3."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    result = _run_all(tmp_path, path="/usr/bin:/bin")
    assert result.returncode in (0, 1), (
        f"Python must not infra-gate, got {result.returncode}. "
        f"stderr: {result.stderr[:500]}"
    )
