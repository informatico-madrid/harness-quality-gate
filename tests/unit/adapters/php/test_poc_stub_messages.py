"""Exact-message pins for every POC version()/invoke() stub.

The NotImplementedError messages are part of the doctor/diagnostic surface;
pinning them with full-string matches kills the None/case/XX-wrap string
mutations on each raise site (guide §4.3).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from harness_quality_gate.adapters.php.dead_code_adapter import DeadCodeAdapter
from harness_quality_gate.adapters.php.dep_analyser_adapter import DepAnalyserAdapter
from harness_quality_gate.adapters.php.deptrac_adapter import DeptracAdapter
from harness_quality_gate.adapters.php.pcov_adapter import PcovAdapter
from harness_quality_gate.adapters.php.phpunit_adapter import PhpUnitAdapter
from harness_quality_gate.adapters.php.security_checker_adapter import SecurityCheckerAdapter
from harness_quality_gate.adapters.php.visitor_runner_adapter import VisitorRunnerAdapter


@pytest.mark.parametrize("adapter_cls,message", [
    (DeadCodeAdapter, "dead-code-detector version detection not implemented (POC)"),
    (PcovAdapter, "pcov version detection not implemented (POC)"),
    (SecurityCheckerAdapter, "security-checker version detection not implemented (POC)"),
    (DepAnalyserAdapter, "composer-dependency-analyser version detection not implemented (POC)"),
    (PhpUnitAdapter, "phpunit version detection not implemented (POC)"),
    (DeptracAdapter, "deptrac version detection not implemented (POC)"),
    (VisitorRunnerAdapter, "VisitorRunnerAdapter.version() is not implemented for PoC visitors"),
])
def test_version_stub_raises_exact_message(tmp_path: Path, adapter_cls, message) -> None:
    with pytest.raises(NotImplementedError, match=f"^{re.escape(message)}$"):
        adapter_cls().version(tmp_path)


def test_pcov_invoke_stub_raises_exact_message(tmp_path: Path) -> None:
    with pytest.raises(
        NotImplementedError,
        match=r"^pcov invocation not implemented \(POC\)$",
    ):
        PcovAdapter().invoke(tmp_path, [])
