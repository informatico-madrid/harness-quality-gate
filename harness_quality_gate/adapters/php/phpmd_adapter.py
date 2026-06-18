"""PHPMD antipattern / code-quality adapter (Tier A L3A).

Wraps ``phpmd`` via subprocess + JSON parse.

Design: Component Responsibilities / phpmd_adapter, PHP Tier A tools.
Requirements: FR-31, FR-32, FR-44.
"""

from __future__ import annotations

import json
import os
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

# Standard PHPMD rulesets for L3A analysis.
DEFAULT_RULESETS = "cleancode,codesize,controversial,design,naming,unusedcode"


class PhpMdAdapter(ToolAdapter):
    """Wraps PHPMD for L3A antipattern + code-quality analysis (Tier A).

    At POC level only L3A is implemented.  L1-L4 return empty LayerResult.
    """

    _name = "phpmd"

    @property
    def name(self) -> str:
        return self._name

    # -- version ----------------------------------------------------------

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        """Return version string like ``'2.14.0'``."""
        cmd = self._phpmd_binary(repo)
        if cmd is None:
            raise RuntimeError("phpmd not found on PATH or in vendor/bin")
        result = subprocess.run(
            [*cmd, "--version"],
            cwd=str(repo),
            env={**os.environ, **(env or {})},
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"phpmd --version failed: {result.stderr.strip()}")
        # Output: "PHPMD 2.14.0 ..."
        parts = result.stdout.strip().split()
        for p in parts:
            if p[0].isdigit() and "." in p:
                return p
        return result.stdout.strip()

    def _phpmd_binary(self, repo: Path) -> list[str] | None:
        """Resolve the phpmd binary: system PATH > vendor/bin."""
        if repo is None:
            raise RuntimeError("repository path is None")
        system = shutil.which("phpmd")
        if system:
            return [system]
        vendor_bin = repo / "vendor" / "bin" / "phpmd"
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
        cmd = self._phpmd_binary(repo)
        if cmd is None:
            raise RuntimeError("phpmd not found on PATH or in vendor/bin")
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
        """Parse PHPMD JSON output into :class:`Finding` objects.

        PHPMD JSON format:
        {
          "files": [
            {
              "file": "path/to/File.php",
              "violations": [
                {
                  "beginLine": 10,
                  "endLine": 20,
                  "rule": "LongVariable",
                  "description": "The variable $myVar is ...",
                  "externalRuleInfo": ...,
                  "priority": 3,
                  "md5hash": "...",
                  "package": "App\\Controllers",
                  "packageCycle": false,
                  "fullPackage": "App\\Controllers",
                  "startLine": 10,
                  "endLine": 20,
                  "function": null,
                  "class": "MyClass",
                  "method": "myMethod",
                  "variables": [...]
                }
              ]
            }
          ]
        }
        """
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        files = data.get("files")
        if not isinstance(files, list):
            return findings

        for file_entry in files:
            if not isinstance(file_entry, dict):
                continue
            filepath = file_entry.get("file", "")
            violations = file_entry.get("violations")
            if not isinstance(violations, list):
                continue
            for v in violations:
                if not isinstance(v, dict):
                    continue
                description = v.get("description", "")
                rule = v.get("rule")
                line = v.get("beginLine") or v.get("startLine")
                class_name = v.get("class")
                method_name = v.get("method")

                # Build a descriptive message with context
                context_parts = []
                if class_name:
                    context_parts.append(class_name)
                if method_name:
                    context_parts.append(method_name)
                context = ".".join(context_parts) if context_parts else None

                message = description
                if context:
                    message = f"{context}: {description}"
                if line:
                    message = f"Line {line}: {message}"

                # Priority map (PHPMD priority 1-5, 1=most severe)
                priority = v.get("priority", 3)
                severity = _priority_to_severity(priority)

                fix_hint = f"Rule: {rule}" if rule else None

                findings.append(
                    Finding(
                        node=filepath,
                        severity=severity,
                        message=message,
                        fix_hint=fix_hint,
                    )
                )

        return findings

    # -- L3A run (POC level) ----------------------------------------------

    def run_l3a(
        self,
        repo: Path,
        env: Mapping[str, str],
        rulesets: str = DEFAULT_RULESETS,
    ) -> list[Finding]:
        """Run PHPMD with the default rulesets and return findings."""
        return self._run_phpmd(repo, rulesets, env, timeout=300.0)

    def _run_phpmd(
        self,
        repo: Path,
        rulesets: str,
        env: Mapping[str, str],
        timeout: float,
    ) -> list[Finding]:
        """Execute phpmd against *repo* and return parsed findings."""
        analysis_args = [
            str(repo),
            "json",
            rulesets,
        ]
        invocation = self.invoke(repo, analysis_args, env=env, timeout=timeout)
        logger.info(
            "PHPMD exit=%d stdout=%dchars stderr=%dchars duration=%.1fs",
            invocation.exitcode,
            len(invocation.stdout),
            len(invocation.stderr),
            invocation.duration_seconds,
        )
        return self.parse(invocation.stdout, invocation.stderr, invocation.exitcode)


def _priority_to_severity(priority: int) -> str:
    """Map PHPMD priority (1-5) to severity string.

    PHPMD priority scale:
      1 = highest importance
      5 = lowest importance
    """
    mapping = {
        1: "critical",
        2: "major",
        3: "minor",
    }
    # 4, 5 and anything unexpected all map to the "info" default
    return mapping.get(priority, "info")
