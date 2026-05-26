"""PHP CS Fixer code-quality adapter (Tier A L3A).

Wraps ``php-cs-fixer fix --dry-run`` via subprocess + JSON parse.

Design: Component Responsibilities / php_cs_fixer_adapter, PHP Tier A tools.
Requirements: FR-8, US-3.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter, ToolInvocation

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PhpCsFixerAdapter
# ---------------------------------------------------------------------------

class PhpCsFixerAdapter(ToolAdapter):
    """Wraps PHP CS Fixer for L3A code-quality checks (@PER-CS2.0).

    At POC level only L3A is implemented.  L1-L4 return empty LayerResult.
    """

    _name = "php-cs-fixer"

    @property
    def name(self) -> str:
        return self._name

    # -- version ----------------------------------------------------------

    def version(
        self,
        repo: Path,
        env: Mapping[str, str] | None = None,
    ) -> str:
        """Return version string like ``'3.65.0'``."""
        cmd = self._cs_fixer_binary(repo)
        if cmd is None:
            raise RuntimeError(
                "php-cs-fixer not found on PATH or in vendor/bin"
            )
        result = subprocess.run(
            [*cmd, "--version"],
            cwd=str(repo),
            env={**__import__("os").environ, **(env or {})},
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"php-cs-fixer --version failed: {result.stderr.strip()}"
            )
        return result.stdout.strip()

    def _cs_fixer_binary(self, repo: Path) -> list[str] | None:
        """Resolve the php-cs-fixer binary: system PATH > vendor/bin."""
        system = shutil.which("php-cs-fixer")
        if system:
            return [system]
        vendor_bin = repo / "vendor" / "bin" / "php-cs-fixer"
        if vendor_bin.is_file():
            return [str(vendor_bin)]
        return None

    # -- invoke -----------------------------------------------------------

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        cmd = self._cs_fixer_binary(repo)
        if cmd is None:
            raise RuntimeError(
                "php-cs-fixer not found on PATH or in vendor/bin"
            )
        return self._run(
            [*cmd, *args],
            cwd=repo,
            env=env,
            timeout=timeout,
        )

    # -- parse ------------------------------------------------------------

    def parse(
        self,
        stdout: str,
        stderr: str,
        exitcode: int,
    ) -> list[Finding]:
        """Parse PHP CS Fixer JSON output into :class:`Finding` objects.

        Extracts ``files[]`` from ``--format=json`` output and maps each
        entry to a Finding with severity="warning" (code-style issues).

        Supports two JSON formats:

        1. Detailed (violations array)::

             {"files": [{"name": "x.php", "violations": [{"line": 1, ...}]}]}

        2. Simple (name + diff)::

             {"files": [{"name": "x.php", "diff": "..."}]}
        """
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        for entry in data.get("files", []):
            if not isinstance(entry, dict):
                continue
            name = entry.get("name", "")
            if not name:
                continue

            # Detailed format: per-violation findings
            violations = entry.get("violations")
            if isinstance(violations, list) and violations:
                for v in violations:
                    if not isinstance(v, dict):
                        continue
                    line = v.get("line")
                    msg = v.get("message", "")
                    hint = v.get("fix")
                    detail = msg
                    if line:
                        detail = f"line {line}: {detail}"
                    findings.append(
                        Finding(
                            node=name,
                            severity="warning",
                            message=detail or name,
                            fix_hint=hint if isinstance(hint, str) else None,
                        )
                    )
            else:
                # Simple format: file-level diff finding
                diff = entry.get("diff", "")
                findings.append(
                    Finding(
                        node=name,
                        severity="warning",
                        message=name,
                        fix_hint=diff if diff else None,
                    )
                )

        return findings
