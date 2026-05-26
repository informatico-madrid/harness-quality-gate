"""Python language adapter — POC stub.

Subclasses ``BaseAdapter`` and returns empty passing ``LayerResult``
for every layer. No tools wired yet.

FR-33  Python adapter contract
US-12  Python quality-gate entry point
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from ..base import BaseAdapter
from ...models import Finding, LayerResult


class PythonAdapter(BaseAdapter):
    """Stub Python adapter — all layers return an empty passing result."""

    name = "python"

    # -- abstract: tool_versions / check_tools ----------------------------

    def tool_versions(self) -> dict[str, str]:
        return {}

    def check_tools(self) -> list[str]:
        return []

    # -- abstract: layer runners ------------------------------------------

    def run_l3a(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        return LayerResult(
            layer="l3a",
            language=self.name,
            passed=True,
            findings=[],
            duration_sec=0.0,
        )

    def run_l1(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        return LayerResult(
            layer="l1",
            language=self.name,
            passed=True,
            findings=[],
            duration_sec=0.0,
        )

    def run_l2(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        return LayerResult(
            layer="l2",
            language=self.name,
            passed=True,
            findings=[],
            duration_sec=0.0,
        )

    def run_l3b(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        return LayerResult(
            layer="l3b",
            language=self.name,
            passed=True,
            findings=[],
            duration_sec=0.0,
        )

    def run_l4(self, repo: Path, env: Mapping[str, str]) -> LayerResult:
        return LayerResult(
            layer="l4",
            language=self.name,
            passed=True,
            findings=[],
            duration_sec=0.0,
        )
