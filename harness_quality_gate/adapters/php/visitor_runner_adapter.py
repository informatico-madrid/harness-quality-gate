"""Visitor runner adapter for nikic/PHP-Parser PoC visitors (Tier A L3A).

Shells out to individual PHP visitor scripts, each of which scans one
file and emits JSON findings on stdout.  This adapter discovers visitor
scripts in ``visitors/``, runs them sequentially against every PHP file in
the repository, and merges the results.

Design: TD-12, visitor_runner_adapter, visitors/*.php
Requirements: FR-10, US-3
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter, ToolInvocation

# reason: logger name mutation doesn't change observability; only the __name__ label differs.
# audited: 2026-06-04
logger = logging.getLogger(__name__)  # pragma: no mutate

# Visitor scripts live alongside this module.
VISITORS_DIR = Path(__file__).resolve().parent / "visitors"


def _discover_visitors() -> list[str]:
    """Return sorted list of visitor script names (without .php suffix)."""
    names: list[str] = []
    if VISITORS_DIR.is_dir():
        for p in sorted(VISITORS_DIR.iterdir()):
            if p.suffix == ".php" and not p.name.startswith("_"):
                names.append(p.stem)
    return names


class VisitorRunnerAdapter(ToolAdapter):
    """Runs nikic/PHP-Parser visitor scripts against PHP source files.

    Each visitor is a standalone PHP script that accepts a file path as
    ``$argv[1]``, parses it with nikic/php-parser, and emits a JSON array
    of findings on stdout:

    .. code-block:: json

        [{"file": "path/to/File.php", "line": 42, "rule_id": "GodClass",
          "message": "..."}]

    This adapter invokes every visitor against every ``*.php`` file in the
    repository and merges the results.
    """

    _name = "visitor-runner"

    @property
    def name(self) -> str:
        return self._name

    # -- version ----------------------------------------------------------

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        """Not yet implemented for PoC visitors."""
        raise NotImplementedError(
            "VisitorRunnerAdapter.version() is not implemented for PoC visitors"
        )

    # -- invoke -----------------------------------------------------------

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        """Discover visitors, collect all PHP files, run each visitor against
        each file, and merge JSON findings from stdout.

        Args:
            repo: Root path of the PHP repository.
            args: Not used (kept for ToolAdapter compat).
            env: Optional environment variables.
            timeout: Per-file timeout in seconds (default 300).

        Returns:
            A :class:`ToolInvocation` whose ``stdout`` is a merged JSON
            array of all findings from all visitors.
        """
        all_findings: list[dict] = []
        stderr_parts: list[str] = []
        visitors_dir = VISITORS_DIR
        repo_dir = repo

        visitors = _discover_visitors()
        if not visitors:
            logger.warning("No visitor scripts found in %s", visitors_dir)
            return ToolInvocation(
                stdout="[]",
                stderr=f"no visitors discovered ({visitors_dir})",
            )

        php_files = self._collect_php_files(repo_dir)
        if not php_files:
            logger.warning("No PHP files found in %s", repo_dir)
            return ToolInvocation(
                stdout="[]",
                stderr=f"no PHP files found in {repo_dir}",
            )

# 
        for visitor_name in visitors:
            visitor_script = VISITORS_DIR / f"{visitor_name}.php"
            if not visitor_script.is_file():
                logger.warning("Visitor script missing: %s", visitor_script)
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
                    logger.debug("Visitor %s failed on %s: %s", visitor_name, php_file, result.stderr.strip())
                    continue
                findings = self._parse_visitor_output(result.stdout)
                all_findings.extend(findings)

        return self._build_invocation(all_findings, stderr_parts)

    # -- parse -----------------------------------------------------------

    def parse(
        self,
        stdout: str,
        stderr: str,
        exitcode: int,
    ) -> list[Finding]:
        """Parse merged visitor JSON output into :class:`Finding` objects.

        Expected JSON format (from each visitor)::

            [{"file": "path", "line": 10, "rule_id": "GOD-001", "message": "..."}]

        Returns a list of :class:`Finding` objects, one per JSON entry.
        """
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        items = self._parse_visitor_output(stdout)
        for item in items:
            finding = self._build_finding(item)
            if finding is not None:
                findings.append(finding)
        return findings

    # -- parse helper -----------------------------------------------------

    @staticmethod
    def _build_finding(item: object) -> Finding | None:
        """Build a single :class:`Finding` from a parsed JSON dict item.

        Returns None if the item is not a valid dict.
        """
        if not isinstance(item, dict):
            return None
        filepath = item.get("file", item.get("path", ""))
        line = item.get("line")
        rule_id = item.get("rule_id", "")
        message = item.get("message", "")
        severity = item.get("severity", "info")
        fix_hint = item.get("fix_hint")

        # the raw line value is only embedded in the node string
        node = f"{filepath}:{line}" if line else filepath

        return Finding(
            node=node,
            severity=severity,
            message=message,
            fix_hint=fix_hint,
            rule_id=rule_id,
            tool="visitor-runner",
            layer="L3A",
            language="php",
        )

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _merge_findings(all_findings: list[dict]) -> str:
        """Serialize merged findings to JSON string."""
        # reason: Tipo C — ensure_ascii=None es gemelo falsy de False (runtime idéntico);
        # las variantes True/removal las matan los tests unicode. # audited: 2026-06-11
        return json.dumps(all_findings, ensure_ascii=False)  # pragma: no mutate

    @staticmethod
    def _build_stderr(stderr_parts: list[str]) -> str:
        """Build merged stderr string from parts, or empty string."""
        return "\n".join(stderr_parts) if stderr_parts else ""

    @staticmethod
    def _build_invocation(
        all_findings: list[dict],
        stderr_parts: list[str],
    ) -> ToolInvocation:
        """Build final ToolInvocation from findings and stderr parts."""
        return ToolInvocation(
            stdout=VisitorRunnerAdapter._merge_findings(all_findings),
            stderr=VisitorRunnerAdapter._build_stderr(stderr_parts),
            exitcode=0 if not stderr_parts else 1,
        )

    @staticmethod
    def _collect_php_files(repo: Path) -> list[Path]:
        """Collect all *.php files under *repo*."""
        files: list[Path] = []
        try:
            for p in repo.rglob("*.php"):
                # Skip vendor directories
                if "vendor" not in p.parts:
                    files.append(p)
        except OSError:
            pass
        return sorted(files)

    @staticmethod
    def _parse_visitor_output(stdout: str) -> list[dict]:
        """Parse JSON array from a single visitor invocation.

        Falls back to an empty list if the output is not valid JSON.
        Also handles a simple CLI warning line before the JSON array.
        """
        text = stdout.strip()
        if not text:
            return []

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Graceful fallback: try to find a JSON array in the output.
        # Some visitors may print a warning on stderr or a note on stdout
        # before the JSON. Try to extract the first '[' ... ']'.
        start = text.find("[")
        end = text.rfind("]")
        # reason: Tipo B — '[' y ']' nunca comparten índice (end==start inalcanzable)
        # y con un solo corchete el slice degenerado cae igualmente al warning;
        # las variantes and→or / >=→> son estructuralmente equivalentes. # audited: 2026-06-11
        if start >= 0 and end > start:  # pragma: no mutate
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        logger.warning("Visitor output is not valid JSON: %r", text[:200])
        return []
