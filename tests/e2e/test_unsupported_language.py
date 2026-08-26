"""E2E: unsupported languages stop before adapters and checkpoint writes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.mark.e2e
def test_declared_typescript_exits_2_without_touching_checkpoint(
    tmp_path: Path,
) -> None:
    (tmp_path / ".quality-gate-lang").write_text("typescript\n", encoding="utf-8")
    checkpoint_dir = tmp_path / "_quality-gate"
    checkpoint_dir.mkdir()
    sentinel = checkpoint_dir / "existing.json"
    sentinel.write_text("unchanged\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness_quality_gate",
            "all",
            str(tmp_path),
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=30,
    )

    assert result.returncode == 2
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "error": "unsupported project language: typescript",
        "language": "typescript",
        "supported_languages": ["python", "php"],
        "exit_code": 2,
    }
    assert sentinel.read_text(encoding="utf-8") == "unchanged\n"
    assert sorted(path.name for path in checkpoint_dir.iterdir()) == ["existing.json"]
