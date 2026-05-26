"""Unit tests for the allow-list audit engine.

Covers unjustified → non-zero exit; --diff-from → ignored in POC;
all-justified → exit 0; no markers → exit 0.
"""

from __future__ import annotations

from pathlib import Path

from harness_quality_gate.allow_list_auditor import AllowListAuditor


# ---------------------------------------------------------------------------
# Helpers — fixture-like via tmp_path (pytest)
# ---------------------------------------------------------------------------


def _write_php(tmp_path: Path, name: str, content: str) -> Path:
    """Write a .php file under tmp_path and return its path."""
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Unjustified → exit 1
# ---------------------------------------------------------------------------


def test_auditor_unjustified_no_metadata(tmp_path: Path) -> None:
    """@infection-ignore-all without reason/audited → exit 1."""
    _write_php(tmp_path, "test.php", """<?php
class Foo {
    // @infection-ignore-all
}
""")
    report = AllowListAuditor().audit(tmp_path)
    assert report.exit_code == 1
    warnings = [f for f in report.findings if f.severity == "warning"]
    assert len(warnings) >= 1


def test_auditor_missing_reason_only(tmp_path: Path) -> None:
    """Has audited but no reason → unjustified."""
    _write_php(tmp_path, "test.php", """<?php
/**
 * audited: 2026-01-01
 */
class Foo {
    // @infection-ignore-all
}
""")
    report = AllowListAuditor().audit(tmp_path)
    assert report.exit_code == 1


def test_auditor_missing_audited_only(tmp_path: Path) -> None:
    """Has reason but no audited → unjustified."""
    _write_php(tmp_path, "test.php", """<?php
/**
 * reason: test coverage
 */
class Foo {
    // @infection-ignore-all
}
""")
    report = AllowListAuditor().audit(tmp_path)
    assert report.exit_code == 1


# ---------------------------------------------------------------------------
# Justified → exit 0
# ---------------------------------------------------------------------------


def test_auditor_justified_marker(tmp_path: Path) -> None:
    """@infection-ignore-all with reason+audited → exit 0."""
    _write_php(tmp_path, "test.php", """<?php
/**
 * reason: test coverage
 * audited: 2026-01-01
 */
class Foo {
    // @infection-ignore-all
}
""")
    report = AllowListAuditor().audit(tmp_path)
    assert report.exit_code == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_auditor_no_markers(tmp_path: Path) -> None:
    """No @infection-ignore-all in repo → exit 0."""
    _write_php(tmp_path, "test.php", "<?php class Foo { public function test(): void {} }")
    report = AllowListAuditor().audit(tmp_path)
    assert report.exit_code == 0


def test_auditor_diff_from_ignored_in_poc(tmp_path: Path) -> None:
    """diff_from parameter is ignored in POC — still scans all files."""
    _write_php(tmp_path, "test.php", """<?php
class Foo {
    // @infection-ignore-all
}
""")
    report = AllowListAuditor().audit(tmp_path, diff_from="main")
    assert report.exit_code == 1


def test_auditor_summary(tmp_path: Path) -> None:
    """Summary includes counts of justified/unjustified."""
    _write_php(tmp_path, "test.php", """<?php
/**
 * reason: test coverage
 * audited: 2026-01-01
 */
class Foo {
    // @infection-ignore-all
}
""")
    _write_php(tmp_path, "test2.php", """<?php
class Bar {
    // @infection-ignore-all
}
""")
    report = AllowListAuditor().audit(tmp_path)
    assert "justified" in report.summary
    assert "unjustified" in report.summary
