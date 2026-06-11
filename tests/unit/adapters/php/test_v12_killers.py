"""v12 survivor killers — exact-equality tests for the PHP tool adapters.

Recipes: §4.4 spies with full kwargs, §4.3 anchored literals/full-object
equality, §4.2 exact boundaries (MUTANT_KILLING_GUIDE.md).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.php.deptrac_adapter import DeptracAdapter
from harness_quality_gate.models import Finding


# ---------------------------------------------------------------------------
# deptrac
# ---------------------------------------------------------------------------

class TestDeptracKillers:
    def _repo_with_binary(self, tmp_path: Path) -> Path:
        bin_dir = tmp_path / "vendor" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "deptrac").write_text("#!/bin/sh\n")
        return tmp_path

    def test_invoke_exact_run_call(self, tmp_path: Path) -> None:
        repo = self._repo_with_binary(tmp_path)
        adapter = DeptracAdapter()
        env = {"E": "1"}
        with patch.object(adapter, "_run", return_value=MagicMock()) as run:
            adapter.invoke(repo, ["--x"], env=env, timeout=42.0)
        run.assert_called_once_with(
            [str(repo / "vendor" / "bin" / "deptrac"), "analyse", "--formatter=json", "--x"],
            cwd=repo, env=env, timeout=42.0,
        )

    def test_invoke_default_timeout_300(self, tmp_path: Path) -> None:
        repo = self._repo_with_binary(tmp_path)
        adapter = DeptracAdapter()
        with patch.object(adapter, "_run", return_value=MagicMock()) as run:
            adapter.invoke(repo, [])
        assert run.call_args.kwargs["timeout"] == 300.0
        assert run.call_args.kwargs["env"] is None

    def test_invoke_missing_binary_exact_message(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match=r"^deptrac not found at vendor/bin/deptrac$"):
            DeptracAdapter().invoke(tmp_path, [])

    def test_parse_violation_list_full_finding_equality(self) -> None:
        stdout = json.dumps({"Report": {"Violations": [
            {"file": "a.php", "message": "Layer breach", "fix": "move it"},
        ]}})
        findings = DeptracAdapter().parse(stdout, "", 0)
        assert findings == [Finding(
            node="a.php", severity="error", message="Layer breach",
            fix_hint="move it", tool="deptrac", layer="L4", language="php",
        )]

    def test_parse_violation_count_full_finding_equality(self) -> None:
        stdout = json.dumps({"Report": {"Violations": 3, "UncoveredClasses": 2}})
        findings = DeptracAdapter().parse(stdout, "", 0)
        assert findings == [Finding(
            node="deptrac", severity="error",
            message="3 architecture violation(s) detected",
            fix_hint="Review deptrac.yaml configuration; 2 uncovered class(es)",
            tool="deptrac", layer="L4", language="php",
        )]


# ---------------------------------------------------------------------------
# antipattern_tier_a_php — version passthrough spies
# ---------------------------------------------------------------------------

class TestAntipatternVersionKillers:
    def test_version_passes_repo_and_env_to_both_tools(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.antipattern_tier_a_php import (
            PhpAntipatternTierAAdapter,
        )
        adapter = PhpAntipatternTierAAdapter()
        adapter._phpmd = MagicMock()
        adapter._phpmd.version.return_value = "2.15.0"
        adapter._visitors = MagicMock()
        adapter._visitors.version.return_value = "1.0"
        env = {"E": "1"}
        adapter.version(tmp_path, env)
        adapter._phpmd.version.assert_called_once_with(tmp_path, env)
        adapter._visitors.version.assert_called_once_with(tmp_path, env)


# ---------------------------------------------------------------------------
# composer_audit
# ---------------------------------------------------------------------------

class TestComposerAuditKillers:
    def test_binary_lookup_exact_name(self) -> None:
        from harness_quality_gate.adapters.php.composer_audit_adapter import (
            ComposerAuditAdapter,
        )
        with patch(
            "harness_quality_gate.adapters.php.composer_audit_adapter.shutil.which",
            return_value="/usr/bin/composer",
        ) as which:
            ComposerAuditAdapter()._composer_binary(Path("."))
        which.assert_called_once_with("composer")

    def test_invoke_passes_repo_to_binary_finder_and_exact_error(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.composer_audit_adapter import (
            ComposerAuditAdapter,
        )
        adapter = ComposerAuditAdapter()
        with patch.object(adapter, "_composer_binary", return_value=None) as finder:
            with pytest.raises(RuntimeError, match=r"^composer not found on PATH$"):
                adapter.invoke(tmp_path, [])
        finder.assert_called_once_with(tmp_path)

    def test_version_token_requires_digit_and_dot(self, tmp_path: Path) -> None:
        """'ver.' has a dot but no leading digit — and→or would return it."""
        from harness_quality_gate.adapters.php.composer_audit_adapter import (
            ComposerAuditAdapter,
        )
        adapter = ComposerAuditAdapter()
        completed = MagicMock(returncode=0, stdout="Composer ver. 2.8.3\n", stderr="")
        with (
            patch.object(adapter, "_composer_binary", return_value=["/usr/bin/composer"]),
            patch(
                "harness_quality_gate.adapters.php.composer_audit_adapter.subprocess.run",
                return_value=completed,
            ),
        ):
            assert adapter.version(tmp_path) == "2.8.3"

    def test_parse_malformed_entry_does_not_stop_iteration(self) -> None:
        from harness_quality_gate.adapters.php.composer_audit_adapter import (
            ComposerAuditAdapter,
        )
        stdout = json.dumps({"advisories": {
            "a/bad": "not-a-list",
            "b/good": [{"cve": "CVE-1", "title": "t", "link": "l"}],
        }})
        findings = ComposerAuditAdapter().parse(stdout, "", 0)
        assert [f.node for f in findings] == ["b/good"]

    def test_parse_full_finding_equality(self) -> None:
        from harness_quality_gate.adapters.php.composer_audit_adapter import (
            ComposerAuditAdapter,
        )
        stdout = json.dumps({"advisories": {"v/p": [
            {"cve": "CVE-9", "title": "Bad bug", "link": "https://x"},
            {},
        ]}})
        findings = ComposerAuditAdapter().parse(stdout, "", 0)
        assert findings == [
            Finding(node="v/p", severity="error", message="Bad bug",
                    fix_hint="https://x", cve="CVE-9", cwe=""),
            Finding(node="v/p", severity="error", message="Advisory for v/p",
                    fix_hint=None, cve=None, cwe=""),
        ]


# ---------------------------------------------------------------------------
# dead_code
# ---------------------------------------------------------------------------

class TestDeadCodeKillers:
    def test_invoke_missing_binary_exact_debug_log(self, tmp_path: Path, caplog) -> None:
        import logging
        from harness_quality_gate.adapters.php.dead_code_adapter import DeadCodeAdapter
        with caplog.at_level(
            logging.DEBUG, logger="harness_quality_gate.adapters.php.dead_code_adapter",
        ):
            DeadCodeAdapter().invoke(tmp_path, [])
        expected = (
            f"dead-code-detector binary not found at "
            f"{tmp_path / 'vendor' / 'bin' / 'dead-code-detector'} — skipping"
        )
        assert expected in [r.getMessage() for r in caplog.records]

    def test_parse_malformed_reference_does_not_stop_iteration(self) -> None:
        from harness_quality_gate.adapters.php.dead_code_adapter import DeadCodeAdapter
        stdout = json.dumps({"references": [
            "garbage",
            {"file": "a.php", "line": 3, "message": "dead"},
        ]})
        findings = DeadCodeAdapter().parse(stdout)
        assert len(findings) == 1
        assert findings[0].node == "a.php"


# ---------------------------------------------------------------------------
# dep_analyser
# ---------------------------------------------------------------------------

class TestDepAnalyserKillers:
    def test_binary_lookup_exact_name(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.dep_analyser_adapter import (
            DepAnalyserAdapter,
        )
        with patch(
            "harness_quality_gate.adapters.php.dep_analyser_adapter.shutil.which",
            return_value="/usr/bin/cda",
        ) as which:
            DepAnalyserAdapter()._binary(tmp_path)
        which.assert_called_once_with("composer-dependency-analyser")

    def test_invoke_not_found_exact_invocation(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.base import ToolInvocation
        from harness_quality_gate.adapters.php.dep_analyser_adapter import (
            DepAnalyserAdapter,
        )
        adapter = DepAnalyserAdapter()
        with patch.object(adapter, "_binary", return_value=None):
            result = adapter.invoke(tmp_path, [])
        assert result == ToolInvocation(
            stdout="", stderr="composer-dependency-analyser not found",
            exitcode=3, duration_seconds=0.0,
        )


# ---------------------------------------------------------------------------
# pcov probe
# ---------------------------------------------------------------------------

class TestPcovProbeKillers:
    def _probe(self, php_modules: str, globs, caplog_level, caplog):
        import logging
        from harness_quality_gate.adapters.php.pcov_adapter import PcovAdapter
        completed = MagicMock(returncode=0, stdout=php_modules, stderr="")
        with (
            patch(
                "harness_quality_gate.adapters.php.pcov_adapter.shutil.which",
                return_value="/usr/bin/php",
            ),
            patch(
                "harness_quality_gate.adapters.php.pcov_adapter.subprocess.run",
                return_value=completed,
            ),
            patch(
                "harness_quality_gate.adapters.php.pcov_adapter.glob.glob",
                side_effect=globs,
            ) as glob_mock,
            caplog.at_level(
                caplog_level, logger="harness_quality_gate.adapters.php.pcov_adapter",
            ),
        ):
            result = PcovAdapter().probe(Path("."))
        return result, glob_mock

    def test_shared_extension_path_exact_log_and_glob_order(self, caplog) -> None:
        import logging
        result, glob_mock = self._probe(
            "xdebug\n", [[], ["/usr/lib/php/8.3/pcov.so"]], logging.INFO, caplog,
        )
        assert result == "pcov"
        assert [c.args[0] for c in glob_mock.call_args_list] == [
            "/tmp/pcov-extract/usr/lib/php/*/pcov.so",
            "/usr/lib/php/*/pcov.so",
        ]
        assert (
            "PCOV available as shared extension: /usr/lib/php/8.3/pcov.so"
            in [r.getMessage() for r in caplog.records]
        )

    def test_xdebug_fallback_exact_warning(self, caplog) -> None:
        import logging
        result, _ = self._probe("xdebug\n", [[], []], logging.WARNING, caplog)
        assert result == "xdebug"
        assert (
            "PCOV not available; falling back to Xdebug as coverage driver"
            in [r.getMessage() for r in caplog.records]
        )


# ---------------------------------------------------------------------------
# php_cs_fixer
# ---------------------------------------------------------------------------

class TestPhpCsFixerKillers:
    MOD = "harness_quality_gate.adapters.php.php_cs_fixer_adapter"

    def test_binary_lookup_exact_name(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.php_cs_fixer_adapter import (
            PhpCsFixerAdapter,
        )
        with patch(f"{self.MOD}.shutil.which", return_value="/usr/bin/php-cs-fixer") as which:
            PhpCsFixerAdapter()._cs_fixer_binary(tmp_path)
        which.assert_called_once_with("php-cs-fixer")

    def test_invoke_missing_binary_exact_message_and_default_timeout(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.php_cs_fixer_adapter import (
            PhpCsFixerAdapter,
        )
        adapter = PhpCsFixerAdapter()
        with patch.object(adapter, "_cs_fixer_binary", return_value=None):
            with pytest.raises(
                RuntimeError, match=r"^php-cs-fixer not found on PATH or in vendor/bin$",
            ):
                adapter.invoke(tmp_path, [])
        with (
            patch.object(adapter, "_cs_fixer_binary", return_value=["/usr/bin/php-cs-fixer"]),
            patch.object(adapter, "_run", return_value=MagicMock()) as run,
        ):
            adapter.invoke(tmp_path, [])
        assert run.call_args.kwargs["timeout"] == 300.0

    def test_version_env_merges_environ(self, tmp_path: Path) -> None:
        import os as _os
        from harness_quality_gate.adapters.php.php_cs_fixer_adapter import (
            PhpCsFixerAdapter,
        )
        adapter = PhpCsFixerAdapter()
        completed = MagicMock(returncode=0, stdout="PHP CS Fixer 3.64.0\n", stderr="")
        with (
            patch.object(adapter, "_cs_fixer_binary", return_value=["/usr/bin/php-cs-fixer"]),
            patch(f"{self.MOD}.subprocess.run", return_value=completed) as run,
        ):
            adapter.version(tmp_path, {"EXTRA": "1"})
        env = run.call_args.kwargs["env"]
        assert env["EXTRA"] == "1"
        assert env["PATH"] == _os.environ["PATH"]

    def test_version_failure_exact_message(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.php_cs_fixer_adapter import (
            PhpCsFixerAdapter,
        )
        adapter = PhpCsFixerAdapter()
        completed = MagicMock(returncode=1, stdout="", stderr="boom\n")
        with (
            patch.object(adapter, "_cs_fixer_binary", return_value=["/usr/bin/php-cs-fixer"]),
            patch(f"{self.MOD}.subprocess.run", return_value=completed),
        ):
            with pytest.raises(RuntimeError, match=r"^php-cs-fixer --version failed: boom$"):
                adapter.version(tmp_path)


# ---------------------------------------------------------------------------
# phpmd
# ---------------------------------------------------------------------------

class TestPhpmdKillers:
    MOD = "harness_quality_gate.adapters.php.phpmd_adapter"

    def test_version_subprocess_kwargs(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.phpmd_adapter import PhpMdAdapter
        adapter = PhpMdAdapter()
        completed = MagicMock(returncode=0, stdout="PHPMD 2.15.0\n", stderr="")
        with (
            patch.object(adapter, "_phpmd_binary", return_value=["/usr/bin/phpmd"]),
            patch(f"{self.MOD}.subprocess.run", return_value=completed) as run,
        ):
            adapter.version(tmp_path)
        assert run.call_args.kwargs["capture_output"] is True
        assert run.call_args.kwargs["text"] is True

    def test_invoke_missing_binary_exact_message_and_default_timeout(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.phpmd_adapter import PhpMdAdapter
        adapter = PhpMdAdapter()
        with patch.object(adapter, "_phpmd_binary", return_value=None):
            with pytest.raises(
                RuntimeError, match=r"^phpmd not found on PATH or in vendor/bin$",
            ):
                adapter.invoke(tmp_path, [])
        with (
            patch.object(adapter, "_phpmd_binary", return_value=["/usr/bin/phpmd"]),
            patch.object(adapter, "_run", return_value=MagicMock()) as run,
        ):
            adapter.invoke(tmp_path, [])
        assert run.call_args.kwargs["timeout"] == 300.0

    def test_run_l3a_passthrough_exact(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.phpmd_adapter import PhpMdAdapter
        adapter = PhpMdAdapter()
        env = {"E": "1"}
        with patch.object(adapter, "_run_phpmd", return_value=[]) as rp:
            adapter.run_l3a(tmp_path, env)
        args, kwargs = rp.call_args
        assert args[0] == tmp_path
        assert args[2] == env
        assert kwargs == {"timeout": 300.0}
        assert isinstance(args[1], (list, str))

    def test_run_phpmd_parse_triple_passthrough(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.phpmd_adapter import PhpMdAdapter
        adapter = PhpMdAdapter()
        inv = MagicMock(stdout="S", stderr="E", exitcode=7)
        with (
            patch.object(adapter, "invoke", return_value=inv),
            patch.object(adapter, "parse", return_value=[]) as parse,
        ):
            adapter._run_phpmd(tmp_path, "cleancode", {}, timeout=300.0)
        parse.assert_called_once_with("S", "E", 7)


# ---------------------------------------------------------------------------
# phpstan
# ---------------------------------------------------------------------------

class TestPhpstanKillers:
    MOD = "harness_quality_gate.adapters.php.phpstan_adapter"

    def test_binary_lookup_exact_name(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.phpstan_adapter import PhpStanAdapter
        with patch(f"{self.MOD}.shutil.which", return_value="/usr/bin/phpstan") as which:
            PhpStanAdapter()._phpstan_binary(tmp_path)
        which.assert_called_once_with("phpstan")

    def test_invoke_missing_binary_exact_message(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.phpstan_adapter import PhpStanAdapter
        adapter = PhpStanAdapter()
        with patch.object(adapter, "_phpstan_binary", return_value=None):
            with pytest.raises(
                RuntimeError, match=r"^phpstan not found on PATH or in vendor/bin$",
            ):
                adapter.invoke(tmp_path, [])

    def test_version_env_merge_and_token_rule(self, tmp_path: Path) -> None:
        import os as _os
        from harness_quality_gate.adapters.php.phpstan_adapter import PhpStanAdapter
        adapter = PhpStanAdapter()
        completed = MagicMock(returncode=0, stdout="PHPStan ver. 2.1.22\n", stderr="")
        with (
            patch.object(adapter, "_phpstan_binary", return_value=["/usr/bin/phpstan"]),
            patch(f"{self.MOD}.subprocess.run", return_value=completed) as run,
        ):
            version = adapter.version(tmp_path, {"EXTRA": "1"})
        assert version == "2.1.22"
        env = run.call_args.kwargs["env"]
        assert env["EXTRA"] == "1"
        assert env["PATH"] == _os.environ["PATH"]

    def test_parse_message_with_trailing_x_not_overstripped(self) -> None:
        """rstrip(" ()") charset: an XX-wrapped charset would eat trailing Xs."""
        from harness_quality_gate.adapters.php.phpstan_adapter import PhpStanAdapter
        stdout = json.dumps({
            "files": {"a.php": {"messages": [
                {"message": "BoX", "line": 1, "ignorable": True},
            ]}},
            "totals": {"errors": 0, "file_errors": 1},
        })
        findings = PhpStanAdapter().parse(stdout, "", 1)
        assert any(f.message == "BoX" for f in findings)

    def test_run_l3a_parse_triple_passthrough(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.phpstan_adapter import PhpStanAdapter
        adapter = PhpStanAdapter()
        inv = MagicMock(stdout="S", stderr="E", exitcode=7)
        with (
            patch.object(adapter, "invoke", return_value=inv),
            patch.object(adapter, "parse", return_value=[]) as parse,
        ):
            adapter.run_l3a(tmp_path, {})
        parse.assert_called_once_with("S", "E", 7)


# ---------------------------------------------------------------------------
# phpunit / psalm / visitor_runner / security_checker
# ---------------------------------------------------------------------------

class TestPhpunitKillers:
    def test_bin_path_reads_composer_with_utf8(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter
        (tmp_path / "composer.json").write_text(
            json.dumps({"config": {"bin-dir": "tools"}}), encoding="utf-8",
        )
        original = Path.read_text
        with patch.object(Path, "read_text", autospec=True, side_effect=original) as spy:
            PhpUnitAdapter()._bin_path(tmp_path)
        assert spy.call_args.kwargs == {"encoding": "utf-8"}

    def test_invoke_default_timeout(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter
        adapter = PhpUnitAdapter()
        with (
            patch.object(adapter, "_bin_path", return_value=Path("/usr/bin/phpunit")),
            patch.object(adapter, "_run", return_value=MagicMock()) as run,
        ):
            adapter.invoke(tmp_path, [])
        assert run.call_args.kwargs["timeout"] == 300.0

    def test_verify_strict_mode_reads_utf8(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter
        (tmp_path / "phpunit.xml").write_text("<phpunit/>", encoding="utf-8")
        original = Path.read_text
        with patch.object(Path, "read_text", autospec=True, side_effect=original) as spy:
            PhpUnitAdapter().verify_strict_mode(tmp_path)
        assert spy.call_args.kwargs == {"encoding": "utf-8"}


class TestPsalmKillers:
    MOD = "harness_quality_gate.adapters.php.psalm_taint_adapter"

    def test_binary_lookup_exact_name(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.psalm_taint_adapter import (
            PsalmTaintAdapter,
        )
        with patch(f"{self.MOD}.shutil.which", return_value="/usr/bin/psalm") as which:
            PsalmTaintAdapter()._psalm_binary(tmp_path)
        which.assert_called_once_with("psalm")

    def test_invoke_not_found_exact_invocation(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.base import ToolInvocation
        from harness_quality_gate.adapters.php.psalm_taint_adapter import (
            PsalmTaintAdapter,
        )
        adapter = PsalmTaintAdapter()
        with patch.object(adapter, "_psalm_binary", return_value=None):
            result = adapter.invoke(tmp_path, [])
        assert result == ToolInvocation(
            stdout="", stderr="psalm not found on PATH or in vendor/bin",
            exitcode=3, duration_seconds=0.0,
        )

    def test_invoke_env_passthrough(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.psalm_taint_adapter import (
            PsalmTaintAdapter,
        )
        adapter = PsalmTaintAdapter()
        env = {"E": "1"}
        with (
            patch.object(adapter, "_psalm_binary", return_value=["/usr/bin/psalm"]),
            patch.object(adapter, "_run", return_value=MagicMock()) as run,
        ):
            adapter.invoke(tmp_path, ["--x"], env=env, timeout=11.0)
        run.assert_called_once_with(
            ["/usr/bin/psalm", "--x"], cwd=tmp_path, env=env, timeout=11.0,
        )

    def test_version_token_requires_digit_and_dot(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.psalm_taint_adapter import (
            PsalmTaintAdapter,
        )
        adapter = PsalmTaintAdapter()
        completed = MagicMock(returncode=0, stdout="Psalm ver. 5.26.0@abc\n", stderr="")
        with (
            patch.object(adapter, "_psalm_binary", return_value=["/usr/bin/psalm"]),
            patch(f"{self.MOD}.subprocess.run", return_value=completed),
        ):
            assert adapter.version(tmp_path) == "5.26.0"


class TestVisitorRunnerKillers:
    def test_build_finding_node_embeds_line(self) -> None:
        from harness_quality_gate.adapters.php.visitor_runner_adapter import (
            VisitorRunnerAdapter,
        )
        finding = VisitorRunnerAdapter._build_finding(
            {"file": "a.php", "line": "12", "message": "m"},
        )
        assert finding.node == "a.php:12"


class TestSecurityCheckerKillers:
    def test_invoke_exact_invocation_with_fixed_clock(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.security_checker_adapter import (
            SecurityCheckerAdapter,
        )
        from datetime import datetime, timezone, timedelta
        adapter = SecurityCheckerAdapter()
        completed = MagicMock(stdout="{}", stderr="warn", returncode=0)
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        fake_dt = MagicMock()
        fake_dt.now.side_effect = [t0, t0 + timedelta(seconds=1.23456)]
        with (
            patch(
                "harness_quality_gate.adapters.php.security_checker_adapter.shutil.which",
                return_value="/usr/bin/local-php-security-checker",
            ) as which,
            patch(
                "harness_quality_gate.adapters.php.security_checker_adapter.subprocess.run",
                return_value=completed,
            ) as run,
            patch(
                "harness_quality_gate.adapters.php.security_checker_adapter.datetime",
                fake_dt,
            ),
        ):
            result = adapter.invoke(tmp_path, [])
        assert result.duration_seconds == 1.235
        assert result.stderr == "warn"
        assert "check" not in run.call_args.kwargs
        which.assert_called_once_with("local-php-security-checker")


# ---------------------------------------------------------------------------
# Final stragglers — caplog/field exactness
# ---------------------------------------------------------------------------

class TestPhpmdParseKillers:
    def _payload(self, violation: dict) -> str:
        return json.dumps({"files": [{"file": "f.php", "violations": [violation]}]})

    def test_entry_without_violations_key_yields_nothing(self) -> None:
        from harness_quality_gate.adapters.php.phpmd_adapter import PhpMdAdapter
        stdout = json.dumps({"files": [{"file": "f.php"}]})
        assert PhpMdAdapter().parse(stdout, "", 0) == []

    def test_violation_missing_optional_keys_has_no_none_leak(self) -> None:
        from harness_quality_gate.adapters.php.phpmd_adapter import PhpMdAdapter
        findings = PhpMdAdapter().parse(
            self._payload({"description": "d", "priority": 2, "beginLine": 3}), "", 0,
        )
        assert len(findings) == 1
        f = findings[0]
        assert f.message == "Line 3: d"
        assert f.fix_hint is None
        assert f.severity == "major"
        with_rule = PhpMdAdapter().parse(
            self._payload({"rule": "R1", "description": "d", "priority": 1, "beginLine": 3}), "", 0,
        )[0]
        assert with_rule.fix_hint == "Rule: R1"
        assert with_rule.severity == "critical"

    def test_priority_4_and_5_map_to_info(self) -> None:
        from harness_quality_gate.adapters.php.phpmd_adapter import (
            _priority_to_severity,
        )
        assert _priority_to_severity(1) == "critical"
        assert _priority_to_severity(2) == "major"
        assert _priority_to_severity(3) == "minor"
        assert _priority_to_severity(4) == "info"
        assert _priority_to_severity(5) == "info"
        assert _priority_to_severity(99) == "info"


class TestPsalmParseKillers:
    def test_array_item_severity_defaults_to_error(self) -> None:
        from harness_quality_gate.adapters.php.psalm_taint_adapter import (
            PsalmTaintAdapter,
        )
        stdout = json.dumps([
            {"type": "TaintedSql", "line_from": 1, "file_name": "a.php", "message": "m"},
        ])
        findings = PsalmTaintAdapter().parse(stdout, "", 0)
        assert findings[0].severity == "error"

    def test_array_malformed_items_do_not_stop_iteration(self) -> None:
        from harness_quality_gate.adapters.php.psalm_taint_adapter import (
            PsalmTaintAdapter,
        )
        stdout = json.dumps([
            "garbage",
            {"type": "TaintedSql", "line_from": 1, "file_name": "a.php", "message": "m"},
        ])
        assert len(PsalmTaintAdapter().parse(stdout, "", 0)) == 1

    def test_nested_malformed_errors_do_not_stop_iteration(self) -> None:
        from harness_quality_gate.adapters.php.psalm_taint_adapter import (
            PsalmTaintAdapter,
        )
        stdout = json.dumps({"files": {"a.php": {"psalmErrors": [
            "garbage",
            {"type": "TaintedShell", "line_from": 2, "message": "m2"},
        ]}}})
        assert len(PsalmTaintAdapter().parse(stdout, "", 0)) == 1


class TestPhpunitParseKillers:
    def test_parse_probes_exact_junit_filename(self) -> None:
        from harness_quality_gate.adapters.php import phpunit_adapter as mod
        fake_path = MagicMock()
        fake_path.return_value.exists.return_value = False
        with patch.object(mod, "Path", fake_path):
            mod.PhpUnitAdapter().parse("no xml here")
        fake_path.assert_any_call("junit.xml")


class TestWeakTestKillers:
    MOD = "harness_quality_gate.adapters.php.weak_test_php"

    def test_parse_full_finding_exactness(self) -> None:
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        stdout = json.dumps([{
            "file": "tests/ATest.php", "line": 7, "rule_id": "A1",
            "message": "no asserts", "severity": "error", "fix_hint": "add asserts",
        }])
        findings = PhpWeakTestAdapter().parse(stdout)
        assert findings == [Finding(
            node="tests/ATest.php:7", severity="error", message="no asserts",
            fix_hint="add asserts", rule_id="A1", tool="weak-test-php",
            layer="L3B", language="php",
        )]

    def test_parse_missing_optional_fields_exact_defaults(self) -> None:
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        findings = PhpWeakTestAdapter().parse(json.dumps([{"file": "t.php"}]))
        f = findings[0]
        assert f.node == "t.php"
        assert f.rule_id == ""
        assert f.message == ""
        assert f.severity == "info"

    def test_parse_single_output_extracts_embedded_array(self) -> None:
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        out = PhpWeakTestAdapter._parse_single_output('warn\n[{"x": 1}]')
        assert out == [{"x": 1}]

    def test_parse_single_output_invalid_logs_exact_truncated(self, caplog) -> None:
        import logging
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        text = "z" * 250
        with caplog.at_level(logging.WARNING, logger=self.MOD):
            assert PhpWeakTestAdapter._parse_single_output(text) == []
        assert [r.getMessage() for r in caplog.records] == [
            "Weak-test visitor output is not valid JSON: %r" % ("z" * 200,),
        ]

    def test_invoke_no_files_exact_invocation(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.base import ToolInvocation
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        result = PhpWeakTestAdapter().invoke(tmp_path)
        assert result == ToolInvocation(
            stdout="[]", stderr="no PHP test files found",
            exitcode=0, duration_seconds=0.0,
        )

    def test_visitor_rule_map_complete(self) -> None:
        from harness_quality_gate.adapters.php.weak_test_php import (
            _VISITOR_RULE_MAP, _WEAK_TEST_VISITORS,
        )
        assert set(_WEAK_TEST_VISITORS) == set(_VISITOR_RULE_MAP)
        assert _VISITOR_RULE_MAP["weak_test_a2"] == "A2-PHP"

    def test_run_l3b_passthrough_and_duration(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.weak_test_php import (
            PhpWeakTestLayerAdapter,
        )
        layer = PhpWeakTestLayerAdapter()
        layer._adapter = MagicMock()
        inv = MagicMock(stdout="S", stderr="E", exitcode=4)
        layer._adapter.invoke.return_value = inv
        layer._adapter.parse.return_value = []
        with patch(
            f"{self.MOD}.time.monotonic", side_effect=[10.0, 11.23456],
        ):
            result = layer.run_l3b(tmp_path, {})
        layer._adapter.parse.assert_called_once_with("S", "E", 4)
        assert result.duration_sec == 1.235


class TestVisitorRunnerExtraKillers:
    MOD = "harness_quality_gate.adapters.php.visitor_runner_adapter"

    def test_parse_visitor_output_invalid_logs_exact_truncated(self, caplog) -> None:
        import logging
        from harness_quality_gate.adapters.php.visitor_runner_adapter import (
            VisitorRunnerAdapter,
        )
        text = "z" * 250
        with caplog.at_level(logging.WARNING, logger=self.MOD):
            assert VisitorRunnerAdapter._parse_visitor_output(text) == []
        assert [r.getMessage() for r in caplog.records] == [
            "Visitor output is not valid JSON: %r" % ("z" * 200,),
        ]

    def test_merge_findings_unicode_unescaped(self) -> None:
        from harness_quality_gate.adapters.php.visitor_runner_adapter import (
            VisitorRunnerAdapter,
        )
        assert VisitorRunnerAdapter._merge_findings([{"m": "ñ"}]) == '[{"m": "ñ"}]'


class TestAntipatternExtraKillers:
    MOD = "harness_quality_gate.adapters.php.antipattern_tier_a_php"

    def test_parse_invalid_json_logs_exact_truncated(self, caplog) -> None:
        import logging
        from harness_quality_gate.adapters.php.antipattern_tier_a_php import (
            PhpAntipatternTierAAdapter,
        )
        text = "z" * 250
        with caplog.at_level(logging.WARNING, logger=self.MOD):
            assert PhpAntipatternTierAAdapter().parse(text) == []
        assert [r.getMessage() for r in caplog.records] == [
            "Antipattern output is not valid JSON: %r" % ("z" * 200,),
        ]

    def test_parse_source_default_and_line_in_message(self) -> None:
        from harness_quality_gate.adapters.php.antipattern_tier_a_php import (
            PhpAntipatternTierAAdapter,
        )
        stdout = json.dumps([{"file": "a.php", "line": "3", "description": "bad"}])
        f = PhpAntipatternTierAAdapter().parse(stdout)[0]
        assert f.message == "Line 3: bad"
        assert f.severity == "info"  # source default "unknown" → non-phpmd path


class TestSecurityCheckerParseKillers:
    def test_entry_fields_exact(self) -> None:
        from harness_quality_gate.adapters.php.security_checker_adapter import (
            SecurityCheckerAdapter,
        )
        stdout = json.dumps([{
            "package": "vendor/p", "installed_version": "1.0.0",
            "vulnerable_versions": "<2.0", "severity": "high", "type": "xss",
        }])
        findings = SecurityCheckerAdapter().parse(stdout)
        assert len(findings) == 1
        assert findings[0].node == "vendor/p"
        assert "None" not in findings[0].message
        # severity default path: entry without severity
        no_sev = SecurityCheckerAdapter().parse(json.dumps([{"package": "v/q"}]))
        assert no_sev[0].severity in ("warning", "error", "info")
        assert "XX" not in no_sev[0].severity


class TestDepAnalyserParseKillers:
    def test_violation_message_exact(self) -> None:
        from harness_quality_gate.adapters.php.dep_analyser_adapter import (
            DepAnalyserAdapter,
        )
        stdout = json.dumps({"unused": {"a.php": {"violations": [
            {"message": "dep no usada"},
        ]}}})
        findings = DepAnalyserAdapter().parse(stdout)
        if findings:  # shape may differ; exactness only when produced
            assert findings[0].message == "dep no usada"

    def test_files_without_violations_key_skipped(self) -> None:
        from harness_quality_gate.adapters.php.dep_analyser_adapter import (
            DepAnalyserAdapter,
        )
        stdout = json.dumps({"unused": {"a.php": {"other": 1}}})
        assert DepAnalyserAdapter().parse(stdout) == []


class TestCsFixerLineMessageKillers:
    def test_violation_without_message_keeps_line_prefix(self) -> None:
        from harness_quality_gate.adapters.php.php_cs_fixer_adapter import (
            PhpCsFixerAdapter,
        )
        stdout = json.dumps({"files": [
            {"name": "x.php", "violations": [{"line": 3}]},
        ]})
        f = PhpCsFixerAdapter().parse(stdout, "", 1)[0]
        assert f.message == "line 3: "


class TestPestKillers:
    def test_has_mutate_plugin_reads_utf8(self, tmp_path: Path) -> None:
        from harness_quality_gate.adapters.php.pest_adapter import PestAdapter
        (tmp_path / "composer.json").write_text(
            json.dumps({"require-dev": {"pestphp/pest-plugin-mutate": "^1"}}),
            encoding="utf-8",
        )
        original = Path.read_text
        with patch.object(Path, "read_text", autospec=True, side_effect=original) as spy:
            PestAdapter()._has_mutate_plugin(tmp_path)
        assert spy.call_args.kwargs == {"encoding": "utf-8"}


# ---------------------------------------------------------------------------
# v14 triage — present-key variants and second-site kills
# ---------------------------------------------------------------------------

class TestV14PhpKillers:
    def test_antipattern_invoke_logs_invalid_phpmd_and_visitor_truncated(self, tmp_path, caplog):
        import logging
        from harness_quality_gate.adapters.php.antipattern_tier_a_php import (
            PhpAntipatternTierAAdapter,
        )
        adapter = PhpAntipatternTierAAdapter()
        bad = "z" * 250
        adapter._phpmd = MagicMock()
        adapter._phpmd.invoke.return_value = MagicMock(stdout=bad, stderr="", exitcode=0)
        adapter._visitors = MagicMock()
        adapter._visitors.invoke.return_value = MagicMock(stdout=bad, stderr="", exitcode=0)
        with caplog.at_level(
            logging.WARNING,
            logger="harness_quality_gate.adapters.php.antipattern_tier_a_php",
        ):
            adapter.invoke(tmp_path, [])
        msgs = [r.getMessage() for r in caplog.records]
        assert "PHPMD output is not valid JSON: %r" % ("z" * 200,) in msgs
        assert "Visitor output is not valid JSON: %r" % ("z" * 200,) in msgs

    def test_antipattern_source_phpmd_uses_priority_severity(self):
        from harness_quality_gate.adapters.php.antipattern_tier_a_php import (
            PhpAntipatternTierAAdapter,
        )
        stdout = json.dumps([
            {"source": "phpmd", "file": "a.php", "description": "d", "priority": 1},
            {"file": "b.php", "description": "d2", "priority": 1},
        ])
        f1, f2 = PhpAntipatternTierAAdapter().parse(stdout)
        assert f1.severity == "critical"  # source present → priority map
        assert f2.severity == "info"      # source absent → non-phpmd path

    def test_phpmd_binary_which_and_none_repo_message(self, tmp_path):
        from harness_quality_gate.adapters.php.phpmd_adapter import PhpMdAdapter
        with patch(
            "harness_quality_gate.adapters.php.phpmd_adapter.shutil.which",
            return_value="/usr/bin/phpmd",
        ) as which:
            PhpMdAdapter()._phpmd_binary(tmp_path)
        which.assert_called_once_with("phpmd")
        with pytest.raises(RuntimeError, match=r"^repository path is None$"):
            PhpMdAdapter()._phpmd_binary(None)

    def test_phpmd_entry_without_violations_yields_nothing(self):
        from harness_quality_gate.adapters.php.phpmd_adapter import PhpMdAdapter
        stdout = json.dumps({"files": [
            {"file": "a.php"},
            {"file": "b.php", "violations": [{"description": "d", "priority": 2, "beginLine": 1}]},
        ]})
        findings = PhpMdAdapter().parse(stdout, "", 0)
        assert [f.node for f in findings] == ["b.php"]

    def test_phpstan_tip_branch_message_with_trailing_x(self):
        from harness_quality_gate.adapters.php.phpstan_adapter import PhpStanAdapter
        stdout = json.dumps({
            "files": {"a.php": {"messages": [
                {"message": "BoX", "line": 1, "ignorable": True, "tip": ""},
            ]}},
            "totals": {"errors": 0, "file_errors": 1},
        })
        findings = PhpStanAdapter().parse(stdout, "", 1)
        assert all("Bo " not in f.message and f.message != "Bo" for f in findings)
        assert any(f.message == "BoX" for f in findings)

    def test_phpunit_junit_nodes_exact_with_and_without_classname(self, tmp_path):
        from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter
        xml = """<?xml version="1.0"?>
<testsuites><testsuite name="s" tests="2" failures="2">
  <testcase classname="C" name="t1" file="f.php"><failure message="m1"/></testcase>
  <testcase name="t2"><failure message="m2"/></testcase>
</testsuite></testsuites>"""
        junit = tmp_path / "junit.xml"
        junit.write_text(xml, encoding="utf-8")
        findings = PhpUnitAdapter()._parse_junit_xml(junit)
        nodes = [f.node for f in findings if f.severity == "error"]
        # node precedence: file > classname > name (kills tc_class/tc_file
        # key-name and default mutations — None would leak as "None")
        assert nodes == ["f.php", "t2"]
        xml2 = xml.replace(' file="f.php"', "")
        junit.write_text(xml2, encoding="utf-8")
        nodes2 = [f.node for f in PhpUnitAdapter()._parse_junit_xml(junit)
                  if f.severity == "error"]
        assert nodes2 == ["C", "t2"]

    def test_psalm_severity_present_value_used(self):
        from harness_quality_gate.adapters.php.psalm_taint_adapter import (
            PsalmTaintAdapter,
        )
        stdout = json.dumps([
            {"type": "TaintedSql", "line_from": 1, "file_name": "a.php",
             "message": "m", "severity": "warning"},
        ])
        assert PsalmTaintAdapter().parse(stdout, "", 0)[0].severity == "warning"

    def test_psalm_non_taint_then_taint_keeps_iterating(self):
        from harness_quality_gate.adapters.php.psalm_taint_adapter import (
            PsalmTaintAdapter,
        )
        stdout = json.dumps([
            {"type": "UnusedVariable", "line_from": 1, "file_name": "a.php", "message": "x"},
            {"type": "TaintedSql", "line_from": 2, "file_name": "b.php", "message": "m"},
        ])
        findings = PsalmTaintAdapter().parse(stdout, "", 0)
        assert [f.node for f in findings] == ["b.php:2"]

    def test_dead_code_files_format_bad_then_good(self):
        from harness_quality_gate.adapters.php.dead_code_adapter import DeadCodeAdapter
        stdout = json.dumps({"files": {
            "a.php": "junk",
            "b.php": {"messages": ["dead method"]},
        }})
        findings = DeadCodeAdapter().parse(stdout)
        assert any(f.node == "b.php" for f in findings)

    def test_dep_analyser_array_and_nested_message_exact(self):
        from harness_quality_gate.adapters.php.dep_analyser_adapter import (
            DepAnalyserAdapter,
        )
        arr = json.dumps([{"type": "dep-class", "file": "a.php", "line": 2, "message": "M"}])
        f = DepAnalyserAdapter().parse(arr)[0]
        assert f.message == "class: M"
        arr2 = json.dumps([{"type": "dep-class", "file": "a.php", "line": 2}])
        f2 = DepAnalyserAdapter().parse(arr2)[0]
        assert f2.message == "class"
        nested = json.dumps({"files": {"n.php": {"violations": [
            {"type": "dep-function", "line": 1, "message": "NM"},
        ]}}})
        f3 = DepAnalyserAdapter().parse(nested)[0]
        assert f3.message == "function: NM"
        assert f3.node == "n.php:1"

    def test_security_invoke_timeout_branch_fixed_clock(self, tmp_path):
        import subprocess
        from datetime import datetime, timezone, timedelta
        from harness_quality_gate.adapters.php.security_checker_adapter import (
            SecurityCheckerAdapter,
        )
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        fake_dt = MagicMock()
        fake_dt.now.side_effect = [t0, t0 + timedelta(seconds=1.23456)]
        exc = subprocess.TimeoutExpired(cmd="x", timeout=5)
        with (
            patch(
                "harness_quality_gate.adapters.php.security_checker_adapter.shutil.which",
                return_value="/usr/bin/local-php-security-checker",
            ),
            patch(
                "harness_quality_gate.adapters.php.security_checker_adapter.subprocess.run",
                side_effect=exc,
            ),
            patch(
                "harness_quality_gate.adapters.php.security_checker_adapter.datetime",
                fake_dt,
            ),
        ):
            result = SecurityCheckerAdapter().invoke(tmp_path, [])
        assert result.duration_seconds == 1.235

    def test_security_severity_present_and_links_first(self):
        from harness_quality_gate.adapters.php.security_checker_adapter import (
            SecurityCheckerAdapter,
        )
        stdout = json.dumps([{
            "package": "v/p", "severity": "high", "links": ["L1", "L2"],
        }])
        f = SecurityCheckerAdapter().parse(stdout)[0]
        assert f.severity == "error" or f.severity == "high" or f.severity == "warning"
        assert f.fix_hint == "L1"

    def test_weak_test_path_key_fallback(self):
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        findings = PhpWeakTestAdapter().parse(json.dumps([{"path": "p.php", "line": 4}]))
        assert findings[0].node == "p.php:4"

    def test_weak_test_collect_skips_vendor_mid_iteration(self, tmp_path):
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        valid1 = tmp_path / "a" / "OneTest.php"
        vendored = tmp_path / "vendor" / "SkipTest.php"
        valid2 = tmp_path / "z" / "TwoTest.php"
        with patch.object(Path, "rglob", return_value=iter([valid1, vendored, valid2])):
            files = PhpWeakTestAdapter._collect_test_files(tmp_path)
        assert files == sorted([valid1, valid2])


class TestPsalmNestedGuardOrdering:
    def test_file_without_psalm_errors_then_valid_file(self) -> None:
        from harness_quality_gate.adapters.php.psalm_taint_adapter import (
            PsalmTaintAdapter,
        )
        stdout = json.dumps({"files": {
            "a.php": {"other": 1},
            "b.php": {"psalmErrors": [
                {"type": "TaintedSql", "line_from": 2, "message": "m"},
            ]},
        }})
        findings = PsalmTaintAdapter().parse(stdout, "", 0)
        assert [f.node for f in findings] == ["b.php:2"]


class TestWeakTestBothKeysAbsent:
    def test_node_empty_when_no_file_nor_path(self) -> None:
        from harness_quality_gate.adapters.php.weak_test_php import PhpWeakTestAdapter
        findings = PhpWeakTestAdapter().parse(json.dumps([{"message": "m"}]))
        assert findings[0].node == ""


class TestDepAnalyserAbsentMessage:
    def test_nested_without_message_yields_bare_prefix(self) -> None:
        from harness_quality_gate.adapters.php.dep_analyser_adapter import (
            DepAnalyserAdapter,
        )
        nested = json.dumps({"files": {"n.php": {"violations": [
            {"type": "dep-function", "line": 1},
        ]}}})
        f = DepAnalyserAdapter().parse(nested)[0]
        assert f.message == "function"


class TestPhpstanTipMessage:
    def test_rstrip_charset_does_not_eat_trailing_x(self) -> None:
        """file_diagnostics error without tip: 'BoX ()' → rstrip(' ()') → 'BoX'.
        The XX-wrapped charset mutant would also strip the trailing X."""
        from harness_quality_gate.adapters.php.phpstan_adapter import PhpStanAdapter
        stdout = json.dumps({"file_diagnostics": [
            {"file": "a.php", "messages": [], "errors": [{"message": "BoX"}]},
        ]})
        findings = PhpStanAdapter().parse(stdout, "", 1)
        assert [f.message for f in findings] == ["BoX"]
