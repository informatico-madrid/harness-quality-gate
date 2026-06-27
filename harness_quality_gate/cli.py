"""CLI entry point for harness-quality-gate.

Two subcommands:

  all           Run the full quality gate against a repository.
  audit-ignores Scan for unjustified suppression annotations.

Exit-code contract (NFR-15):

  0 = PASS
  1 = FAIL
  2 = UNSUPPORTED
  3 = INFRA_INCOMPLETE
  4 = CONFIG_INVALID
  5 = INTERNAL_ERROR
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters.base import BaseAdapter
from .adapters.php.php_adapter import PhpAdapter
from .adapters.python.python_adapter import PythonAdapter
from .allow_list_auditor import AllowListAuditor, AuditReport
from .checkpoint import build as build_checkpoint
from .checkpoint import write as write_checkpoint
from .config import ConfigInvalid
from .config import load_with_defaults
from .exit_codes import (
    CONFIG_INVALID,
    FAIL,
    INFRA_INCOMPLETE,
    INTERNAL_ERROR,
    PASS,
    UNSUPPORTED,
)
from .messages_es import t
from .models import LayerResult

logger = logging.getLogger("harness_quality_gate.cli")


# ---------------------------------------------------------------------------
# venv self-diagnostic (FR-26/27 — Python)
# ---------------------------------------------------------------------------


def _check_venv(repo: Path, language: str) -> list[str]:
    """Return warnings if the current interpreter is not inside a project venv.

    The Python adapters use ``sys.executable`` (which is venv-aware). When the
    CLI runs from the system interpreter but the project uses a venv, key tools
    (pytest, ruff, pyright, radon) will be missing and layers L1/L3A will fail.

    Returns a list of warning messages (empty = all good).
    """
    warnings: list[str] = []
    if language != "python":
        return warnings

    # Detect if a .venv exists in the repo
    venv_py = repo / ".venv" / "bin" / "python"
    has_venv = venv_py.exists()

    if has_venv:
        # Check if sys.executable IS the venv python
        real_venv = os.path.realpath(venv_py)
        real_current = os.path.realpath(sys.executable)
        if real_current != real_venv:
            warnings.append(
                f"Quality gate running from {sys.executable} "
                f"(outside venv). Project has .venv at {venv_py}. "
                f"Run ``source .venv/bin/activate`` and re-run, or use "
                f"``.venv/bin/python -m harness_quality_gate all .``."
            )
    return warnings


# ---------------------------------------------------------------------------
# Language detection (5 lines — no 419-LOC detector module needed)
# ---------------------------------------------------------------------------


def _detect_language(repo: Path) -> str:
    """Return 'php' if composer.json is present, else 'python'."""
    if (repo / "composer.json").exists():
        return "php"
    return "python"


# ---------------------------------------------------------------------------
# Infra-check (FR-26/27) — inline, no doctor module (deliberate: 69b05df)
# ---------------------------------------------------------------------------

#: Critical PHP tools resolved on PATH or in the target repo's vendor/bin.
_PHP_CRITICAL_TOOLS = ("phpunit", "phpstan", "infection")


def _missing_php_tools(repo: Path) -> list[str]:
    """Return the critical PHP tools that cannot be resolved for *repo*.

    Checks the ``php`` runtime on PATH, then each critical tool on PATH or
    in the repo's composer bin dirs (``vendor/bin`` default, ``bin`` for
    projects with ``config.bin-dir: bin``). Empty list = infra complete.
    """
    missing: list[str] = []
    if shutil.which("php") is None:
        missing.append("php")
    for tool in _PHP_CRITICAL_TOOLS:
        on_path = shutil.which(tool) is not None
        in_repo = any(
            (repo / bin_dir / tool).exists() for bin_dir in ("vendor/bin", "bin")
        )
        if not on_path and not in_repo:
            missing.append(tool)
    return missing


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _asdict(obj: Any) -> Any:
    """Convert a frozen dataclass or plain object to a JSON-serialisable value."""
    import dataclasses

    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)  # type: ignore[arg-type]
    if isinstance(obj, dict):
        return {k: _asdict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_asdict(v) for v in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)


def _exit_with(code: int, data: Any, *, quiet: bool) -> int:
    """Print *data* as JSON (unless *quiet*) and return *code*.

    Every production caller passes a dict or dataclass payload, so output is
    always JSON; the ``--json`` CLI flag is therefore accepted but redundant.
    ``_asdict`` already coerces non-serialisable values to ``str``, so
    ``json.dumps`` needs no ``default=`` handler.
    """
    if not quiet:
        print(json.dumps(_asdict(data), indent=2))
    return code


# ---------------------------------------------------------------------------
# _cmd_all
# ---------------------------------------------------------------------------


def _cmd_all(args: argparse.Namespace) -> int:
    """Run the full quality gate against *args.repo*."""
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        return _exit_with(
            UNSUPPORTED,
            {"error": f"repository not found: {repo}", "exit_code": UNSUPPORTED},
            quiet=args.quiet,
        )

    language = _detect_language(repo)

    # --paths with no values is ambiguous: reject it (security fix #5)
    if args.paths is not None and len(args.paths) == 0:
        return _exit_with(
            CONFIG_INVALID,
            {
                "error": "--paths requires at least one path argument; "
                "use without --paths for a full run",
                "exit_code": CONFIG_INVALID,
            },
            quiet=args.quiet,
        )

    # Validate --paths arguments for security. (An empty list already
    # returned CONFIG_INVALID above, so a non-None paths here is non-empty.)
    if args.paths is not None:
        try:
            from .bootstrap import validate_paths

            validate_paths(args.paths)
        except ValueError as exc:
            return _exit_with(
                CONFIG_INVALID,
                {"error": str(exc), "exit_code": CONFIG_INVALID},
                quiet=args.quiet,
            )

    # Self-diagnostic: warn if running outside venv for a Python project
    _diag_warnings = _check_venv(repo, language)
    for _w in _diag_warnings:
        logger.warning(_w)

    # Config v1 rejection (FR-34): a config file with a deprecated schema is
    # a hard error; a missing config file simply means defaults.
    # Use load_with_defaults() for bundled defaults + project overrides.
    try:
        load_with_defaults(repo)
    except ConfigInvalid as exc:
        return _exit_with(
            CONFIG_INVALID,
            {"error": str(exc), "exit_code": CONFIG_INVALID},
            quiet=args.quiet,
        )
    except FileNotFoundError:
        pass

    # Infra-check (FR-26/27): PHP repos need the critical toolchain up front.
    # Python keeps its original graceful-degradation behaviour (skip + warn).
    if language == "php":
        missing_tools = _missing_php_tools(repo)
        if missing_tools:
            return _exit_with(
                INFRA_INCOMPLETE,
                {
                    "error": t("err.infra.missing", tools=", ".join(missing_tools)),
                    "missing_tools": missing_tools,
                    "exit_code": INFRA_INCOMPLETE,
                },
                quiet=args.quiet,
            )

    # reason: "_quality-gate" dir name is a filesystem convention — test asserts the
    # directory is in the path via PurePath.parts (fixed 2026-06-04). audited: 2026-06-04
    work_dir = repo / "_quality-gate" / "work"

    try:
        if language == "php":
            adapter: BaseAdapter = PhpAdapter()
        else:
            adapter = PythonAdapter(paths=args.paths)
    except Exception as exc:  # noqa: BLE001
        return _exit_with(
            INTERNAL_ERROR,
            {
                "error": f"failed to load adapter for {language!r}: {exc}",
                "exit_code": INTERNAL_ERROR,
            },
            quiet=args.quiet,
        )

    env = {**os.environ, "work_dir": str(work_dir)}
    layer_results: list[LayerResult] = []

    # When --paths is provided for Python repos, run only Tier 1 (L3A + L1)
    # for fast agent feedback. L2, L3B, L4 are skipped.
    # --paths is Python-only; PHP repos ignore it and always run all 5 layers.
    partial_run = args.paths is not None and getattr(adapter, "paths", None) is not None
    # Names for the layers a partial run quick-passes (loop indices 2..4 below);
    # L3A/L1 (indices 0,1) always run for real, so they need no synthesised name.
    skipped_layer_names = {2: "L2", 3: "L3B", 4: "L4"}

    try:
        for idx, run_layer in enumerate(
            (
                adapter.run_l3a,
                adapter.run_l1,
                adapter.run_l2,
                adapter.run_l3b,
                adapter.run_l4,
            )
        ):
            if partial_run and idx >= 2:
                # Quick-pass: record layer as passed for partial runs.
                layer_results.append(
                    LayerResult(
                        layer=skipped_layer_names[idx],
                        language=language,
                        passed=True,
                        findings=[],
                        duration_sec=0.0,
                    )
                )
            else:
                layer_results.append(run_layer(repo, env))
    except Exception as exc:  # noqa: BLE001
        return _exit_with(
            INTERNAL_ERROR,
            {"error": str(exc), "exit_code": INTERNAL_ERROR},
            quiet=args.quiet,
        )

    all_passed = all(lr.passed for lr in layer_results)
    # Check for infra_error verdict: a tool crash (e.g., mutmut with no
    # Python source) should exit 3, not 1 (NFR-8a: crash != quality_failure).
    has_infra_error = any(
        lr.tool_specific is not None
        and lr.tool_specific.get("verdict") == "infra_error"
        for lr in layer_results
    )
    code = PASS if all_passed else (INFRA_INCOMPLETE if has_infra_error else FAIL)

    layer_dicts = []
    for lr in layer_results:
        ld: dict[str, Any] = {
            "layer": lr.layer,
            "language": lr.language,
            "passed": lr.passed,
            "findings": _asdict(lr.findings),
            "duration_sec": lr.duration_sec,
        }
        if lr.tool_specific is not None:
            ld["tool_specific"] = _asdict(lr.tool_specific)
        layer_dicts.append(ld)
    import platform

    runtime: dict[str, Any] = {
        "python_version": platform.python_version(),
        "venv_path": os.path.realpath(sys.executable),
        "venv_activated": _check_venv(repo, language),
        "concurrency": "sequential",
        "ci": bool(os.environ.get("CI")),
    }
    detection_info: dict[str, Any] = {
        "repo_path": str(repo),
        "language": language,
        "framework": None,
        "confidence": 1.0,
        "languages_detected": [language],
        "file_counts": {},
    }
    checkpoint_dict = build_checkpoint(
        layer_results=layer_dicts,
        runtime=runtime,
        detection=detection_info,
    )
    checkpoint_dict["PASS"] = all_passed

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = work_dir / f"quality-gate-{ts}.json"
    try:
        write_checkpoint(output_path, checkpoint_dict)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to write timestamped checkpoint", exc_info=True)
    latest_path = repo / "_quality-gate" / "quality-gate-latest.json"
    try:
        # repo is a verified directory, so the single _quality-gate level needs
        # no parents=True; exist_ok absorbs the dir already made for work/.
        latest_path.parent.mkdir(exist_ok=True)
        # write_bytes + str.encode() (UTF-8 by default) avoids an encoding= kwarg
        # whose mutations are equivalent for this ASCII/UTF-8 JSON. default=str is
        # unneeded: checkpoint_dict is already JSON-serialisable (write_checkpoint
        # above serialises it without one).
        latest_path.write_bytes(json.dumps(checkpoint_dict, indent=2).encode())
    except Exception:  # noqa: BLE001
        logger.warning("Failed to write latest checkpoint", exc_info=True)

    return _exit_with(code, checkpoint_dict, quiet=args.quiet)


# ---------------------------------------------------------------------------
# _cmd_audit_ignores
# ---------------------------------------------------------------------------


def _cmd_audit_ignores(args: argparse.Namespace) -> int:
    """Scan *args.repo* for unjustified suppression annotations.

    Audits both PHP ``@infection-ignore-all`` and Python pragma annotations
    so the self-gate cannot hide unjustified Python pragmas behind a PHP-only
    default.
    """
    repo = Path(args.repo).resolve()
    diff_from = getattr(args, "diff_from", None)
    try:
        reports = [
            AllowListAuditor(language=language).audit(repo, diff_from)
            for language in ("php", "python")
        ]
    except Exception as exc:  # noqa: BLE001
        return _exit_with(
            INTERNAL_ERROR,
            {"error": str(exc), "exit_code": INTERNAL_ERROR},
            quiet=args.quiet,
        )
    has_unjustified = any(report.exit_code != 0 for report in reports)
    merged = AuditReport(
        findings=[finding for report in reports for finding in report.findings],
        summary=" | ".join(report.summary for report in reports),
        exit_code=FAIL if has_unjustified else PASS,
        ignored_count=sum(report.ignored_count for report in reports),
    )
    code = FAIL if has_unjustified else PASS
    return _exit_with(code, merged, quiet=args.quiet)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("repo", nargs="?", default=".", help="Path to repository root")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    parser.add_argument("--quiet", action="store_true", help="Suppress output")


def _build_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser (separated for testability)."""
    parser = argparse.ArgumentParser(
        prog="harness_quality_gate",
        description="Polyglot quality gate for Python and PHP repositories.",
    )
    sub = parser.add_subparsers(dest="command")

    all_p = sub.add_parser("all", help="Run all quality-gate layers")
    _add_common_flags(all_p)
    all_p.add_argument(
        "--paths",
        nargs="*",
        # default=None is argparse's own default for nargs="*" — omitted on
        # purpose so it cannot drift (matches --diff-from below).
        help="Subset of files/dirs to scan — runs only Tier 1 (L3A + L1)",
    )

    audit_p = sub.add_parser("audit-ignores", help="Audit suppression annotations")
    _add_common_flags(audit_p)
    # type=str and default=None are argparse's own defaults — omitted on purpose
    # so they cannot drift (dead parameters).
    audit_p.add_argument("--diff-from", help="Git ref to diff against")
    return parser


def main(argv: list[str] | None = None) -> int:
    # argv=None falls through to argparse, which reads sys.argv[1:] itself.
    parser = _build_parser()

    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return UNSUPPORTED
    if args.command is None:
        parser.print_help()
        return UNSUPPORTED

    dispatch = {
        "all": _cmd_all,
        "audit-ignores": _cmd_audit_ignores,
    }
    return dispatch[args.command](args)
