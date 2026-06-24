"""Kill surviving XX-wrap log string mutations in harness_quality_gate.cli.

Strategy §H3: caplog.set_level(level, logger=...) + exact getMessage() assertion.

Kills:
  - checkpoint PASS value mutation (None/'XXPASSXX'/'pass')
  - LayerResult quick-pass field mutations (language=None, findings=None, duration=None)
  - runtime venv_activated mutation (None vs list)
  - getattr default removal (partial_run logic)
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from harness_quality_gate.cli import _cmd_all
from harness_quality_gate.exit_codes import FAIL, PASS
from harness_quality_gate.models import LayerResult


def _make_args(**kwargs):
    defaults = {"repo": ".", "json": False, "quiet": False, "paths": None}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _make_layer_result(**overrides):
    defaults = dict(
        layer="L3A",
        language="python",
        passed=True,
        findings=[],
        duration_sec=0.0,
    )
    defaults.update(overrides)
    return LayerResult(**defaults)


def _make_mock_adapter(*, passed: bool = True) -> MagicMock:
    adapter = MagicMock()
    lr = _make_layer_result(passed=passed)
    for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
        getattr(adapter, method).return_value = lr
    return adapter


class TestCheckpointPassField:
    """KILL: checkpoint PASS value mutations (None/'XXPASSXX'/'pass')."""

    def test_checkpoint_pass_is_true_when_all_layers_pass(self, tmp_path: Path) -> None:
        """checkpoint['PASS'] must be True (boolean), not None or string."""
        adapter = _make_mock_adapter(passed=True)
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path)))

        assert code == PASS

    def test_checkpoint_pass_is_false_when_layers_fail(self, tmp_path: Path) -> None:
        """checkpoint['PASS'] must be False when layers fail."""
        adapter = MagicMock()
        adapter.run_l3a.return_value = LayerResult(
            layer="L3A", language="python", passed=False, findings=[], duration_sec=0.0,
        )
        adapter.run_l1.return_value = LayerResult(
            layer="L1", language="python", passed=True, findings=[], duration_sec=0.0,
        )
        for method in ("run_l2", "run_l3b", "run_l4"):
            getattr(adapter, method).return_value = LayerResult(
                layer=method.replace("run_", "").upper(),
                language="python", passed=True, findings=[], duration_sec=0.0,
            )
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path)))

        assert code == FAIL


class TestQuickPassLayerResultFields:
    """KILL: LayerResult quick-pass field mutations (mutmut_146/148/149)."""

    def test_quick_pass_l2_fields_exact(self, tmp_path: Path) -> None:
        """Quick-pass L2: language='python', findings=[], duration_sec=0.0."""
        adapter = _make_mock_adapter(passed=True)
        adapter.run_l3a.return_value = LayerResult(
            layer="L3A", language="python", passed=True, findings=[], duration_sec=0.0,
        )
        adapter.run_l1.return_value = LayerResult(
            layer="L1", language="python", passed=True, findings=[], duration_sec=0.0,
        )
        args = _make_args(repo=str(tmp_path))
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(args)

        assert code == PASS

    def test_quick_pass_l3b_l4_fields_exact(self, tmp_path: Path) -> None:
        """Quick-pass L3B and L4 must also have correct fields."""
        adapter = _make_mock_adapter(passed=True)
        adapter.run_l3a.return_value = LayerResult(
            layer="L3A", language="python", passed=True, findings=[], duration_sec=0.5,
        )
        adapter.run_l1.return_value = LayerResult(
            layer="L1", language="python", passed=True, findings=[], duration_sec=1.0,
        )
        args = _make_args(repo=str(tmp_path))
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(args)

        assert code == PASS


class TestGetattrDefaultRemoval:
    """KILL: getattr default removal (mutmut_125)."""

    def test_partial_run_false_when_adapter_no_paths_attr(self, tmp_path: Path) -> None:
        """Adapter without 'paths' attr -> partial_run=False -> all 5 layers called."""
        adapter = MagicMock()
        del adapter.paths
        lr = _make_layer_result()
        for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
            getattr(adapter, method).return_value = lr

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path)))

        assert code == PASS
        assert adapter.run_l3a.called
        assert adapter.run_l1.called
        assert adapter.run_l2.called
        assert adapter.run_l3b.called
        assert adapter.run_l4.called

    def test_partial_run_true_when_adapter_has_paths(self, tmp_path: Path) -> None:
        """Adapter with 'paths' attr -> partial_run=True -> only L3A+L1 called."""
        adapter = MagicMock()
        adapter.paths = ["src/"]
        lr = _make_layer_result()
        for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
            getattr(adapter, method).return_value = lr

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path), paths=["src/"]))

        assert code == PASS
        assert adapter.run_l3a.called
        assert adapter.run_l1.called
        assert not adapter.run_l2.called
        assert not adapter.run_l3b.called
        assert not adapter.run_l4.called


class TestVenvWarningLogger:
    """KILL: logger.warning(_w) when _w is mutated to None (mutmut_7).

    Mutant §H3: logger.warning(None) instead of logger.warning(_w).
    caplog captures the full interpolated message via getMessage().
    """

    def test_venv_warning_logged_with_exact_message(self, tmp_path: Path, caplog) -> None:
        """_check_venv returns a warning string, logger.warning must log it.

        When _check_venv returns non-empty warnings (outside venv with
        .venv present), the CLI iterates and calls logger.warning(_w)
        for each.  If the mutant changes _w → None, getMessage() returns
        'None'.  Asserting the actual warning text kills this.
        """
        import logging

        expected_warning = (
            "Quality gate running from /fake/python "
            "(outside venv). Project has .venv at /repo/.venv/bin/python. "
            "Run ``source .venv/bin/activate`` and re-run, or use "
            "``.venv/bin/python -m harness_quality_gate all .``."
        )

        def fake_check_venv(repo: Path, language: str) -> list[str]:
            return [expected_warning]

        adapter = _make_mock_adapter(passed=True)
        args = _make_args(repo=str(tmp_path), paths=["src/"])

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
            patch(
                "harness_quality_gate.cli._check_venv",
                side_effect=fake_check_venv,
            ),
        ):
            caplog.set_level(logging.WARNING, logger="harness_quality_gate.cli")
            _cmd_all(args)

        messages = [r.getMessage() for r in caplog.records]
        assert expected_warning in messages

    def test_diagnostic_check_venv_called_with_repo_and_language(
        self, tmp_path: Path
    ) -> None:
        """The self-diagnostic passes the detected language through.

        Kills ``_check_venv(repo, language) -> _check_venv(repo, None)``: a
        fixed-return mock would swallow the wrong second argument, so we assert
        the first (diagnostic) call's exact positional arguments.
        """
        adapter = _make_mock_adapter(passed=True)
        args = _make_args(repo=str(tmp_path))
        mock_cv = MagicMock(return_value=[])

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
            patch("harness_quality_gate.cli._detect_language", return_value="python"),
            patch("harness_quality_gate.cli._check_venv", mock_cv),
        ):
            _cmd_all(args)

        expected_repo = Path(str(tmp_path)).resolve()
        # Both the self-diagnostic (line ~204) and the checkpoint runtime build
        # (line ~315) must pass the detected language, not None.
        assert mock_cv.call_args_list == [
            call(expected_repo, "python"),
            call(expected_repo, "python"),
        ]


class TestRuntimeDictAssertions:
    """KILL: runtime dict venv_activated mutation (None vs list)."""

    def test_runtime_venv_activated_is_list(self, tmp_path: Path) -> None:
        """runtime['venv_activated'] must be list, not None."""
        captured_venv = []

        def capture_build(*, layer_results, runtime, detection):
            nonlocal captured_venv
            captured_venv = runtime["venv_activated"]
            from harness_quality_gate.checkpoint import build as _build
            return _build(
                layer_results=layer_results, runtime=runtime, detection=detection
            )

        adapter = _make_mock_adapter(passed=True)
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
            patch("harness_quality_gate.cli.build_checkpoint", side_effect=capture_build),
        ):
            _cmd_all(_make_args(repo=str(tmp_path), quiet=True))

        assert isinstance(captured_venv, list)


# ===================================================================
# _cmd_all checkpoint writing — timestamped + latest files and the
# failure-path warnings (replaces the previous "equivalent" comments
# that left the whole region untested).
# ===================================================================

_CLI_LOGGER = "harness_quality_gate.cli"
_FIXED_NOW = datetime(2026, 6, 24, 13, 45, 7, tzinfo=timezone.utc)


def _freeze_cli_clock(monkeypatch) -> MagicMock:
    """Freeze cli.datetime.now to a fixed UTC instant and record its tz arg."""
    fake = MagicMock(wraps=datetime)
    fake.now.return_value = _FIXED_NOW
    monkeypatch.setattr("harness_quality_gate.cli.datetime", fake)
    return fake


class TestCmdAllCheckpointWriting:
    """Drive _cmd_all all the way through checkpoint persistence."""

    def test_timestamped_checkpoint_exact_name_and_utc(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The timestamped checkpoint lands in work/ with the exact UTC name.

        Kills the strftime-format mutants and ``now(timezone.utc) -> now(None)``.
        """
        fake = _freeze_cli_clock(monkeypatch)
        adapter = _make_mock_adapter(passed=True)
        with patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter):
            _cmd_all(_make_args(repo=str(tmp_path)))

        ts_file = (
            tmp_path / "_quality-gate" / "work"
            / "quality-gate-20260624T134507Z.json"
        )
        assert ts_file.exists()
        fake.now.assert_called_once_with(timezone.utc)

    def test_latest_checkpoint_exact_content(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The latest checkpoint is the exact indented JSON of the payload.

        Kills json.dumps arg mutants (None payload, indent, default=str) and the
        write_text encoding/content mutations.
        """
        _freeze_cli_clock(monkeypatch)
        adapter = _make_mock_adapter(passed=True)
        captured: dict = {}

        def cap_exit(code, data, *, quiet):
            captured["data"] = data
            return code

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli._exit_with", side_effect=cap_exit),
        ):
            _cmd_all(_make_args(repo=str(tmp_path)))

        latest = tmp_path / "_quality-gate" / "quality-gate-latest.json"
        assert latest.exists()
        assert latest.read_text(encoding="utf-8") == json.dumps(
            captured["data"], indent=2
        )

    def test_timestamped_write_failure_logs_exact(
        self, tmp_path: Path, caplog, monkeypatch
    ) -> None:
        """A failing timestamped write logs the exact warning with exc_info."""
        _freeze_cli_clock(monkeypatch)
        adapter = _make_mock_adapter(passed=True)
        caplog.set_level(logging.WARNING, logger=_CLI_LOGGER)
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch(
                "harness_quality_gate.cli.write_checkpoint",
                side_effect=OSError("disk full"),
            ),
        ):
            _cmd_all(_make_args(repo=str(tmp_path)))

        recs = [
            r for r in caplog.records
            if r.getMessage() == "Failed to write timestamped checkpoint"
        ]
        assert len(recs) == 1
        # exc_info=True captures the (type, value, tb) tuple; False/None do not.
        assert isinstance(recs[0].exc_info, tuple)

    def test_latest_write_failure_logs_exact(
        self, tmp_path: Path, caplog, monkeypatch
    ) -> None:
        """A failing latest write logs the exact warning with exc_info."""
        _freeze_cli_clock(monkeypatch)
        adapter = _make_mock_adapter(passed=True)
        caplog.set_level(logging.WARNING, logger=_CLI_LOGGER)
        real_write_bytes = Path.write_bytes

        def boom_latest(self: Path, *a, **k):
            if self.name == "quality-gate-latest.json":
                raise OSError("disk full")
            return real_write_bytes(self, *a, **k)

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch.object(Path, "write_bytes", boom_latest),
        ):
            _cmd_all(_make_args(repo=str(tmp_path)))

        recs = [
            r for r in caplog.records
            if r.getMessage() == "Failed to write latest checkpoint"
        ]
        assert len(recs) == 1
        assert isinstance(recs[0].exc_info, tuple)


class TestCmdAllPartialRunQuickPass:
    """Partial (--paths) runs synthesise the skipped layers exactly."""

    def test_quick_pass_layer_names_and_fields(self, tmp_path: Path) -> None:
        """L2/L3B/L4 are quick-passed with their exact names and empty fields.

        Kills the layer_names string mutants for the skipped layers and the
        ``findings=[]`` / ``duration_sec=0.0`` value mutants.
        """
        adapter = MagicMock()
        adapter.paths = ["src/foo.py"]
        adapter.run_l3a.return_value = LayerResult(
            layer="L3A", language="python", passed=True, findings=[],
            duration_sec=0.1,
        )
        adapter.run_l1.return_value = LayerResult(
            layer="L1", language="python", passed=True, findings=[],
            duration_sec=0.1,
        )
        captured: dict = {}

        def cap_exit(code, data, *, quiet):
            captured["data"] = data
            return code

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
            patch("harness_quality_gate.cli._exit_with", side_effect=cap_exit),
        ):
            _cmd_all(_make_args(repo=str(tmp_path), paths=["src/foo.py"]))

        layers = captured["data"]["layers"]
        assert [ld["layer"] for ld in layers] == ["L3A", "L1", "L2", "L3B", "L4"]
        for ld in layers[2:]:
            assert ld["findings"] == []
            assert ld["duration_sec"] == 0.0


class TestCliParserAndSingles:
    """Argparse help text + remaining _cmd_all passthrough/guard mutants."""

    @staticmethod
    def _all_subparser(parser):
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                return action.choices["all"]
        raise AssertionError("no 'all' subparser")

    def test_paths_help_text_exact(self) -> None:
        """The --paths help string is exact (kills the XX-wrap on it)."""
        from harness_quality_gate.cli import _build_parser

        parser = _build_parser()
        paths_action = next(
            a for a in self._all_subparser(parser)._actions if a.dest == "paths"
        )
        assert paths_action.help == (
            "Subset of files/dirs to scan — runs only Tier 1 (L3A + L1)"
        )

    def test_getattr_paths_default_when_adapter_lacks_attr(
        self, tmp_path: Path
    ) -> None:
        """With --paths set but an adapter lacking ``paths``, the default keeps
        the run alive (kills ``getattr(adapter, 'paths', None)`` -> no default,
        which would raise AttributeError)."""
        adapter = MagicMock()
        del adapter.paths
        lr = _make_layer_result()
        for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
            getattr(adapter, method).return_value = lr

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path), paths=["src/foo.py"]))

        assert code == PASS  # no AttributeError; partial_run resolved to False

    def test_repo_not_found_passes_quiet_through(self, tmp_path: Path) -> None:
        """The repo-not-found error honours the caller's quiet flag (kills
        ``quiet=args.quiet`` -> ``quiet=None`` on that early return)."""
        captured: dict = {}

        def cap_exit(code, data, *, quiet):
            captured["quiet"] = quiet
            return code

        missing = tmp_path / "does-not-exist"
        with patch("harness_quality_gate.cli._exit_with", side_effect=cap_exit):
            _cmd_all(_make_args(repo=str(missing), quiet=True))

        assert captured["quiet"] is True

    def test_invalid_paths_error_passes_quiet_through(self, tmp_path: Path) -> None:
        """The --paths validation error honours quiet (kills quiet=args.quiet
        -> quiet=None on that return)."""
        captured: dict = {}

        def cap_exit(code, data, *, quiet):
            captured["quiet"] = quiet
            return code

        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=MagicMock()),
            patch("harness_quality_gate.cli._exit_with", side_effect=cap_exit),
        ):
            _cmd_all(
                _make_args(repo=str(tmp_path), paths=["../evil"], quiet=True)
            )

        assert captured["quiet"] is True
