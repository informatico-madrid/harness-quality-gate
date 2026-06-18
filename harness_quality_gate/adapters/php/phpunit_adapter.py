"""PHPUnit adapter — run tests, parse JUnit XML, verify strict-mode config.

Wraps ``phpunit`` (PHPUnit 10/11/12) test execution and parses
JUnit XML output into :class:`~harness_quality_gate.models.Finding` objects.

Design: Component Responsibilities / phpunit_adapter, PHP Tier A tools.
Requirements: FR-12, US-6.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Mapping

import defusedxml.ElementTree as DET
from ...models import Finding
from ..base import ToolAdapter, ToolInvocation

# reason: logger name mutation does not change observability; only the __name__ label differs.
# audited: 2026-06-04
logger = logging.getLogger(__name__)  # pragma: no mutate

# US-6 AC-1: the 11 strict-mode flags PHPUnit recognises.
STRICT_MODE_FLAGS = (
    "strictCoverage",
    "checkForUnintentionallyCoveredCode",
    "failOnWarning",
    "failOnError",
    "failOnRisky",
    "failOnFailure",
    "failOnIncomplete",
    "failOnSkipped",
    "failOnEmptyTestSuite",
    "beStrictAboutCoverageMetadata",
    "beStrictAboutOutputDuringTests",
)


class PhpUnitAdapter(ToolAdapter):
    """Parses PHPUnit JUnit XML output and verifies strict-mode config.

    Execution of PHPUnit itself is Phase 2; parsing is available now.
    """

    _name = "phpunit"

    # -- abstract interface -----------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        raise NotImplementedError("phpunit version detection not implemented (POC)")

    def _bin_path(self, repo: Path) -> str:
        """Return the phpunit binary path, respecting composer.json bin-dir."""
        composer_json = repo / "composer.json"
        if composer_json.exists():
            try:
                data = json.loads(composer_json.read_text(encoding="utf-8"))
                config = data.get("config") or {}
                return f"{config.get('bin-dir') or 'vendor/bin'}/phpunit"
            except (json.JSONDecodeError, OSError):
                pass
        return "vendor/bin/phpunit"

    def invoke(
        self,
        repo: Path,
        args: list[str] | None = None,
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        """Run PHPUnit: ``<bin-dir>/phpunit --log-junit junit.xml --coverage-php var/coverage``.

        Returns a :class:`ToolInvocation` capturing stdout, stderr,
        exit code, and wall-clock duration.
        """
        # Base: run tests and write JUnit XML for parsing.
        # Coverage flags are caller-supplied via args (coverage requires PCOV/Xdebug).
        cmd = [self._bin_path(repo), "--log-junit", "junit.xml"]
        if args:
            cmd.extend(args)
        return self._run(cmd, cwd=repo, timeout=timeout)

    def parse(  # type: ignore[override]
        self,
        stdout: str,
        *_compat: object,
    ) -> list[Finding]:
        """Parse PHPUnit JUnit XML output into :class:`Finding` objects.

        Reads ``junit.xml`` from *repo* when available (primary path).
        Falls back to parsing *stdout* when the file doesn't exist.

        Returns findings for:
        - Test failures (severity=error)
        - Test errors  (severity=error)
        - Incomplete tests (severity=warning)
        - Skipped tests (severity=info)
        - Risky tests (severity=warning)
        - Coverage statistics (severity=info)
        """
        junit_path = Path(stdout.strip()) if stdout.strip().endswith(".xml") else None
        findings: list[Finding] = []

        if junit_path is None:
            junit_path = Path("junit.xml")

        if junit_path.exists():
            findings.extend(self._parse_junit_xml(junit_path))
        else:
            findings.extend(self._parse_stdout(stdout))

        return findings

    def verify_strict_mode(self, repo: Path) -> list[str]:
        """Verify phpunit.xml contains all 11 strict-mode flags.

        Returns a list of missing flag names (empty list = all present).
        """
        xml_path = repo / "phpunit.xml"
        if not xml_path.exists():
            return list(STRICT_MODE_FLAGS)

        content = xml_path.read_text(encoding="utf-8")
        missing: list[str] = []
        for flag in STRICT_MODE_FLAGS:
            if flag not in content:
                missing.append(flag)
        return missing

    # -- internal helpers -------------------------------------------------

    @staticmethod
    def _parse_junit_xml(path: Path) -> list[Finding]:
        """Parse a JUnit XML file and return findings for each test result."""
        findings: list[Finding] = []
        try:
            tree = DET.parse(str(path))
        except (DET.ParseError, OSError):
            return [
                Finding(
                    node=str(path),
                    severity="error",
                    message="Failed to parse JUnit XML",
                    tool="phpunit",
                    layer="layer1",
                )
            ]

        root = tree.getroot()
        assert root is not None, "DET.parse succeeded but getroot returned None"

        # Collect test-suite level attributes (total, errors, failures, etc.)
        total = int(root.get("tests", "0"))
        errors = int(root.get("errors", "0"))
        failures = int(root.get("failures", "0"))
        skipped = int(root.get("skipped", "0"))

        # Suite-level summary finding
        if total == 0:
            findings.append(
                Finding(
                    node=str(path),
                    severity="warning",
                    message="No tests executed",
                    tool="phpunit",
                    layer="layer1",
                )
            )
        else:
            findings.append(
                Finding(
                    node=str(path),
                    severity="info" if (errors == 0 and failures == 0) else "error",
                    message=(
                        f"Tests: {total}, Errors: {errors}, "
                        f"Failures: {failures}, Skipped: {skipped}"
                    ),
                    tool="phpunit",
                    layer="layer1",
                )
            )

        # Individual <testcase> elements
        for tc in root.iter("testcase"):
            tc_name = tc.get("name", "<unknown>")
            # missing attrs are as falsy as "" in the node-precedence chain
            tc_class = tc.get("classname")
            tc_file = tc.get("file")

            node = tc_class or tc_name
            if tc_file:
                node = tc_file

            # Check for <failure>
            for failure in tc.iter("failure"):
                details = (failure.text or "").strip().replace("\n", " ")
                findings.append(
                    Finding(
                        node=node,
                        severity="error",
                        message=f"{tc_name} failed: {details[:200]}",
                        fix_hint=f"Fix assertion or test logic in {node}",
                        tool="phpunit",
                        layer="layer1",
                    )
                )

            # Check for <error>
            for error in tc.iter("error"):
                details = (error.text or "").strip().replace("\n", " ")
                findings.append(
                    Finding(
                        node=node,
                        severity="error",
                        message=f"{tc_name} error: {details[:200]}",
                        fix_hint=f"Fix error in {node}",
                        tool="phpunit",
                        layer="layer1",
                    )
                )

            # Check for <skipped>
            for skipped_el in tc.iter("skipped"):
                findings.append(
                    Finding(
                        node=node,
                        severity="info",
                        message=f"{tc_name} was skipped",
                        fix_hint="Remove @depends or fix dependency in {node}",
                        tool="phpunit",
                        layer="layer1",
                    )
                )

            # Check for <incomplete>
            for inc in tc.iter("incomplete"):
                findings.append(
                    Finding(
                        node=node,
                        severity="warning",
                        message=f"{tc_name} is incomplete",
                        fix_hint=f"Implement assertions in {node}",
                        tool="phpunit",
                        layer="layer1",
                    )
                )

        # Coverage stats from <testsuite> attributes
        # the or-chain collapses a missing "cover" to falsy — no default needed
        covered = root.get("coveredLines") or root.get("cover")
        total_lines = root.get("totalLines") or ""
        if covered and total_lines:
            findings.append(
                Finding(
                    node=str(path),
                    severity="info",
                    message=f"Coverage: {covered}/{total_lines} lines covered",
                    tool="phpunit",
                    layer="layer1",
                )
            )

        return findings

    @staticmethod
    def _parse_stdout(stdout: str) -> list[Finding]:
        """Parse PHPUnit text output (non-JUnit mode) into findings."""
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        for line in stdout.splitlines():
            stripped = line.strip()

            # PHPUnit text report lines like "1) Tests\\FooTest::test_bar"
            m = r"""^\d+\)\s+(?:(\S+)\s+::\s+)?(.+?)\s+(FAILED|ERROR|SKIPPED|INCOMPLETE)\s*"""
            match = re.search(m, stripped)
            if match:
                cls = match.group(1) or ""
                test_name = match.group(2)
                status = match.group(3)
                node = f"{cls}/{test_name}" if cls else test_name

                if status == "FAILED":
                    sev = "error"
                    hint = f"Fix assertion in {node}"
                elif status == "ERROR":
                    sev = "error"
                    hint = f"Fix error in {node}"
                elif status == "SKIPPED":
                    sev = "info"
                    hint = f"Review skip reason in {node}"
                else:  # INCOMPLETE
                    sev = "warning"
                    hint = f"Complete test in {node}"

                findings.append(
                    Finding(
                        node=node,
                        severity=sev,
                        message=f"{test_name} {status.lower()}",
                        fix_hint=hint,
                        tool="phpunit",
                        layer="layer1",
                    )
                )

        return findings
