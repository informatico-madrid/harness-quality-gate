"""Self-bootstrap module for harness-quality-gate.

Ensures venv, installs/verifies tools, resolves binary paths,
detects source directories, and suggests CPU concurrency settings.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class ToolNotAvailable(RuntimeError):
    """Raised when a required tool binary cannot be resolved anywhere."""

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        super().__init__(f"Tool not available: {tool_name!r}")


# ---------------------------------------------------------------------------
# Tool manifest
# ---------------------------------------------------------------------------

# Tool manifest: name -> pip package (for ``uv pip install``).
PYTHON_TOOLS: dict[str, str] = {
    "ruff": "ruff",
    "bandit": "bandit",
    "vulture": "vulture",
    "deptry": "deptry",
    "mutmut": "mutmut",
    "pytest": "pytest",
}

# Pyright is npm-only; not installed via pip.
# ``pyright`` is resolved via system PATH (npm global).


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_tool(name: str, repo: Path) -> Path:
    """Resolve a tool binary: prefer ``.venv/bin/``, fallback to system PATH.

    Args:
        name: Binary name (e.g. ``"bandit"``, ``"ruff"``, ``"pyright"``).
        repo: Repository root path (must contain or get a ``.venv/``).

    Returns:
        Absolute :class:`Path` to the binary.

    Raises:
        ToolNotAvailable: If tool is not in ``.venv/`` or system PATH.
    """
    # 1. Check .venv/bin/<name> first
    venv_bin = repo / ".venv" / "bin" / name
    if venv_bin.is_file() and os.access(str(venv_bin), os.X_OK):
        return venv_bin.resolve()

    # 2. Fallback to system PATH
    system_bin = shutil.which(name)
    if system_bin is not None:
        return Path(system_bin).resolve()

    raise ToolNotAvailable(name)


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


def ensure_venv(repo: Path) -> Path:
    """Ensure a ``.venv`` exists in repo. Create one if missing.

    Args:
        repo: Repository root path.

    Returns:
        Path to the venv directory (``repo / ".venv"``).
    """
    venv_dir = repo / ".venv"
    if venv_dir.is_dir():
        return venv_dir

    logger.info("Creating .venv in %s", repo)
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True,
            capture_output=True,
            timeout=60,
        )
    except PermissionError as exc:
        logger.error("Permission denied creating .venv at %s: %s", venv_dir, exc)
        raise RuntimeError(
            f"Cannot create venv at {venv_dir}: check that the repository "
            f"directory is writable"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        logger.warning("venv creation timed out after 60s at %s: %s", venv_dir, exc)
    return venv_dir


def install_tools(repo: Path) -> dict[str, str]:
    """Install all Python quality-gate tools into ``.venv`` via ``uv pip install``.

    Args:
        repo: Repository root path.

    Returns:
        Dict of ``{tool_name: "installed" | "skipped" | "failed: <reason>"}``.
    """
    ensure_venv(repo)
    venv_python = repo / ".venv" / "bin" / "python"
    results: dict[str, str] = {}

    # Find uv or fall back to pip
    uv_bin = shutil.which("uv")
    pip_cmd = [str(venv_python), "-m", "pip"] if not uv_bin else [uv_bin, "pip"]

    for tool_name, package in PYTHON_TOOLS.items():
        try:
            cmd = [*pip_cmd, "install", package]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                results[tool_name] = "installed"
            else:
                logger.error(
                    "Failed to install %s: %s", tool_name, result.stderr.strip()[:200]
                )
                results[tool_name] = f"failed: {result.stderr.strip()[:200]}"
        except Exception as exc:
            results[tool_name] = f"failed: {exc}"

    installed_count = sum(1 for v in results.values() if v == "installed")
    failed_count = sum(1 for v in results.values() if v.startswith("failed:"))
    logger.info(
        "install_tools complete: %d/%d tools installed, %d failed",
        installed_count,
        len(results),
        failed_count,
    )
    return results


def verify_tools(repo: Path) -> list[ToolCheckResult]:
    """Verify all required tools are available and collect version info.

    Args:
        repo: Repository root path.

    Returns:
        List of :class:`ToolCheckResult` for each tool.
    """
    checks: list[ToolCheckResult] = []
    all_tools = list(PYTHON_TOOLS.keys()) + ["pyright"]

    for name in all_tools:
        try:
            binary = resolve_tool(name, repo)
            version = _get_version(binary)
            checks.append(
                ToolCheckResult(
                    name=name,
                    available=True,
                    version=version,
                    path=str(binary),
                )
            )
        except ToolNotAvailable:
            checks.append(
                ToolCheckResult(
                    name=name,
                    available=False,
                    version=None,
                    path=None,
                )
            )

    available = sum(1 for c in checks if c.available)
    unavailable = sum(1 for c in checks if not c.available)
    logger.info(
        "Verified %d tools: %d available, %d unavailable",
        len(checks),
        available,
        unavailable,
    )
    return checks


def _get_version(binary: Path) -> str | None:
    """Get tool version by running ``binary --version``.

    Args:
        binary: Absolute path to the tool binary.

    Returns:
        First line of version output, or ``None`` on failure.
    """
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = (result.stdout or result.stderr).strip()
        return output.split("\n")[0] if output else None
    except Exception:
        return None


def write_manifest(repo: Path) -> Path:
    """Write ``.venv/hqg-tools-manifest.json`` with tool versions.

    Args:
        repo: Repository root path.

    Returns:
        Path to the written manifest file.
    """
    ensure_venv(repo)
    checks = verify_tools(repo)
    manifest = [
        {
            "name": c.name,
            "version": c.version,
            "path": c.path,
            "available": c.available,
        }
        for c in checks
    ]
    manifest_path = repo / ".venv" / "hqg-tools-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return manifest_path


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ToolCheckResult:
    """Result of checking a single tool's availability.

    Attributes:
        name: Tool binary name (e.g. ``"ruff"``).
        available: Whether the tool binary was found on disk.
        version: First line of ``tool --version`` output, or ``None``.
        path: Absolute path to the resolved binary, or ``None``.
    """

    name: str
    available: bool
    version: str | None
    path: str | None
