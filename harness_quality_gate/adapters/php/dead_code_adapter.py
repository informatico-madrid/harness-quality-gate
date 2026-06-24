"""ShipMonk dead-code-detector adapter (L4 architecture layer).

Wraps ``vendor/bin/dead-code-detector`` (or ``phpstan analyse`` with
dead-code.neon) into :class:`~harness_quality_gate.models.Finding` objects.

Design: Component Responsibilities / dead_code_adapter, PHP Tier A tools.
Requirements: FR-21, US-9.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter, ToolInvocation

# reason: logger name mutation does not change observability; only the __name__ label differs.
# audited: 2026-06-04
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DeadCodeAdapter
# ---------------------------------------------------------------------------


class DeadCodeAdapter(ToolAdapter):
    """Wraps ShipMonk dead-code-detector for L4 static analysis.

    At POC level only parsing is implemented. Actual invocation
    delegates to ``_run`` and gracefully skips when the binary
    is absent.
    """

    _name = "dead-code-detector"

    # -- abstract interface -----------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        raise NotImplementedError(
            "dead-code-detector version detection not implemented (POC)"
        )

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        """Run the tool if present; return empty invocation when missing."""
        binary = repo / "vendor" / "bin" / "dead-code-detector"
        if not binary.is_file():
            logger.debug("dead-code-detector binary not found at %s — skipping", binary)
            return ToolInvocation()

        cmd = ["php", str(binary), *args]
        return self._run(cmd, cwd=repo, env=env, timeout=timeout)

    def parse(  # type: ignore[override]
        self,
        stdout: str,
        *_compat: object,
    ) -> list[Finding]:
        """Parse JSON/JSON5 output into :class:`Finding` objects.

        Supports:
        1. ShipMonk JSON: ``{"references": [{"file": "...", "line": N, "message": "..."}]}``
        2. Generic per-file: ``{"files": {"path": {"messages": ["..."]}}}``
        3. Raw lines (each line → one Finding).
        """
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        # --- try valid JSON first ------------------------------------------
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            # fallback: treat each non-empty line as a finding
            return self._parse_lines(stdout)

        if isinstance(data, dict):
            # ShipMonk format: {"references": [...]}
            references = data.get("references")
            if isinstance(references, list):
                for ref in references:
                    if isinstance(ref, dict):
                        findings.append(
                            Finding(
                                node=ref.get("file", ""),
                                severity="warning",
                                message=ref.get("message")
                                or ref.get("tip")
                                or "Dead code reference",
                                fix_hint=ref.get("tip"),
                                tool=self._name,
                                layer="L4",
                                language="php",
                            )
                        )
                return findings

            # Generic per-file format: {"files": {"path": {"messages": [...]}}}
            files = data.get("files")
            if isinstance(files, dict):
                for filepath, file_data in files.items():
                    if not isinstance(file_data, dict):
                        continue
                    messages = file_data.get("messages", [])
                    for msg in messages:
                        if isinstance(msg, str):
                            findings.append(
                                Finding(
                                    node=filepath,
                                    severity="warning",
                                    message=msg,
                                    tool=self._name,
                                    layer="L4",
                                    language="php",
                                )
                            )
                        elif isinstance(msg, dict):
                            findings.append(
                                Finding(
                                    node=filepath,
                                    severity="warning",
                                    message=msg.get("message", ""),
                                    fix_hint=msg.get("tip"),
                                    tool=self._name,
                                    layer="L4",
                                    language="php",
                                )
                            )
                return findings

        return findings

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _parse_lines(stdout: str) -> list[Finding]:
        """Fallback parser: one finding per non-empty line."""
        findings: list[Finding] = []
        for line in stdout.splitlines():
            line = line.strip()
            if line:
                findings.append(
                    Finding(
                        node=line,
                        severity="warning",
                        message=line,
                        tool="dead-code-detector",
                        layer="L4",
                        language="php",
                    )
                )
        return findings
