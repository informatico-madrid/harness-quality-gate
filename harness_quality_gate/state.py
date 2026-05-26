"""State helpers for harness-quality-gate.

Namespaced scratch directories per adapter (NFR-6, TD-15).
"""

from __future__ import annotations

from pathlib import Path


def scratch_dir(repo: Path, language: str, tool: str) -> Path:
    """Return (and create on demand) the namespaced scratch directory for a tool.

    Layout::

        <repo>/_quality-gate/work/<language>/<tool>/
    """
    base = repo / "_quality-gate" / "work" / language / tool
    base.mkdir(parents=True, exist_ok=True)
    return base
