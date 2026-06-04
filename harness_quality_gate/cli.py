"""CLI entry point for harness-quality-gate.

Two subcommands:

  all           Run the full quality gate against a repository.
  audit-ignores Scan for unjustified suppression annotations.

Exit-code contract (NFR-15):

  0 = PASS
  1 = FAIL
  2 = UNSUPPORTED
  5 = INTERNAL_ERROR
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters.php.php_adapter import PhpAdapter
from .adapters.python.python_adapter import PythonAdapter
from .allow_list_auditor import AllowListAuditor, AuditReport
from .checkpoint import build as build_checkpoint
from .checkpoint import write as write_checkpoint
from .exit_codes import FAIL, INTERNAL_ERROR, PASS, UNSUPPORTED
from .models import LayerResult

logger = logging.getLogger("harness_quality_gate.cli")


# ---------------------------------------------------------------------------
# Language detection (5 lines — no 419-LOC detector module needed)
# ---------------------------------------------------------------------------

def _detect_language(repo: Path) -> str:
    """Return 'php' if composer.json is present, else 'python'."""
    if (repo / "composer.json").exists():
        return "php"
    return "python"


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


def _exit_with(code: int, data: Any, *, json_mode: bool = False, quiet: bool = False) -> int:
    if not quiet:
        payload = _asdict(data) if not isinstance(data, str) else data
        if json_mode or isinstance(payload, dict):
            print(json.dumps(payload, indent=2, default=str))
        else:
            print(payload)
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
            json_mode=args.json,
            quiet=args.quiet,
        )

    language = _detect_language(repo)
    work_dir = repo / "_quality-gate" / "work"

    try:
        adapter = PhpAdapter() if language == "php" else PythonAdapter()
    except Exception as exc:  # noqa: BLE001
        return _exit_with(
            INTERNAL_ERROR,
            {"error": f"failed to load adapter for {language!r}: {exc}", "exit_code": INTERNAL_ERROR},
            json_mode=args.json,
            quiet=args.quiet,
        )

    env = {**os.environ, "work_dir": str(work_dir)}
    layer_results: list[LayerResult] = []
    try:
        for run_layer in (adapter.run_l3a, adapter.run_l1, adapter.run_l2, adapter.run_l3b, adapter.run_l4):
            layer_results.append(run_layer(repo, env))
    except Exception as exc:  # noqa: BLE001
        return _exit_with(
            INTERNAL_ERROR,
            {"error": str(exc), "exit_code": INTERNAL_ERROR},
            json_mode=args.json,
            quiet=args.quiet,
        )

    all_passed = all(lr.passed for lr in layer_results)
    code = PASS if all_passed else FAIL

    layer_dicts = [
        {
            "layer": lr.layer,
            "language": lr.language,
            "passed": lr.passed,
            "findings": _asdict(lr.findings),
            "duration_sec": lr.duration_sec,
            **({"tool_specific": lr.tool_specific} if lr.tool_specific else {}),
        }
        for lr in layer_results
    ]
    import platform
    runtime = {
        "python_version": platform.python_version(),
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

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = work_dir / f"quality-gate-{ts}.json"
    try:
        write_checkpoint(output_path, checkpoint_dict)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to write timestamped checkpoint", exc_info=True)
    latest_path = repo / "_quality-gate" / "quality-gate-latest.json"
    try:
        latest_path.parent.mkdir(parents=True, exist_ok=True)
        latest_path.write_text(json.dumps(checkpoint_dict, indent=2, default=str), encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.warning("Failed to write latest checkpoint", exc_info=True)

    return _exit_with(code, checkpoint_dict, json_mode=args.json, quiet=args.quiet)


# ---------------------------------------------------------------------------
# _cmd_audit_ignores
# ---------------------------------------------------------------------------

def _cmd_audit_ignores(args: argparse.Namespace) -> int:
    """Scan *args.repo* for unjustified suppression annotations.

    Audits both PHP ``@infection-ignore-all`` and Python ``# pragma: no mutate``
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
            json_mode=args.json,
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
    return _exit_with(code, merged, json_mode=args.json, quiet=args.quiet)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("repo", nargs="?", default=".", help="Path to repository root")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    parser.add_argument("--quiet", action="store_true", help="Suppress output")


def main(argv: list[str] | None = None) -> int:  # pragma: no mutate
    if argv is None:
        argv = sys.argv[1:]
    parser = argparse.ArgumentParser(
        prog="harness_quality_gate",
        description="Polyglot quality gate for Python and PHP repositories.",
    )
    sub = parser.add_subparsers(dest="command")

    all_p = sub.add_parser("all", help="Run all quality-gate layers")
    _add_common_flags(all_p)

    audit_p = sub.add_parser("audit-ignores", help="Audit suppression annotations")
    _add_common_flags(audit_p)
    audit_p.add_argument("--diff-from", type=str, default=None, help="Git ref to diff against")

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
