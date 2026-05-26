"""Data models for harness-quality-gate.

Per design.md `## Data Models`: 11 frozen dataclasses covering detection,
findings, mutation stats, ignore entries, audit reports, tool checks,
layer results, runtime info, checkpoint v2, tool taxonomy, and concurrency plans.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Runtime:
    python_version: str
    concurrency: str
    ci: bool


@dataclass(frozen=True)
class Detection:
    repo_path: str
    language: str
    framework: str | None
    confidence: float
    runtime: Runtime
    # Fields added by 3-tier detector (1.4+)
    languages_detected: list[str] = field(default_factory=list)
    frameworks: dict[str, list[str]] = field(default_factory=dict)
    file_counts: dict[str, int] = field(default_factory=dict)

    @property
    def primary(self) -> str:
        """Alias for language — the primary detected language."""
        return self.language


@dataclass(frozen=True)
class Finding:
    node: str
    severity: str
    message: str
    fix_hint: str | None


@dataclass(frozen=True)
class MutationStats:
    total: int
    killed: int
    survived: int
    timed_out: int
    escaped: int
    untested: int
    msi: float
    covered_msi: float


@dataclass(frozen=True)
class IgnoreEntry:
    tool: str
    hash: str
    reason: str
    date_added: str
    expiry: str | None


@dataclass(frozen=True)
class AuditReport:
    findings: list[Finding]
    summary: str


@dataclass(frozen=True)
class ToolCheckReport:
    tool: str
    exit_code: int
    output: str | None
    error: str | None


@dataclass(frozen=True)
class LayerResult:
    layer: str
    language: str
    passed: bool
    findings: list[Finding]
    duration_sec: float


@dataclass(frozen=True)
class CheckpointV2:
    version: str
    timestamp: str
    repository: str
    language: str
    layers: list[LayerResult]
    mutation: MutationStats | None


@dataclass(frozen=True)
class ToolTaxonomyEntry:
    tool: str
    layer: str
    tier: str
    language: str


@dataclass(frozen=True)
class ConcurrencyPlan:
    mode: str
    ci_detected: bool
    max_threads: int
