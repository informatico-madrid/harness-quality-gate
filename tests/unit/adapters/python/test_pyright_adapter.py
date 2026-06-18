"""Unit tests for PyrightAdapter.

Comprehensive tests covering parse, _map_severity, _build_detail, and invoke.
Goal: Kill all mutation testing survivors on each method.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from harness_quality_gate.adapters.base import ToolInvocation
from harness_quality_gate.models import Finding
from harness_quality_gate.bootstrap import ToolNotAvailable
from harness_quality_gate.adapters.python.pyright_adapter import PyrightAdapter


@pytest.fixture
def adapter():
    return PyrightAdapter()


# ── _map_severity ────────────────────────────────────────────────────────


class TestMapSeverity:
    """Test _map_severity static method.

    Kills mutations on _SEV_MAP.get(severity, "warning").
    """

    def test_maps_error(self):
        assert PyrightAdapter._map_severity("error") == "error"

    def test_maps_warning(self):
        assert PyrightAdapter._map_severity("warning") == "warning"

    def test_maps_information(self):
        assert PyrightAdapter._map_severity("information") == "info"

    def test_unknown_defaults_to_warning(self):
        """Kills: default "warning" → None/XXXX."""
        assert PyrightAdapter._map_severity("unknown") == "warning"

    def test_empty_string_defaults_to_warning(self):
        """Kills: default "warning" → "" changes behavior."""
        assert PyrightAdapter._map_severity("") == "warning"


# ── _build_detail ────────────────────────────────────────────────────────


class TestBuildDetail:
    """Test _build_detail method.

    Kills mutations that change the detail string construction.
    """

    def test_detail_with_line_and_char(self, adapter):
        """All fields present → full detail format."""
        detail = adapter._build_detail(
            filename="src/a.py", message="typo", rule="N999",
            line=5, char=10,
        )
        assert detail == "src/a.py:5:10 [N999]: typo"

    def test_detail_with_line_no_char(self, adapter):
        """Line present, char missing → detail without col."""
        detail = adapter._build_detail(
            filename="src/a.py", message="typo", rule="N999",
            line=5, char=0,
        )
        assert detail == "src/a.py:5 [N999]: typo"

    def test_detail_no_line(self, adapter):
        """No line → message only."""
        detail = adapter._build_detail(
            filename="src", message="typo", rule="N999",
            line=0, char=0,
        )
        assert detail == "typo"


# ── parse — empty/invalid ────────────────────────────────────────────────


class TestParseEmptyAndInvalid:
    """Test parse with empty, invalid, or unexpected inputs."""

    def test_empty_stdout(self, adapter):
        """Empty stdout → no findings."""
        assert adapter.parse("") == []
        assert adapter.parse("   ") == []

    def test_non_json_output(self, adapter):
        """Non-JSON stdout → no findings."""
        assert adapter.parse("not json at all") == []

    def test_json_non_dict(self, adapter):
        """JSON dict but no generalDiagnostics key → no findings."""
        findings = adapter.parse(json.dumps({"foo": "bar"}))
        assert findings == []

    def test_json_dict_no_diagnostics(self, adapter):
        """JSON dict but no 'generalDiagnostics' key → no findings."""
        data = {"otherKey": "value"}
        assert adapter.parse(json.dumps(data)) == []

    def test_diagnostics_not_list(self, adapter):
        """generalDiagnostics is a dict, not a list → no findings."""
        data = {"generalDiagnostics": {"error": "msg"}}
        assert adapter.parse(json.dumps(data)) == []


# ── parse — complete finding ─────────────────────────────────────────────


class TestParseCompleteFinding:
    """Test parse with a complete finding entry."""

    def test_complete_finding_all_fields(self, adapter):
        entry = {
            "file": "src/a.py",
            "severity": "error",
            "message": "Cannot assign to final variable",
            "rule": "reportGeneralTypeIssues",
            "range": {
                "start": {"line": 10, "character": 5},
            },
        }
        findings = adapter.parse(json.dumps({"generalDiagnostics": [entry]}))
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "src/a.py"
        assert f.severity == "error"
        assert f.rule_id == "reportGeneralTypeIssues"
        assert "src/a.py:10:5" in f.message
        assert "reportGeneralTypeIssues" in f.message
        assert "Cannot assign to final variable" in f.message
        assert f.tool == "pyright"
        assert f.layer == "L3A"
        assert f.language == "python"


# ── parse — missing fields ──────────────────────────────────────────────


class TestParseMissingFields:
    """Test parse with missing optional fields in diagnostics."""

    def test_missing_file(self, adapter):
        """File missing → defaults to ''."""
        entry = {
            "severity": "warning",
            "message": "some issue",
            "range": {"start": {"line": 1, "character": 0}},
        }
        findings = adapter.parse(json.dumps({"generalDiagnostics": [entry]}))
        assert len(findings) == 1
        assert findings[0].node == ""
        assert findings[0].rule_id is None

    def test_missing_rule(self, adapter):
        """Rule missing → rule_id=None."""
        entry = {
            "file": "src/a.py",
            "severity": "error",
            "message": "X",
        }
        findings = adapter.parse(json.dumps({"generalDiagnostics": [entry]}))
        assert len(findings) == 1
        assert findings[0].rule_id is None

    def test_empty_severity_defaults_warning(self, adapter):
        """Severity '' → _map_severity returns 'warning'."""
        entry = {
            "file": "src/a.py",
            "severity": "",
            "message": "bad",
        }
        findings = adapter.parse(json.dumps({"generalDiagnostics": [entry]}))
        assert findings[0].severity == "warning"


# ── parse — non-dict in diagnostics ─────────────────────────────────────


class TestParseNonDictDiagnostic:
    """Test that non-dict entries in diagnostics are skipped (continue, not break).

    Kills mutmut: continue→break on isinstance(diag, dict) check.
    """

    def test_non_dict_skips_not_breaks(self, adapter):
        """Non-dict entry followed by valid entry → both should be processed.

        Original: continue (skip non-dict, keep going) → 2 findings.
        Mutant:  break (exit loop on non-dict) → 1 finding.
        """
        data = [
            "not a dict",
            {
                "file": "src/a.py",
                "severity": "error",
                "message": "valid",
            },
        ]
        findings = adapter.parse(json.dumps({"generalDiagnostics": data}))
        assert len(findings) == 1  # Only the second entry
        assert findings[0].node == "src/a.py"

    def test_multiple_non_dicts_then_valid(self, adapter):
        """Multiple non-dicts followed by valid → only valid counted."""
        data = [
            "string",
            42,
            None,
            {"file": "src/b.py", "message": "ok"},
        ]
        findings = adapter.parse(json.dumps({"generalDiagnostics": data}))
        assert len(findings) == 1
        assert findings[0].node == "src/b.py"


# ── parse — or-vs-and (mutmut_81) ───────────────────────────────────────


class TestParseOrVsAnd:
    """Test the `detail or message or str(diag)` expression.

    Kills mutmut: `or` → `and` change.
    With all falsy fields, `detail or message or str(diag)` returns str(diag),
    but `detail and message and str(diag)` returns "" (first falsy).
    """

    def test_all_falsy_fields_returns_diag_str(self, adapter):
        """All fields empty: detail='', message='', diag={} → str(diag) returned.

        Original: "" or "" or str({}) → str({}) → truthy → message set to str(diag)
        Mutant:   "" and "" and str({}) → "" → falsy but last result is ""
        """
        entry = {
            "file": "",
            "severity": "",
            "message": "",
        }
        findings = adapter.parse(json.dumps({"generalDiagnostics": [entry]}))
        assert len(findings) == 1
        f = findings[0]
        # Original: str(diag) = "{'file': '', 'severity': '', 'message': ''}"
        # Mutant: "" → would fail this assertion if mutant changes or→and
        assert f.message == "{'file': '', 'severity': '', 'message': ''}"


# ── invoke — binary not found ───────────────────────────────────────────

class TestInvokeBinaryNotFound:
    """Tests for when pyright is not found on PATH.

    Kills mutmut survivors on invoke that remove the early return
    when binary is None, or remove the _run() call entirely.
    """

    @patch("harness_quality_gate.adapters.python.pyright_adapter.resolve_tool", side_effect=ToolNotAvailable("pyright"))
    def test_invoke_returns_exitcode_3_when_pyright_missing(self, mock_which, adapter):
        """Binary missing → ToolInvocation with exitcode=3, no subprocess call.

        Kills:
          - Remove `if binary is None: return ...` early return
          - Return None instead of ToolInvocation if _run removed
        """
        result = adapter.invoke(
            repo=MagicMock(),
            args=[],
            env=None,
        )
        assert isinstance(result, ToolInvocation)
        assert result.exitcode == 3
        assert result.stderr == "pyright not found on PATH or .venv"


# ── version ─────────────────────────────────────────────────────────────

class TestVersion:
    """Test the version() method.

    Kills mutations on lines 33, 36-40 of pyright_adapter.py:
      - Line 33: name property body
      - Lines 36-40: version method body (binary lookup, _run call, return)
    """

    def test_name_property_returns_tool_name(self):
        """Accessing .name must return 'pyright'.

        Kills mutation on line 33: `return self._name` removed/changed.
        """
        assert PyrightAdapter().name == "pyright"

    def test_version_raises_when_pyright_missing(self):
        """Binary not found → RuntimeError.

        Kills mutations that remove the `if binary is None: raise` branch.
        """
        adapter = PyrightAdapter()
        with patch("harness_quality_gate.adapters.python.pyright_adapter.resolve_tool", side_effect=ToolNotAvailable("pyright")):
            with pytest.raises(RuntimeError, match="pyright not found on PATH or .venv"):
                adapter.version(Path("/tmp"))

    def test_version_calls_run_with_correct_cmd(self):
        """invoke version → _run([binary, --version], cwd, env).

        Kills mutations:
          - Line 39: cmd elements [binary, --version] → wrong/None
          - Line 39: cwd arg → None
          - Line 39: env arg → None
          - Line 40: result.stdout.strip() → None
          - Line 40: split()[-1] → different index
        """
        adapter = PyrightAdapter()
        binary = "/usr/bin/mock_pyright"
        mock_result = MagicMock(stdout="pyright 1.1.265")

        with patch("harness_quality_gate.adapters.python.pyright_adapter.resolve_tool", return_value=Path(binary)):
            with patch.object(PyrightAdapter, "_run", return_value=mock_result) as mock_run:
                repo = Path("/repo/X")
                result = adapter.version(repo)

        mock_run.assert_called_once_with(
            [binary, "--version"], cwd=repo, env=None,
        )
        assert result == "1.1.265"

    def test_version_empty_stdout_returns_unknown(self):
        """Empty stdout → 'unknown' via the else branch.

        Kills mutation: `if result.stdout` → always truthy, returns bad split.
        """
        adapter = PyrightAdapter()
        mock_result = MagicMock(stdout="")

        with patch("harness_quality_gate.adapters.python.pyright_adapter.resolve_tool", return_value=Path("/bin/pyright")):
            with patch.object(PyrightAdapter, "_run", return_value=mock_result):
                result = adapter.version(Path("/tmp"))
        assert result == "unknown"

    def test_version_wiring_exact_call_args(self):
        """version() calls _run with exact binary cmd + cwd + env.

        Kills mutmut_13: env mutation on version call.
        """
        adapter = PyrightAdapter()
        binary = "/usr/bin/pyright"
        mock_result = MagicMock(stdout="pyright 1.1.265")

        with patch("harness_quality_gate.adapters.python.pyright_adapter.resolve_tool", return_value=Path(binary)): 
            with patch.object(PyrightAdapter, "_run", return_value=mock_result) as mock_run:
                result = adapter.version(Path("/repo/X"), env={"PATH_OVERRIDE": "/usr/bin"})
        mock_run.assert_called_once()
        assert mock_run.call_args.args[0] == [binary, "--version"]
        assert mock_run.call_args.kwargs["env"] == {"PATH_OVERRIDE": "/usr/bin"}
        assert result == "1.1.265"

    def test_version_env_none_passed(self):
        """env=None passed to _run when not specified.

        Kills mutmut_19: env=env → env=None mutation.
        """
        adapter = PyrightAdapter()
        mock_result = MagicMock(stdout="pyright 1.1.265")
        with patch("harness_quality_gate.adapters.python.pyright_adapter.resolve_tool", return_value=Path("/usr/bin/pyright")):
            with patch.object(PyrightAdapter, "_run", return_value=mock_result) as mock_run:
                adapter.version(Path("/tmp"))
        assert mock_run.call_args.kwargs["env"] is None

    def test_version_asserts_shutil_which_arg_is_literal_pyright(self):
        """Spy on resolve_tool and assert the literal tool name "pyright" + repo.

        Kills mutmut_2: resolve_tool("pyright") → resolve_tool(None, repo).
        The mutant passes None, which breaks the assert_called_once_with("pyright", repo).
        """
        adapter = PyrightAdapter()
        mock_result = MagicMock(stdout="pyright 1.1.265")
        with patch(
            "harness_quality_gate.adapters.python.pyright_adapter.resolve_tool",
            return_value=Path("/usr/bin/pyright"),
        ) as resolve_mock:
            with patch.object(PyrightAdapter, "_run", return_value=mock_result):
                adapter.version(Path("/repo/X"))
        resolve_mock.assert_called_once_with("pyright", Path("/repo/X"))


class TestInvokeNormalPath:
    """Tests for normal invoke path with mocked _run.

    Kills mutmut survivors on invoke that change command construction.
    """

    @pytest.fixture(autouse=True)
    def _pyright_on_path(self):
        """Deterministic: these tests must not require pyright installed
        (CI runners don't have it — only mypy gates the repo there)."""
        def _resolve(name, repo):
            if name == "pyright":
                return Path("/usr/bin/pyright")
            raise ToolNotAvailable(name)
        with patch(
            "harness_quality_gate.adapters.python.pyright_adapter.resolve_tool",
            side_effect=_resolve,
        ):
            yield

    def test_invoke_construction_with_no_args(self, adapter):
        """invoke with empty args builds cmd with binary + flag + repo."""
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch.object(PyrightAdapter, "_run", return_value=mock_result) as mock_run:
            adapter.invoke(repo=Path("/tmp/repo"), args=[])

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "--outputjson" in cmd
        assert str(Path("/tmp/repo")) in cmd
        assert mock_run.call_args[1]["cwd"] == Path("/tmp/repo")

    def test_invoke_construction_with_args(self, adapter):
        """invoke with custom args includes them in the command."""
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch.object(PyrightAdapter, "_run", return_value=mock_result) as mock_run:
            adapter.invoke(
                repo=Path("/tmp/repo"),
                args=["--project", "/tmp/repo/pyrightconfig.json"],
            )

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "--project" in cmd
        assert "/tmp/repo/pyrightconfig.json" in cmd

    def test_invoke_wiring_exact_call_args(self, adapter):
        """invoke() calls _run with exact cmd + cwd/env/timeout.

        Kills mutmut_1,23,24,27,28: cmd element mutations (binary, flags),
        cwd→None, env→None, timeout→mutated. All via §4.4 spy + §4.7 argv.
        """
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch.object(PyrightAdapter, "_run", return_value=mock_result) as mock_run:
            adapter.invoke(
                repo=Path("/tmp/repo"),
                args=["--typeCheckingStyle", "strict"],
                env={"PYRIGHT_ENV": "1"},
                timeout=180.0,
            )

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        # Verify binary + flags + args + repo
        assert "--outputjson" in cmd
        assert "--typeCheckingStyle" in cmd
        assert "strict" in cmd
        assert str(Path("/tmp/repo")) in cmd
        assert call_args[1]['cwd'] == Path("/tmp/repo")
        assert call_args[1]['env'] == {"PYRIGHT_ENV": "1"}
        assert call_args[1]['timeout'] == 180.0

    def test_invoke_default_timeout(self, adapter):
        """Default timeout=300.0 forwarded to _run.

        Kills mutmut on timeout default mutation.
        """
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch.object(PyrightAdapter, "_run", return_value=mock_result) as mock_run:
            adapter.invoke(repo=Path("/tmp/repo"), args=[])
        assert mock_run.call_args[1]['timeout'] == 300.0


# ---------------------------------------------------------------------------
# Phase 2: detect_source_dir usage
# ---------------------------------------------------------------------------


def test_pyright_invoke_uses_detect_source_dir_with_src(tmp_path: Path):
    """When src/ exists, pyright uses detect_source_dir('src').

    Phase 2 convergence: pyright detects the source dir instead of
    hardcoding 'src', enabling config-driven source directories.
    """
    # Create a repo with src/
    src = tmp_path / "src"
    src.mkdir()

    mock_result = MagicMock()
    mock_result.stdout = "[]"
    mock_result.stderr = ""
    mock_result.returncode = 0

    with patch(
        "harness_quality_gate.adapters.python.pyright_adapter.resolve_tool",
        return_value=Path("/usr/bin/pyright"),
    ):
        with patch.object(PyrightAdapter, "_run", return_value=mock_result) as mock_run:
            adapter = PyrightAdapter()
            adapter.invoke(tmp_path, [])

    cmd = mock_run.call_args[0][0]
    # Should scan src/, not tests/
    assert src.name in cmd
    assert "tests" not in cmd


def test_pyright_invoke_fallback_when_no_src(tmp_path: Path):
    """When no src/ or packages exist, pyright falls back to repo root.

    Phase 2 convergence: no source dir found → repo root as target.
    """
    # Empty tmp_path (no src/, no packages)
    mock_result = MagicMock()
    mock_result.stdout = "[]"
    mock_result.stderr = ""
    mock_result.returncode = 0

    with patch(
        "harness_quality_gate.adapters.python.pyright_adapter.resolve_tool",
        return_value=Path("/usr/bin/pyright"),
    ):
        with patch.object(PyrightAdapter, "_run", return_value=mock_result) as mock_run:
            adapter = PyrightAdapter()
            adapter.invoke(tmp_path, [])

    cmd = mock_run.call_args[0][0]
    # When no source dirs found, repo root is the target
    assert str(tmp_path) in cmd
    # Should exclude tests/ from scan
    assert "tests" not in cmd


def test_pyright_passes_pythonpath_when_python_path_given(tmp_path: Path):
    """When python_path is provided, --pythonpath flag is included.

    Phase 2 convergence: --pythonpath from python_adapter._run_pyright
    ensures pyright resolves imports from .venv.
    """
    venv_py = Path("/tmp/repo/.venv/bin/python")

    mock_result = MagicMock()
    mock_result.stdout = "[]"
    mock_result.stderr = ""
    mock_result.returncode = 0

    with patch(
        "harness_quality_gate.adapters.python.pyright_adapter.resolve_tool",
        return_value=Path("/usr/bin/pyright"),
    ):
        with patch.object(PyrightAdapter, "_run", return_value=mock_result) as mock_run:
            adapter = PyrightAdapter()
            adapter.invoke(tmp_path, [], python_path=venv_py)

    cmd = mock_run.call_args[0][0]
    assert "--pythonpath" in cmd
    idx = cmd.index("--pythonpath")
    assert cmd[idx + 1] == str(venv_py)


def test_pyright_no_pythonpath_when_none(tmp_path: Path):
    """When python_path=None, --pythonpath flag is NOT included.

    Verifies that the python_path conditional is respected.
    """
    mock_result = MagicMock()
    mock_result.stdout = "[]"
    mock_result.stderr = ""
    mock_result.returncode = 0

    with patch(
        "harness_quality_gate.adapters.python.pyright_adapter.resolve_tool",
        return_value=Path("/usr/bin/pyright"),
    ):
        with patch.object(PyrightAdapter, "_run", return_value=mock_result) as mock_run:
            adapter = PyrightAdapter()
            adapter.invoke(tmp_path, [], python_path=None)

    cmd = mock_run.call_args[0][0]
    assert "--pythonpath" not in cmd
