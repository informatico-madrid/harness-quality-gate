"""Final straggler killers: checkpoint, config, base timeout-branch,
allow_list_auditor line numbers, and assorted exact pins."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from harness_quality_gate.checkpoint import build, write


def _valid_data(repository: str = "repo-ñ") -> dict:
    return {
        "version": "v2",
        "timestamp": "2026-01-01T00:00:00Z",
        "repository": repository,
        "language": "php",
        "layers": [],
    }


class TestCheckpointWriteKillers:
    def test_write_exact_payload_and_unicode(self, tmp_path: Path) -> None:
        data = _valid_data()
        target = tmp_path / "out.json"
        write(target, data)
        content = target.read_text(encoding="utf-8")
        assert content == json.dumps(data, indent=2, ensure_ascii=False)
        assert "repo-ñ" in content  # unicode stays unescaped

    def test_write_mkstemp_exact_kwargs(self, tmp_path: Path) -> None:
        target = tmp_path / "out.json"
        real = tempfile.mkstemp
        with patch(
            "harness_quality_gate.checkpoint.tempfile.mkstemp", side_effect=real,
        ) as spy:
            write(target, _valid_data())
        assert spy.call_args.kwargs == {
            "dir": str(tmp_path), "prefix": ".quality-gate-", "suffix": ".tmp",
        }

    def test_write_fdopen_utf8(self, tmp_path: Path) -> None:
        real = os.fdopen
        with patch("harness_quality_gate.checkpoint.os.fdopen", side_effect=real) as spy:
            write(tmp_path / "out.json", _valid_data())
        assert spy.call_args.kwargs == {"encoding": "utf-8"}
        assert spy.call_args.args[1] == "w"

    def test_write_latest_also_writes_timestamped_copy(self, tmp_path: Path) -> None:
        data = _valid_data()
        target = tmp_path / "quality-gate-latest.json"
        write(target, data)
        stamped = tmp_path / "quality-gate-2026-01-01T00:00:00Z.json"
        assert stamped.exists()
        assert stamped.read_text(encoding="utf-8") == target.read_text(encoding="utf-8")

    def test_write_non_latest_writes_single_file(self, tmp_path: Path) -> None:
        write(tmp_path / "other.json", _valid_data())
        assert sorted(p.name for p in tmp_path.iterdir()) == ["other.json"]


class TestCheckpointBuildKillers:
    def test_language_empty_when_detection_lacks_it(self) -> None:
        data = build(layer_results=[], runtime={}, detection={"repo_path": "/r"})
        assert data["language"] == ""
        assert data["repository"] == "/r"


class TestConfigLoadKillers:
    def test_load_decodes_utf8_content(self, tmp_path: Path) -> None:
        """Config bytes decode as UTF-8 (PyYAML auto-detects from ``read_bytes``).

        Behaviour pin (not an implementation-detail spy): a non-ASCII value must
        round-trip through ``load``. Any decoding regression — or YAML being fed
        the wrong bytes — corrupts ``source_dir`` and fails this assertion.
        """
        (tmp_path / ".quality-gate.yaml").write_text(
            "schema_version: 2\nsource_dir: configuración\n", encoding="utf-8",
        )
        from harness_quality_gate.config import load
        cfg = load(tmp_path)
        assert cfg.source_dir == "configuración"

    def test_validate_ci_env_vars_passthrough_and_empty_default(self) -> None:
        from harness_quality_gate.config import validate
        cfg = validate({"schema_version": 2, "concurrency": {"ci_env_vars": ["MY_CI"]}})
        assert cfg.concurrency.ci_env_vars == ["MY_CI"]
        cfg2 = validate({"schema_version": 2})
        assert cfg2.concurrency.ci_env_vars == []


class TestBaseRunTimeoutBranchKillers:
    def test_timeout_invocation_exact_with_fixed_clock(self) -> None:
        import subprocess
        from harness_quality_gate.adapters.base import ToolAdapter, ToolInvocation
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        fake_dt = MagicMock()
        fake_dt.now.side_effect = [t0, t0 + timedelta(seconds=1.23456)]
        exc = subprocess.TimeoutExpired(cmd="x", timeout=5, output=b"so-far", stderr=None)
        with (
            patch("harness_quality_gate.adapters.base.subprocess.run", side_effect=exc),
            patch("harness_quality_gate.adapters.base.datetime", fake_dt),
        ):
            result = ToolAdapter._run(["x"], timeout=5)
        assert result == ToolInvocation(
            stdout="so-far", stderr="TIMEOUT", exitcode=-1, duration_seconds=1.235,
        )


class TestAllowListLineNumbers:
    def test_unjustified_message_exact_line_number(self, tmp_path: Path) -> None:
        from harness_quality_gate.allow_list_auditor import AllowListAuditor
        (tmp_path / "m.py").write_text(
            "a = 1\nb = 2\nx = 3  # pragma: " "no mutate\n", encoding="utf-8",
        )
        report = AllowListAuditor(language="python").audit(tmp_path)
        assert report.findings, "must flag the unjustified pragma"
        assert (
            "Unjustified # pragma: " "no mutate at line 3: missing reason/audited metadata"
            == report.findings[0].message
        )

    def test_justified_message_exact_line_number(self, tmp_path: Path) -> None:
        from harness_quality_gate.allow_list_auditor import AllowListAuditor
        (tmp_path / "m.py").write_text(
            "# reason: equivalent\n# audited: 2026-06-11\nx = 3  # pragma: " "no mutate\n",
            encoding="utf-8",
        )
        report = AllowListAuditor(language="python").audit(tmp_path)
        justified = [f for f in report.findings if "Justified" in f.message]
        assert justified[0].message == "Justified # pragma: " "no mutate at line 3"


class TestCheckpointTimestampedEncoding:
    def test_timestamped_copy_written_utf8(self, tmp_path: Path) -> None:
        original = Path.write_text
        with patch.object(Path, "write_text", autospec=True, side_effect=original) as spy:
            write(tmp_path / "quality-gate-latest.json", _valid_data())
        assert spy.call_args.kwargs == {"encoding": "utf-8"}


class TestAllowListMetadataWindow:
    """The reason/audited tags must sit WITHIN the preceding window."""

    def test_metadata_outside_window_is_unjustified(self, tmp_path: Path) -> None:
        """Tags more than _METADATA_WINDOW lines before the pragma don't count.

        Kills ``start = max(0, i - _METADATA_WINDOW)`` -> ``start = None`` (which
        would scan ALL preceding lines and wrongly accept far-away metadata).
        """
        from harness_quality_gate.allow_list_auditor import AllowListAuditor

        (tmp_path / "m.py").write_text(
            "# reason: equivalent\n"
            "# audited: 2026-06-24\n"
            "a = 1\n"
            "b = 2\n"
            "c = 3\n"
            "d = 4\n"
            "e = 5\n"
            "x = 6  # pragma: " "no mutate\n",
            encoding="utf-8",
        )
        report = AllowListAuditor(language="python").audit(tmp_path)
        # The pragma (line 8) is 7 lines below the metadata → outside the
        # 5-line window → unjustified.
        assert report.exit_code == 1
        assert any("Unjustified" in f.message for f in report.findings)

    def test_metadata_inside_window_is_justified(self, tmp_path: Path) -> None:
        """Tags within the window justify the pragma (guards the same branch)."""
        from harness_quality_gate.allow_list_auditor import AllowListAuditor

        (tmp_path / "m.py").write_text(
            "# reason: equivalent\n"
            "# audited: 2026-06-24\n"
            "x = 6  # pragma: " "no mutate\n",
            encoding="utf-8",
        )
        report = AllowListAuditor(language="python").audit(tmp_path)
        assert report.exit_code == 0
