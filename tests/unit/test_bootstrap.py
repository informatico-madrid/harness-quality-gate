"""Unit tests for harness_quality_gate.bootstrap.

Covers the public API: ToolCandidate, find_tool_candidates, resolve_tool,
validate_paths, detect_source_dir, suggest_max_children, and
ToolNotAvailable. The bootstrap module no longer installs or verifies
tools (per ``specs/php-support/decisions.md`` §1 — the LLM agent is the
installer; see ``steps/step-00-install.md`` §0.8 for the disambiguation
flow when multiple candidates exist).
"""

from __future__ import annotations

import logging
import os
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path
from unittest.mock import call, patch

import pytest

from harness_quality_gate.bootstrap import (
    PROVENANCE_OVERRIDE,
    PROVENANCE_PATH,
    PROVENANCE_VENDOR,
    PROVENANCE_VENV,
    VENV_BIN_DIR,
    ToolCandidate,
    ToolNotAvailable,
    detect_source_dir,
    find_tool_candidates,
    resolve_tool,
    suggest_max_children,
    validate_paths,
)


# ===================================================================
# ToolCandidate value object
# ===================================================================


class TestToolCandidate:
    """ToolCandidate(path, provenance) — frozen dataclass."""

    def test_construction_and_access(self) -> None:
        """Attributes are readable after construction."""
        c = ToolCandidate(path=Path("/usr/bin/ruff"), provenance="PATH")
        assert c.path == Path("/usr/bin/ruff")
        assert c.provenance == "PATH"

    def test_frozen_blocks_mutation(self) -> None:
        """Attempting to mutate raises FrozenInstanceError."""
        c = ToolCandidate(path=Path("/bin/x"), provenance="PATH")
        with pytest.raises(FrozenInstanceError):
            c.path = Path("/other")  # type: ignore[misc]

    def test_equality(self) -> None:
        """Two candidates with same path+provenance are equal (frozen → hashable)."""
        a = ToolCandidate(path=Path("/bin/x"), provenance="PATH")
        b = ToolCandidate(path=Path("/bin/x"), provenance="PATH")
        assert a == b
        assert hash(a) == hash(b)
        assert len({a, b}) == 1  # set semantics prove hash works

    def test_inequality_on_path(self) -> None:
        """Different path → not equal."""
        a = ToolCandidate(path=Path("/bin/x"), provenance="PATH")
        b = ToolCandidate(path=Path("/bin/y"), provenance="PATH")
        assert a != b

    def test_inequality_on_provenance(self) -> None:
        """Different provenance → not equal (kills XX-wrap mutants)."""
        a = ToolCandidate(path=Path("/bin/x"), provenance="PATH")
        b = ToolCandidate(path=Path("/bin/x"), provenance=".venv")
        assert a != b
        # Exact strings, not substrings — kills "PATH"→"XXPATHXX" mutants.
        assert a.provenance == "PATH"
        assert b.provenance == ".venv"
        assert a.provenance != "XXPATHXX"


# ===================================================================
# ToolNotAvailable — extended with `tried` list
# ===================================================================


class TestToolNotAvailableTried:
    """ToolNotAvailable now carries a `tried` list of checked paths."""

    def test_backward_compat_no_tried(self) -> None:
        """Constructor with only tool_name keeps the original message format."""
        exc = ToolNotAvailable("ruff")
        assert exc.tool_name == "ruff"
        assert exc.tried == []
        # Exact match — kills the "Tool not available: {tool_name!r}" XX-wrap
        # mutant (would become "XXTool not available: {tool_name!r}XX").
        assert str(exc) == "Tool not available: 'ruff'"

    def test_with_empty_tried_list(self) -> None:
        """Explicit empty tried list behaves like the no-arg case."""
        exc = ToolNotAvailable("ruff", tried=[])
        assert exc.tried == []
        assert str(exc) == "Tool not available: 'ruff'"

    def test_with_single_tried_path(self) -> None:
        """Single tried path is included in the message."""
        tried = [Path("/opt/custom/ruff")]
        exc = ToolNotAvailable("ruff", tried=tried)
        assert exc.tried == tried
        msg = str(exc)
        assert "Tool not available: 'ruff'" in msg
        # Exact path appears in the message.
        assert "/opt/custom/ruff" in msg
        # Format suffix marker is exact (kills "(tried: {paths})" mutants).
        assert "(tried: /opt/custom/ruff)" in msg

    def test_with_multiple_tried_paths_joined(self) -> None:
        """Multiple tried paths are joined with ", " in the message."""
        tried = [Path("/a/ruff"), Path("/b/ruff"), Path("/c/ruff")]
        exc = ToolNotAvailable("ruff", tried=tried)
        assert exc.tried == tried
        msg = str(exc)
        # Exact joined string — kills the ", " separator mutant.
        assert "(tried: /a/ruff, /b/ruff, /c/ruff)" in msg

    def test_is_runtime_error_subclass(self) -> None:
        """ToolNotAvailable stays a RuntimeError for back-compat with callers."""
        assert issubclass(ToolNotAvailable, RuntimeError)


# ===================================================================
# find_tool_candidates
# ===================================================================


def _make_executable(path: Path) -> Path:
    """Create an executable file at *path* and return the resolved path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o755, exist_ok=True)
    return path.resolve()


class TestFindToolCandidates:
    """find_tool_candidates(name, repo, *, preferred=None, vendor_bin=None)."""

    def test_no_candidates_returns_empty_list(self, tmp_path: Path) -> None:
        """Nothing on disk and nothing on PATH → empty list."""
        with patch("shutil.which", return_value=None):
            result = find_tool_candidates("ghost", tmp_path)
        assert result == []

    def test_venv_only(self, tmp_path: Path) -> None:
        """Only .venv/bin/<name> exists → one .venv candidate."""
        venv_bin = _make_executable(tmp_path / ".venv" / "bin" / "ruff")
        with patch("shutil.which", return_value=None):
            result = find_tool_candidates("ruff", tmp_path)
        assert len(result) == 1
        assert result[0] == ToolCandidate(path=venv_bin, provenance=".venv")

    def test_path_only(self, tmp_path: Path) -> None:
        """Only system PATH has it → one PATH candidate (must be executable)."""
        system_bin = _make_executable(tmp_path / "system" / "ruff")
        with patch("shutil.which", return_value=str(system_bin)):
            result = find_tool_candidates("ruff", tmp_path)
        assert len(result) == 1
        assert result[0] == ToolCandidate(
            path=system_bin.resolve(),
            provenance="PATH",
        )

    def test_venv_and_path_precedence(self, tmp_path: Path) -> None:
        """Both venv and PATH exist → venv first, PATH second."""
        venv_bin = _make_executable(tmp_path / ".venv" / "bin" / "ruff")
        system_bin = _make_executable(tmp_path / "system" / "ruff")
        with patch("shutil.which", return_value=str(system_bin)):
            result = find_tool_candidates("ruff", tmp_path)
        assert len(result) == 2
        # Exact order — kills reverse() and swap mutants.
        assert result[0].path == venv_bin
        assert result[0].provenance == ".venv"
        assert result[1].path == system_bin.resolve()
        assert result[1].provenance == "PATH"

    def test_vendor_bin_param(self, tmp_path: Path) -> None:
        """vendor_bin param adds a vendor candidate after venv."""
        venv_bin = _make_executable(tmp_path / ".venv" / "bin" / "ruff")
        vendor_bin = _make_executable(tmp_path / "vendor" / "bin" / "ruff")
        with patch("shutil.which", return_value=None):
            result = find_tool_candidates("ruff", tmp_path, vendor_bin="vendor/bin")
        assert len(result) == 2
        assert result[0].path == venv_bin
        assert result[0].provenance == ".venv"
        assert result[1].path == vendor_bin
        assert result[1].provenance == "vendor"

    def test_vendor_bin_param_relative_resolution(self, tmp_path: Path) -> None:
        """vendor_bin is relative to repo (not cwd).

        The contract: ``vendor_bin`` is resolved against ``repo``, not against
        ``os.getcwd()``. If the code used cwd, the result would be empty
        (no such file at ``<cwd>/vendor/bin/ruff``); instead it returns
        the file under ``tmp_path``.

        We do NOT patch ``os.getcwd`` here because mutmut's trampoline
        calls ``os.getcwd`` during import — patching it breaks the
        sandbox. The test still proves the point: the result is under
        ``tmp_path`` (the explicit repo), which cannot happen if the
        code resolved against any other directory.
        """
        _make_executable(tmp_path / "vendor" / "bin" / "ruff")
        with patch("shutil.which", return_value=None):
            result = find_tool_candidates("ruff", tmp_path, vendor_bin="vendor/bin")
        assert len(result) == 1
        assert result[0].path.resolve() == (tmp_path / "vendor" / "bin" / "ruff").resolve()
        assert result[0].provenance == "vendor"

    def test_vendor_bin_skipped_when_unset(self, tmp_path: Path) -> None:
        """vendor_bin=None → no vendor candidate even if vendor/bin/<name> exists."""
        _make_executable(tmp_path / "vendor" / "bin" / "ruff")
        with patch("shutil.which", return_value=None):
            result = find_tool_candidates("ruff", tmp_path)
        assert result == []

    def test_preferred_absolute_path(self, tmp_path: Path) -> None:
        """preferred with absolute path takes precedence over venv and PATH."""
        override_bin = _make_executable(tmp_path / "opt" / "my-ruff")
        venv_bin = _make_executable(tmp_path / ".venv" / "bin" / "ruff")
        system_bin = _make_executable(tmp_path / "system" / "ruff")
        with patch("shutil.which", return_value=str(system_bin)):
            result = find_tool_candidates(
                "ruff", tmp_path, preferred=str(override_bin)
            )
        assert len(result) == 3
        # Exact precedence: override > .venv > PATH.
        assert result[0].path == override_bin.resolve()
        assert result[0].provenance == "override"
        assert result[1].path == venv_bin
        assert result[1].provenance == ".venv"
        assert result[2].path == system_bin.resolve()
        assert result[2].provenance == "PATH"

    def test_preferred_relative_path_resolved_against_repo(self, tmp_path: Path) -> None:
        """preferred relative path is resolved against repo, not cwd.

        Same contract as ``test_vendor_bin_param_relative_resolution``:
        we do NOT patch ``os.getcwd`` (breaks mutmut's trampoline) and
        instead prove the point by asserting the result lives under the
        explicit ``tmp_path`` repo root.
        """
        override_bin = _make_executable(tmp_path / "tools" / "ruff")
        with patch("shutil.which", return_value=None):
            result = find_tool_candidates(
                "ruff", tmp_path, preferred="tools/ruff"
            )
        assert len(result) == 1
        assert result[0].path.resolve() == override_bin.resolve()
        assert result[0].provenance == "override"

    def test_preferred_pathobject_input(self, tmp_path: Path) -> None:
        """preferred accepts a Path object, not just a string."""
        override_bin = _make_executable(tmp_path / "opt" / "my-ruff")
        with patch("shutil.which", return_value=None):
            result = find_tool_candidates(
                "ruff", tmp_path, preferred=override_bin
            )
        assert len(result) == 1
        assert result[0].path == override_bin.resolve()
        assert result[0].provenance == "override"

    def test_preferred_nonexistent_is_filtered(self, tmp_path: Path) -> None:
        """A preferred path that doesn't exist is silently dropped."""
        venv_bin = _make_executable(tmp_path / ".venv" / "bin" / "ruff")
        with patch("shutil.which", return_value=None):
            result = find_tool_candidates(
                "ruff", tmp_path, preferred="/nonexistent/ruff"
            )
        # Falls through to venv.
        assert len(result) == 1
        assert result[0].path == venv_bin
        assert result[0].provenance == ".venv"

    def test_preferred_nonexecutable_is_filtered(self, tmp_path: Path) -> None:
        """A preferred path that exists but isn't executable is dropped."""
        # Venv entry is non-executable.
        non_exec = tmp_path / ".venv" / "bin" / "ruff"
        non_exec.parent.mkdir(parents=True, exist_ok=True)
        non_exec.touch(mode=0o644)
        # And pretend shutil.which returns the same path non-resolved.
        # (Edge case: the tool IS on PATH but our touch made it non-exec.)
        with patch("shutil.which", return_value=None):
            result = find_tool_candidates("ruff", tmp_path, preferred=str(non_exec))
        # Preferred is non-executable → filtered. Venv is non-executable → filtered.
        # shutil.which returns None → empty list.
        assert result == []

    def test_dedup_when_venv_points_to_path(self, tmp_path: Path) -> None:
        """Same resolved path from two sources → only the highest-precedence entry."""
        # Create a single file. Pretend shutil.which returns the same path
        # (resolved to the venv file).
        venv_bin = _make_executable(tmp_path / ".venv" / "bin" / "ruff")
        with patch("shutil.which", return_value=str(venv_bin)):
            result = find_tool_candidates("ruff", tmp_path)
        # Deduplicated: only the .venv candidate, not the PATH duplicate.
        assert len(result) == 1
        assert result[0].provenance == ".venv"

    def test_dedup_preserves_first_seen_provenance(self, tmp_path: Path) -> None:
        """When the same file appears in venv and vendor, venv wins (its provenance
        is the first-seen one)."""
        shared_bin = _make_executable(tmp_path / ".venv" / "bin" / "ruff")
        # Symlink vendor/bin/ruff → same venv file.
        vendor_path = tmp_path / "vendor" / "bin" / "ruff"
        vendor_path.parent.mkdir(parents=True, exist_ok=True)
        vendor_path.symlink_to(shared_bin)
        with patch("shutil.which", return_value=None):
            result = find_tool_candidates(
                "ruff", tmp_path, vendor_bin="vendor/bin"
            )
        # The symlink resolves to the same Path as the venv file → deduplicated.
        assert len(result) == 1
        assert result[0].provenance == ".venv"

    def test_venv_file_non_executable_filtered(self, tmp_path: Path) -> None:
        """A .venv/bin/<name> file without the executable bit is filtered out."""
        non_exec = tmp_path / ".venv" / "bin" / "ruff"
        non_exec.parent.mkdir(parents=True, exist_ok=True)
        non_exec.touch(mode=0o644)
        with patch("shutil.which", return_value=None):
            result = find_tool_candidates("ruff", tmp_path)
        assert result == []

    def test_vendor_file_non_executable_filtered(self, tmp_path: Path) -> None:
        """A vendored file without the executable bit is filtered out."""
        venv_bin = _make_executable(tmp_path / ".venv" / "bin" / "ruff")
        non_exec_vendor = tmp_path / "vendor" / "bin" / "ruff"
        non_exec_vendor.parent.mkdir(parents=True, exist_ok=True)
        non_exec_vendor.touch(mode=0o644)
        with patch("shutil.which", return_value=None):
            result = find_tool_candidates(
                "ruff", tmp_path, vendor_bin="vendor/bin"
            )
        # Only venv passes the executable check.
        assert len(result) == 1
        assert result[0] == ToolCandidate(path=venv_bin, provenance=".venv")

    def test_shutil_which_returning_none_for_phantom(self, tmp_path: Path) -> None:
        """shutil.which returns None → no PATH candidate."""
        with patch("shutil.which", return_value=None):
            result = find_tool_candidates("phantom", tmp_path)
        assert result == []

    def test_shutil_which_called_with_exact_name(self, tmp_path: Path) -> None:
        """Kills "ruff"→"XXruffXX" mutants — the literal name is passed."""
        with patch("shutil.which", return_value=None) as mock_which:
            find_tool_candidates("ruff", tmp_path)
        mock_which.assert_called_once_with("ruff")

    def test_provenance_constants_values(self) -> None:
        """PROVENANCE_* constants have exact expected values (kills XX-wrap
        mutants in the module-level constants)."""
        assert PROVENANCE_OVERRIDE == "override"
        assert PROVENANCE_VENV == ".venv"
        assert PROVENANCE_VENDOR == "vendor"
        assert PROVENANCE_PATH == "PATH"
        assert VENV_BIN_DIR == ".venv/bin"


# ===================================================================
# resolve_tool (extended with preferred and vendor_bin kwargs)
# ===================================================================


class TestResolveTool:
    """resolve_tool(name, repo, *, preferred=None, vendor_bin=None) -> Path."""

    def test_prefers_venv_bin(self, tmp_path: Path) -> None:
        """Should return .venv/bin/<name> when it exists and is executable."""
        tool_bin = tmp_path / ".venv" / "bin" / "ruff"
        tool_bin.parent.mkdir(parents=True, exist_ok=True)
        tool_bin.touch(mode=0o755, exist_ok=True)

        result = resolve_tool("ruff", tmp_path)
        assert result == tool_bin.resolve()

    def test_fallback_to_system_path(self, tmp_path: Path) -> None:
        """Should fallback to shutil.which when .venv/bin/<name> is missing.

        New contract (post-candidate-aware refactor): the PATH hit must
        pass the executability check too. We mock shutil.which to point
        at a real executable we create in tmp_path.
        """
        system_bin = _make_executable(tmp_path / "system" / "ruff")
        with patch("shutil.which", return_value=str(system_bin)):
            result = resolve_tool("ruff", tmp_path)

        assert result == system_bin.resolve()

    def test_raises_when_not_found(self, tmp_path: Path) -> None:
        """Should raise ToolNotAvailable when tool is not in .venv or system PATH."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(ToolNotAvailable) as exc_info:
                resolve_tool("bandit", tmp_path)
            assert "bandit" in str(exc_info.value)

    def test_venv_file_not_executable(self, tmp_path: Path) -> None:
        """Should fallback when .venv/bin/<name> exists but is not executable.

        New contract: the PATH candidate must also pass the executability
        check (we mock it to point at a real executable in tmp_path).
        """
        tool_bin = tmp_path / ".venv" / "bin" / "ruff"
        tool_bin.parent.mkdir(parents=True, exist_ok=True)
        tool_bin.touch(mode=0o644)  # not executable
        system_bin = _make_executable(tmp_path / "system" / "ruff")
        with patch("shutil.which", return_value=str(system_bin)):
            result = resolve_tool("ruff", tmp_path)

        assert result == system_bin.resolve()

    def test_called_with_exact_args(self) -> None:
        """resolve_tool calls os.access with the venv path AND with the PATH
        candidate (when both pass the executability check). The exact
        args (path, X_OK) matter for killing argument-passthrough mutants.
        """
        fake_repo = Path("/fake/repo")
        fake_venv_bin = fake_repo / ".venv" / "bin" / "ruff"
        fake_path_bin = Path("/fake/sys/ruff")

        def fake_is_file(self: Path) -> bool:
            return str(self) in (str(fake_venv_bin), str(fake_path_bin))

        with (
            patch.object(Path, "is_file", fake_is_file),
            patch("os.access", return_value=True) as mock_access,
            patch("shutil.which", return_value=str(fake_path_bin)),
        ):
            resolve_tool("ruff", fake_repo)

        # Both candidates are checked with exact (str, os.X_OK) args.
        expected_calls = [
            call(str(fake_venv_bin), os.X_OK),
            call(str(fake_path_bin), os.X_OK),
        ]
        assert mock_access.call_args_list == expected_calls

    def test_raises_on_missing_venv_with_path_in_error(self) -> None:
        """ToolNotAvailable message contains the tool name."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(ToolNotAvailable) as exc_info:
                resolve_tool("vulture", Path("/x"))
            assert "vulture" in exc_info.value.tool_name

    def test_preferred_overrides_venv(self, tmp_path: Path) -> None:
        """preferred (when valid) wins over .venv and PATH."""
        override_bin = _make_executable(tmp_path / "opt" / "my-ruff")
        _make_executable(tmp_path / ".venv" / "bin" / "ruff")
        with patch("shutil.which", return_value="/usr/bin/ruff"):
            result = resolve_tool("ruff", tmp_path, preferred=str(override_bin))
        assert result == override_bin.resolve()

    def test_preferred_invalid_falls_through_to_venv(self, tmp_path: Path) -> None:
        """preferred pointing to a non-existent path falls through to other candidates."""
        venv_bin = _make_executable(tmp_path / ".venv" / "bin" / "ruff")
        with patch("shutil.which", return_value=None):
            result = resolve_tool(
                "ruff", tmp_path, preferred="/nope/ruff"
            )
        assert result == venv_bin.resolve()

    def test_preferred_invalid_no_other_candidates_raises(self, tmp_path: Path) -> None:
        """preferred invalid AND no other candidates → ToolNotAvailable with
        `tried` listing preferred first then venv then PATH (none)."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(ToolNotAvailable) as exc_info:
                resolve_tool("ghost", tmp_path, preferred="/nope/ghost")
        assert exc_info.value.tool_name == "ghost"
        # The tried list has at least the preferred path.
        assert any(str(p) == "/nope/ghost" for p in exc_info.value.tried)

    def test_vendor_bin_kwarg_resolves_vendored(self, tmp_path: Path) -> None:
        """vendor_bin kwarg locates a tool in <repo>/<vendor_bin>/<name>."""
        vendor_bin = _make_executable(tmp_path / "tools" / "ruff")
        with patch("shutil.which", return_value=None):
            result = resolve_tool(
                "ruff", tmp_path, vendor_bin="tools"
            )
        assert result == vendor_bin.resolve()

    def test_no_candidates_raises_with_full_tried_list(self, tmp_path: Path) -> None:
        """When nothing exists anywhere, the exception's tried list contains
        venv path, vendor path (if vendor_bin), and PATH path (if shutil.which
        returns non-None). Exact ordering matters for the LLM-facing message."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(ToolNotAvailable) as exc_info:
                resolve_tool("missing", tmp_path)
        assert exc_info.value.tool_name == "missing"
        # Tried contains the venv location first.
        tried_strs = [str(p) for p in exc_info.value.tried]
        assert tried_strs[0] == str(tmp_path / ".venv" / "bin" / "missing")

    def test_no_candidates_with_shutil_which_hit(self, tmp_path: Path) -> None:
        """When shutil.which returns a path but no other source matches, the
        tried list still includes the PATH hit (so the LLM can show it)."""
        with patch("shutil.which", return_value="/usr/bin/ghost"):
            # .venv/bin/ghost does not exist, vendor_bin not set, but shutil.which hit.
            with pytest.raises(ToolNotAvailable) as exc_info:
                resolve_tool("ghost", tmp_path)
        tried_strs = [str(p) for p in exc_info.value.tried]
        # The PATH hit should appear (the find_tool_candidates filter rejects it
        # because Path("/usr/bin/ghost").is_file() is False on this test box,
        # but _build_tried_list still surfaces it).
        assert any("/usr/bin/ghost" in s for s in tried_strs)

    def test_no_candidates_with_vendor_bin(self, tmp_path: Path) -> None:
        """When vendor_bin is set, its location is included in the tried list."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(ToolNotAvailable) as exc_info:
                resolve_tool("missing", tmp_path, vendor_bin="vendor/bin")
        tried_strs = [str(p) for p in exc_info.value.tried]
        assert str(tmp_path / ".venv" / "bin" / "missing") in tried_strs
        assert str(tmp_path / "vendor" / "bin" / "missing") in tried_strs

    def test_preferred_relative_path_resolved_against_repo(self, tmp_path: Path) -> None:
        """preferred relative path is resolved against repo (not cwd).

        Same contract as the find_tool_candidates twin: assertion is on
        the resolved path living under the explicit ``tmp_path`` repo,
        not under whatever cwd might be. We do NOT patch ``os.getcwd``
        (it would break mutmut's trampoline at import time).
        """
        override_bin = _make_executable(tmp_path / "tools" / "ruff")
        with patch("shutil.which", return_value=None):
            result = resolve_tool("ruff", tmp_path, preferred="tools/ruff")
        assert result.resolve() == override_bin.resolve()

    def test_preferred_path_object_input(self, tmp_path: Path) -> None:
        """preferred accepts a Path object too."""
        override_bin = _make_executable(tmp_path / "opt" / "my-ruff")
        result = resolve_tool("ruff", tmp_path, preferred=override_bin)
        assert result == override_bin.resolve()

    def test_exception_carries_tried_paths_for_llm_disambiguation(
        self, tmp_path: Path
    ) -> None:
        """The exception's tried list is exactly what the LLM needs to
        present the user with the full picture — kills
        `_build_tried_list(...)` arg-passthrough mutants."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(ToolNotAvailable) as exc_info:
                resolve_tool("missing", tmp_path, preferred="custom/path")
        # Preferred path appears first in the tried list.
        tried_strs = [str(p) for p in exc_info.value.tried]
        assert tried_strs[0] == str(tmp_path / "custom" / "path")
        # venv path also appears.
        assert str(tmp_path / ".venv" / "bin" / "missing") in tried_strs


# ===================================================================
# detect_source_dir
# ===================================================================


class TestDetectSourceDir:
    """detect_source_dir(repo) -> str."""

    def test_returns_from_yaml_config(self, tmp_path: Path) -> None:
        """When quality-gate.yaml has source_dir, return it."""
        config = tmp_path / "_quality-gate" / "quality-gate.yaml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("source_dir: my_app\n", encoding="utf-8")
        # Create the source dir so validation passes
        (tmp_path / "my_app").mkdir()

        with patch("yaml.safe_load", return_value={"source_dir": "my_app"}):
            result = detect_source_dir(tmp_path)

        assert result == "my_app"

    def test_returns_src_when_exists(self, tmp_path: Path) -> None:
        """When src/ exists and no config, return "src"."""
        (tmp_path / "src").mkdir()

        result = detect_source_dir(tmp_path)
        assert result == "src"

    def test_empty_when_ambiguous(self, tmp_path: Path) -> None:
        """When no config, no src/, and multiple packages, return empty string."""
        qg_dir = tmp_path / "_quality-gate"
        qg_dir.mkdir(exist_ok=True)

        with patch("harness_quality_gate.adapters.base.package_dirs", return_value=["a", "b"]):
            result = detect_source_dir(tmp_path)
        assert result == ""

    def test_returns_single_package_index_0(self, tmp_path: Path) -> None:
        """When exactly one package detected, return package_dirs[0]
        (catches mutmut_18: pkgs[0]→pkgs[1])."""
        qg_dir = tmp_path / "_quality-gate"
        qg_dir.mkdir(exist_ok=True)

        with patch("harness_quality_gate.adapters.base.package_dirs", return_value=["my_pkg"]):
            result = detect_source_dir(tmp_path)

        assert result == "my_pkg"

    def test_returns_empty_when_no_source_detected(self, tmp_path: Path) -> None:
        """When no config, no src/, and no packages detected, return empty string.
        Catches mutmut_20: return '' → return 'XXXX'."""
        qg_dir = tmp_path / "_quality-gate"
        qg_dir.mkdir(exist_ok=True)

        with patch("harness_quality_gate.adapters.base.package_dirs", return_value=[]):
            result = detect_source_dir(tmp_path)

        assert result == ""
        assert result != "XXXX"

    def test_yaml_parse_error_logs_warning(self, tmp_path: Path, caplog) -> None:
        """YAML parse errors should log a warning."""
        config = tmp_path / "_quality-gate" / "quality-gate.yaml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("::::", encoding="utf-8")

        with patch("yaml.safe_load", side_effect=Exception("bad yaml")):
            detect_source_dir(tmp_path)

        assert any("Failed to read project config" in record.message for record in caplog.records)


# ===================================================================
# suggest_max_children
# ===================================================================


class TestSuggestMaxChildren:
    """suggest_max_children() -> int."""

    def test_returns_half_cpus(self) -> None:
        """Should return cpu_count // 2."""
        with patch("os.cpu_count", return_value=8):
            assert suggest_max_children() == 4

    def test_uses_default_when_cpu_count_none(self) -> None:
        """Should default to 2 when cpu_count returns None."""
        with patch("os.cpu_count", return_value=None):
            assert suggest_max_children() == 1

    def test_minimum_is_one(self) -> None:
        """Should never return less than 1 even if cpu_count is 1."""
        with patch("os.cpu_count", return_value=1):
            assert suggest_max_children() == 1

    def test_uses_default_when_few_cpus(self) -> None:
        """Should suggest at least 1 when cpu_count returns 2."""
        with patch("os.cpu_count", return_value=2):
            assert suggest_max_children() == 1

    def test_returns_int_not_float(self) -> None:
        """Should return int, not float from division.
        Catches mutmut_7: max(1, cpus // 2) → max(1, cpus / 2)."""
        with patch("os.cpu_count", return_value=8):
            result = suggest_max_children()
        assert isinstance(result, int), f"Expected int but got {type(result).__name__}"
        assert result == 4


# ===================================================================
# ToolNotAvailable
# ===================================================================


class TestToolNotAvailable:
    """ToolNotAvailable exception."""

    def test_message_contains_tool_name(self) -> None:
        """The exception message should include the tool name."""
        exc = ToolNotAvailable("ruff")
        assert exc.tool_name == "ruff"
        assert "ruff" in str(exc)

    def test_is_runtime_error(self) -> None:
        """ToolNotAvailable should be a subclass of RuntimeError."""
        assert issubclass(ToolNotAvailable, RuntimeError)


# ===================================================================
# New tests for security fix #1: validate_paths
# ===================================================================


class TestValidatePaths:
    """validate_paths validates --paths arguments for security."""

    def test_valid_relative_paths(self):
        """Relative paths should pass without raising."""
        # Should not raise
        validate_paths(["src/foo.py", "tests/"])

    def test_absolute_path_rejected(self) -> None:
        """Absolute paths should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            validate_paths(["/etc/passwd"])
        assert "/etc/passwd" in str(exc_info.value)

    def test_directory_traversal_rejected(self) -> None:
        """Paths containing .. (component-wise) should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            validate_paths(["../etc/passwd"])
        assert "../etc/passwd" in str(exc_info.value)

        with pytest.raises(ValueError) as exc_info:
            validate_paths(["foo/../../bar"])
        assert "foo/../../bar" in str(exc_info.value)

    def test_flag_like_rejected(self) -> None:
        """Flag-like strings (starting with -) should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            validate_paths(["--config"])
        assert "--config" in str(exc_info.value)

        with pytest.raises(ValueError) as exc_info:
            validate_paths(["-x"])
        assert "-x" in str(exc_info.value)

    def test_empty_list_allowed(self) -> None:
        """validate_paths([]) should pass (empty is OK — caller handles it)."""
        # Should not raise
        validate_paths([])

    def test_mixed_valid_invalid(self) -> None:
        """If one path is invalid among valids, should raise ValueError."""
        with pytest.raises(ValueError):
            validate_paths(["src/foo.py", "../bar", "tests/"])

    def test_null_byte_rejected(self) -> None:
        """Paths containing null bytes should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            validate_paths(["src/x\x00foo.py"])
        assert "null bytes are not allowed" in str(exc_info.value)


# ===================================================================
# New tests for security fix #6: containment check in detect_source_dir
# ===================================================================


class TestDetectSourceDirContainment:
    """detect_source_dir rejects YAML source_dir that escapes repo root."""

    def test_detect_source_dir_rejects_escaping_path(self, tmp_path: Path, caplog) -> None:
        """YAML source_dir: '../../../parent_dir' where parent_dir/ sits outside repo
        should be rejected (falls through to next detection method)."""
        # Create a directory one level ABOVE the repo, and symlink to it.
        # tmp_path will be something like /tmp/pytest-xxx/test_thing,
        # so its parent is /tmp/pytest-xxx/
        outside = tmp_path.parent / "outside_repo_dir"
        outside.mkdir(exist_ok=True)

        config = tmp_path / "_quality-gate" / "quality-gate.yaml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("source_dir: ../outside_repo_dir\n", encoding="utf-8")

        with (
            patch("yaml.safe_load", return_value={"source_dir": "../outside_repo_dir"}),
            caplog.at_level("WARNING"),
        ):
            result = detect_source_dir(tmp_path)

        # Should NOT return the escaped path — falls through to fallback
        assert result != "../outside_repo_dir"
        assert any("escapes repo root" in record.message for record in caplog.records)

    def test_detect_source_dir_accepts_valid_subdir(self, tmp_path: Path) -> None:
        """YAML source_dir: 'my_pkg' where my_pkg/ exists inside repo should return
        'my_pkg'."""
        config = tmp_path / "_quality-gate" / "quality-gate.yaml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("source_dir: my_pkg\n", encoding="utf-8")
        (tmp_path / "my_pkg").mkdir()

        with patch("yaml.safe_load", return_value={"source_dir": "my_pkg"}):
            result = detect_source_dir(tmp_path)

        assert result == "my_pkg"


# ===================================================================
# New tests for fixes (logging, validation)
# ===================================================================


class TestDetectSourceDirValidation:
    """detect_source_dir validates YAML source_dir against repo root."""

    def test_invalid_source_dir_returns_empty(self, tmp_path: Path, caplog) -> None:
        """YAML source_dir that doesn't exist as directory should return '' and log a warning.
        This catches the new validation logic: (repo / source_dir).is_dir() check."""
        config = tmp_path / "_quality-gate" / "quality-gate.yaml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("source_dir: nonexistent_pkg\n", encoding="utf-8")
        # Do NOT create nonexistent_pkg/ directory

        with (
            patch("yaml.safe_load", return_value={"source_dir": "nonexistent_pkg"}),
            caplog.at_level("WARNING"),
        ):
            result = detect_source_dir(tmp_path)

        assert result == ""
        assert any("does not exist as directory" in record.message for record in caplog.records)

    def test_valid_source_dir_returns_name(self, tmp_path: Path) -> None:
        """YAML source_dir that exists as directory should return its name."""
        config = tmp_path / "_quality-gate" / "quality-gate.yaml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("source_dir: my_app\n", encoding="utf-8")
        (tmp_path / "my_app").mkdir()

        with patch("yaml.safe_load", return_value={"source_dir": "my_app"}):
            result = detect_source_dir(tmp_path)

        assert result == "my_app"



# ===================================================================
# Mutant killers: exact-message logs + argument-passthrough wiring
# (replaces brittle substring/`any(...)` assertions that let
# XX-wrap, count, and passthrough mutants survive — see MUTANT_KILLING_GUIDE
# H1/H3/H7/H14)
# ===================================================================

_BOOT_LOGGER = "harness_quality_gate.bootstrap"


class TestDetectSourceDirExactWarnings:
    """detect_source_dir: exact warning text + package_dirs wiring."""

    def _write_config(self, repo: Path) -> Path:
        config = repo / "_quality-gate" / "quality-gate.yaml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("source_dir: x\n", encoding="utf-8")
        return config

    def test_escape_warning_exact_message(self, tmp_path: Path, caplog) -> None:
        """source_dir escaping the repo logs the exact warning (kills the
        source_dir_str->None passthrough and the escape-string mutants)."""
        self._write_config(tmp_path)
        with (
            patch("yaml.safe_load", return_value={"source_dir": "../evil"}),
            caplog.at_level(logging.WARNING, logger=_BOOT_LOGGER),
        ):
            result = detect_source_dir(tmp_path)

        assert result == ""
        messages = [r.getMessage() for r in caplog.records]
        assert (
            f"YAML source_dir '../evil' escapes repo root {tmp_path} — ignored"
            in messages
        )

    def test_does_not_exist_warning_exact_message(
        self, tmp_path: Path, caplog,
    ) -> None:
        """In-repo but non-directory source_dir logs the exact warning
        (kills source_candidate->None and the message XX-wrap / lowercase)."""
        self._write_config(tmp_path)
        with (
            patch("yaml.safe_load", return_value={"source_dir": "ghost"}),
            caplog.at_level(logging.WARNING, logger=_BOOT_LOGGER),
        ):
            result = detect_source_dir(tmp_path)

        assert result == ""
        source_candidate = tmp_path / "ghost"
        messages = [r.getMessage() for r in caplog.records]
        assert (
            f"YAML source_dir 'ghost' does not exist as directory in "
            f"{source_candidate}" in messages
        )

    def test_yaml_read_failure_exact_message(self, tmp_path: Path, caplog) -> None:
        """A parse failure logs the config path exactly (kills project_config
        ->None and the dropped-argument mutants)."""
        config = self._write_config(tmp_path)
        with (
            patch("yaml.safe_load", side_effect=ValueError("bad yaml")),
            caplog.at_level(logging.WARNING, logger=_BOOT_LOGGER),
        ):
            detect_source_dir(tmp_path)

        messages = [r.getMessage() for r in caplog.records]
        assert f"Failed to read project config {config}" in messages

    def test_package_dirs_called_with_repo(self, tmp_path: Path) -> None:
        """Step 3 resolves packages from the given repo (kills package_dirs(None))."""
        with patch(
            "harness_quality_gate.adapters.base.package_dirs", return_value=["solo"],
        ) as mock_pkg:
            result = detect_source_dir(tmp_path)

        assert result == "solo"
        mock_pkg.assert_called_once_with(tmp_path)


class TestDetectSourceDirRealYaml:
    def test_real_yaml_source_dir_round_trips(self, tmp_path: Path) -> None:
        """A real YAML config is actually read (kills safe_load(read_bytes())->safe_load(None))."""
        cfg = tmp_path / "_quality-gate" / "quality-gate.yaml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("source_dir: mypkg\n", encoding="utf-8")
        (tmp_path / "mypkg").mkdir()
        assert detect_source_dir(tmp_path) == "mypkg"

    def test_dict_without_source_dir_does_not_warn(
        self, tmp_path: Path, caplog
    ) -> None:
        """A dict lacking source_dir is skipped, not KeyError'd (kills and->or)."""
        cfg = tmp_path / "_quality-gate" / "quality-gate.yaml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("other: value\n", encoding="utf-8")
        caplog.set_level(logging.WARNING, logger=_BOOT_LOGGER)
        result = detect_source_dir(tmp_path)
        assert result == ""
        assert not any(
            "Failed to read project config" in r.getMessage()
            for r in caplog.records
        )
