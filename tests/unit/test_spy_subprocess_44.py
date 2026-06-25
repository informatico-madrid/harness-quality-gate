"""§4.4 — Spies sobre dependencias

Spy-based tests that verify subprocess.run receives the EXACT command and
keyword arguments.  Every tool that passes subprocess.run (directly or via
ToolAdapter._run) gets a def-spies capturing cmd + kwargs.

RULES:
  CERO PRAGMAS  –  NO pragma of any kind in harness_quality_gate/
  def spy_*() — never lambda
  assert_called_once_with() — never bare assert_called()
  Captures captured by mutable dict / list via def spy.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from harness_quality_gate.adapters.base import ToolAdapter, ToolInvocation


# ------------------------------------------------------------------
# Shared spy helper — avoids lambda everywhere
# ------------------------------------------------------------------

def _fake_completed(*, returncode: int = 0, stdout: str = "", stderr: str = ""):
    """Return a CompletedProcess-like object for subprocess."""
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


# ==================================================================
# BanditAdapter.invoke  — mutmut_5, 7, 24, 27, 28, 29
# BanditAdapter.version — mutmut_7, 8
# ==================================================================

class TestBanditAdapterSubprocessSpies:
    """Spy ToolAdapter._run to capture subprocess args in bandit_adapter."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.bandit_adapter import BanditAdapter
        return BanditAdapter()

    def test_invoke_subprocess_cmd_and_kwargs(self, tmp_path: Path):
        """invoke() passes correct cmd and all kwargs to _run."""
        adapter = self._adapter()
        captured = {}

        def spy_run(*args, **kwargs):
            captured["cmd"] = list(args[1])
            captured["kwargs"] = dict(kwargs)
            return ToolInvocation(stdout='{"results": []}', exitcode=0)

        with patch("harness_quality_gate.adapters.python.bandit_adapter.resolve_tool", return_value=Path("/fake/bandit")):
            with patch.object(ToolAdapter, "_run", spy_run):
                adapter.invoke(tmp_path, [], timeout=300.0)

        cmd = captured["cmd"]
        kwargs = captured["kwargs"]

        assert "/fake/bandit" in cmd        # kills None, XXbanditXX
        assert "-r" in cmd                  # kills "-xx"
        assert "-q" in cmd                  # kills removal of quiet flag
        assert "--format" in cmd
        assert "json" in cmd
        assert kwargs.get("cwd") is tmp_path
        assert kwargs["env"] is None
        # timeout: kills 299, 301, None, True
        if "timeout" in kwargs:
            assert kwargs["timeout"] == 300.0


    def test_invoke_env_passthrough_to_run(self, tmp_path: Path):
        """env dict flows through invoke → _run."""
        adapter = self._adapter()
        captured = {}

        def spy_run(*args, **kwargs):
            captured["env"] = kwargs.get("env")
            return ToolInvocation(stdout='{"results": []}', exitcode=0)

        with patch("harness_quality_gate.adapters.python.bandit_adapter.resolve_tool", return_value=Path("/fake/bandit")):
            with patch.object(ToolAdapter, "_run", spy_run):
                adapter.invoke(tmp_path, [], env={"MY_VAR": "secret"})

        assert captured["env"] is not None
        assert captured["env"].get("MY_VAR") == "secret"


    def test_version_subprocess_cmd_and_kwargs(self, tmp_path: Path):
        """version() → _run with cmd=['binary', '--version']."""
        adapter = self._adapter()
        captured = {}

        def spy_run(*args, **kwargs):
            captured["cmd"] = list(args[1])
            captured["kwargs"] = dict(kwargs)
            return ToolInvocation(stdout="bandit 1.7.5")

        with patch("harness_quality_gate.adapters.python.bandit_adapter.resolve_tool", return_value=Path("/fake/bandit")):
            with patch.object(ToolAdapter, "_run", spy_run):
                adapter.version(tmp_path)

        cmd = captured["cmd"]
        assert len(cmd) == 2            # binary + --version (kills removal)
        assert cmd[0] == "/fake/bandit"
        assert cmd[1] == "--version"    # kills --VERSION, --versionX, None


    def test_invoke_args_appended_to_cmd(self, tmp_path: Path):
        """Extra args are extended into the command."""
        adapter = self._adapter()
        captured = {}

        def spy_run(*args, **kwargs):
            captured["cmd"] = list(args[1])
            return ToolInvocation(stdout='{"results": []}', exitcode=0)

        with patch("harness_quality_gate.adapters.python.bandit_adapter.resolve_tool", return_value=Path("/fake/bandit")):
            with patch.object(ToolAdapter, "_run", spy_run):
                adapter.invoke(tmp_path, ["--ignore-paths", "tests"])

        cmd = captured["cmd"]
        assert "--ignore-paths" in cmd
        inv = cmd.index("--ignore-paths")
        assert cmd[inv + 1] == "tests"


    def test_invoke_tool_not_found_skips_run(self, tmp_path: Path):
        """When resolve_tool raises, invoke returns error without calling _run."""
        adapter = self._adapter()
        run_called = [False]

        def no_run(*args, **kwargs):
            run_called[0] = True
            return ToolInvocation()

        from harness_quality_gate.bootstrap import ToolNotAvailable
        with patch("harness_quality_gate.adapters.python.bandit_adapter.resolve_tool", side_effect=ToolNotAvailable("bandit")):
            with patch.object(ToolAdapter, "_run", no_run):
                inv = adapter.invoke(tmp_path, [])

        assert not run_called[0], "_run must not be called when tool is missing"
        assert inv.exitcode == 3
        assert "not found on PATH" in inv.stderr


# ==================================================================
# PyrightAdapter.invoke  — mutmut_5, 33, 36, 37, 38
# ==================================================================

class TestPyrightAdapterSubprocessSpies:
    """Spy _run on pyright_adapter to verify subprocess args."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.pyright_adapter import PyrightAdapter
        return PyrightAdapter()

    def test_invoke_cmd_structure(self, tmp_path: Path):
        """invoke() sends binary + --outputjson + scan targets."""
        adapter = self._adapter()
        captured = {}

        def spy_run(*args, **kwargs):
            captured["cmd"] = list(args[1])
            captured["kwargs"] = dict(kwargs)
            return ToolInvocation(stdout=json.dumps({"generalDiagnostics": []}))

        with patch("harness_quality_gate.adapters.python.pyright_adapter.resolve_tool", return_value=Path("/fake/pyright")):
            with patch.object(ToolAdapter, "_run", spy_run):
                adapter.invoke(tmp_path, [])

        cmd = captured["cmd"]
        assert cmd[0] == "/fake/pyright"    # kills XXpyrightXX, resolution to None
        assert "--outputjson" in cmd         # kills removal of JSON flag

        kwargs = captured["kwargs"]
        assert kwargs.get("timeout") == 300.0  # kills 299, 301, None


    def test_invoke_python_path_passthrough(self, tmp_path: Path):
        """--pythonpath is passed when python_path is set."""
        adapter = self._adapter()
        captured = {}

        def spy_run(*args, **kwargs):
            captured["cmd"] = list(args[1])
            return ToolInvocation(stdout="[]")

        python_path = Path("/fake/.venv/bin/python")
        with patch("harness_quality_gate.adapters.python.pyright_adapter.resolve_tool", return_value=Path("/fake/pyright")):
            with patch.object(ToolAdapter, "_run", spy_run):
                adapter.invoke(tmp_path, [], python_path=python_path)

        cmd = captured["cmd"]
        idx = cmd.index("--pythonpath")
        assert cmd[idx + 1] == str(python_path)


    def test_invoke_paths_override_scan_targets(self, tmp_path: Path):
        """When paths are provided, they are used as scan targets."""
        adapter = self._adapter()
        captured = {}

        def spy_run(*args, **kwargs):
            captured["cmd"] = list(args[1])
            return ToolInvocation(stdout="[]")

        with patch("harness_quality_gate.adapters.python.pyright_adapter.resolve_tool", return_value=Path("/fake/pyright")):
            with patch.object(ToolAdapter, "_run", spy_run):
                adapter.invoke(tmp_path, [], paths=["src/main.py"])

        cmd = captured["cmd"]
        assert "src/main.py" in cmd


# ==================================================================
# VultureAdapter.invoke  — mutmut_25, 28, 29, 30
# VultureAdapter.parse   — mutmut_5
# ==================================================================

class TestVultureAdapterSubprocessSpies:
    """Spy _run on vulture_adapter to verify subprocess args."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.vulture_adapter import VultureAdapter
        return VultureAdapter()

    def test_invoke_cmd_structure(self, tmp_path: Path):
        """invoke() includes --min-confidence and scan targets."""
        adapter = self._adapter()
        captured = {}

        def spy_run(*args, **kwargs):
            captured["cmd"] = list(args[1])
            captured["kwargs"] = dict(kwargs)
            return ToolInvocation(stdout="")

        with patch("harness_quality_gate.adapters.python.vulture_adapter.resolve_tool", return_value=Path("/fake/vulture")):
            with patch.object(ToolAdapter, "_run", spy_run):
                adapter.invoke(tmp_path, [], min_confidence=80, timeout=500.0)

        cmd = captured["cmd"]
        assert cmd[0] == "/fake/vulture"    # kills None, XXvultureXX
        assert "--min-confidence" in cmd
        min_conf_idx = cmd.index("--min-confidence")
        assert cmd[min_conf_idx + 1] == "80"
        kwargs = captured["kwargs"]
        assert kwargs.get("timeout") == 500.0  # kills 499, 501, None


    def test_invoke_tool_not_found_returns_error(self, tmp_path: Path):
        """When tool missing, invoke returns error ToolInvocation."""
        adapter = self._adapter()
        run_called = [False]

        def no_run(*args, **kwargs):
            run_called[0] = True
            return ToolInvocation()

        from harness_quality_gate.bootstrap import ToolNotAvailable
        with patch("harness_quality_gate.adapters.python.vulture_adapter.resolve_tool", side_effect=ToolNotAvailable("vulture")):
            with patch.object(ToolAdapter, "_run", no_run):
                inv = adapter.invoke(tmp_path, [])

        assert not run_called[0]
        assert inv.exitcode == 3


# ==================================================================
# RuffAdapter.invoke  — mutmut_34
# ==================================================================

class TestRuffAdapterSubprocessSpies:
    """Spy _run on ruff_adapter to verify subprocess args."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.ruff_adapter import RuffAdapter
        return RuffAdapter()

    def test_invoke_cmd_structure(self, tmp_path: Path):
        """invoke() sends ruff check --output-format=json."""
        adapter = self._adapter()
        captured = {}

        def spy_run(*args, **kwargs):
            captured["cmd"] = list(args[1])
            captured["kwargs"] = dict(kwargs)
            return ToolInvocation(stdout="[]")

        with patch("harness_quality_gate.adapters.python.ruff_adapter.resolve_tool", return_value=Path("/fake/ruff")):
            with patch.object(ToolAdapter, "_run", spy_run):
                adapter.invoke(tmp_path, [], timeout=400.0)

        cmd = captured["cmd"]
        assert cmd[0] == "/fake/ruff"       # kills None, XXruffXX
        assert "check" in cmd               # kills "check"→None, XXcheckXX
        assert "--output-format=json" in cmd
        kwargs = captured["kwargs"]
        assert kwargs.get("timeout") == 400.0   # kills 399, 401, None


# ==================================================================
# PhpWeakTestAdapter.invoke  — mutmut_89, 91, 92
# ==================================================================

class TestPhpWeakTestAdapterSubprocessSpies:
    """Spy subprocess.run called directly by PhpWeakTestAdapter.invoke."""

    def _adapter(self):
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        return PhpWeakTestAdapter()

    def test_invoke_subprocess_run_exact_kwargs(self, tmp_path: Path):
        """invoke() subprocess.run gets capture_output=True, text=True, timeout, check=False."""
        adapter = self._adapter()
        captured = {}

        def spy_run(*args, **kwargs):
            captured["cmd"] = list(args[0])
            captured["kwargs"] = dict(kwargs)
            return _fake_completed(stdout="[]", returncode=0)

        # The adapter collects *.php files; create a minimal test file
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        test_file = test_dir / "ExampleTest.php"
        test_file.write_text("<?php class ExampleTest {}")

        visitors_dir = Path(__file__).resolve().parent.parent.parent \
            / "harness_quality_gate" / "adapters" / "php" / "visitors"

        with patch.object(adapter, '_collect_test_files', return_value=[test_file]):
            # Create a dummy visitor file so the adapter doesn't skip
            visitor_file = Path(tmp_path) / "dummy_visitor.php"
            visitor_file.write_text("<?php echo '[]';")

            # We patch the subprocess.run inside the adapter's module
            with patch("harness_quality_gate.adapters.php.weak_test_php.subprocess.run", spy_run):
                inv = adapter.invoke(tmp_path)

        assert captured["cmd"], "subprocess.run must be called"
        cmd = captured["cmd"]
        kwargs = captured["kwargs"]

        assert cmd[0] == "php"              # kills XXphpXX, None
        assert kwargs.get("capture_output") is True   # kills False, None
        assert kwargs.get("text") is True               # kills False, None
        assert kwargs.get("check") is False             # kills True, None
        assert isinstance(kwargs.get("timeout"), float) # kills None, 0


# ==================================================================
# MutmutAdapter.run  — mutmut_30
# ==================================================================

class TestMutmutAdapterSubprocessSpies:
    """Spy _run on MutmutAdapter.run to verify subprocess args."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.mutmut_adapter import MutmutAdapter
        return MutmutAdapter()

    def test_run_cmd_structure(self, tmp_path: Path):
        """run() sends binary + 'run' + paths + max-children."""
        adapter = self._adapter()
        captured = {}

        def spy_run(*args, **kwargs):
            captured["cmd"] = list(args[1])
            captured["kwargs"] = dict(kwargs)
            return ToolInvocation(stdout="")

        with patch("harness_quality_gate.adapters.python.mutmut_adapter.resolve_tool", return_value=Path("/fake/mutmut")):
            with patch.object(ToolAdapter, "_run", spy_run):
                env = {"MUTATION_MAX_CHILDREN": "4"}
                adapter.run(tmp_path, env=env, paths=["src/"])

        cmd = captured["cmd"]
        assert cmd[0] == "/fake/mutmut"
        assert "run" in cmd               # kills "run"→None or removal
        assert "src/" in cmd              # kills paths removal
        assert "--max-children" in cmd    # kills removal of flag
        idx = cmd.index("--max-children")
        assert cmd[idx + 1] == "4"


    def test_run_without_paths_skips_paths(self, tmp_path: Path):
        """run() without paths does not add file targets."""
        adapter = self._adapter()
        captured = {}

        def spy_run(*args, **kwargs):
            captured["cmd"] = list(args[1])
            return ToolInvocation(stdout="")

        with patch("harness_quality_gate.adapters.python.mutmut_adapter.resolve_tool", return_value=Path("/fake/mutmut")):
            with patch.object(ToolAdapter, "_run", spy_run):
                adapter.run(tmp_path)

        cmd = captured["cmd"]
        assert cmd[0] == "/fake/mutmut"
        assert "run" in cmd
        # No file paths added
        assert cmd == ["/fake/mutmut", "run"]


# ==================================================================
# AllowListAuditor.audit  — mutmut_19, 20, 22, 27
# ==================================================================

class TestAllowListAuditorSubprocessSpies:
    """Spy Path.read_text to verify encoding and error_handler kwargs."""

    def test_audit_read_text_kwargs_exact(self, tmp_path: Path):
        """AllowListAuditor.audit calls Path.read_text with encoding='utf-8', errors='replace'."""
        from harness_quality_gate.allow_list_auditor import AllowListAuditor, _EXCLUDED_DIRS

        # Create a Python source file with a pragma
        py_file = tmp_path / "bad.py"
        py_file.write_text("x = 1  # pragma: " "no mutate\n", encoding="utf-8")

        captured_calls = []
        original_read_text = Path.read_text

        # No defaults in the spy: capture exactly what audit() passes, so a
        # dropped kwarg shows up as missing (not silently back-filled).
        def spy_read_text(self, *args, **kwargs):
            captured_calls.append(dict(kwargs))
            return original_read_text(self)

        with patch.object(Path, "read_text", spy_read_text):
            report = AllowListAuditor(language="python").audit(tmp_path)

        # Exit-code 1 because the pragma is unjustified
        assert report.exit_code == 1
        assert len(captured_calls) >= 1

        # Every call passes BOTH kwargs explicitly (kills drop/None/case mutants).
        for kwargs in captured_calls:
            assert kwargs.get("encoding") == "utf-8"
            assert kwargs.get("errors") == "replace"


# ==================================================================
# PythonAdapter._run_pytest  — mutmut_27, 29, 33-41 (11 restantes)
# ==================================================================

class TestPythonAdapterRunPytestSpies:
    """Spy pytest.invoke to verify subprocess args."""

    def _adapter(self):
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        return PythonAdapter()

    def test_pytest_subprocess_invoked_via_invoke(self, tmp_path: Path):
        """_run_pytest calls self.pytest.invoke with proper repo/env."""
        adapter = self._adapter()
        captured = {}

        def spy_invoke(self_inner, repo, args, *, env=None, paths=None, timeout=300.0):
            captured["repo"] = repo
            captured["env"] = dict(env) if env else None
            captured["timeout"] = timeout
            return ToolInvocation(stdout="", exitcode=0)

        with patch.object(type(adapter.pytest), "invoke", spy_invoke):
            adapter._run_pytest(tmp_path, {"PY_COLORS": "1"})

        assert captured["repo"] is tmp_path
        assert captured["env"] is not None
        assert "PY_COLORS" in captured["env"]
        # pytest.invoke eventually calls ToolAdapter._run which calls subprocess.run.
        # The env dict flows through — kills mutmut env mutations.


    def test_pytest_env_path_prepending(self, tmp_path: Path):
        """When venv pytest exists, PATH is prepended with venv bin dir."""
        adapter = self._adapter()
        captured_env = {}

        def spy_invoke_captures_env(self_inner, repo, args, *, env=None, paths=None, timeout=300.0):
            captured_env["env"] = dict(env) if env else {}
            return ToolInvocation(stdout="", exitcode=0)

        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True, exist_ok=True)
        pytest_bin = venv_bin / "pytest"
        pytest_bin.touch(mode=0o755)

        with patch.object(type(adapter.pytest), "invoke", spy_invoke_captures_env):
            adapter._run_pytest(tmp_path, {})

        assert captured_env["env"]
        # PATH must start with venv_bin
        env_path = captured_env["env"]["PATH"]
        assert env_path.startswith(str(venv_bin))


# ==================================================================
# PythonAdapter.run_l4 — verify resolve_tool is called with repo (H1)
# ==================================================================

class TestPythonAdapterL4ResolveToolSpies:
    """Verify resolve_tool is called with repo (not None) in L4 path."""

    def test_l4_resolve_tool_called_with_repo_not_none(self, tmp_path: Path):
        """resolve_tool in _run_bandit must receive repo (not None)."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        calls = []

        def spy_resolve_tool(name, repo):
            calls.append((name, repo))
            from harness_quality_gate.bootstrap import ToolNotAvailable
            raise ToolNotAvailable(name)

        adapter = PythonAdapter(paths=["fake"])
        # paths is set, so run_l4 should return quick-pass;
        # let's call _run_bandit directly.
        with patch("harness_quality_gate.adapters.python.python_adapter.resolve_tool", spy_resolve_tool):
            adapter._run_bandit(tmp_path, {})

        for name, repo_arg in calls:
            assert repo_arg is not None       # kills identity: repo→None
            assert repo_arg == tmp_path       # kills repo→random_path

    def test_l4_resolve_tool_name_bandit(self, tmp_path: Path):
        """resolve_tool in _run_bandit must receive name='bandit'."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        calls = []

        def spy_resolve_tool(name, repo):
            calls.append(name)
            from harness_quality_gate.bootstrap import ToolNotAvailable
            raise ToolNotAvailable(name)

        adapter = PythonAdapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.resolve_tool", spy_resolve_tool):
            adapter._run_bandit(tmp_path, {})

        # Calls must include 'bandit'
        assert "bandit" in calls


# ==================================================================
# PythonAdapter.check_tools  — mutmut_7, 11
# ==================================================================

class TestPythonAdapterCheckToolsSpies:
    """Verify resolve_tool is called correctly in check_tools."""

    def test_check_tools_resolve_tool_called(self, tmp_path: Path):
        """check_tools calls resolve_tool('ruff', repo) and resolve_tool('pyright', repo)."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        calls = []

        def spy_resolve_tool(name, repo):
            calls.append((name, repo))
            return Path("/fake/" + name)

        adapter = PythonAdapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.resolve_tool", spy_resolve_tool):
            adapter.check_tools()

        call_names = [c[0] for c in calls]
        assert call_names == ["ruff", "pyright"]   # kills order, names, None

    def test_check_tools_repo_not_none(self, tmp_path: Path):
        """check_tools resolve_tool repo arg is not None."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        repos = []

        def spy_resolve_tool(name, repo):
            repos.append(repo)
            return Path("/fake/" + name)

        adapter = PythonAdapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.resolve_tool", spy_resolve_tool):
            adapter.check_tools()

        assert len(repos) == 2
        for repo_arg in repos:
            assert repo_arg is not None
            assert str(repo_arg) == "."


class TestPythonAdapterH1Wiring:
    """§H1: resolve_tool must receive repo (not None) for check_tools."""

    def test_resolve_tool_called_with_repo(self, tmp_path: Path):
        """check_tools passes repo='.', not None, to resolve_tool."""
        from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
        calls = []

        def spy(name, repo):
            calls.append((name, repo))
            return Path("/fake/" + name)

        adapter = PythonAdapter()
        with patch("harness_quality_gate.adapters.python.python_adapter.resolve_tool", spy):
            adapter.check_tools()

        for name, repo_arg in calls:
            assert repo_arg is not None, f"{name}: repo must not be None"
            assert str(repo_arg) == "."


# ==================================================================
# Checkpoint write — ensure_ascii=False  (mutmut_13)
# Already tested in test_checkpoint.py test_write_ensure_ascii_false_not_none
# No additional tests needed — existing test is sufficient.
# ==================================================================
