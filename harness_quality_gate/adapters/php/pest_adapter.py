"""Pest test runner + mutation-testing adapter.

Wraps ``vendor/bin/pest`` for L1 layer execution and detects
``pestphp/pest-plugin-mutate`` presence for mutation-testing orchestration.

Design: Component Responsibilities / pest_adapter, PHP Tier A L1 tool.
Requirements: FR-11, US-7.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter, ToolInvocation


class PestAdapter(ToolAdapter):
    """Wraps Pest test runner with mutation-skipping fallback (TD-6).

    If ``pestphp/pest-plugin-mutate`` is absent from composer.json,
    mutation testing is marked skipped on the returned result.
    """

    _name = "pest"

    # -- abstract interface -----------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        cmd = self._pest_binary(repo)
        if cmd is None:
            raise RuntimeError("pest not found on PATH or in vendor/bin")
        result = subprocess.run(
            [*cmd, "--version"],
            cwd=str(repo),
            env={**__import__("os").environ, **(env or {})},
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"pest --version failed: {result.stderr.strip()}")
        parts = result.stdout.strip().split()
        for p in parts:
            if p[0].isdigit() and "." in p:
                return p
        return result.stdout.strip()

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        cmd = self._pest_binary(repo)
        if cmd is None:
            raise RuntimeError("pest not found on PATH or in vendor/bin")
        return self._run(
            [*cmd, *args],
            cwd=repo,
            env=env,
            timeout=timeout,
        )

    def parse(
        self,
        stdout: str,
        stderr: str,
        exitcode: int,
    ) -> list[Finding]:
        """Parse Pest output — currently returns empty list.

        Pest itself is a test runner (not a static analysis tool);
        findings are driven by coverage/mutation data instead.
        """
        return []

    # -- concrete helpers -------------------------------------------------

    def _pest_binary(self, repo: Path) -> list[str] | None:
        """Resolve the pest binary: vendor/bin first, then PATH."""
        if repo is None:
            raise RuntimeError("repository path is None")
        vendor_bin = repo / "vendor" / "bin" / "pest"
        if vendor_bin.is_file():
            return [str(vendor_bin)]
        system = shutil.which("pest")
        if system:
            return [system]
        return None

    def _has_mutate_plugin(self, repo: Path) -> bool:
        """Check whether pest-plugin-mutate is listed in composer.json."""
        composer_path = repo / "composer.json"
        if not composer_path.is_file():
            return False
        try:
            data = json.loads(composer_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        for section in ("require", "require-dev"):
            deps = data.get(section) or {}
            if isinstance(deps, dict) and "pestphp/pest-plugin-mutate" in deps:
                return True
        return False
