"""Unit tests for harness_quality_gate.bootstrap.

Covers all public APIs: resolve_tool, detect_source_dir, suggest_max_children,
ensure_venv, install_tools, verify_tools, write_manifest, _get_version,
plus ToolNotAvailable and ToolCheckResult.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import fields as dataclass_fields
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.bootstrap import (
    PYTHON_TOOLS,
    ToolCheckResult,
    ToolNotAvailable,
    _get_version,
    detect_source_dir,
    ensure_venv,
    install_tools,
    resolve_tool,
    suggest_max_children,
    validate_paths,
    verify_tools,
    write_manifest,
)


# ===================================================================
# Test helpers
# ===================================================================


class _FakeCompletedProcess:
    """A minimal mock for subprocess.CompletedProcess."""

    def __init__(self, returncode=0, stdout="", stderr="") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ===================================================================
# resolve_tool
# ===================================================================


class TestResolveTool:
    """resolve_tool(name, repo) -> Path."""

    def test_prefers_venv_bin(self, tmp_path: Path) -> None:
        """Should return .venv/bin/<name> when it exists and is executable."""
        tool_bin = tmp_path / ".venv" / "bin" / "ruff"
        tool_bin.parent.mkdir(parents=True, exist_ok=True)
        tool_bin.touch(mode=0o755, exist_ok=True)

        result = resolve_tool("ruff", tmp_path)
        assert result == tool_bin.resolve()

    def test_fallback_to_system_path(self, tmp_path: Path) -> None:
        """Should fallback to shutil.which when .venv/bin/<name> is missing."""
        with patch("shutil.which", return_value="/usr/bin/ruff"):
            result = resolve_tool("ruff", tmp_path)

        assert result == Path("/usr/bin/ruff").resolve()

    def test_raises_when_not_found(self, tmp_path: Path) -> None:
        """Should raise ToolNotAvailable when tool is not in .venv or system PATH."""
        with (
            patch.object(Path, "is_file", return_value=False),
            patch("os.access", return_value=False),
            patch("shutil.which", return_value=None),
        ):
            with pytest.raises(ToolNotAvailable) as exc_info:
                resolve_tool("bandit", tmp_path)
            assert "bandit" in str(exc_info.value)

    def test_venv_file_not_executable(self, tmp_path: Path) -> None:
        """Should fallback when .venv/bin/<name> exists but is not executable."""
        tool_bin = tmp_path / ".venv" / "bin" / "ruff"
        tool_bin.parent.mkdir(parents=True, exist_ok=True)
        tool_bin.touch(mode=0o644)  # not executable

        with patch("shutil.which", return_value="/usr/bin/ruff"):
            result = resolve_tool("ruff", tmp_path)

        assert result == Path("/usr/bin/ruff").resolve()

    def test_called_with_exact_args(self) -> None:
        """resolve_tool calls os.access with exact (path, X_OK) on success."""
        fake_repo = Path("/fake/repo")
        fake_bin = fake_repo / ".venv" / "bin" / "ruff"

        with (
            patch.object(Path, "is_file", return_value=True),
            patch("os.access", return_value=True) as mock_access,
        ):
            resolve_tool("ruff", fake_repo)

        mock_access.assert_called_once_with(str(fake_bin), os.X_OK)

    def test_raises_on_missing_venv_with_path_in_error(self) -> None:
        """ToolNotAvailable message contains the tool name."""
        with (
            patch.object(Path, "is_file", return_value=False),
            patch("os.access", return_value=False),
            patch("shutil.which", return_value=None),
        ):
            with pytest.raises(ToolNotAvailable) as exc_info:
                resolve_tool("vulture", Path("/x"))
            assert "vulture" in exc_info.value.tool_name


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
# ensure_venv
# ===================================================================


class TestEnsureVenv:
    """ensure_venv(repo) -> Path."""

    def test_returns_existing_venv(self, tmp_path: Path) -> None:
        """When .venv already exists, return it without side effects."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()

        result = ensure_venv(tmp_path)
        assert result == venv_dir

    def test_creates_venv_when_missing(self, tmp_path: Path) -> None:
        """When .venv is missing, create it via python -m venv."""
        venv_dir = tmp_path / ".venv"

        with patch("subprocess.run") as mock_run:
            result = ensure_venv(tmp_path)

        assert result == venv_dir
        mock_run.assert_called_once_with(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True,
            capture_output=True,
            timeout=60,
        )

    def test_logs_creation_message(self, tmp_path: Path, caplog) -> None:
        """Should log an info message when creating the venv."""
        venv_dir = tmp_path / ".venv"

        with patch("subprocess.run"):
            with caplog.at_level("INFO"):
                ensure_venv(tmp_path)
                assert any("Creating .venv" in record.message for record in caplog.records)

    def test_does_not_call_venv_twice(self, tmp_path: Path) -> None:
        """Existing .venv should not trigger subprocess."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()

        with patch("subprocess.run") as mock_run:
            ensure_venv(tmp_path)
        mock_run.assert_not_called()


# ===================================================================
# install_tools
# ===================================================================


class TestInstallTools:
    """install_tools(repo) -> dict."""

    def test_skips_if_uv_not_found(self, tmp_path: Path) -> None:
        """When uv is not found, fall back to pip."""
        venv_dir = tmp_path / ".venv"
        venv_python = venv_dir / "bin" / "python"
        venv_python.parent.mkdir(parents=True, exist_ok=True)
        venv_python.touch()

        with (
            patch("subprocess.run", return_value=_FakeCompletedProcess(returncode=0)),
            patch("shutil.which", return_value=None),
            patch("sys.executable", str(venv_python)),
        ):
            results = install_tools(tmp_path)

        assert all(v == "installed" for v in results.values())
        assert list(results.keys()) == list(PYTHON_TOOLS.keys())

    def test_installs_with_uv_when_found(self, tmp_path: Path) -> None:
        """When uv is found, use it instead of pip."""
        venv_dir = tmp_path / ".venv"
        venv_python = venv_dir / "bin" / "python"
        venv_python.parent.mkdir(parents=True, exist_ok=True)
        venv_python.touch()
        uv_bin = Path("/usr/local/bin/uv")
        uv_bin.parent.mkdir(exist_ok=True)

        with (
            patch("subprocess.run", return_value=_FakeCompletedProcess(returncode=0)),
            patch("shutil.which", return_value=str(uv_bin)),
            patch("sys.executable", str(venv_python)),
        ):
            results = install_tools(tmp_path)

        assert "installed" in results.values()

    def test_failure_included_in_results(self, tmp_path: Path) -> None:
        """Failed installs should include error message."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir(exist_ok=True)

        with (
            patch("shutil.which", return_value="/fake/uv"),
            patch("subprocess.run", return_value=_FakeCompletedProcess(
                returncode=1, stderr=b"error: cannot find package",
            )),
        ):
            results = install_tools(tmp_path)

        assert any("failed:" in msg for msg in results.values())

    def test_failure_message_format(self, tmp_path: Path) -> None:
        """Error output should be trimmed to 200 chars with 'failed:' prefix
        (catches mutmut_40: [:200]→[:201])."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir(exist_ok=True)
        long_stderr = "x" * 300

        with (
            patch("shutil.which", return_value="/fake/uv"),
            patch("subprocess.run", return_value=_FakeCompletedProcess(
                returncode=1, stderr=long_stderr,
            )),
        ):
            results = install_tools(tmp_path)

        for name, msg in results.items():
            assert msg.startswith("failed: ")
            content = msg[len("failed: "):]
            assert len(content) == 200  # trimmed to exactly 200 chars

    def test_subprocess_run_calls_exact_commands(self, tmp_path: Path) -> None:
        """All subprocess.run calls must have correct command structure.
        Catches mutmut_2~11 (venv_python path string mutations),
        mutmut_14 (None in pip_cmd), mutmut_15~21 (pip_cmd string mutations),
        mutmut_25,26 (install string mutations)."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir(exist_ok=True)
        uv_bin = str(tmp_path / "bin" / "uv")

        with (
            patch("shutil.which", return_value=uv_bin),
            patch("subprocess.run", return_value=_FakeCompletedProcess(returncode=0)) as mock_run,
        ):
            install_tools(tmp_path)

        # ensure_venv already sees .venv exists, so all calls are from install loop
        assert len(mock_run.call_args_list) == len(PYTHON_TOOLS)

        for i, call in enumerate(mock_run.call_args_list):
            cmd = call.args[0]
            assert len(cmd) == 4, f"Call {i}: expected 4 args [uv pip install pkg], got {len(cmd)}: {cmd}"
            assert cmd[1] == "pip"       # catches mutmut_15 (XX-mXX), mutmut_16 (-M)
            assert cmd[2] == "install"   # catches mutmut_17 (XXpipXX), mutmut_18 (PIP)
            assert cmd[3] in PYTHON_TOOLS.values(), f"Call {i}: unexpected package {cmd[3]}"
            assert call.kwargs["capture_output"] is True
            assert call.kwargs["text"] is True
            assert call.kwargs["timeout"] == 120

    def test_subprocess_run_calls_exact_commands_when_fallback_pip(self, tmp_path: Path) -> None:
        """When uv is missing, pip_cmd uses venv_python -m pip path.
        Catches mutmut_7~9 (venv_python path string mutations in pip fallback),
        mutmut_27 (cmd arg removed), mutmut_40 (stderr slice bound)."""
        venv_dir = tmp_path / ".venv"
        venv_python = venv_dir / "bin" / "python"
        venv_python.parent.mkdir(parents=True, exist_ok=True)
        venv_python.touch()

        with (
            patch("shutil.which", return_value=None),
            patch("sys.executable", str(venv_python)),
            patch("subprocess.run", return_value=_FakeCompletedProcess(returncode=0)) as mock_run,
        ):
            install_tools(tmp_path)

        assert len(mock_run.call_args_list) == len(PYTHON_TOOLS)

        for i, call in enumerate(mock_run.call_args_list):
            cmd = call.args[0]
            assert len(cmd) == 5, f"Call {i}: expected 5 args [python -m pip install pkg], got {len(cmd)}: {cmd}"
            assert cmd[0] == str(venv_python)      # catches mutmut_2 (None), mutmut_6~9 (path mutations)
            assert cmd[1] == "-m"                   # catches mutmut_15 (XX-mXX), mutmut_16 (-M)
            assert cmd[2] == "pip"                  # catches mutmut_17 (XXpipXX), mutmut_18 (PIP)
            assert cmd[4] in PYTHON_TOOLS.values()  # catches mutmut_25,26 (XXpkgXX, Pkg)
            assert call.kwargs["capture_output"] is True
            assert call.kwargs["text"] is True
            assert call.kwargs["timeout"] == 120

    def test_subprocess_run_has_exact_kwargs(self, tmp_path: Path) -> None:
        """install_tools calls subprocess.run with exact keyword arguments."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir(exist_ok=True)

        with (
            patch("shutil.which", return_value="/fake/uv"),
            patch("subprocess.run", return_value=_FakeCompletedProcess(returncode=0)) as mock_run,
        ):
            install_tools(tmp_path)

        for call in mock_run.call_args_list:
            assert "capture_output" in call.kwargs
            assert call.kwargs["capture_output"] is True
            assert call.kwargs["text"] is True
            assert "timeout" in call.kwargs
            assert call.kwargs["timeout"] == 120

    def test_exception_handled(self, tmp_path: Path) -> None:
        """Exceptions during install should be caught and stored."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir(exist_ok=True)

        with (
            patch("shutil.which", return_value="/fake/uv"),
            patch("subprocess.run", side_effect=OSError("timeout")),
        ):
            results = install_tools(tmp_path)

        assert any("failed:" in msg and "timeout" in msg for msg in results.values())


# ===================================================================
# verify_tools
# ===================================================================


class TestVerifyTools:
    """verify_tools(repo) -> list."""

    def test_returns_list_of_all_tools(self, tmp_path: Path) -> None:
        """Should return exactly len(PYTHON_TOOLS) + 1 results."""
        fake_path = Path("/bin/fake")

        with (
            patch("harness_quality_gate.bootstrap.resolve_tool", return_value=fake_path),
            patch("harness_quality_gate.bootstrap._get_version", return_value="1.0.0"),
        ):
            results = verify_tools(tmp_path)

        assert len(results) == len(PYTHON_TOOLS) + 1

    def test_includes_pyright_name(self, tmp_path: Path) -> None:
        """Result names must include exact 'pyright' (catches mutmut_5: XXpyrightXX,
        mutmut_6: PYRIGHT)."""
        fake_path = Path("/bin/fake")

        with (
            patch("harness_quality_gate.bootstrap.resolve_tool", return_value=fake_path),
            patch("harness_quality_gate.bootstrap._get_version", return_value="1.0.0"),
        ):
            results = verify_tools(tmp_path)

        names = {r.name for r in results}
        assert "pyright" in names
        assert "PYRIGHT" not in names
        assert "XXpyrightXX" not in names

    def test_available_true_for_found_tools(self, tmp_path: Path) -> None:
        """Tools found via resolve_tool should have available=True."""
        fake_path = Path("/bin/fake")

        with (
            patch("harness_quality_gate.bootstrap.resolve_tool", return_value=fake_path),
            patch("harness_quality_gate.bootstrap._get_version", return_value="1.0.0"),
        ):
            results = verify_tools(tmp_path)

        for r in results:
            assert r.available is True

    def test_result_fields(self, tmp_path: Path) -> None:
        """Check that all fields are populated correctly.
        Catches mutmut_17: path=str(binary) -> str(None)."""
        fake_path = Path("/bin/fake")
        fake_str = str(fake_path)

        with (
            patch("harness_quality_gate.bootstrap.resolve_tool", return_value=fake_path),
            patch("harness_quality_gate.bootstrap._get_version", return_value="1.2.3"),
        ):
            results = verify_tools(tmp_path)

        for r in results:
            assert r.name is not None
            assert r.version is not None
            assert r.path is not None
            # str(None) returns the string "None", verify path is actual string from binary
            assert r.path == fake_str, f"Expected {fake_str!r} but got {r.path!r}"

    def test_available_true_with_path_content(self, tmp_path: Path) -> None:
        """Tools found via resolve_tool should have correct path and available=True.
        Catches str(None) mutations in verify_tools available branch."""
        fake_path = Path("/bin/fake")

        with (
            patch("harness_quality_gate.bootstrap.resolve_tool", return_value=fake_path),
            patch("harness_quality_gate.bootstrap._get_version", return_value="1.0.0"),
        ):
            results = verify_tools(tmp_path)

        for r in results:
            assert r.available is True
            assert r.path is not None and r.path != "None"

    def test_unavailable_tool_handled(self, tmp_path: Path) -> None:
        """Unavailable tools should have available=False."""
        with patch("harness_quality_gate.bootstrap.resolve_tool", side_effect=ToolNotAvailable("missing")):
            results = verify_tools(tmp_path)

        assert any(not r.available for r in results)

    def test_unavailable_tool_has_non_none_name_and_available(self, tmp_path: Path) -> None:
        """Unavailable tool entries must have name and available as proper types
        (catches mutmut_19: name=None, mutmut_20: available=None)."""
        with patch("harness_quality_gate.bootstrap.resolve_tool", side_effect=ToolNotAvailable("missing")):
            results = verify_tools(tmp_path)

        for r in results:
            assert r.name is not None and not isinstance(r.name, type(None).__class__), \
                f"ToolEntry {r.name} has None name (mutmut_19)"
            assert r.available is not None and isinstance(r.available, bool), \
                f"ToolEntry {r.name} has None available (mutmut_20)"
            assert not r.available
            assert r.version is None
            assert r.path is None


# ===================================================================
# _get_version
# ===================================================================


class TestGetVersion:
    """_get_version(binary) -> str or None."""

    def test_returns_first_line(self) -> None:
        """Should return the first line of --version output."""
        fake_binary = Path("/bin/fake")

        with patch("subprocess.run", return_value=_FakeCompletedProcess(
            stdout="ruff 0.8.0\nruff-something-else",
        )):
            result = _get_version(fake_binary)

        assert result == "ruff 0.8.0"

    def test_returns_none_on_failure(self) -> None:
        """Should return None when both stdout and stderr are empty (no output at all)."""
        fake_binary = Path("/bin/fake")

        with patch("subprocess.run", return_value=_FakeCompletedProcess(
            returncode=1, stdout="", stderr="",
        )):
            result = _get_version(fake_binary)

        assert result is None

    def test_returns_none_on_exception(self) -> None:
        """Should return None when subprocess raises."""
        fake_binary = Path("/bin/fake")

        with patch("subprocess.run", side_effect=OSError("boom")):
            result = _get_version(fake_binary)

        assert result is None

    def test_subprocess_run_called_with_exact_args(self) -> None:
        """Verify exact subprocess.run command and all kwargs
        (catches mutmut_2:cmd→None, _5:timeout→None, _6:cmd removed,
        _10:str(None), _11:XX--versionXX, _12:--VERSION, _15:timeout=11)."""
        fake_path = Path("/bin/test")

        with (
            patch("subprocess.run", return_value=_FakeCompletedProcess(stdout="0.1.0")) as mock_run,
        ):
            _get_version(fake_path)

        mock_run.assert_called_once_with(
            [str(fake_path), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_falls_back_to_stderr(self) -> None:
        """When stdout is empty, should fallback to stderr and return first line."""
        fake_binary = Path("/bin/fake")

        with patch("subprocess.run", return_value=_FakeCompletedProcess(
            returncode=0, stdout="", stderr="version 1.0.0\nextra",
        )):
            result = _get_version(fake_binary)

        assert result == "version 1.0.0"


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
# ToolCheckResult
# ===================================================================


class TestToolCheckResult:
    """ToolCheckResult dataclass."""

    def test_has_expected_fields(self) -> None:
        """Should have name, available, version, path fields."""
        field_names = {f.name for f in dataclass_fields(ToolCheckResult)}
        assert field_names == {"name", "available", "version", "path"}

    def test_serialization(self) -> None:
        """Should behave like a standard dataclass."""
        result = ToolCheckResult(name="ruff", available=True, version="1.0", path="/bin/ruff")
        assert result.name == "ruff"
        assert result.available is True

    def test_none_fields_allowed(self) -> None:
        """version and path can be None."""
        result = ToolCheckResult(name="ruff", available=False, version=None, path=None)
        assert result.version is None
        assert result.path is None


# ===================================================================
# write_manifest
# ===================================================================


class TestWriteManifest:
    """write_manifest(repo) -> path, writes JSON."""

    def test_writes_correct_json_structure(self, tmp_path: Path) -> None:
        """Manifest JSON has correct key names and structure."""
        checks = [
            ToolCheckResult(name="ruff", available=True, version="0.8.0", path="/.venv/bin/ruff"),
            ToolCheckResult(name="pyright", available=False, version=None, path=None),
        ]
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir(exist_ok=True)

        with (
            patch("harness_quality_gate.bootstrap.ensure_venv", return_value=venv_dir),
            patch("harness_quality_gate.bootstrap.verify_tools", return_value=checks),
        ):
            result_path = write_manifest(tmp_path)

        assert result_path.exists()
        assert result_path == tmp_path / ".venv" / "hqg-tools-manifest.json"

        data = json.loads(result_path.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == 2

        ruff_entry = data[0]
        assert ruff_entry["name"] == "ruff"
        assert ruff_entry["version"] == "0.8.0"
        assert ruff_entry["path"] == "/.venv/bin/ruff"
        assert ruff_entry["available"] is True

        pyright_entry = data[1]
        assert pyright_entry["name"] == "pyright"
        assert pyright_entry["version"] is None
        assert pyright_entry["path"] is None
        assert pyright_entry["available"] is False

    def test_returns_manifest_path(self, tmp_path: Path) -> None:
        """Must return the exact path to the manifest file."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir(exist_ok=True)

        checks = [ToolCheckResult(name="ruff", available=True, version=None, path=None)]

        with (
            patch("harness_quality_gate.bootstrap.ensure_venv", return_value=venv_dir),
            patch("harness_quality_gate.bootstrap.verify_tools", return_value=checks),
        ):
            result = write_manifest(tmp_path)

        assert isinstance(result, Path)
        assert result == tmp_path / ".venv" / "hqg-tools-manifest.json"

    def test_manifest_indentation(self, tmp_path: Path) -> None:
        """Manifest uses indent=2 for pretty printing."""
        checks = [
            ToolCheckResult(name="ruff", available=True, version="1.0", path="/bin/ruff")
        ]
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir(exist_ok=True)

        with (
            patch("harness_quality_gate.bootstrap.ensure_venv", return_value=venv_dir),
            patch("harness_quality_gate.bootstrap.verify_tools", return_value=checks),
        ):
            result = write_manifest(tmp_path)

        assert isinstance(result, Path)
        assert result == tmp_path / ".venv" / "hqg-tools-manifest.json"

        content = (tmp_path / ".venv" / "hqg-tools-manifest.json").read_text()
        # indent=2 produces "\n  {" pattern, indent=3 would produce "\n   {"
        # Check for the indented opening brace
        lines = content.split("\n")
        first_indented = next((l for l in lines if l.startswith("  ")), None)
        assert first_indented is not None
        # Must start with exactly 2 spaces, not 3 or more
        stripped = first_indented.lstrip(" ")
        leading = len(first_indented) - len(stripped)
        assert leading == 2

    def test_manifest_contains_all_tool_entries(self, tmp_path: Path) -> None:
        """write_manifest should produce JSON with entries for every tool."""
        checks = []
        for tool_name in PYTHON_TOOLS:
            checks.append(ToolCheckResult(name=tool_name, available=True, version="1.0", path="/b/x"))
        checks.append(ToolCheckResult(name="pyright", available=True, version="2.0", path="/b/pyright"))
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir(exist_ok=True)

        with (
            patch("harness_quality_gate.bootstrap.ensure_venv", return_value=venv_dir),
            patch("harness_quality_gate.bootstrap.verify_tools", return_value=checks),
        ):
            manifest_path = write_manifest(tmp_path)

        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        names = {entry["name"] for entry in data}
        for tool_name in PYTHON_TOOLS:
            assert tool_name in names
        assert "pyright" in names

    def test_manifest_encode_lowercase_utf8(self, tmp_path: Path) -> None:
        """Must use lowercase 'utf-8' encoding key (catches mutmut_23: 'utf-8'→'UTF-8').
        Intercepts write_text to capture the encoding value."""
        # We need to intercept write_text to verify the encoding kwarg.
        # Mutmut mutation: encoding="utf-8" → encoding="UTF-8"
        write_calls = []

        original_write_text = Path.write_text
        def capture_write_text(self, content, *args, **kwargs):
            write_calls.append(kwargs)
            return original_write_text(self, content, *args, **kwargs)

        checks = [
            ToolCheckResult(name="ruff", available=True, version="0.8.0", path="/.venv/bin/ruff"),
        ]
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir(exist_ok=True)

        with (
            patch("harness_quality_gate.bootstrap.ensure_venv", return_value=venv_dir),
            patch("harness_quality_gate.bootstrap.verify_tools", return_value=checks),
            patch("pathlib.Path.write_text", capture_write_text),
        ):
            write_manifest(tmp_path)

        # find the write call for the manifest file
        encoding_used = None
        for kwargs in write_calls:
            # write_calls captures all write_text calls, include venv dir creation
            if "encoding" in kwargs:
                encoding_used = kwargs["encoding"]

        # The key test: encoding must be lowercase "utf-8"
        # If mutmut_23 is active, it would be "UTF-8" and we assert differently
        # Since both are byte-equivalent, we assert the literal string to catch the mutation
        assert encoding_used == "utf-8", f"Expected 'utf-8' but got {encoding_used!r}"


# ===================================================================
# Integration-style: end-to-end flow of public APIs
# ===================================================================


class TestEndToEndFlow:
    """Test that public functions compose correctly together."""

    def test_install_tools_produces_dict_with_all_keys(self, tmp_path: Path) -> None:
        """Return dict must contain all PYTHON_TOOLS keys."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir(parents=True, exist_ok=True)
        venv_python = venv_dir / "bin" / "python"
        venv_python.parent.mkdir(parents=True, exist_ok=True)
        venv_python.touch()

        def mock_run(cmd, *args, **kwargs):
            return _FakeCompletedProcess(returncode=0)

        with (
            patch("subprocess.run", side_effect=mock_run),
            patch("sys.executable", str(venv_python)),
        ):
            results = install_tools(tmp_path)

        for key in PYTHON_TOOLS:
            assert key in results

    def test_verify_tools_with_mocked_resolve(self, tmp_path: Path) -> None:
        """verify_tools should return exactly len(PYTHON_TOOLS) + 1 results."""
        fake_path = Path("/bin/fake")
        with (
            patch("harness_quality_gate.bootstrap.resolve_tool", return_value=fake_path),
            patch("harness_quality_gate.bootstrap._get_version", return_value="0.0.0"),
        ):
            results = verify_tools(tmp_path)

        assert len(results) == len(PYTHON_TOOLS) + 1
        for r in results:
            assert r.available is True
            assert r.version == "0.0.0"


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
# New tests for fixes (timeout, PermissionError, logging, validation)
# ===================================================================


class TestEnsureVenvTimeout:
    """ensure_venv handles TimeoutExpired gracefully."""

    def test_timeout_expired_logs_warning_and_returns(self, tmp_path: Path, caplog) -> None:
        """subprocess.TimeoutExpired should log a warning and still return venv_dir."""
        venv_dir = tmp_path / ".venv"

        with (
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["python", "-m", "venv"], timeout=60)),
            caplog.at_level("WARNING"),
        ):
            result = ensure_venv(tmp_path)

        assert result == venv_dir
        assert any("timed out" in record.message for record in caplog.records)


class TestEnsureVenvPermissionError:
    """ensure_venv raises RuntimeError on PermissionError."""

    def test_permission_error_raises_clear_runtime_error(self, tmp_path: Path) -> None:
        """PermissionError from subprocess.run should raise RuntimeError with clear message."""
        venv_dir = tmp_path / ".venv"

        with patch("subprocess.run", side_effect=PermissionError("Permission denied")):
            with pytest.raises(RuntimeError) as exc_info:
                ensure_venv(tmp_path)

        assert "Cannot create venv" in str(exc_info.value)
        assert "writable" in str(exc_info.value).lower()


class TestInstallToolsLogging:
    """install_tools logs errors on individual failures."""

    def test_logger_error_called_on_tool_failure(self, tmp_path: Path, caplog) -> None:
        """When a tool install fails (non-zero returncode), logger.error is called."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir(exist_ok=True)

        with (
            patch("shutil.which", return_value="/fake/uv"),
            patch("subprocess.run", return_value=_FakeCompletedProcess(returncode=1, stderr=b"no such package")),
            caplog.at_level("ERROR"),
        ):
            results = install_tools(tmp_path)

        # Results have failures, and logger.error was called for each tool
        assert all(msg.startswith("failed:") for msg in results.values())
        assert any("Failed to install" in record.message for record in caplog.records)


class TestVerifyToolsLogging:
    """verify_tools logs a summary at info level."""

    def test_logger_info_calls_summary_on_verify(self, tmp_path: Path, caplog) -> None:
        """verify_tools should log summary: 'Verified N tools: M available, K unavailable'."""
        fake_path = Path("/bin/fake")

        with (
            patch("harness_quality_gate.bootstrap.resolve_tool", return_value=fake_path),
            patch("harness_quality_gate.bootstrap._get_version", return_value="1.0.0"),
            caplog.at_level("INFO"),
        ):
            results = verify_tools(tmp_path)

        assert any("Verified" in record.message for record in caplog.records)
        assert any("available" in record.message for record in caplog.records)
        assert any("unavailable" in record.message for record in caplog.records)


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

