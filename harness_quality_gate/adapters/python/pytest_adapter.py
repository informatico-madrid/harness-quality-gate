"""Pytest adapter.

Wraps ``pytest --junitxml`` and parses JUnit XML output into :class:`Finding[]`.

Design: Component Responsibilities / pytest_adapter.
Requirements: FR-29, US-3.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Mapping

import defusedxml.ElementTree as DET
from ...models import Finding
from ..base import ToolAdapter, ToolInvocation


# reason: Tipo C — este default de stderr solo alimenta el check `"CRITICAL" in stderr`
# dentro de parse(); cualquier relleno sin esa palabra es gemelo del vacío. El pragma
# vive aquí porque en la línea de firma (continuación) mutmut lo ignora. # audited: 2026-06-11
_NO_STDERR = ""  # pragma: no mutate


class PytestAdapter(ToolAdapter):
    """Wraps ``pytest`` and parses JUnit XML output into findings."""

    _name = "pytest"

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        result = self._run(
            [sys.executable, "-m", "pytest", "--version"],
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
        paths: list[str] | None = None,
    ) -> ToolInvocation:
        python = sys.executable
        # The JUnit report goes to a temp file: writing it to /dev/stdout
        # interleaves it with the terminal report and the XML becomes
        # unparseable, silently hiding test failures (simulation bug H8).
        fd, junit_name = tempfile.mkstemp(prefix="hqg-junit-", suffix=".xml")
        os.close(fd)
        junit_path = Path(junit_name)
        cmd = [
            python,
            "-m",
            "pytest",
            "--junitxml",
            str(junit_path),
            "-o",
            "junit_suite_name=pytest",
        ]
        if args:
            cmd.extend(args)
        # When explicit paths are provided (partial run), use them as
        # test collection targets instead of auto-discovering tests/.
        if paths:
            cmd.extend(paths)
        elif (repo / "tests").is_dir():
            # Collect tests/ only when present — default collection would also
            # pick up the copies under mutants/ (H10).
            cmd.append("tests")
        try:
            result = self._run(cmd, cwd=repo, env=env, timeout=timeout)
            # bytes.decode() defaults to strict UTF-8 (no locale dependence,
            # no mutable encoding literal)
            xml_report = (
                junit_path.read_bytes().decode()
                if junit_path.exists() and junit_path.stat().st_size
                else ""
            )
            return ToolInvocation(
                stdout=xml_report,
                stderr=result.stderr,
                exitcode=result.exitcode,
                duration_seconds=result.duration_seconds,
            )
        finally:
            junit_path.unlink(missing_ok=True)

    def parse(
        self,
        stdout: str,
        stderr: str = _NO_STDERR,
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
            if exitcode != 0:
                findings.append(self._unparseable_finding(exitcode))
            return findings

        try:
            root = DET.fromstring(stdout)
        except DET.ParseError:
            if exitcode != 0:
                findings.append(self._unparseable_finding(exitcode))
            return findings

        failures = []
        errors = []
        skipped = []

        for testcase in root.findall(".//testcase"):
            classname = testcase.get("classname") or ""
            name = testcase.get("name") or ""
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
            # findings is empty at this point — append puts the summary first
            findings.append(
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
            if exitcode == 5 and not findings:
                # findings is empty here, so append == insert(0)
                findings.append(
                    Finding(
                        node="pytest",
                        severity="error",
                        message="pytest collected no tests (exit code 5)",
                        fix_hint="Add tests under tests/ — L1 validates test "
                        "execution and cannot pass without tests.",
                        tool="pytest",
                        layer="L1",
                        language="python",
                        rule_id="no-tests",
                    ),
                )
            else:
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

    @staticmethod
    def _unparseable_finding(exitcode: int) -> Finding:
        """Error finding for runs whose JUnit XML is missing or invalid.

        Without this, a crashed/uncollectable pytest run silently produced
        zero findings and L1 passed with broken tests (simulation bug H8).
        """
        return Finding(
            node="pytest",
            severity="error",
            message=(
                f"pytest exited with code {exitcode} but produced no "
                "parseable JUnit XML report"
            ),
            fix_hint="Run pytest manually in the repo to inspect the failure "
            "(collection error, crash or misconfiguration).",
            tool="pytest",
            layer="L1",
            language="python",
            rule_id="parse-error",
        )
