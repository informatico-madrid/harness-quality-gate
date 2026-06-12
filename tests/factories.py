"""Factory helpers for building test data.

Builds Detection, Finding, LayerResult, IgnoreEntry, and FakeAdapter
instances without repeating boilerplate in every test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from harness_quality_gate.adapters.base import BaseAdapter  # pyright: ignore[reportMissingImports]
from harness_quality_gate.models import (
    Detection,
    Finding,
    IgnoreEntry,
    LayerResult,
    Runtime,
)


# ---------------------------------------------------------------------------
# Detection factory
# ---------------------------------------------------------------------------

def build_detection(
    language: str = "python",
    framework: str | None = None,
    confidence: float = 0.95,
    repo_path: str = "/tmp/test-repo",
    runtime: Runtime | None = None,
    languages_detected: list[str] | None = None,
    frameworks: dict[str, list[str]] | None = None,
    file_counts: dict[str, int] | None = None,
) -> Detection:
    """Build a Detection instance with sensible defaults."""
    return Detection(
        repo_path=repo_path,
        language=language,
        framework=framework,
        confidence=confidence,
        runtime=runtime or Runtime(python_version="3.12", concurrency="auto", ci=False),
        languages_detected=languages_detected or [language],
        frameworks=frameworks or {},
        file_counts=file_counts or {},
    )


# ---------------------------------------------------------------------------
# Finding factory
# ---------------------------------------------------------------------------

def build_finding(
    node: str = "src/example.py",
    severity: str = "MEDIUM",
    message: str = "Example finding",
    fix_hint: str | None = None,
    cve: str | None = None,
    cwe: str = "",
    tool: str | None = None,
    layer: str | None = None,
    language: str | None = None,
    rule_id: str | None = None,
) -> Finding:
    """Build a Finding instance with sensible defaults."""
    return Finding(
        node=node,
        severity=severity,
        message=message,
        fix_hint=fix_hint,
        cve=cve,
        cwe=cwe,
        tool=tool,
        layer=layer,
        language=language,
        rule_id=rule_id,
    )


# ---------------------------------------------------------------------------
# LayerResult factory
# ---------------------------------------------------------------------------

def build_layer_result(
    layer: str = "L3A",
    language: str = "python",
    passed: bool = True,
    findings: list[Finding] | None = None,
    duration_sec: float = 0.5,
    tool_specific: dict[str, object] | None = None,
) -> LayerResult:
    """Build a LayerResult instance with sensible defaults."""
    return LayerResult(
        layer=layer,
        language=language,
        passed=passed,
        findings=findings or [],
        duration_sec=duration_sec,
        tool_specific=tool_specific,
    )


# ---------------------------------------------------------------------------
# IgnoreEntry factory
# ---------------------------------------------------------------------------

def build_ignore_entry(
    tool: str = "ruff",
    hash_val: str = "abc123def456",
    reason: str = "Intentional style difference",
    date_added: str = "2026-01-01",
    expiry: str | None = None,
) -> IgnoreEntry:
    """Build an IgnoreEntry instance with sensible defaults."""
    return IgnoreEntry(
        tool=tool,
        hash=hash_val,
        reason=reason,
        date_added=date_added,
        expiry=expiry,
    )


# ---------------------------------------------------------------------------
# FakeAdapter — a minimal BaseAdapter for testing
# ---------------------------------------------------------------------------

@dataclass
class FakeAdapter(BaseAdapter):
    """Stub adapter that returns configurable results.

    Useful for testing orchestrator logic without invoking real tools.
    """

    language: str = "python"
    tool_name: str = "fake"
    tier: str = "tier-3"
    findings: list[Finding] = field(default_factory=list)
    passed: bool = True

    def run(self, _repo: str, _opts: dict[str, Any] | None = None) -> LayerResult:
        """Return a pre-built LayerResult."""
        return build_layer_result(
            layer=self.tier,
            language=self.language,
            passed=self.passed,
            findings=self.findings,
        )

    def check_available(self) -> bool:
        """Always reports available (fake tool)."""
        return True
