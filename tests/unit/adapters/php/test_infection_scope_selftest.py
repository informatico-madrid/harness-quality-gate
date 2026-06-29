"""Infection scope guard self-test (HRM-E5 / Story 5.3).

Verifies ``check_infection_scope()`` enforces that Infection's
``source.directories`` is exactly ``["src"]`` and never includes
oracle directories (features/, tests/, fixtures/).
"""

from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from harness_quality_gate.adapters.php.infection_scope_guard import (
    _load_infection_config,
    check_infection_scope,
)

# ---------------------------------------------------------------------------
# Fixtures — real fixture files
# ---------------------------------------------------------------------------

_FIXTURE_PASS = (
    Path(__file__).resolve().parents[4]
    / "tests"
    / "fixtures"
    / "php-pure-pass"
    / "infection.json5"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_infection_json5(
    tmp_dir: Path, directories: list[str], excludes: list[str] | None = None
) -> Path:
    """Write a minimal infection.json5 into *tmp_dir* and return the dir."""
    config: dict = {"source": {"directories": directories}}
    if excludes is not None:
        config["source"]["excludes"] = excludes
    # Write as JSON5 (comments + trailing commas are fine for our parser)
    json5_path = tmp_dir / "infection.json5"
    json5_path.write_text(
        json.dumps(config, indent=4) + "\n",
        encoding="utf-8",
    )
    return tmp_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCheckInfectionScope:
    """HRM-E5 self-test suite."""

    # ── GREEN: real fixture passes ──────────────────────────────────────

    def test_green_real_fixture_pass(self) -> None:
        """Load real ``php-pure-pass/infection.json5`` → no exception."""
        assert _FIXTURE_PASS.is_file(), f"Fixture missing: {_FIXTURE_PASS}"
        # Must parse the actual file — no mocks
        config = _load_infection_config(_FIXTURE_PASS.parent)
        assert config["source"]["directories"] == ["src"]
        check_infection_scope(_FIXTURE_PASS.parent)

    # ── RED: $schema URL truncated by naive comment regex ─────────────────

    def test_red_schema_url_not_truncated_by_comment_strip(self) -> None:
        """A $schema URL (https://...) must survive JSON5 comment-stripping.

        The naive ``//[^\n]*`` regex truncates ``https://...`` at ``//``,
        corrupting the JSON and raising ``JSONDecodeError`` (since the
        ``json5`` package is NOT installed in this repo, the fallback
        always runs).
        """
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "infection.json5"
            config_path.write_text(
                '{\n'
                '  "$schema": "https://raw.githubusercontent.com/infection/infection/0.29.0/resources/schema.json",\n'
                '  "source": {"directories": ["src"]}\n'
                '}\n',
                encoding="utf-8",
            )
            # Must not raise; URL preserved
            config = _load_infection_config(Path(tmp))
            assert config["$schema"].startswith(
                "https://raw.githubusercontent.com/infection/infection/0.29.0/resources/schema.json"
            ), f"$schema URL truncated by comment-stripping: {config['$schema']!r}"
            check_infection_scope(Path(tmp))  # valid ["src"] scope → no raise

    # ── RED: oracle directories in source.directories ───────────────────

    def test_red_features_in_dirs(self) -> None:
        """source.directories includes 'features' → RuntimeError."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_infection_json5(Path(tmp), ["src", "features"])
            with pytest.raises(RuntimeError, match="features"):
                check_infection_scope(Path(tmp))

    def test_red_tests_in_dirs(self) -> None:
        """source.directories includes 'tests' → RuntimeError."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_infection_json5(Path(tmp), ["src", "tests"])
            with pytest.raises(RuntimeError, match="tests"):
                check_infection_scope(Path(tmp))

    def test_red_fixtures_in_dirs(self) -> None:
        """source.directories includes 'fixtures' → RuntimeError."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_infection_json5(Path(tmp), ["src", "fixtures"])
            with pytest.raises(RuntimeError, match="fixtures"):
                check_infection_scope(Path(tmp))

    # ── RED: wildcard / parent directory ────────────────────────────────

    def test_red_wildcard_parent_dir(self) -> None:
        """source.directories: ['..'] → oracle-style RuntimeError."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_infection_json5(Path(tmp), [".."])
            with pytest.raises(RuntimeError, match="path-scope includes oracle directory"):
                check_infection_scope(Path(tmp))

    # ── WARNING: missing excludes (no failure) ──────────────────────────

    def test_warning_missing_excludes_no_fail(self) -> None:
        """source.directories: ['src'] but NO excludes → no raise, log warning."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_infection_json5(Path(tmp), ["src"], excludes=None)
            # Must NOT raise — missing excludes is a soft warning only
            check_infection_scope(Path(tmp))

    # ── PASS: excludes present ──────────────────────────────────────────

    def test_pass_excludes_present(self) -> None:
        """source.directories: ['src'] WITH excludes containing 'features' → clean."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_infection_json5(Path(tmp), ["src"], excludes=["features"])
            check_infection_scope(Path(tmp))

    # ── RED: not exactly ["src"] — extra arbitrary dir ──────────────────

    def test_red_extra_arbitrary_dir(self) -> None:
        """source.directories: ['src', 'lib'] → RuntimeError (not exact ['src'])."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_infection_json5(Path(tmp), ["src", "lib"])
            with pytest.raises(RuntimeError):
                check_infection_scope(Path(tmp))

    # ── RED: empty directories ──────────────────────────────────────────

    def test_red_empty_directories(self) -> None:
        """source.directories: [] → RuntimeError."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_infection_json5(Path(tmp), [])
            with pytest.raises(RuntimeError):
                check_infection_scope(Path(tmp))

    # ── RED: only src is missing ────────────────────────────────────────

    def test_red_src_only_other_dir(self) -> None:
        """source.directories: ['lib'] (no src) → RuntimeError."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_infection_json5(Path(tmp), ["lib"])
            with pytest.raises(RuntimeError):
                check_infection_scope(Path(tmp))

    # ── Mutant-killing: missing directories key ─────────────────────────

    def test_red_no_directories_key(self, tmp_path: Path) -> None:
        """source key present but directories key absent → RuntimeError not TypeError."""
        (tmp_path / "infection.json5").write_text(
            '{"source": {}}\n', encoding="utf-8"
        )
        with pytest.raises(RuntimeError):
            check_infection_scope(tmp_path)

    # ── Mutant-killing: oracle dir → specific error message ─────────────

    def test_red_oracle_dir_specific_message(self, tmp_path: Path) -> None:
        """Oracle dir triggers 'path-scope includes oracle directory' error."""
        _write_infection_json5(tmp_path, ["src", "features"])
        with pytest.raises(RuntimeError, match="path-scope includes oracle directory"):
            check_infection_scope(tmp_path)

    # ── Mutant-killing: glob/traversal patterns → specific error message ─

    def test_red_dot_dir(self, tmp_path: Path) -> None:
        """source.directories: ['.'] → oracle-style RuntimeError."""
        _write_infection_json5(tmp_path, ["."])
        with pytest.raises(RuntimeError, match="path-scope includes oracle directory"):
            check_infection_scope(tmp_path)

    def test_red_glob_star_dir(self, tmp_path: Path) -> None:
        """source.directories: ['*'] → oracle-style RuntimeError."""
        _write_infection_json5(tmp_path, ["*"])
        with pytest.raises(RuntimeError, match="path-scope includes oracle directory"):
            check_infection_scope(tmp_path)

    def test_red_glob_doublestar_dir(self, tmp_path: Path) -> None:
        """source.directories: ['**'] → oracle-style RuntimeError."""
        _write_infection_json5(tmp_path, ["**"])
        with pytest.raises(RuntimeError, match="path-scope includes oracle directory"):
            check_infection_scope(tmp_path)

    # ── Mutant-killing: non-oracle mismatch → specific error message ─────

    def test_red_extra_arbitrary_dir_exact_message(self, tmp_path: Path) -> None:
        """Non-oracle extra dir → 'source.directories must be exactly' message."""
        _write_infection_json5(tmp_path, ["src", "lib"])
        with pytest.raises(RuntimeError, match="source.directories must be exactly"):
            check_infection_scope(tmp_path)

    # ── Mutant-killing: warning for missing excludes ─────────────────────

    def test_warning_logged_for_missing_excludes(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No excludes → warning 'source.excludes is not configured' is logged."""
        _write_infection_json5(tmp_path, ["src"], excludes=None)
        import logging
        with caplog.at_level(logging.WARNING):
            check_infection_scope(tmp_path)
        messages = [r.message for r in caplog.records]
        assert any("source.excludes is not configured" in m for m in messages)

    def test_no_warning_when_excludes_include_features(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """excludes contains 'features' → no warning about excludes."""
        _write_infection_json5(tmp_path, ["src"], excludes=["features"])
        import logging
        with caplog.at_level(logging.WARNING):
            check_infection_scope(tmp_path)
        messages = [r.message for r in caplog.records]
        assert not any("source.excludes is not configured" in m for m in messages)
        assert not any("does not include 'features'" in m for m in messages)

    def test_warning_logged_when_excludes_missing_features(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """excludes present but 'features' absent → warning about missing 'features'."""
        _write_infection_json5(tmp_path, ["src"], excludes=["tests"])
        import logging
        with caplog.at_level(logging.WARNING):
            check_infection_scope(tmp_path)
        messages = [r.message for r in caplog.records]
        assert any("does not include 'features'" in m for m in messages)


class TestLoadInfectionConfig:
    """Mutation-killing tests for _load_infection_config's JSON5 parser."""

    def test_file_not_found_has_meaningful_message(self, tmp_path: Path) -> None:
        """Missing infection.json5 → FileNotFoundError with descriptive message."""
        empty_dir = tmp_path / "no_config_here"
        empty_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="infection.json5 not found"):
            _load_infection_config(empty_dir)

    def test_json5_full_line_comment_stripped(self, tmp_path: Path) -> None:
        """A full-line // comment is stripped so JSON parses cleanly."""
        (tmp_path / "infection.json5").write_text(
            '{\n'
            '  // this is a comment\n'
            '  "source": {"directories": ["src"]}\n'
            '}\n',
            encoding="utf-8",
        )
        config = _load_infection_config(tmp_path)
        assert config["source"]["directories"] == ["src"]

    def test_json5_trailing_comma_stripped(self, tmp_path: Path) -> None:
        """Trailing commas in arrays and objects are stripped before parsing."""
        (tmp_path / "infection.json5").write_text(
            '{"source": {"directories": ["src",],}}\n',
            encoding="utf-8",
        )
        config = _load_infection_config(tmp_path)
        assert config["source"]["directories"] == ["src"]

    def test_json5_library_used_when_available(self, tmp_path: Path) -> None:
        """When the json5 package is importable, it parses the file directly.

        json5 is NOT installed in this repo, so the fallback regex path is
        what normally runs. This test injects a stub ``json5`` module to
        exercise the library branch (``_json5.loads``) — covering the
        otherwise-unreachable import-success path.
        """
        sentinel = {"source": {"directories": ["src"]}}
        fake_json5 = types.ModuleType("json5")
        fake_json5.loads = lambda text: sentinel  # type: ignore[attr-defined]
        (tmp_path / "infection.json5").write_text(
            '{"source": {"directories": ["src"]}}\n', encoding="utf-8"
        )
        with patch.dict(sys.modules, {"json5": fake_json5}):
            config = _load_infection_config(tmp_path)
        assert config is sentinel
