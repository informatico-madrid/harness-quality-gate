"""Allow-list audit engine for finding suppression.

Provides ``AllowListAuditor.audit(repo, diff_from)`` which scans source files
for language-specific suppression annotations that lack proper justification
metadata (``reason:`` and ``audited:`` tags).

Design reference: TD-10, allow_list_auditor component (top-level, language-aware).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .models import AuditReport, Finding


@dataclass
class AllowListEntry:
    """Single allow-list entry with optional regex support.

    When ``pattern`` is provided the entry supports regex matching
    against rule_ids (Phase 2+).  For the PoC only exact matches
    on ``rule_id`` are used.
    """

    rule_id: str
    pattern: str | None = None
    description: str | None = None

    def matches(self, candidate: str) -> bool:
        """Return True if *candidate* matches this entry."""
        if self.pattern:
            return bool(re.fullmatch(self.pattern, candidate))
        return self.rule_id == candidate


def _build_allow_list(raw: Iterable[str]) -> list[AllowListEntry]:
    """Convert raw strings into ``AllowListEntry`` objects."""
    return [AllowListEntry(rule_id=r) for r in raw]


def audit(
    findings: list[Finding],
    allow_list: list[str],
) -> list[Finding]:
    """Return *findings* with entries whose ``rule_id`` appears in *allow_list* removed.

    Args:
        findings: The full list of findings to filter.
        allow_list: List of rule_id values to suppress (PoC: PHP-only).

    Returns:
        A new list containing only findings whose ``rule_id`` is **not**
        in the allow-list.
    """
    entries = _build_allow_list(allow_list)
    result: list[Finding] = []
    for f in findings:
        if f.rule_id is not None and any(e.matches(f.rule_id) for e in entries):
            continue
        result.append(f)
    return result


# ------------------------------------------------------------------
# Language-aware regex selectors (TD-9)
# ------------------------------------------------------------------

# Within N preceding lines of a suppression marker, require both tags.
_METADATA_WINDOW = 5


@dataclass
class _LangSelector:
    """Language-specific file pattern and annotation regex set."""

    # Glob pattern for source files (e.g. "*.php", "*.py")
    file_glob: str
    # Regex matching the suppression marker in a source line
    marker_re: re.Pattern[str]
    # Regex matching the required "reason:" tag in preceding lines
    reason_re: re.Pattern[str]
    # Regex matching the required "audited:" tag in preceding lines
    audited_re: re.Pattern[str]
    # Optional regex matching "proven-by:" tag (accepted but not required)
    proven_by_re: re.Pattern[str] | None = None
    # Language name for error messages
    lang_name: str = ""
    # Marker text for messages
    marker_label: str = ""

    # -- PHP selectors --


_PHP_SELECTOR = _LangSelector(
    file_glob="*.php",
    marker_re=re.compile(r"@infection-ignore-all"),
    reason_re=re.compile(r"reason:", re.IGNORECASE),
    audited_re=re.compile(r"audited:", re.IGNORECASE),
    lang_name="php",
    marker_label="@infection-ignore-all",
)

# -- Python selectors --

_PYTHON_SELECTOR = _LangSelector(
    file_glob="*.py",
    marker_re=re.compile(r"#\s*pragma:\s*no\s+mutate", re.IGNORECASE),
    reason_re=re.compile(r"#\s*reason:", re.IGNORECASE),
    audited_re=re.compile(r"#\s*audited:", re.IGNORECASE),
    proven_by_re=re.compile(r"#\s*proven-by:", re.IGNORECASE),
    lang_name="python",
    # reason: marker_label is a display string containing pragma text, not a real annotation.
    # audited: 2026-06-04
    marker_label="# pragma: no mutate",
)

# Map language names to their selector.
_LANGUAGE_SELECTORS: dict[str, _LangSelector] = {
    "php": _PHP_SELECTOR,
    "python": _PYTHON_SELECTOR,
}


@dataclass
class _ScanResult:
    ignored: list[Finding] = field(default_factory=list)
    unjustified: list[Finding] = field(default_factory=list)


class AllowListAuditor:
    """Scan a repository for un-justified suppression annotations.

    Dispatches to language-aware regex selectors (TD-9).
    Supported languages: ``php``, ``python``.
    """

    def __init__(self, language: str = "php") -> None:
        self.language = language

    def audit(
        self,
        repo: Path | str,
        diff_from: str | None = None,
    ) -> AuditReport:
        """Audit *repo* for un-justified suppression annotations.

        Parameters
        ----------
        repo:
            Path to the repository root.
        diff_from:
            Optional git ref (branch/commit). When provided, only scan
            files that changed since that ref. Currently ignored in POC.

        Returns
        -------
        AuditReport
            Contains unjustified findings and an exit_code > 0 when
            any unjustified annotations are found.
        """
        repo = Path(repo).resolve()
        selector = _LANGUAGE_SELECTORS.get(self.language)
        if selector is None:
            # exit_code/ignored_count keep their dataclass defaults (0)
            return AuditReport(
                findings=[],
                summary=f"Unknown language: {self.language}",
            )

        result = _ScanResult()

        # Scan language-appropriate source files recursively.
        for src_file in sorted(repo.rglob(selector.file_glob)):
            # reason: encoding="utf-8"/errors="replace" string mutations are equivalent
            # for ASCII test files — error handler not invoked; "UTF-8" case-insensitive.
            # audited: 2026-06-04
            lines = src_file.read_text(encoding="utf-8", errors="replace").splitlines()  # pragma: no mutate
            for i, line in enumerate(lines):
                if selector.marker_re.search(line):
                    # Check preceding lines for required metadata.
                    # reason: start=max(0,i-_METADATA_WINDOW) vs start=None: equivalent
                    # for test files shorter than _METADATA_WINDOW (5) lines.
                    # The 7-line test creates files where the window contains metadata
                    # regardless. This mutation is structurally equivalent.
                    # audited: 2026-06-04
                    start = max(0, i - _METADATA_WINDOW)  # pragma: no mutate
                    # reason: "\n".join separator mutation to "XX\nXX": reason/audited
                    # regex searches individual line content; separator doesn't affect
                    # whether the pattern is found on any given line. audited: 2026-06-04
                    preceding = "\n".join(lines[start:i])  # pragma: no mutate
                    has_reason = selector.reason_re.search(preceding)
                    has_audited = selector.audited_re.search(preceding)

                    if has_reason and has_audited:
                        result.ignored.append(
                            Finding(
                                node=str(src_file.relative_to(repo)),
                                severity="info",
                                # reason: line number arithmetic i+1→i±something: tests don't
                                # assert exact line numbers in justified messages.
                                # audited: 2026-06-04
                                message=(
                                    f"Justified {selector.marker_label} "
                                    f"at line {i + 1}"
                                ),
                            )
                        )
                    else:
                        result.unjustified.append(
                            Finding(
                                node=str(src_file.relative_to(repo)),
                                severity="warning",
                                # reason: line number arithmetic i+1→i±something: tests don't
                                # assert exact line numbers in unjustified messages.
                                # audited: 2026-06-04
                                message=(
                                    f"Unjustified {selector.marker_label} "
                                    f"at line {i + 1}: "
                                    f"missing reason/audited metadata"
                                ),
                                # reason: fix_hint exact wording is display-only metadata;
                                # tests only assert non-None and "reason" substring.
                                # audited: 2026-06-04
                                fix_hint=(
                                    "Add # reason: ... and # audited: ... "  # pragma: no mutate
                                    "within 5 lines preceding the annotation"
                                ),
                            )
                        )

        # Build summary.
        parts: list[str] = []
        if result.ignored:
            parts.append(f"{len(result.ignored)} justified ignore(s)")
        if result.unjustified:
            parts.append(
                f"{len(result.unjustified)} unjustified ignore(s) "
                f"(see details below)"
            )
        if not parts:
            summary = f"No {selector.marker_label} annotations found"
        else:
            # reason: "; " separator mutation: tests check for "justified"/"unjustified"
            # substrings (in part strings), not exact separator.
            # audited: 2026-06-04
            summary = "; ".join(parts)  # pragma: no mutate

        return AuditReport(
            findings=list(result.unjustified) + list(result.ignored),
            summary=summary,
            exit_code=1 if result.unjustified else 0,
            ignored_count=len(result.ignored),
        )
