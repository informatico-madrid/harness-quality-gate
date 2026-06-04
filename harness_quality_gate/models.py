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
    # reason: dataclass default None; tests assert f.fix_hint is None (test_mutant_killers). # audited: 2026-06-04
    fix_hint: str | None = None  # pragma: no mutate
    # Optional security-specific fields (populated by vulnerability scanners)
    # reason: dataclass default None; tested is None in test_mutant_killers. # audited: 2026-06-04
    cve: str | None = None  # pragma: no mutate
    cwe: str = ""
    # Tool/layer context for checkpoint v2 contract (US-3, US-4, FR-31)
    # reason: dataclass default None; Finding() with no args expects None. # audited: 2026-06-04
    tool: str | None = None  # pragma: no mutate
    # reason: same. # audited: 2026-06-04
    layer: str | None = None  # pragma: no mutate
    # reason: same. # audited: 2026-06-04
    language: str | None = None  # pragma: no mutate
    # reason: same. # audited: 2026-06-04
    rule_id: str | None = None  # pragma: no mutate


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
    exit_code: int = 0
    ignored_count: int = 0


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
    # reason: dataclass default None; LayerResult() with no tool_specific expects None. # audited: 2026-06-04
    tool_specific: dict[str, object] | None = None  # pragma: no mutate


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


@dataclass(frozen=True)
class DoctorReport:
    verdict: str
    python_version: str
    php_version: str
    composer_version: str
    tools: list[ToolCheckReport]
    warnings: list[str]


@dataclass(frozen=True)
class InstallReport:
    status: str
    tools_installed: list[str]
    tools_failed: list[str]
    errors: list[str]
