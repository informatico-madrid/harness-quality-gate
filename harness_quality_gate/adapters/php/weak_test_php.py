"""PHP weak-test detection adapter (L3B).

Implements rules A1, A2-PHP, A3, A4, A5, A6, A7, A8 via nikic/PHP-Parser
visitor scripts.  Driven through ``VisitorRunnerAdapter`` which handles
subprocess invocation and JSON merging.

Design: Component Responsibilities / weak_test_php, visitor_runner_adapter
Requirements: FR-35, TD-13, US-17
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Mapping

from ...models import Finding, LayerResult
from ..base import ToolAdapter, ToolInvocation
from .visitor_runner_adapter import VisitorRunnerAdapter

logger = logging.getLogger(__name__)

# Weak-test visitor names (matches weak_test_a{1..8}.php in visitors/)
_WEAK_TEST_VISITORS = [
    "weak_test_a1",   # A1 — zero-assertion
    "weak_test_a2",   # A2-PHP — mocks-only (TD-13)
    "weak_test_a3",   # A3 — SUT-mocked
    "weak_test_a4",   # A4 — overly-broad expectException
    "weak_test_a5",   # A5 — markTestSkipped/Incomplete
    "weak_test_a6",   # A6 — @codeCoverageIgnore spam
    "weak_test_a7",   # A7 — only constructor + instanceof
    "weak_test_a8",   # A8 — assertion on tautology
]

# Map visitor names to rule_id for Finding layer tagging
_VISITOR_RULE_MAP = {
    "weak_test_a1": "A1",
    "weak_test_a2": "A2-PHP",
    "weak_test_a3": "A3",
    "weak_test_a4": "A4",
    "weak_test_a5": "A5",
    "weak_test_a6": "A6",
    "weak_test_a7": "A7",
    "weak_test_a8": "A8",
}


class PhpWeakTestAdapter(ToolAdapter):
    """Runs weak-test visitor scripts (A1–A8) against PHP test files.

    Delegates visitor invocation to ``VisitorRunnerAdapter`` and post-processes
    the merged findings to tag each finding with its visitor/layer context.

    Uses a scoped subset of visitors (weak_test_a*.php) rather than the
    full visitor_runner discovery to avoid running antipattern visitors.
    """

    _name = "weak-test-php"

    def __init__(self) -> None:
        self._runner = VisitorRunnerAdapter()

    # -- abstract interface -----------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    # -- version ----------------------------------------------------------

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        """Return visitor count as version string (PoC)."""
        return f"{len(_WEAK_TEST_VISITORS)} visitors"

    # -- invoke -----------------------------------------------------------

    def invoke(
        self,
        repo: Path,
        args: list[str] | None = None,
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        """Run weak-test visitor scripts against PHP test files.

        Collects ``*Test.php`` files under *repo* (skipping vendor), then runs
        each weak-test visitor against each test file.  The merged JSON output
        from all visitors is returned in ``stdout``.

        Args:
            repo: Root path of the PHP repository.
            args: Not used (kept for ToolAdapter compat).
            env: Optional environment variables.
            timeout: Per-file timeout in seconds (default 300).

        Returns:
            A :class:`ToolInvocation` with merged findings on ``stdout``.
        """
        t0 = time.monotonic()
        all_findings: list[dict] = []
        stderr_parts: list[str] = []

        visitors_dir = Path(__file__).resolve().parent / "visitors"
        php_files = self._collect_test_files(repo)

        if not php_files:
            logger.warning("No PHP test files found in %s", repo)
            return ToolInvocation(stdout="[]", stderr="no PHP test files found", exitcode=0)

# 
        for visitor_name in _WEAK_TEST_VISITORS:
            visitor_script = visitors_dir / f"{visitor_name}.php"
            if not visitor_script.is_file():
                logger.warning("Weak-test visitor missing: %s", visitor_script)
                continue

            for php_file in php_files:
                result = subprocess.run(
                    ["php", str(visitor_script), str(php_file)],
                    cwd=str(repo),
                    env={**os.environ, **(env or {})},
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
                if result.returncode != 0:
                    stderr_parts.append(
                        f"visitor={visitor_name} file={php_file} exit={result.returncode}: "
                        f"{result.stderr.strip()}"
                    )
                    logger.debug("Weak-test visitor %s failed on %s: %s",
                                 visitor_name, php_file, result.stderr.strip())
                    continue

                parsed = self._parse_single_output(result.stdout)
                # Tag with visitor rule_id for layer context
                rule_id = _VISITOR_RULE_MAP.get(visitor_name, visitor_name)
                for finding in parsed:
                    finding["rule_id"] = rule_id
                all_findings.extend(parsed)

        duration = time.monotonic() - t0
        merged_stdout = json.dumps(all_findings, ensure_ascii=False)
        merged_stderr = "\n".join(stderr_parts) if stderr_parts else ""

        return ToolInvocation(
            stdout=merged_stdout,
            stderr=merged_stderr,
            exitcode=0 if not stderr_parts else 1,
            duration_seconds=round(duration, 3),
        )

    # -- parse -----------------------------------------------------------

    def parse(
        self,
        stdout: str,
        stderr: str = "",
        exitcode: int = 0,
    ) -> list[Finding]:
        """Parse merged weak-test JSON output into :class:`Finding` objects.

        Expected JSON format::

            [{"file": "tests/...", "line": 42, "rule_id": "A1",
              "message": "...", "severity": "error", "fix_hint": "..."}]

        Returns a list of :class:`Finding` objects, each tagged with
        ``layer="L3B"`` and ``language="php"``.
        """
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        items = self._parse_single_output(stdout)
        for item in items:
            if not isinstance(item, dict):
                continue
            filepath = item.get("file", item.get("path", ""))
            line = item.get("line")
            rule_id = item.get("rule_id", "")
            message = item.get("message", "")
            severity = item.get("severity", "info")
            fix_hint = item.get("fix_hint")

            node = f"{filepath}:{line}" if line else filepath
            if line:
                try:
                    line = int(line)
                except (ValueError, TypeError):
                    pass

            findings.append(
                Finding(
                    node=node,
                    severity=severity,
                    message=message,
                    fix_hint=fix_hint,
                    rule_id=rule_id,
                    tool=self._name,
                    layer="L3B",
                    language="php",
                )
            )
        return findings

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _collect_test_files(repo: Path) -> list[Path]:
        """Collect test PHP files under *repo*.

        Looks for files matching ``*Test.php`` or directories named
        ``tests/`` / ``Tests/``.  Skips ``vendor/`` and ``node_modules/``.
        """
        files: list[Path] = []
        try:
            for p in repo.rglob("*.php"):
                # Skip vendor / node_modules
                parts = [str(part) for part in p.parts]
                if any(excluded in parts for excluded in ["vendor", "node_modules"]):
                    continue
                # Only test files
                if re.search(r"(Test|Test\.php)$", p.name):
                    files.append(p)
        except OSError:
            pass
        return sorted(files)

    @staticmethod
    def _parse_single_output(stdout: str) -> list[dict]:
        """Parse JSON from a single visitor invocation.

        Handles valid JSON output or a simple CLI warning line before the
        JSON array.
        """
        text = stdout.strip()
        if not text:
            return []

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Graceful fallback: try to extract JSON array from mixed output.
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        logger.warning("Weak-test visitor output is not valid JSON: %r", text[:200])
        return []


# ---------------------------------------------------------------------------
# PhpWeakTestAdapter for layer orchestration (used by PhpAdapter.run_l3b)
# ---------------------------------------------------------------------------

class PhpWeakTestLayerAdapter:
    """Thin wrapper providing run_l3b for use by PhpAdapter.

    PhpAdapter composes ToolAdapters and calls their run_l3a/run_l1/etc.
    This wrapper provides a ``run_l3b(repo, env) -> LayerResult`` interface
    that delegates to ``PhpWeakTestAdapter``.
    """

    def __init__(self) -> None:
        self._adapter = PhpWeakTestAdapter()

    def run_l3b(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Run all weak-test visitors (A1–A8) and return findings.

        Args:
            repo: Root path of the PHP repository.
            env: Environment variables.

        Returns:
            A :class:`LayerResult` with ``layer="L3B"`` and merged findings.
        """
        t0 = time.monotonic()
        invocation = self._adapter.invoke(
            repo, [], env=env, timeout=300.0
        )
        findings = self._adapter.parse(
            invocation.stdout, invocation.stderr, invocation.exitcode
        )
        duration = time.monotonic() - t0

        logger.info(
            "weak-test-php: %d findings from %d files (%.1fs)",
            len(findings),
            len(self._adapter._collect_test_files(repo)),
            duration,
        )

        return LayerResult(
            layer="L3B",
            language="php",
            passed=len(findings) == 0,
            findings=findings,
            duration_sec=round(duration, 3),
        )
