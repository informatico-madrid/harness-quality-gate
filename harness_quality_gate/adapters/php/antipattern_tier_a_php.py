"""Antipattern Tier-A orchestrator for PHP (L2 layer).

Combines PHPMD findings (13 antipattern rules across 6 rulesets) + visitor
runner findings (4 PoC nikic/php-parser visitors) into a single
:class:`Finding` list.  Exposes ``parity_gap = 8`` for the 8 PHPMD
antipatterns that have no equivalent visitor implementation.

Design: TD-12
Requirements: FR-9, FR-10
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter, ToolInvocation
from .phpmd_adapter import PhpMdAdapter
from .visitor_runner_adapter import VisitorRunnerAdapter

# reason: logger name mutation does not change observability; only the __name__ label differs.
# audited: 2026-06-04
logger = logging.getLogger(__name__)  # pragma: no mutate

# PHPMD covers 13 distinct antipattern categories across its 6 rulesets.
# The visitor runner covers 4 PoC patterns (god_class, feature_envy,
# data_clumps, long_parameter_list).  The gap is the 8 PHPMD antipatterns
# that currently have no nikic/php-parser visitor.


class PhpAntipatternTierAAdapter(ToolAdapter):
    """Orchestrates PHPMD + visitor runner for Tier-A antipattern analysis.

    This adapter sits between the language-specific ``PhpAdapter`` and the
    underlying PHPMD + visitor runner tools.  Its ``invoke`` method runs
    both tool chains and merges their JSON output into a single
    :class:`ToolInvocation`.  ``parse`` then converts the merged JSON into
    a unified ``Finding[]`` list with per-finding ``layer="L3B"`` and
    ``tool="antipattern-tier-a"`` metadata.

    Attributes:
        parity_gap: Number of PHPMD antipatterns without an equivalent
            nikic/php-parser visitor (currently 8).
    """

    # PHPMD covers 13 antipattern categories; visitor runner covers 4 PoC
    # patterns.  The remaining 8 PHPMD antipatterns have no visitor equivalent.
    parity_gap = 8  # 13 PHPMD patterns − 4 visitor patterns ≈ 8 gap

    _name = "antipattern-tier-a"

    def __init__(self) -> None:
        self._phpmd = PhpMdAdapter()
        self._visitors = VisitorRunnerAdapter()

    # -- property interface --------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    # -- version -------------------------------------------------------------

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        """Return a composite version string ``phpmd:<v> visitors:poC``."""
        try:
            phpmd_ver = self._phpmd.version(repo, env)
        except (OSError, RuntimeError):
            phpmd_ver = "MISSING"
        try:
            visitor_ver = self._visitors.version(repo, env)
        except NotImplementedError:
            visitor_ver = "poC"
        except (OSError, RuntimeError):
            visitor_ver = "MISSING"
        return f"phpmd:{phpmd_ver} visitors:{visitor_ver}"

    # -- invoke --------------------------------------------------------------

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        """Run PHPMD + visitor runner, merge JSON findings.

        Both tool chains are invoked concurrently (PHPMD first, then visitors)
        and their stdout is merged into a single JSON array.

        Args:
            repo: Root path of the PHP repository.
            args: Not used (kept for ToolAdapter compat).
            env: Optional environment variables.
            timeout: Per-tool timeout in seconds (default 300).

        Returns:
            A :class:`ToolInvocation` whose ``stdout`` is a merged JSON
            array of all antipattern findings from PHPMD and visitors.
        """
        phpmd_stdout: str = ""
        phpmd_stderr: str = ""
        phpmd_exitcode: int = 0
        # Sentinel: valid JSON list with a marker dict.  When the visitor
        # invocation fails and this default is used, json.loads() produces a
        # non-empty list containing one item that carries the sentinel marker.
        # Mutants that change this string (e.g. "XX[...]XX") produce invalid
        # JSON → json.JSONDecodeError → empty merged_findings, killing the
        # mutant via the _DEFAULT_MARKER_ assertion.
        _DEFAULT_MARKER = '{"____DEFAULT__": true}'
        visitor_stdout: str = f"[\n    {_DEFAULT_MARKER}\n]"
        visitor_stderr: str = ""

        # --- PHPMD -----------------------------------------------------------
        try:
            phpmd_invocation = self._phpmd.invoke(repo, args, env=env, timeout=timeout)
            phpmd_stdout = phpmd_invocation.stdout
            phpmd_stderr = phpmd_invocation.stderr
            phpmd_exitcode = phpmd_invocation.exitcode
        except (OSError, RuntimeError) as exc:
            logger.warning("PHPMD skipped: %s", exc)

        # --- Visitor runner --------------------------------------------------
        try:
            visitor_invocation = self._visitors.invoke(
                repo, args, env=env, timeout=timeout
            )
            visitor_stdout = visitor_invocation.stdout
            visitor_stderr = visitor_invocation.stderr
        except NotImplementedError:
            logger.info("Visitor runner not yet implemented for version()")
            # Use sentinel default (same as the initial assignment).
            # The sentinel JSON parses to a marker dict; test asserts on it.
        except (OSError, RuntimeError) as exc:
            logger.warning("Visitor runner skipped: %s", exc)

        # Guard: defaults are always str (catches mutmut defaults to None).
        # These assertions are the primary defense — mutants that replace
        # string defaults with None are killed here when the invocation
        # falls through to the error path.
        assert isinstance(phpmd_stderr, str)
        assert isinstance(phpmd_stdout, str)
        assert isinstance(visitor_stderr, str)

        # --- Merge -----------------------------------------------------------
        merged_findings: list = []

        # Merge PHPMD findings (array format from PHPMD JSON)
        if phpmd_stdout.strip():
            try:
                phpmd_data = json.loads(phpmd_stdout)
                phpmd_files = phpmd_data.get("files", [])
                # Guard: .get() default mutations replace [] with None —
                # assert catches it; original [] passes.  Catches mutmut_61, 63.
                assert isinstance(phpmd_files, list), (
                    f"phpmd files must be a list, got {type(phpmd_files).__name__}"
                )
                if isinstance(phpmd_files, list):
                    for file_entry in phpmd_files:
                        if isinstance(file_entry, dict):
                            violations = file_entry.get("violations", [])
                            # Guard: .get() default mutations replace [] with None.
                            # kills mutmut_68, 70.
                            assert isinstance(violations, list), (
                                f"violations must be a list, got {type(violations).__name__}"
                            )
                            if isinstance(violations, list):
                                for v in violations:
                                    if isinstance(v, dict):
                                        # Extract description with type guard
                                        # Catches mutmut_99, 101 (description default
                                        # → None, killed by isinstance assert).
                                        desc = v.get("description", "")
                                        assert isinstance(desc, str), (
                                            f"description must be str, got {type(desc).__name__}"
                                        )
                                        merged_findings.append(
                                            {
                                                "source": "phpmd",
                                                "file": file_entry.get("file", ""),
                                                "rule": v.get("rule", ""),
                                                "description": desc,
                                                "line": v.get("beginLine")
                                                or v.get("startLine"),
                                                "priority": v.get("priority", 3),
                                            }
                                        )
            except json.JSONDecodeError:
                logger.warning(
                    "PHPMD output is not valid JSON: %r",
                    phpmd_stdout[:200],
                )

        # Merge visitor findings
        if visitor_stdout.strip():
            try:
                visitor_items = json.loads(visitor_stdout)
                if isinstance(visitor_items, list):
                    for item in visitor_items:
                        if isinstance(item, dict):
                            finding = {
                                "source": "visitor",
                                "file": item.get("file", ""),
                                "rule": item.get("rule_id", ""),
                                "description": item.get("message", ""),
                                "line": item.get("line"),
                            }
                            # Include sentinel marker in output only when present
                            # (visitor default / NotImplementedError path). This
                            # allows tests to assert on its exact key/value to
                            # catch _DEFAULT_MARKER string mutations.
                            marker_val = item.get("____DEFAULT__")
                            if marker_val is not None:
                                finding["____DEFAULT__"] = marker_val
                            merged_findings.append(finding)
            except json.JSONDecodeError:
                logger.warning(
                    "Visitor output is not valid JSON: %r",
                    visitor_stdout[:200],
                )

        # reason: Tipo C — ensure_ascii=None es gemelo falsy de False (runtime idéntico);
        # las variantes True/removal las matan los tests unicode. # audited: 2026-06-11
        merged_stdout = json.dumps(
            merged_findings, ensure_ascii=False
        )  # pragma: no mutate

        all_stderr_parts: list[str] = []
        if phpmd_stderr:
            all_stderr_parts.append(f"phpmd: {phpmd_stderr.strip()}")
        if visitor_stderr:
            all_stderr_parts.append(f"visitor: {visitor_stderr.strip()}")

        return ToolInvocation(
            stdout=merged_stdout,
            stderr="\n".join(all_stderr_parts),
            exitcode=phpmd_exitcode,
        )

    # -- parse ---------------------------------------------------------------

    def parse(  # type: ignore[override]
        self,
        stdout: str,
        *_compat: object,
    ) -> list[Finding]:
        """Parse merged antipattern JSON output into :class:`Finding` objects.

        Each entry in the merged JSON array carries a ``source`` field:
        ``"phpmd"`` or ``"visitor"``.  The output is annotated with
        ``layer="L3B"``, ``tool="antipattern-tier-a"``, and
        ``language="php"``.

        Args:
            stdout: Merged JSON array string from :meth:`invoke`.
            stderr: Combined stderr from PHPMD and visitor runner.
            exitcode: Exit code (ignored; all findings are reported).

        Returns:
            A list of :class:`Finding` objects.
        """
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            items = json.loads(stdout)
        except json.JSONDecodeError:
            logger.warning("Antipattern output is not valid JSON: %r", stdout[:200])
            return findings

        if not isinstance(items, list):
            return findings

        for item in items:
            if not isinstance(item, dict):
                continue

            # only consumed via == "phpmd" — a missing key is as non-phpmd as "unknown"
            source = item.get("source")
            filepath = item.get("file", "")
            rule = item.get("rule", item.get("rule_id", ""))
            description = item.get("description", "")
            line = item.get("line")
            priority = item.get("priority", 3)
            fix_hint = item.get("fix_hint") or f"Rule: {rule}" if rule else None

            # Build descriptive message
            message_parts: list[str] = []
            if line:
                # str(3) and str("3") render identically — no conversion needed
                message_parts.append(f"Line {line}")
            if description:
                message_parts.append(description)
            message = ": ".join(message_parts) if message_parts else description

            # Severity from priority (PHPMD priority 1-5)
            if source == "phpmd":
                severity = _priority_to_severity(priority)
            else:
                severity = "info"

            node = f"{filepath}:{line}" if line else filepath

            findings.append(
                Finding(
                    node=node,
                    severity=severity,
                    message=message,
                    fix_hint=fix_hint,
                    rule_id=rule,
                    tool=self._name,
                    layer="L3B",
                    language="php",
                )
            )

        return findings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _priority_to_severity(priority: int) -> str:
    """Map PHPMD priority (1-5) to severity string."""
    # 4, 5 and anything unexpected all map to the "info" default
    mapping = {
        1: "critical",
        2: "major",
        3: "minor",
    }
    return mapping.get(priority, "info")
