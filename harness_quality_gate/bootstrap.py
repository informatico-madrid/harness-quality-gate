"""Tool resolution and source-dir detection helpers for harness-quality-gate.

Public API: :class:`ToolNotAvailable`, :class:`ToolCandidate`,
:func:`find_tool_candidates`, :func:`resolve_tool`, :func:`validate_paths`,
:func:`detect_source_dir`, :func:`suggest_max_children`.

Per ``specs/php-support/decisions.md`` §1, installation is **not** a CLI
subcommand — the LLM agent is the installer and follows
``steps/step-00-install.md``. This module only resolves binaries that are
already on disk (``.venv/bin/``, project vendored dirs, or system
``PATH``); it does not install anything.

When multiple candidates exist for a tool (e.g. ``.venv/bin/ruff`` and
``/usr/local/bin/ruff``), :func:`find_tool_candidates` returns ALL of them
with provenance so the calling agent can present the options to the user
or pick deterministically via :func:`resolve_tool`'s ``preferred`` kwarg.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Subdirectory under ``repo`` where Python tools are usually installed
#: when the project uses a venv. Public so callers can refer to it
#: symbolically instead of hardcoding the string.
VENV_BIN_DIR = ".venv/bin"

#: Provenance values for :class:`ToolCandidate`. Kept as module constants
#: (not Enum) so callers can compare against plain strings without import.
PROVENANCE_OVERRIDE = "override"  # explicit preferred= (config-driven)
PROVENANCE_VENV = ".venv"        # <repo>/.venv/bin/<name>
PROVENANCE_VENDOR = "vendor"     # <repo>/<vendor_bin>/<name>
PROVENANCE_PATH = "PATH"          # shutil.which()


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class ToolNotAvailable(RuntimeError):
    """Raised when a required tool binary cannot be resolved anywhere.

    Attributes:
        tool_name: The binary name that was requested.
        tried: Absolute paths checked (in order) before giving up. The
            list always contains the *would-have-been* candidates, not
            only the valid ones, so the LLM can present the full picture
            to the user (see ``steps/step-00-install.md`` §0.8).
    """

    def __init__(
        self,
        tool_name: str,
        tried: list[Path] | None = None,
    ) -> None:
        self.tool_name = tool_name
        self.tried: list[Path] = tried if tried is not None else []
        msg = f"Tool not available: {tool_name!r}"
        if self.tried:
            paths = ", ".join(str(p) for p in self.tried)
            msg += f" (tried: {paths})"
        super().__init__(msg)


# ---------------------------------------------------------------------------
# Value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolCandidate:
    """A single candidate path for a tool, with provenance.

    A candidate is "valid" by construction: the path is guaranteed to be
    a file and executable. Use :func:`find_tool_candidates` to obtain
    these; do not construct instances manually for unknown paths.

    Attributes:
        path: Absolute, resolved path to the candidate binary.
        provenance: Where this candidate came from. One of the
            ``PROVENANCE_*`` module constants.
    """

    path: Path
    provenance: str


# ---------------------------------------------------------------------------
# Candidate detection
# ---------------------------------------------------------------------------


def _is_executable(path: Path) -> bool:
    """Return True if *path* is a file and has the executable bit set.

    Centralised so :func:`find_tool_candidates` and the per-source
    pre-checks share the exact same predicate (DRY).
    """
    return path.is_file() and os.access(str(path), os.X_OK)


def find_tool_candidates(
    name: str,
    repo: Path,
    *,
    preferred: str | Path | None = None,
    vendor_bin: str | None = None,
) -> list[ToolCandidate]:
    """Return ALL valid candidate paths for *name*, ordered by precedence.

    Precedence (first match wins in :func:`resolve_tool`):

    1. ``preferred`` — explicit override (config-driven). Resolved against
       *repo* when relative.
    2. ``.venv/bin/<name>`` — project virtualenv.
    3. ``<vendor_bin>/<name>`` — when *vendor_bin* is given (e.g. PHP
       ``vendor/bin`` or any project-local vendored layout).
    4. ``shutil.which(name)`` — system PATH.

    Candidates are deduplicated by resolved path: if the same file
    appears in two sources (e.g. a venv symlink pointing to a PATH
    binary), only the highest-precedence copy is returned. Candidates
    that do not exist or are not executable are filtered out — the
    return value never contains invalid paths.

    Args:
        name: Binary name (e.g. ``"ruff"``, ``"pyright"``).
        repo: Repository root path.
        preferred: Explicit override path (absolute or relative to
            *repo*). When given and valid, it appears first in the
            result. When given and INVALID, it is silently dropped —
            this matches the existing venv-fallback behaviour (a
            non-executable venv entry falls through to PATH).
        vendor_bin: Optional relative directory inside *repo* to check
            after ``.venv``. Common value: ``"vendor/bin"`` for PHP
            composer dependencies.

    Returns:
        Ordered list of valid :class:`ToolCandidate` (may be empty).
    """
    candidates: list[ToolCandidate] = []
    seen_resolved: set[Path] = set()

    def _add(candidate_path: Path, provenance: str) -> None:
        """Append a candidate iff it is valid and not already seen."""
        if not _is_executable(candidate_path):
            return
        resolved = candidate_path.resolve()
        if resolved in seen_resolved:
            return
        seen_resolved.add(resolved)
        candidates.append(ToolCandidate(path=resolved, provenance=provenance))

    # 1. preferred (config override; resolved against repo if relative)
    if preferred is not None:
        preferred_path = Path(preferred)
        if not preferred_path.is_absolute():
            preferred_path = repo / preferred_path
        _add(preferred_path, PROVENANCE_OVERRIDE)

    # 2. project venv
    _add(repo / VENV_BIN_DIR / name, PROVENANCE_VENV)

    # 3. project vendored layout
    if vendor_bin:
        _add(repo / vendor_bin / name, PROVENANCE_VENDOR)

    # 4. system PATH
    system_bin = shutil.which(name)
    if system_bin is not None:
        _add(Path(system_bin), PROVENANCE_PATH)

    return candidates


# ---------------------------------------------------------------------------
# Single-path resolution
# ---------------------------------------------------------------------------


def _build_tried_list(
    name: str,
    repo: Path,
    preferred: str | Path | None,
    vendor_bin: str | None,
) -> list[Path]:
    """Build the ordered list of paths that *would have been* candidates.

    Used only for the error message in :func:`resolve_tool` when no
    valid candidate exists. Includes paths even when they do not exist
    on disk, so the LLM can show the user exactly what was checked.
    """
    tried: list[Path] = []
    if preferred is not None:
        preferred_path = Path(preferred)
        if not preferred_path.is_absolute():
            preferred_path = repo / preferred_path
        tried.append(preferred_path)
    tried.append(repo / VENV_BIN_DIR / name)
    if vendor_bin:
        tried.append(repo / vendor_bin / name)
    system_bin = shutil.which(name)
    if system_bin is not None:
        tried.append(Path(system_bin))
    return tried


def resolve_tool(
    name: str,
    repo: Path,
    *,
    preferred: str | Path | None = None,
    vendor_bin: str | None = None,
) -> Path:
    """Resolve *name* to a single absolute executable path.

    Thin wrapper over :func:`find_tool_candidates` that returns the
    highest-precedence candidate. The full candidate list (for LLM
    disambiguation) is available via :func:`find_tool_candidates`.

    Args:
        name: Binary name (e.g. ``"bandit"``, ``"ruff"``, ``"pyright"``).
        repo: Repository root path.
        preferred: Optional override (config-driven or LLM-supplied).
        vendor_bin: Optional relative dir to check (e.g. PHP vendor/bin).

    Returns:
        Absolute :class:`Path` to the resolved binary.

    Raises:
        ToolNotAvailable: When no valid candidate exists. The exception
            carries the full list of paths that were checked so the
            LLM can present the user with a complete picture (see
            ``steps/step-00-install.md`` §0.8).
    """
    candidates = find_tool_candidates(
        name,
        repo,
        preferred=preferred,
        vendor_bin=vendor_bin,
    )
    if candidates:
        return candidates[0].path
    raise ToolNotAvailable(name, tried=_build_tried_list(name, repo, preferred, vendor_bin))


def validate_paths(paths: list[str]) -> None:
    """Validate ``--paths`` arguments for security.

    Rejects:
    - Absolute paths (e.g. ``/etc/passwd``)
    - Paths containing ``..`` (directory traversal)
    - Flag-like strings (e.g. ``--config``, ``-x``)

    Args:
        paths: List of path strings from the CLI ``--paths`` argument.

    Raises:
        ValueError: If any path is invalid.
    """
    for p in paths:
        if "\x00" in p:
            raise ValueError(
                f"Invalid --paths argument {p!r}: null bytes are not allowed"
            )
        if p.startswith("/"):
            raise ValueError(
                f"Invalid --paths argument {p!r}: absolute paths are not allowed"
            )
        if ".." in p.split("/"):
            raise ValueError(
                f"Invalid --paths argument {p!r}: directory traversal is not allowed"
            )
        if p.startswith("-"):
            raise ValueError(
                f"Invalid --paths argument {p!r}: flag-like strings are not allowed"
            )


def detect_source_dir(repo: Path) -> str:
    """Detect the production source directory for a repo.

    Detection flow:

    1. Check ``_quality-gate/quality-gate.yaml`` for ``source_dir``
    2. Check if ``src/`` exists → return ``"src"``
    3. List top-level dirs with ``__init__.py`` (Python packages)
    4. If still ambiguous → return ``""`` (caller must ask user)

    Returns:
        Source directory name relative to repo root
        (e.g. ``"src"``, ``"my_pkg"``, or ``""``).
    """
    # Step 1: Check project-level config
    project_config = repo / "_quality-gate" / "quality-gate.yaml"
    if project_config.is_file():
        try:
            import yaml

            raw = yaml.safe_load(project_config.read_bytes()) or {}
            if isinstance(raw, dict) and "source_dir" in raw:
                source_dir_str = str(raw["source_dir"])
                source_candidate = repo / source_dir_str
                # Safety: reject source_dir that escapes the repo root.
                try:
                    resolved = source_candidate.resolve()
                    repo_resolved = repo.resolve()
                    if (
                        not str(resolved).startswith(str(repo_resolved) + "/")
                        and resolved != repo_resolved
                    ):
                        logger.warning(
                            "YAML source_dir %r escapes repo root %s — ignored",
                            source_dir_str,
                            repo,
                        )
                    elif source_candidate.is_dir():
                        return source_dir_str
                    else:
                        logger.warning(
                            "YAML source_dir %r does not exist as directory in %s",
                            source_dir_str,
                            source_candidate,
                        )
                except OSError:
                    logger.warning(
                        "YAML source_dir %r could not be resolved — ignored",
                        source_dir_str,
                    )
        except Exception:
            logger.warning(
                "Failed to read project config %s", project_config
            )

    # Step 2: Default src/ check
    if (repo / "src").is_dir():
        return "src"

    # Step 3: Try package_dirs from adapters.base
    try:
        from .adapters.base import package_dirs

        pkgs = package_dirs(repo)
        if len(pkgs) == 1:
            return pkgs[0]
        if pkgs:
            # Multiple packages — ambiguous, caller should ask user
            return ""
    except Exception:
        pass

    # Step 4: Can't determine
    return ""


def suggest_max_children() -> int:
    """Suggest a ``max-children`` value for mutmut based on CPU count.

    Default: ``cpu_count // 2`` (minimum 1).

    Returns:
        An integer suggestion for the ``--max-children`` flag.

    Note:
        This function does **not** log a warning if the value exceeds
        ``cpu_count`` — that is the caller's responsibility (PythonAdapter
        or CLI).
    """
    cpus = os.cpu_count()
    if not cpus:
        # CPU count unknown → conservative single child.
        return 1
    return max(1, cpus // 2)
