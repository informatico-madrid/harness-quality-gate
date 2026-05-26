"""Allow-list audit engine for finding suppression.

Provides ``audit()`` which filters a list of ``Finding`` objects against
an allow-list of ``rule_id`` values.

Design reference: TD-10, allow_list_auditor component.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .models import Finding


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
