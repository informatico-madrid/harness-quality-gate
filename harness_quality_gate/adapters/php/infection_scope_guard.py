"""Infection scope guard — HRM-E5 binding enforcer (Story 5.3).

Reads ``<target_dir>/infection.json5`` and asserts that
``source.directories`` is exactly ``["src"]`` — anything wider
(including ``"features"``, ``"tests"``, ``"fixtures"``, or globs)
is a violation. The Tier-A oracle (Behat ``features/``) must
never be mutation-targeted by Infection.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Directories that contain Tier-A oracle assets — must never be mutation-targeted.
# Set literal values must not be mutated — each string is an oracle dir
# name whose presence/absence is the test contract.
_ORACLE_DIRS = frozenset({"features", "tests", "fixtures"})


# ---------------------------------------------------------------------------
# JSON5 loader (fallback when json5 package is absent)
# ---------------------------------------------------------------------------


def _load_infection_config(target_dir: Path) -> dict:
    """Load and parse ``infection.json5`` from *target_dir*.

    Uses a lightweight JSON5 parser: strips single-line comments and
    trailing commas before handing off to :func:`json.loads`. Falls back
    to the ``json5`` library if available.

    Args:
        target_dir: Root of the PHP project.

    Returns:
        Parsed config dict.

    Raises:
        FileNotFoundError: When ``infection.json5`` does not exist.
        json.JSONDecodeError: When the file is not valid JSON/JSON5.
    """
    config_path = target_dir / "infection.json5"
    if not config_path.is_file():
        raise FileNotFoundError(
            f"infection.json5 not found in {target_dir}. "
            "The scope guard cannot validate missing configuration."
        )
    # reason: codecs.lookup normalizes encoding names to lowercase (Type F);
    # "utf-8" and "UTF-8" are indistinguishable through codecs.lookup.
    # audited: 2026-06-30
    text = config_path.read_text(encoding="utf-8")  # pragma: no mutate
    try:
        import json5 as _json5  # noqa: F401  # type: ignore[import-not-found]

        return _json5.loads(text)
    except ImportError:
        stripped = re.sub(r"(?m)^\s*//[^\n]*", "", text)
        stripped = re.sub(r",(\s*[}\]])", r"\1", stripped)
        return json.loads(stripped)


def check_infection_scope(target_dir: Path) -> None:
    """Validate Infection path-scope against the Tier-A oracle boundary.

    Enforces that ``source.directories`` is exactly ``["src"]``.  Any
    deviation — extra directories, wildcards, parent references, or
    oracle directories — raises immediately.

    When ``source.excludes`` is absent but directories is exact ``["src"]``,
    a *warning* is logged (not an error).

    Args:
        target_dir: Root of the PHP project containing ``infection.json5``.

    Raises:
        RuntimeError: If ``source.directories`` is not exactly ``["src"]``
            or includes oracle directories (features/, tests/, fixtures/).
        FileNotFoundError: If ``infection.json5`` is missing.
    """
    config = _load_infection_config(target_dir)
    source = config.get("source") or {}
    directories = list(source.get("directories", []))

    # ── Exact equality check — only ["src"] is allowed ──────────────────
    if directories != ["src"]:
        # Find the most specific offender for the error message.
        offending = [
            d for d in directories if d in _ORACLE_DIRS or d in (".", "..", "*", "**")
        ]
        if offending:
            raise RuntimeError(
                f"infection: path-scope includes oracle directory "
                f"'{offending[0]}' — Tier-A oracle must never be "
                f"mutation-targeted"
            )
        raise RuntimeError(
            f"infection: source.directories must be exactly ['src'], "
            f"got {directories!r}"
        )

    # ── Advisory: missing or incomplete excludes (warning, not error) ───
    raw_excludes = source.get("excludes")
    if raw_excludes is None:
        logger.warning(
            "infection: source.excludes is not configured — "
            "consider adding 'features' to reduce false-positive "
            "mutation targets"
        )
    else:
        excludes_list = list(raw_excludes)
        if "features" not in excludes_list:
            logger.warning(
                "infection: source.excludes does not include 'features' — "
                "the Tier-A oracle Behat features may still be mutation-targeted"
            )
