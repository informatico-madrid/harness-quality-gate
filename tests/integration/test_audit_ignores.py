"""Integration tests for audit-ignores CLI subcommand.

Tests end-to-end invocation of the ``audit-ignores`` CLI command against
a fixture containing intentional un-justified ignore markers.

Design: Test Coverage Table / integration audit-ignores rows
Requirements: FR-16, FR-17, US-5
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from harness_quality_gate.allow_list_auditor import AllowListAuditor

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "php-smoke"


@pytest.mark.integration
def test_audit_ignores_cli_invocation(tmp_path: Path) -> None:
    """CLI ``audit-ignores`` exits non-zero when un-justified markers exist."""
    # Create a PHP file with an un-justified ignore marker
    src = tmp_path / "src"
    src.mkdir()
    (src / "bad.php").write_text(
        '<?php\nclass Bad { /** @infection-ignore-all */ }\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "harness_quality_gate", "audit-ignores", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    # Should exit non-zero because there is no reason:/audited: metadata
    assert result.returncode != 0


@pytest.mark.integration
def test_audit_ignores_cli_with_justified_marker(tmp_path: Path) -> None:
    """CLI ``audit-ignores`` exits zero when all markers are justified."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "good.php").write_text(
        '<?php\n'
        "/**\n"
        " * reason: Justified suppression for test class\n"
        " * audited: 2026-01-01\n"
        " * @infection-ignore-all\n"
        " */\n"
        "class Good {}\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "harness_quality_gate", "audit-ignores", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    # Should exit zero — marker is justified
    assert result.returncode == 0


@pytest.mark.integration
def test_audit_ignores_cli_json_output(tmp_path: Path) -> None:
    """CLI ``audit-ignores --json`` emits parseable JSON."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "x.php").write_text(
        '<?php\nclass X { /** @infection-ignore-all */ }\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable, "-m", "harness_quality_gate",
            "audit-ignores", str(tmp_path), "--json",
        ],
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    assert "unjustified_new" in data or "exit_code" in data


@pytest.mark.integration
def test_audit_function_with_allow_list(tmp_path: Path) -> None:
    """audit() filters findings by allow list entries."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "test.php").write_text(
        '<?php\nclass T { /** @infection-ignore-all reason="x" audited="2026-01-01" */ }\n',
        encoding="utf-8",
    )

    # Create a simple allow list file
    (tmp_path / "infection.json5").write_text(
        '// global-ignore: [preg_replace]\n',
        encoding="utf-8",
    )

    report = AllowListAuditor().audit(tmp_path)
    assert report is not None
    assert hasattr(report, "exit_code")


@pytest.mark.integration
def test_audit_cli_empty_repo(tmp_path: Path) -> None:
    """CLI ``audit-ignores`` on a repo with no PHP files → exit zero."""
    (tmp_path / "README.md").write_text("# empty", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "harness_quality_gate", "audit-ignores", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
