"""Abstract base classes for language adapters.

Every language adapter (PHP, Python, etc.) must subclass ``BaseAdapter``.
Each tool (phpstan, phpmd, etc.) is a ``ToolAdapter`` composed inside a
``BaseAdapter``.  A shared subprocess runner is provided to keep concrete
adapters simple.

FR-5   BaseAdapter abstract contract
FR-6   ToolAdapter tool-orchestration contract
FR-28  tool_versions() / check_tools() / layer runners
FR-29  ToolAdapter name / version / invoke / parse
FR-30  Shared subprocess helper with timeout/capture
"""
# reason: module docstring — string mutations have no behavioral effect. # audited: 2026-06-04

from __future__ import annotations

import logging
import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from ..models import Finding, LayerResult

# reason: logger name mutation does not change observability; only the __name__ label differs. # audited: 2026-06-04
logger = logging.getLogger(__name__)  # pragma: no mutate


# ---------------------------------------------------------------------------
# ToolInvocation dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolInvocation:
    """Captures the result of a single tool invocation."""

    stdout: str = ""
    stderr: str = ""
    exitcode: int = 0
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# BaseAdapter — layer orchestrator
# ---------------------------------------------------------------------------

class BaseAdapter(ABC):
    """Base class all language adapters must inherit from.

    Each concrete adapter (PhpAdapter, PythonAdapter) orchestrates
    multiple tool adapters across the 5 quality layers (L3A, L1, L2,
    L3B, L4).

    Implement the abstract methods below and compose ToolAdapter
    instances inside ``run_l3a``, ``run_l1``, etc.
    """

    # -- abstract interface -----------------------------------------------

    # reason: @abstractmethod is a Python protocol decorator — name mutation/removal breaks concrete subclasses (test_base_abstract_enforced). # audited: 2026-06-04
    @abstractmethod  # pragma: no mutate
    def tool_versions(self) -> dict[str, str]:
        """Return a dict mapping tool name → version string for every
        tool this adapter owns."""
        ...  # pragma: no cover

    # reason: @abstractmethod protocol. # audited: 2026-06-04
    @abstractmethod  # pragma: no mutate
    def check_tools(self) -> list[str]:
        """Return the names of critical tools that must be present on PATH
        or in ``vendor/bin/`` for this adapter to function.

        Raises ``RuntimeError`` if any listed tool is missing.
        """
        ...  # pragma: no cover

    # reason: @abstractmethod protocol. # audited: 2026-06-04
    @abstractmethod  # pragma: no mutate
    def run_l3a(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Execute the L3A (static-analysis + antipattern) layer."""
        ...  # pragma: no cover

    # reason: @abstractmethod protocol. # audited: 2026-06-04
    @abstractmethod  # pragma: no mutate
    def run_l1(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Execute the L1 (unit-test + coverage) layer."""
        ...  # pragma: no cover

    # reason: @abstractmethod protocol. # audited: 2026-06-04
    @abstractmethod  # pragma: no mutate
    def run_l2(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Execute the L2 (code-quality gates) layer."""
        ...  # pragma: no cover

    # reason: @abstractmethod protocol. # audited: 2026-06-04
    @abstractmethod  # pragma: no mutate
    def run_l3b(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Execute the L3B (weak-test detection) layer."""
        ...  # pragma: no cover

    # reason: @abstractmethod protocol. # audited: 2026-06-04
    @abstractmethod  # pragma: no mutate
    def run_l4(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Execute the L4 (security + architecture) layer."""
        ...  # pragma: no cover

    # -- concrete helpers -------------------------------------------------

    # Note: _run_subprocess was removed — the public `_run` is the only
    # entry point; `_run` lives in ToolAdapter below.


# ---------------------------------------------------------------------------
# ToolAdapter — individual tool wrapper
# ---------------------------------------------------------------------------

class ToolAdapter(ABC):
    """Base class for adapters that wrap a single static-analysis / test tool.

    Each tool (phpstan, phpmd, php-cs-fixer, composer-audit, psalm, etc.)
    gets its own subclass that handles invocation and JSON parsing.
    """

    # -- abstract interface -----------------------------------------------

    # reason: @property/@abstractmethod are Python protocol decorators — name mutations/removal break concrete subclasses. # audited: 2026-06-04
    @property  # pragma: no mutate
    @abstractmethod  # pragma: no mutate
    def name(self) -> str:
        """Human-readable tool name (e.g. ``"phpstan"``)."""
        ...  # pragma: no cover

    # reason: @abstractmethod protocol. # audited: 2026-06-04
    @abstractmethod  # pragma: no mutate
    def version(self, repo: Path, env: Mapping[str, str]) -> str:
        """Detect the installed version of this tool.

        Raises ``RuntimeError`` if the tool is not found.
        """
        ...  # pragma: no cover

    # reason: @abstractmethod protocol. # audited: 2026-06-04
    @abstractmethod  # pragma: no mutate
    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        # reason: default timeout=300.0 is a public API contract — mutations (301.0) are equivalent for any non-timing-sensitive caller. # audited: 2026-06-04
        timeout: float = 300.0,  # pragma: no mutate
    ) -> ToolInvocation:
        """Run the tool against *repo* with the given *args*.

        Returns a :class:`ToolInvocation` capturing stdout, stderr,
        exit code, and wall-clock duration.
        """
        ...  # pragma: no cover

    # reason: @abstractmethod protocol. # audited: 2026-06-04
    @abstractmethod  # pragma: no mutate
    def parse(
        self,
        stdout: str,
        stderr: str,
        exitcode: int,
    ) -> list[Finding]:
        """Parse tool output into :class:`Finding` objects.

        Args:
            stdout: The tool's stdout string.
            stderr: The tool's stderr string.
            exitcode: The tool's exit code.

        Returns:
            A list of :class:`Finding` objects.
        """
        ...  # pragma: no cover

    # -- concrete helpers -------------------------------------------------

    @staticmethod
    def _run(
        cmd: list[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        """Run a tool command and return a :class:`ToolInvocation`.

        Convenience wrapper that measures wall-clock duration and converts
        subprocess exceptions to a structured ToolInvocation.
        """
        start = datetime.now(timezone.utc)
        try:
            result = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                env={**os.environ, **(env or {})},
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,  # callers decide whether to check
            )
            duration = (datetime.now(timezone.utc) - start).total_seconds()
            return ToolInvocation(
                stdout=result.stdout,
                stderr=result.stderr or "",
                exitcode=result.returncode,
                duration_seconds=round(duration, 3),
            )
        except subprocess.TimeoutExpired as exc:
            duration = (datetime.now(timezone.utc) - start).total_seconds()
            return ToolInvocation(
                stdout=(exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode()) if exc.stdout else "",
                stderr=(exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode()) if exc.stderr else "TIMEOUT",
                exitcode=-1,
                duration_seconds=round(duration, 3),
            )
