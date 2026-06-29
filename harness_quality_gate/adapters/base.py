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

logger = logging.getLogger(__name__)


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


# Conventional top-level dirs that hold Python files but are not the
# shipped package (bandit/vulture must not sweep tests, for example).
_NON_PACKAGE_DIRS = frozenset({"test", "tests", "docs", "examples", "scripts"})


def package_dirs(repo: Path) -> list[str]:
    """Top-level Python package dirs (package-at-root layout, self-eval F2).

    A package is a non-hidden top-level directory containing ``__init__.py``,
    excluding conventional non-package dirs. Mutation artifacts never match:
    ``mutants/`` has no top-level ``__init__.py``. A *repo* path that does
    not exist yields no packages (degraded runs pass paths never created).
    """
    if not repo.is_dir():
        return []
    return sorted(
        child.name
        for child in repo.iterdir()
        if child.is_dir()
        and not child.name.startswith(".")
        and child.name not in _NON_PACKAGE_DIRS
        and (child / "__init__.py").is_file()
    )


def source_targets(
    repo: Path, *candidates: str, exclude_tests: bool = False
) -> list[str]:
    """Return the repo-relative scan targets among *candidates* that exist.

    The skill contract prefers ``src/`` and ``tests/`` in the target repo;
    scanning the whole repo would also sweep the mutation artifacts
    (``mutants/``, mutmut cache) that L1's own campaign generates
    (simulation bug H10). Repos with the package at the root (no ``src/``)
    additionally get their top-level packages appended (self-eval F2).
    Callers fall back to the repo root when nothing matches.

    When *exclude_tests* is True, directories whose stem matches ``test*``
    (case-insensitive) are stripped from the result — useful for
    type-checkers like pyright that should only scan production code.
    """
    targets = [c for c in candidates if (repo / c).is_dir()]
    targets.extend(p for p in package_dirs(repo) if p not in targets)
    if exclude_tests:
        targets = [t for t in targets if "test" not in str(t).lower()]
    return targets


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

    @abstractmethod
    def tool_versions(self) -> dict[str, str]:
        """Return a dict mapping tool name → version string for every
        tool this adapter owns."""
        ...  # pragma: no cover

    @abstractmethod
    def check_tools(self) -> list[str]:
        """Return the names of critical tools that must be present on PATH
        or in ``vendor/bin/`` for this adapter to function.

        Raises ``RuntimeError`` if any listed tool is missing.
        """
        ...  # pragma: no cover

    @abstractmethod
    def run_l3a(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Execute the L3A (static-analysis + antipattern) layer."""
        ...  # pragma: no cover

    @abstractmethod
    def run_l1(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Execute the L1 (unit-test + coverage) layer."""
        ...  # pragma: no cover

    @abstractmethod
    def run_l2(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Execute the L2 (code-quality gates) layer."""
        ...  # pragma: no cover

    @abstractmethod
    def run_l3b(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        """Execute the L3B (weak-test detection) layer."""
        ...  # pragma: no cover

    @abstractmethod
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

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable tool name (e.g. ``"phpstan"``)."""
        ...  # pragma: no cover

    @abstractmethod
    def version(self, repo: Path, env: Mapping[str, str]) -> str:
        """Detect the installed version of this tool.

        Raises ``RuntimeError`` if the tool is not found.
        """
        ...  # pragma: no cover

    @abstractmethod
    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        """Run the tool against *repo* with the given *args*.

        Returns a :class:`ToolInvocation` capturing stdout, stderr,
        exit code, and wall-clock duration.
        """
        ...  # pragma: no cover

    @abstractmethod
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
            )
            duration = (datetime.now(timezone.utc) - start).total_seconds()
            return ToolInvocation(
                stdout=result.stdout,
                stderr=result.stderr,
                exitcode=result.returncode,
                duration_seconds=round(duration, 3),
            )
        except subprocess.TimeoutExpired as exc:
            duration = (datetime.now(timezone.utc) - start).total_seconds()
            msg = (
                f"tool timed out after {round(duration, 3)}s (cmd={exc.cmd!r}, "
                f"timeout={timeout}s, cwd={cwd})"
            )
            logger.warning(msg)
            raise RuntimeError(msg) from exc
