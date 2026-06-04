"""PHPStan static-analysis adapter (Tier A L3A).

Wraps ``phpstan analyse`` via subprocess + JSON parse.

Design: Component Responsibilities / phpstan_adapter, PHP Tier A tools.
Requirements: FR-31, FR-32, FR-44.
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

# reason: logger name mutation does not change observability; only the __name__ label differs.
# audited: 2026-06-04
logger = logging.getLogger(__name__)  # pragma: no mutate


# ---------------------------------------------------------------------------
# PhpStanAdapter
# ---------------------------------------------------------------------------

class PhpStanAdapter(ToolAdapter):
    """Wraps PHPStan for L3A static analysis (Tier A).

    At POC level only L3A is implemented.  L1-L4 return empty LayerResult.
    """

    _name = "phpstan"

    @property
    def name(self) -> str:
        return self._name

    # -- version ----------------------------------------------------------

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        """Return version string like ``'2.1.34'``."""
        cmd = self._phpstan_binary(repo)
        if cmd is None:
            raise RuntimeError("phpstan not found on PATH or in vendor/bin")
        result = subprocess.run(
            [*cmd, "--version"],
            cwd=str(repo),
            env={**__import__("os").environ, **(env or {})},
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"phpstan --version failed: {result.stderr.strip()}")
        # Output: "PHP 2.1.34 by.neon ..." or "Version 2.1.34 ..."
        parts = result.stdout.strip().split()
        for p in parts:
            if p[0].isdigit() and "." in p:
                return p
        return result.stdout.strip()

    def _phpstan_binary(self, repo: Path) -> list[str] | None:
        """Resolve the phpstan binary: system PATH > vendor/bin."""
        system = shutil.which("phpstan")
        if system:
            return [system]
        vendor_bin = repo / "vendor" / "bin" / "phpstan"
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
        cmd = self._phpstan_binary(repo)
        if cmd is None:
            raise RuntimeError("phpstan not found on PATH or in vendor/bin")
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
        """Parse PHPStan JSON output into :class:`Finding` objects.

        Supports two JSON formats:

        1. ``--error-format=json`` (PHPStan >= 1.x):
           {"file_diagnostics": [{"file": "path", "messages": [...], "errors": [...]}]}

        2. Legacy format (used in tests/spec):
           {"files": {"path/to/File.php": {"messages": [{"message": "x", "line": 1}]}}}
        """
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        # Format 1: file_diagnostics (real phpstan --error-format=json output)
        file_diagnostics = data.get("file_diagnostics")
        if isinstance(file_diagnostics, list):
            for fd in file_diagnostics:
                filepath = fd.get("file", "")
                messages = fd.get("messages", [])
                errors = fd.get("errors", [])
                for msg in messages:
                    findings.append(
                        Finding(
                            node=filepath,
                            severity="error",
                            message=msg,
                            fix_hint=None,
                            tool=self._name,
                            layer="L3A",
                            language="php",
                        )
                    )
                for err in errors:
                    findings.append(
                        Finding(
                            node=filepath,
                            severity="error",
                            message=f"{err.get('message', '')} ({err.get('tip', '')})".rstrip(" ()"),
                            fix_hint=err.get("tip"),
                            tool=self._name,
                            layer="L3A",
                            language="php",
                        )
                    )
            return findings

        # Format 2: legacy {"files": {"path": {"messages": [{"message": "..."}]}}}
        files = data.get("files")
        if isinstance(files, dict):
            for filepath, file_data in files.items():
                if not isinstance(file_data, dict):
                    continue
                messages = file_data.get("messages", [])
                for msg_item in messages:
                    if isinstance(msg_item, str):
                        message = msg_item
                    elif isinstance(msg_item, dict):
                        message = msg_item.get("message", "")
                    else:
                        continue
                    findings.append(
                        Finding(
                            node=filepath,
                            severity="error",
                            message=message,
                            fix_hint=None,
                            tool=self._name,
                            layer="L3A",
                            language="php",
                        )
                    )
        return findings

    # -- L3A run (POC level) ----------------------------------------------

    def run_l3a(self, repo: Path, env: Mapping[str, str]) -> list[Finding]:
        """Run PHPStan and return findings."""
        analyse_args = [
            "analyse",
            "--no-progress",
            "--error-format=json",
            "--level=max",
            str(repo),
        ]
        invocation = self.invoke(repo, analyse_args, env=env, timeout=600.0)
        return self.parse(invocation.stdout, invocation.stderr, invocation.exitcode)
