"""Pytest adapter.

Wraps ``pytest --junitxml`` and parses JUnit XML output into :class:`Finding[]`.

Design: Component Responsibilities / pytest_adapter.
Requirements: FR-29, US-3.
"""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter, ToolInvocation


class PytestAdapter(ToolAdapter):
    """Wraps ``pytest`` and parses JUnit XML output into findings."""

    _name = "pytest"

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        result = self._run(
            [shutil.which("python3") or "python3", "-m", "pytest", "--version"],
            cwd=repo,
            env=env,
        )
        return result.stdout.strip() or "unknown"

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        python = shutil.which("python3") or "python3"
        cmd = [python, "-m", "pytest", "--junitxml", "/dev/stdout", "-o", "junit_suite_name=pytest"]
        if args:
            cmd.extend(args)
        return self._run(cmd, cwd=repo, env=env, timeout=timeout)

    def parse(
        self,
        stdout: str,
        stderr: str = "",
        exitcode: int = 0,
    ) -> list[Finding]:
        """Parse JUnit XML output into :class:`Finding` objects."""
        findings: list[Finding] = []
        # Handle test execution warnings from stderr
        if stderr and "CRITICAL" in stderr:
            findings.append(
                Finding(
                    node="pytest",
                    severity="warning",
                    message=stderr.strip(),
                    fix_hint="Check pytest configuration or environment.",
                    tool="pytest",
                    layer="L1",
                    language="python",
                    rule_id="stderr",
                )
            )
        if not stdout.strip():
            return findings

        try:
            root = ET.fromstring(stdout)
        except ET.ParseError:
            return findings

        failures = []
        errors = []
        skipped = []

        for testcase in root.findall(".//testcase"):
            classname = testcase.get("classname", "")
            name = testcase.get("name", "")
            full_name = f"{classname}.{name}" if classname else name

            failure = testcase.find("failure")
            error = testcase.find("error")
            skip = testcase.find("skipped")

            if failure is not None:
                msg = failure.get("message", failure.text or "")
                msg = msg.strip() if msg else f"Test failed: {full_name}"
                failures.append(
                    Finding(
                        node=full_name,
                        severity="error",
                        message=msg,
                        tool="pytest",
                        layer="L1",
                        language="python",
                        rule_id="failure",
                    )
                )
            elif error is not None:
                msg = error.get("message", error.text or "")
                msg = msg.strip() if msg else f"Test error: {full_name}"
                errors.append(
                    Finding(
                        node=full_name,
                        severity="error",
                        message=msg,
                        tool="pytest",
                        layer="L1",
                        language="python",
                        rule_id="error",
                    )
                )
            elif skip is not None:
                msg = skip.get("message", skip.text or "")
                msg = msg.strip() if msg else f"Test skipped: {full_name}"
                skipped.append(
                    Finding(
                        node=full_name,
                        severity="info",
                        message=msg,
                        tool="pytest",
                        layer="L1",
                        language="python",
                        rule_id="skipped",
                    )
                )

        # Add a summary finding when tests failed
        total_failures = len(failures)
        total_errors = len(errors)
        total_skipped = len(skipped)
        if total_failures or total_errors:
            parts = []
            if total_failures:
                parts.append(f"{total_failures} failure(s)")
            if total_errors:
                parts.append(f"{total_errors} error(s)")
            if total_skipped:
                parts.append(f"{total_skipped} skipped")
            findings.insert(
                0,
                Finding(
                    node="pytest",
                    severity="error",
                    message=" ".join(parts),
                    fix_hint="Review failing test assertions and stack traces.",
                    tool="pytest",
                    layer="L1",
                    language="python",
                    rule_id="summary",
                ),
            )

        findings.extend(failures)
        findings.extend(errors)
        findings.extend(skipped)

        # Add exitcode finding if abnormal
        if exitcode > 0:
            findings.insert(
                0,
                Finding(
                    node="pytest",
                    severity="error",
                    message=f"Test execution failed with exit code {exitcode}",
                    fix_hint="Review the test output and check for environment issues.",
                    tool="pytest",
                    layer="L1",
                    language="python",
                    rule_id="exitcode",
                ),
            )

        return findings
