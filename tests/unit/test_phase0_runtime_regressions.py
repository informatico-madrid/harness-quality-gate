"""Regression tests for the Phase-0 runtime-contract fixes (plan unificado 2026-06-11).

Covers the four dogfooding bugs that crashed ``all`` at runtime:

- PyrightAdapter.parse() signature mismatch — accepted 1 arg, the call site
  passes 3 → TypeError → INTERNAL_ERROR (exit 5).
- P7: ``tool_specific`` containing dataclasses (MutationStats) reached
  ``json.dumps``/``validate`` unconverted → checkpoint silently lost.
- P8: finding dicts kept ``None`` optional fields (rule_id, fix_hint) →
  jsonschema "None is not of type 'string'" → checkpoint silently lost.
- P10: missing tool binaries raise ``FileNotFoundError`` (OSError), which the
  PHP adapters only caught as RuntimeError → crash instead of skip-with-warning.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_quality_gate.adapters.base import ToolInvocation
from harness_quality_gate.bootstrap import ToolNotAvailable
from harness_quality_gate.adapters.php.antipattern_tier_a_php import (
    PhpAntipatternTierAAdapter,
)
from harness_quality_gate.adapters.php.pcov_adapter import PcovAdapter
from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
from harness_quality_gate.adapters.python.pyright_adapter import PyrightAdapter
from harness_quality_gate.adapters.python.python_adapter import PythonAdapter
from harness_quality_gate.checkpoint import build as build_checkpoint
from harness_quality_gate.checkpoint import validate as validate_checkpoint
from harness_quality_gate.cli import _cmd_all
from harness_quality_gate.exit_codes import PASS
from harness_quality_gate.models import LayerResult, MutationStats


def _make_args(**kwargs):
    import argparse
    defaults = {"repo": ".", "json": False, "quiet": False}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# PyrightAdapter.parse signature (crash: TypeError at python_adapter.py call)
# ---------------------------------------------------------------------------

class TestPyrightParseSignature:
    _PYRIGHT_JSON = json.dumps({
        "generalDiagnostics": [
            {
                "file": "src/calc.py",
                "severity": "error",
                "message": "Type mismatch",
                "rule": "reportGeneralTypeIssues",
                "range": {"start": {"line": 7, "character": 4}},
            }
        ]
    })

    def test_parse_accepts_three_positional_args(self):
        """The exact call shape used by PythonAdapter._run_pyright must not
        raise TypeError: parse(stdout, stderr, exitcode)."""
        assert PyrightAdapter().parse("", "some stderr", 1) == []

    def test_parse_three_args_returns_exact_finding(self):
        findings = PyrightAdapter().parse(self._PYRIGHT_JSON, "stderr-ignored", 1)
        assert len(findings) == 1
        f = findings[0]
        assert f.node == "src/calc.py"
        assert f.severity == "error"
        assert f.message == "src/calc.py:7:4 [reportGeneralTypeIssues]: Type mismatch"
        assert f.tool == "pyright"
        assert f.layer == "L3A"
        assert f.language == "python"
        assert f.rule_id == "reportGeneralTypeIssues"

    def test_run_pyright_call_site_no_longer_crashes(self, tmp_path):
        """Integration through the call site that crashed: _run_pyright invokes
        parse(stdout, stderr, exitcode) against the real PyrightAdapter."""
        adapter = PythonAdapter()
        invocation = ToolInvocation(stdout=self._PYRIGHT_JSON, stderr="", exitcode=1)
        with (
            patch("harness_quality_gate.adapters.python.python_adapter.resolve_tool",
                  return_value=Path("/usr/bin/pyright")),
            patch.object(adapter.pyright, "invoke", return_value=invocation),
        ):
            findings = adapter._run_pyright(tmp_path, {})
        assert len(findings) == 1
        assert findings[0].rule_id == "reportGeneralTypeIssues"


# ---------------------------------------------------------------------------
# P7 — tool_specific with dataclasses must serialise through _asdict
# ---------------------------------------------------------------------------

class TestToolSpecificDataclassSerialisation:
    _STATS = MutationStats(
        total=10, killed=9, survived=1, timed_out=0,
        escaped=0, untested=0, msi=90.0, covered_msi=90.0,
    )

    def _adapter_with_stats(self) -> MagicMock:
        adapter = MagicMock()
        for method in ("run_l3a", "run_l1", "run_l2", "run_l3b", "run_l4"):
            getattr(adapter, method).return_value = LayerResult(
                layer=method.replace("run_", "").upper(), language="python",
                passed=True, findings=[], duration_sec=0.0,
                tool_specific={"mutation_stats": self._STATS},
            )
        return adapter

    def test_cmd_all_converts_mutation_stats_to_plain_dict(self, tmp_path):
        adapter = self._adapter_with_stats()
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint") as mock_write,
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path), quiet=True))
        assert code == PASS
        checkpoint_dict = mock_write.call_args.args[1]
        stats = checkpoint_dict["layers"][0]["tool_specific"]["mutation_stats"]
        assert stats == {
            "total": 10, "killed": 9, "survived": 1, "timed_out": 0,
            "escaped": 0, "untested": 0, "msi": 90.0, "covered_msi": 90.0,
        }
        # The original crash: json.dumps over the checkpoint raised TypeError.
        json.dumps(checkpoint_dict)

    def test_cmd_all_stdout_json_round_trips_with_stats(self, tmp_path, capsys):
        adapter = self._adapter_with_stats()
        with (
            patch("harness_quality_gate.cli.PythonAdapter", return_value=adapter),
            patch("harness_quality_gate.cli.write_checkpoint"),
        ):
            code = _cmd_all(_make_args(repo=str(tmp_path)))
        assert code == PASS
        out = json.loads(capsys.readouterr().out)
        assert out["layers"][0]["tool_specific"]["mutation_stats"]["survived"] == 1


# ---------------------------------------------------------------------------
# P8 — None-valued optional fields in finding dicts must be stripped
# ---------------------------------------------------------------------------

class TestCheckpointStripsNoneFromFindingDicts:
    def _layer_with_none_fields(self) -> dict:
        return {
            "layer": "L3A",
            "language": "python",
            "passed": False,
            "findings": [{
                "node": "src/calc.py",
                "severity": "error",
                "message": "boom",
                "fix_hint": None,
                "cve": None,
                "cwe": "",
                "tool": "ruff",
                "layer": "L3A",
                "language": "python",
                "rule_id": None,
            }],
            "duration_sec": 0.1,
        }

    def test_build_strips_none_values_and_keeps_the_rest(self):
        data = build_checkpoint(
            layer_results=[self._layer_with_none_fields()],
            runtime={"python_version": "3.12", "concurrency": "sequential", "ci": False},
            detection={"repo_path": "/r", "language": "python"},
        )
        finding = data["layers"][0]["findings"][0]
        assert "rule_id" not in finding
        assert "fix_hint" not in finding
        assert "cve" not in finding
        assert finding == {
            "node": "src/calc.py", "severity": "error", "message": "boom",
            "cwe": "", "tool": "ruff", "layer": "L3A", "language": "python",
        }

    def test_built_checkpoint_with_none_fields_passes_schema_validation(self):
        """The original crash: jsonschema ValidationError 'None is not of type
        string' on rule_id — the checkpoint was silently never written."""
        data = build_checkpoint(
            layer_results=[self._layer_with_none_fields()],
            runtime={"python_version": "3.12", "concurrency": "sequential", "ci": False},
            detection={"repo_path": "/r", "language": "python"},
        )
        validate_checkpoint(data)  # must not raise
        assert data["version"] == "v2"
        assert isinstance(data["layers"], list)
        assert len(data["layers"]) == 1
        finding = data["layers"][0]["findings"][0]
        assert "rule_id" not in finding, "None fields must be stripped before schema validation"


# ---------------------------------------------------------------------------
# P10 — FileNotFoundError (OSError) from missing binaries degrades to skip
# ---------------------------------------------------------------------------

_FNF = FileNotFoundError(2, "No such file or directory", "vendor/bin/phpunit")


class TestPhpAdapterOSErrorDegradation:
    def test_run_phpunit_tests_missing_binary_returns_empty(self, tmp_path):
        adapter = PhpAdapter()
        with patch.object(adapter._phpunit, "invoke", side_effect=_FNF):
            assert adapter._run_phpunit_tests(tmp_path, {}) == []

    def test_run_pest_tests_missing_binary_returns_empty(self, tmp_path):
        adapter = PhpAdapter()
        with patch.object(adapter._pest, "invoke", side_effect=_FNF):
            assert adapter._run_pest_tests(tmp_path, {}) == []

    def test_run_l4_all_binaries_missing_completes_without_crash(self, tmp_path):
        adapter = PhpAdapter()
        tools = (
            "_psalm_taint", "_composer_audit", "_security_checker",
            "_dead_code", "_dep_analyser", "_deptrac",
        )
        patches = [
            patch.object(getattr(adapter, name), "invoke", side_effect=_FNF)
            for name in tools if hasattr(adapter, name)
        ]
        assert patches, "no L4 tool attributes found on PhpAdapter"
        for p in patches:
            p.start()
        try:
            result = adapter.run_l4(tmp_path, {})
        finally:
            for p in patches:
                p.stop()
        assert result.layer == "L4"
        assert result.language == "php"
        assert result.passed is True
        assert result.findings == []

    def test_tool_versions_missing_binary_marks_missing(self):
        adapter = PhpAdapter()
        with patch.object(adapter._phpstan, "version", side_effect=_FNF):
            versions = adapter.tool_versions()
        assert versions[adapter._phpstan.name] == "MISSING"

    def test_check_tools_missing_binary_raises_listing_tool(self):
        adapter = PhpAdapter()
        with (
            patch.object(adapter._phpstan, "version", side_effect=_FNF),
            patch.object(adapter._phpmd, "version", return_value="2.15"),
            patch.object(adapter._cs_fixer, "version", return_value="3.0"),
        ):
            with pytest.raises(RuntimeError) as excinfo:
                adapter.check_tools()
        assert adapter._phpstan.name in str(excinfo.value)


class TestAntipatternTierAOSErrorDegradation:
    def test_version_missing_phpmd_reports_missing(self, tmp_path):
        adapter = PhpAntipatternTierAAdapter()
        with (
            patch.object(adapter._phpmd, "version", side_effect=_FNF),
            patch.object(adapter._visitors, "version", return_value="poC"),
        ):
            assert adapter.version(tmp_path) == "phpmd:MISSING visitors:poC"

    def test_invoke_missing_phpmd_still_returns_invocation(self, tmp_path):
        adapter = PhpAntipatternTierAAdapter()
        with (
            patch.object(adapter._phpmd, "invoke", side_effect=_FNF),
            patch.object(adapter._visitors, "invoke", side_effect=_FNF),
        ):
            invocation = adapter.invoke(tmp_path, [])
        assert isinstance(invocation, ToolInvocation)


class TestPcovOSErrorDegradation:
    def test_probe_layer_result_missing_php_fails_layer_not_crash(self, tmp_path):
        adapter = PcovAdapter()
        with patch.object(adapter, "probe", side_effect=_FNF):
            result = adapter.probe_layer_result(tmp_path)
        assert result.layer == "L1"
        assert result.language == "php"
        assert result.passed is False
