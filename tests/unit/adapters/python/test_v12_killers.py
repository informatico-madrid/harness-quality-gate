"""v12 survivor killers — exact-equality tests for the Python tool adapters."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.base import ToolInvocation
from harness_quality_gate.adapters.python.bandit_adapter import BanditAdapter
from harness_quality_gate.adapters.python.deptry_adapter import DeptryAdapter
from harness_quality_gate.adapters.python.mutmut_adapter import MutmutAdapter
from harness_quality_gate.adapters.python.pyright_adapter import PyrightAdapter
from harness_quality_gate.adapters.python.pytest_adapter import PytestAdapter
from harness_quality_gate.adapters.python.ruff_adapter import RuffAdapter


class TestDeptryKillers:
    MOD = "harness_quality_gate.adapters.python.deptry_adapter"

    def test_invoke_which_exact_and_not_found_invocation(self, tmp_path: Path) -> None:
        with patch(f"{self.MOD}.shutil.which", return_value=None) as which:
            result = DeptryAdapter().invoke(tmp_path, [])
        which.assert_called_once_with("deptry")
        assert result == ToolInvocation(
            stdout="", stderr="deptry not found on PATH", exitcode=3,
            duration_seconds=0.0,
        )

    def test_parse_string_item_exact_finding(self) -> None:
        stdout = json.dumps({"errors": {"unused_imports": ["requests"]}})
        findings = DeptryAdapter().parse(stdout)
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "requests"
        assert f.message == "unused_imports: requests"
        assert f.severity == "warning"

    def test_parse_dict_item_with_location_exact_detail(self) -> None:
        stdout = json.dumps({"errors": {"missing_imports": [
            {"module": "numpy", "filepath": "src/a.py", "line": 7},
        ]}})
        findings = DeptryAdapter().parse(stdout)
        assert findings[0].node == "src/a.py"
        assert findings[0].message == "src/a.py:7 — missing_imports: numpy"


class TestMutmutAdapterKillers:
    MOD = "harness_quality_gate.adapters.python.mutmut_adapter"

    def test_invoke_which_exact_and_not_found_invocation(self, tmp_path: Path) -> None:
        with patch(f"{self.MOD}.shutil.which", return_value=None) as which:
            result = MutmutAdapter().invoke(tmp_path, [])
        which.assert_called_once_with("mutmut")
        assert result == ToolInvocation(
            stdout="", stderr="mutmut not found on PATH", exitcode=3,
            duration_seconds=0.0,
        )

    def test_invoke_exact_cmd_and_default_timeout(self, tmp_path: Path) -> None:
        adapter = MutmutAdapter()
        with (
            patch(f"{self.MOD}.shutil.which", return_value="/usr/bin/mutmut"),
            patch.object(adapter, "_run", return_value=MagicMock()) as run,
        ):
            adapter.invoke(tmp_path, ["--extra"])
        run.assert_called_once_with(
            ["/usr/bin/mutmut", "results", "--all", "true", "--extra"],
            cwd=tmp_path, env=None, timeout=600.0,
        )


class TestVersionTokenKillers:
    def test_pyright_version_takes_last_token(self, tmp_path: Path) -> None:
        adapter = PyrightAdapter()
        inv = MagicMock(stdout="pyright version 1.1.300\n")
        with (
            patch(
                "harness_quality_gate.adapters.python.pyright_adapter.shutil.which",
                return_value="/usr/bin/pyright",
            ),
            patch.object(adapter, "_run", return_value=inv),
        ):
            assert adapter.version(tmp_path) == "1.1.300"

    def test_pyright_version_missing_exact_message(self, tmp_path: Path) -> None:
        with patch(
            "harness_quality_gate.adapters.python.pyright_adapter.shutil.which",
            return_value=None,
        ):
            with pytest.raises(RuntimeError, match=r"^pyright not found on PATH$"):
                PyrightAdapter().version(tmp_path)

    def test_ruff_version_takes_last_token(self, tmp_path: Path) -> None:
        adapter = RuffAdapter()
        inv = MagicMock(stdout="ruff version 0.6.8\n")
        with (
            patch(
                "harness_quality_gate.adapters.python.ruff_adapter.shutil.which",
                return_value="/usr/bin/ruff",
            ),
            patch.object(adapter, "_run", return_value=inv),
        ):
            assert adapter.version(tmp_path) == "0.6.8"


class TestPytestAdapterKillers:
    _JUNIT = """<?xml version="1.0"?>
<testsuites>
  <testsuite name="pytest" tests="3" failures="1" errors="1" skipped="1">
    <testcase classname="t" name="a"><failure message="boom-f"/></testcase>
    <testcase classname="t" name="b"><error message="boom-e"/></testcase>
    <testcase classname="t" name="c"><skipped message="meh"/></testcase>
  </testsuite>
</testsuites>"""

    def test_invoke_fallback_python3_literal_in_cmd(self, tmp_path: Path) -> None:
        adapter = PytestAdapter()
        with (
            patch(
                "harness_quality_gate.adapters.python.pytest_adapter.shutil.which",
                return_value=None,
            ) as which,
            patch.object(adapter, "_run", return_value=MagicMock()) as run,
        ):
            adapter.invoke(tmp_path, [])
        which.assert_called_once_with("python3")
        assert run.call_args.args[0][0] == "python3"

    def test_parse_summary_first_with_exact_joined_message(self) -> None:
        findings = PytestAdapter().parse(self._JUNIT, "", 0)
        assert findings[0].rule_id == "summary"
        assert findings[0].message == "1 failure(s) 1 error(s) 1 skipped"

    def test_parse_stderr_without_critical_emits_no_stderr_finding(self) -> None:
        findings = PytestAdapter().parse(self._JUNIT, "plain noise", 0)
        assert all(f.rule_id != "stderr" for f in findings)

    def test_parse_stderr_with_critical_emits_finding(self) -> None:
        findings = PytestAdapter().parse(self._JUNIT, "CRITICAL boom", 0)
        assert any(f.rule_id == "stderr" for f in findings)


class TestBanditKillers:
    def _issue(self, **over):
        base = {
            "filename": "a.py", "line_number": 3, "test_id": "B101",
            "issue_text": "msg", "issue_severity": "MEDIUM",
        }
        base.update(over)
        return json.dumps({"results": [base]})

    def test_medium_maps_to_warning(self) -> None:
        findings = BanditAdapter().parse(self._issue())
        assert findings[0].severity == "warning"

    def test_missing_severity_defaults_to_warning_via_medium(self) -> None:
        findings = BanditAdapter().parse(self._issue(issue_severity=None))
        assert findings[0].severity == "warning"

    def test_missing_cwe_is_exactly_empty_string(self) -> None:
        findings = BanditAdapter().parse(self._issue())
        assert findings[0].cwe == ""


class TestVultureKillers:
    def test_invoke_which_exact_name(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.python.vulture_adapter import VultureAdapter
        with patch(
            "harness_quality_gate.adapters.python.vulture_adapter.shutil.which",
            return_value=None,
        ) as which:
            VultureAdapter().invoke(tmp_path, [])
        which.assert_called_once_with("vulture")


class TestBanditResultsDefault:
    def test_payload_without_results_key_returns_empty(self) -> None:
        assert BanditAdapter().parse(json.dumps({"other": 1})) == []


class TestV14PythonKillers:
    def test_deptry_version_exact_message_and_run_spy(self, tmp_path):
        with patch(
            "harness_quality_gate.adapters.python.deptry_adapter.shutil.which",
            return_value=None,
        ):
            with pytest.raises(RuntimeError, match=r"^deptry not found on PATH$"):
                DeptryAdapter().version(tmp_path)
        adapter = DeptryAdapter()
        inv = MagicMock(stdout="deptry 0.20.0\n")
        with (
            patch(
                "harness_quality_gate.adapters.python.deptry_adapter.shutil.which",
                return_value="/usr/bin/deptry",
            ),
            patch.object(adapter, "_run", return_value=inv) as run,
        ):
            adapter.version(tmp_path)
        run.assert_called_once_with(["/usr/bin/deptry", "--version"], cwd=tmp_path, env=None)

    def test_deptry_dict_without_module_or_path_node_unknown(self):
        stdout = json.dumps({"errors": {"unused_imports": [{}]}})
        assert DeptryAdapter().parse(stdout)[0].node == "<unknown>"

    @pytest.mark.parametrize("mod,cls,msg", [
        ("mutmut_adapter", "MutmutAdapter", "mutmut not found on PATH"),
        ("vulture_adapter", "VultureAdapter", "vulture not found on PATH"),
    ])
    def test_version_missing_exact_messages(self, tmp_path, mod, cls, msg):
        import importlib
        module = importlib.import_module(f"harness_quality_gate.adapters.python.{mod}")
        adapter = getattr(module, cls)()
        import re as _re
        with patch(
            f"harness_quality_gate.adapters.python.{mod}.shutil.which", return_value=None,
        ):
            with pytest.raises(RuntimeError, match=f"^{_re.escape(msg)}$"):
                adapter.version(tmp_path)

    def test_pytest_version_cmd_exact_both_paths(self, tmp_path):
        adapter = PytestAdapter()
        inv = MagicMock(stdout="pytest 8.0\n")
        with (
            patch(
                "harness_quality_gate.adapters.python.pytest_adapter.shutil.which",
                return_value="/usr/bin/python3",
            ) as which,
            patch.object(adapter, "_run", return_value=inv) as run,
        ):
            adapter.version(tmp_path)
        # the lookup KEY must be exactly "python3" (kills XX/upper variants)
        which.assert_called_once_with("python3")
        assert run.call_args.args[0] == ["/usr/bin/python3", "-m", "pytest", "--version"]
        with (
            patch(
                "harness_quality_gate.adapters.python.pytest_adapter.shutil.which",
                return_value=None,
            ),
            patch.object(adapter, "_run", return_value=inv) as run2,
        ):
            adapter.version(tmp_path)
        assert run2.call_args.args[0] == ["python3", "-m", "pytest", "--version"]

    def test_vulture_parse_fields_exact(self):
        from harness_quality_gate.adapters.python.vulture_adapter import VultureAdapter
        stdout = (
            "a.py:7: unused function 'foo' (60% confidence)\n"
            "b.py:2: unused variable 'tmp' (100% confidence)\n"
        )
        findings = VultureAdapter().parse(stdout)
        f_full, f_min = findings[0], findings[1]
        assert f_full.message == "a.py:7 — unused function 'foo'"
        assert f_full.node == "a.py"
        assert f_min.message == "b.py:2 — unused variable 'tmp'"
        assert "XX" not in f_min.message
        assert (f_min.fix_hint or "") == "Remove dead code at b.py:2: unused variable 'tmp'"

    def test_bandit_cwe_non_dict_non_str_stays_empty(self):
        stdout = json.dumps({"results": [{
            "filename": "a.py", "issue_severity": "LOW", "cwe": [1, 2],
        }]})
        assert BanditAdapter().parse(stdout)[0].cwe == ""


class TestPytestParseDefaults:
    def test_single_arg_call_no_exitcode_or_stderr_findings(self) -> None:
        xml = '<?xml version="1.0"?><testsuites><testsuite name="p" tests="1"><testcase classname="c" name="ok"/></testsuite></testsuites>'
        findings = PytestAdapter().parse(xml)
        assert findings == []


class TestScanTargetsExcludeMutationArtifacts:
    """Simulation bug H10: the gate's own mutation artifacts (mutants/,
    .mutmut cache) polluted L3A/L1/L4 on subsequent runs because every
    adapter scanned the whole repo. Per the skill contract the project
    has src/ and tests/ — adapters must target them when present."""

    def _repo(self, tmp_path: Path, dirs=("src", "tests", "mutants")) -> Path:
        for d in dirs:
            (tmp_path / d).mkdir()
        return tmp_path

    def test_ruff_targets_src_and_tests_when_present(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path)
        adapter = RuffAdapter()
        with (
            patch("harness_quality_gate.adapters.python.ruff_adapter.shutil.which",
                  return_value="/usr/bin/ruff"),
            patch.object(adapter, "_run", return_value=MagicMock()) as run,
        ):
            adapter.invoke(repo, [])
        cmd = run.call_args.args[0]
        assert cmd == ["/usr/bin/ruff", "check", "--output-format=json",
                       "src", "tests"]

    def test_ruff_falls_back_to_repo_root_without_src_tests(self, tmp_path: Path) -> None:
        adapter = RuffAdapter()
        with (
            patch("harness_quality_gate.adapters.python.ruff_adapter.shutil.which",
                  return_value="/usr/bin/ruff"),
            patch.object(adapter, "_run", return_value=MagicMock()) as run,
        ):
            adapter.invoke(tmp_path, [])
        assert run.call_args.args[0] == ["/usr/bin/ruff", "check",
                                         "--output-format=json", "."]

    def test_pyright_targets_only_src_when_present(self, tmp_path: Path) -> None:
        """step-03a contract is ``pyright src/`` — source dirs only, no tests
        (ruff lints tests; pyright gates the shipped sources, self-eval F6)."""
        repo = self._repo(tmp_path)
        adapter = PyrightAdapter()
        with (
            patch("harness_quality_gate.adapters.python.pyright_adapter.shutil.which",
                  return_value="/usr/bin/pyright"),
            patch.object(adapter, "_run", return_value=MagicMock()) as run,
        ):
            adapter.invoke(repo, [])
        assert run.call_args.args[0] == ["/usr/bin/pyright", "--outputjson",
                                         "src"]

    def test_bandit_recurses_only_src_when_present(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path)
        adapter = BanditAdapter()
        with (
            patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which",
                  return_value="/usr/bin/bandit"),
            patch.object(adapter, "_run", return_value=MagicMock()) as run,
        ):
            adapter.invoke(repo, [])
        assert run.call_args.args[0] == ["/usr/bin/bandit", "-r", "-q",
                                         "--format", "json", "src"]

    def test_vulture_scans_only_src_when_present(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.python.vulture_adapter import VultureAdapter
        repo = self._repo(tmp_path)
        adapter = VultureAdapter()
        with (
            patch("harness_quality_gate.adapters.python.vulture_adapter.shutil.which",
                  return_value="/usr/bin/vulture"),
            patch.object(adapter, "_run", return_value=MagicMock()) as run,
        ):
            adapter.invoke(repo, [])
        assert run.call_args.args[0] == ["/usr/bin/vulture", "src"]

    def test_deptry_extends_excludes_with_mutation_artifacts(self, tmp_path: Path) -> None:
        adapter = DeptryAdapter()
        with (
            patch("harness_quality_gate.adapters.python.deptry_adapter.shutil.which",
                  return_value="/usr/bin/deptry"),
            patch.object(adapter, "_run", return_value=MagicMock()) as run,
        ):
            adapter.invoke(tmp_path, [])
        cmd = run.call_args.args[0]
        assert cmd[0] == "/usr/bin/deptry"
        assert cmd[1] == "--json-output"
        assert cmd[2].endswith(".json")
        assert cmd[3:] == ["--extend-exclude", "mutants",
                           "--extend-exclude", "\\.mutmut", "."]

    def test_pytest_collects_only_tests_dir_when_present(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path)
        adapter = PytestAdapter()
        with (
            patch("harness_quality_gate.adapters.python.pytest_adapter.shutil.which",
                  return_value="/usr/bin/python3"),
            patch.object(adapter, "_run", return_value=MagicMock(
                stdout="", stderr="", exitcode=0, duration_seconds=0.1)) as run,
        ):
            adapter.invoke(repo, [])
        cmd = run.call_args.args[0]
        assert cmd[-1] == "tests"

    def test_pytest_no_tests_dir_keeps_default_collection(self, tmp_path: Path) -> None:
        adapter = PytestAdapter()
        with (
            patch("harness_quality_gate.adapters.python.pytest_adapter.shutil.which",
                  return_value="/usr/bin/python3"),
            patch.object(adapter, "_run", return_value=MagicMock(
                stdout="", stderr="", exitcode=0, duration_seconds=0.1)) as run,
        ):
            adapter.invoke(tmp_path, [])
        cmd = run.call_args.args[0]
        assert cmd[-1] == "junit_suite_name=pytest"


class TestPackageAtRootLayout:
    """Self-eval F2: repos with the package at the repo root (no src/) were
    only partially scanned — source_targets must also detect top-level
    Python packages (dirs with __init__.py), still excluding mutation
    artifacts and conventional non-package dirs."""

    def _pkg_repo(self, tmp_path: Path) -> Path:
        (tmp_path / "mypkg").mkdir()
        (tmp_path / "mypkg" / "__init__.py").write_text("")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "__init__.py").write_text("")
        (tmp_path / "mutants").mkdir()
        (tmp_path / "mutants" / "mypkg").mkdir()
        (tmp_path / "plans").mkdir()  # plain dir without __init__.py
        (tmp_path / "stray.py").write_text("")
        return tmp_path

    def test_source_targets_detects_root_package(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.base import source_targets
        repo = self._pkg_repo(tmp_path)
        assert source_targets(repo, "src", "tests") == ["tests", "mypkg"]

    def test_source_targets_multiple_packages_sorted(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.base import source_targets
        repo = self._pkg_repo(tmp_path)
        (repo / "apkg").mkdir()
        (repo / "apkg" / "__init__.py").write_text("")
        assert source_targets(repo, "src", "tests") == ["tests", "apkg", "mypkg"]

    def test_source_targets_deduplicates_candidate_packages(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.base import source_targets
        repo = self._pkg_repo(tmp_path)
        assert source_targets(repo, "mypkg") == ["mypkg"]

    def test_source_targets_excludes_non_package_and_hidden_dirs(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.base import source_targets
        repo = self._pkg_repo(tmp_path)
        for name in ("test", "docs", "examples", "scripts", ".hidden"):
            (repo / name).mkdir()
            (repo / name / "__init__.py").write_text("")
        assert source_targets(repo, "src") == ["mypkg"]

    def test_source_targets_src_layout_unchanged(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.base import source_targets
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        assert source_targets(tmp_path, "src", "tests") == ["src", "tests"]

    def test_ruff_targets_root_package(self, tmp_path: Path) -> None:
        repo = self._pkg_repo(tmp_path)
        adapter = RuffAdapter()
        with (
            patch("harness_quality_gate.adapters.python.ruff_adapter.shutil.which",
                  return_value="/usr/bin/ruff"),
            patch.object(adapter, "_run", return_value=MagicMock()) as run,
        ):
            adapter.invoke(repo, [])
        assert run.call_args.args[0] == ["/usr/bin/ruff", "check",
                                         "--output-format=json",
                                         "tests", "mypkg"]

    def test_bandit_targets_root_package_not_tests(self, tmp_path: Path) -> None:
        repo = self._pkg_repo(tmp_path)
        adapter = BanditAdapter()
        with (
            patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which",
                  return_value="/usr/bin/bandit"),
            patch.object(adapter, "_run", return_value=MagicMock()) as run,
        ):
            adapter.invoke(repo, [])
        assert run.call_args.args[0] == ["/usr/bin/bandit", "-r", "-q",
                                         "--format", "json", "mypkg"]

    def test_vulture_targets_root_package_not_tests(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.python.vulture_adapter import VultureAdapter
        repo = self._pkg_repo(tmp_path)
        adapter = VultureAdapter()
        with (
            patch("harness_quality_gate.adapters.python.vulture_adapter.shutil.which",
                  return_value="/usr/bin/vulture"),
            patch.object(adapter, "_run", return_value=MagicMock()) as run,
        ):
            adapter.invoke(repo, [])
        assert run.call_args.args[0] == ["/usr/bin/vulture", "mypkg"]

    def test_bandit_falls_back_to_repo_root_without_packages(self, tmp_path: Path) -> None:
        adapter = BanditAdapter()
        with (
            patch("harness_quality_gate.adapters.python.bandit_adapter.shutil.which",
                  return_value="/usr/bin/bandit"),
            patch.object(adapter, "_run", return_value=MagicMock()) as run,
        ):
            adapter.invoke(tmp_path, [])
        assert run.call_args.args[0] == ["/usr/bin/bandit", "-r", "-q",
                                         "--format", "json", str(tmp_path)]

    def test_source_targets_nonexistent_repo_no_crash(self, tmp_path: Path) -> None:
        """A repo path that does not exist must not crash package detection.

        Several adapter tests (and degraded runs) pass paths that were never
        created; iterdir() on them raised FileNotFoundError (F2 regression).
        """
        from harness_quality_gate.adapters.base import source_targets
        ghost = tmp_path / "does-not-exist"
        assert source_targets(ghost, "src", "tests") == []

    def test_pyright_targets_root_package_not_tests(self, tmp_path: Path) -> None:
        repo = self._pkg_repo(tmp_path)
        adapter = PyrightAdapter()
        with (
            patch("harness_quality_gate.adapters.python.pyright_adapter.shutil.which",
                  return_value="/usr/bin/pyright"),
            patch.object(adapter, "_run", return_value=MagicMock()) as run,
        ):
            adapter.invoke(repo, [])
        assert run.call_args.args[0] == ["/usr/bin/pyright", "--outputjson",
                                         "mypkg"]
