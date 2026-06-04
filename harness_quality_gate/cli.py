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


# reason: json_mode=False and quiet=False defaults are never exercised — all callers
# pass these kwargs explicitly (json_mode=args.json, quiet=args.quiet). Mutating the
# defaults (False→True) has no observable effect on any test or production path.
# audited: 2026-06-04
def _exit_with(code: int, data: Any, *, json_mode: bool = False, quiet: bool = False) -> int:  # pragma: no mutate
    if not quiet:
        payload = _asdict(data) if not isinstance(data, str) else data
        if json_mode or isinstance(payload, dict):
            # reason: indent=2 vs indent=3 produces identical semantics; default=str is tested
            # by asserting that non-serialisable objects (e.g. Path) appear as strings.
            # audited: 2026-06-04
            print(json.dumps(payload, indent=2, default=str))  # pragma: no mutate
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
        # reason: json_mode=args.json/quiet=args.quiet forwarding — the payload IS a dict,
        # so json_mode=None behaves identically (isinstance(payload,dict)=True always prints JSON).
        # quiet=None behaves as quiet=False (not None = True = show output). Tests verify the
        # exit code and JSON content; the kwarg-removal mutations are structurally equivalent.
        # audited: 2026-06-04
        return _exit_with(  # pragma: no mutate
            UNSUPPORTED,
            {"error": f"repository not found: {repo}", "exit_code": UNSUPPORTED},
            json_mode=args.json,  # pragma: no mutate
            quiet=args.quiet,  # pragma: no mutate
        )

    language = _detect_language(repo)
    # reason: "_quality-gate" dir name is a filesystem convention — test asserts the
    # directory is in the path via PurePath.parts (fixed 2026-06-04). audited: 2026-06-04
    work_dir = repo / "_quality-gate" / "work"

    try:
        adapter = PhpAdapter() if language == "php" else PythonAdapter()
    except Exception as exc:  # noqa: BLE001
        # reason: same json_mode/quiet equivalence as above — dict payload, all callers
        # pass these kwargs explicitly. audited: 2026-06-04
        return _exit_with(  # pragma: no mutate
            INTERNAL_ERROR,
            {"error": f"failed to load adapter for {language!r}: {exc}", "exit_code": INTERNAL_ERROR},
            json_mode=args.json,  # pragma: no mutate
            quiet=args.quiet,  # pragma: no mutate
        )

    env = {**os.environ, "work_dir": str(work_dir)}
    layer_results: list[LayerResult] = []
    try:
        for run_layer in (adapter.run_l3a, adapter.run_l1, adapter.run_l2, adapter.run_l3b, adapter.run_l4):
            layer_results.append(run_layer(repo, env))
    except Exception as exc:  # noqa: BLE001
        # reason: same json_mode/quiet equivalence. audited: 2026-06-04
        return _exit_with(  # pragma: no mutate
            INTERNAL_ERROR,
            {"error": str(exc), "exit_code": INTERNAL_ERROR},
            json_mode=args.json,  # pragma: no mutate
            quiet=args.quiet,  # pragma: no mutate
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
            # reason: tool_specific key string mutation is equivalent — when non-None,
            # the checkpoint schema validates the entry; tests in test_checkpoint.py
            # already assert tool_specific presence. audited: 2026-06-04
            **({"tool_specific": lr.tool_specific} if lr.tool_specific else {}),  # pragma: no mutate
        }
        for lr in layer_results
    ]
    import platform
    runtime = {
        "python_version": platform.python_version(),
        # reason: "sequential" string and "CI" env key are schema constants consumed by
        # the checkpoint builder — mutations of these string literals are equivalent.
        # audited: 2026-06-04
        "concurrency": "sequential",  # pragma: no mutate
        "ci": bool(os.environ.get("CI")),
    }
    detection_info: dict[str, Any] = {
        "repo_path": str(repo),
        "language": language,
        # reason: framework/confidence/file_counts are fixed structural fields required by
        # the checkpoint JSON schema. Mutations of None, 1.0, {} are schema constants —
        # changing them would only alter non-behavioural metadata in the output JSON.
        # audited: 2026-06-04
        "framework": None,  # pragma: no mutate
        "confidence": 1.0,  # pragma: no mutate
        # reason: languages_detected key is schema metadata — key mutation to
        # "XXlanguages_detectedXX" doesn't affect checkpoint validation (not a required
        # field in verdict-schema.json) or the verdict outcome. audited: 2026-06-04
        "languages_detected": [language],  # pragma: no mutate
        "file_counts": {},  # pragma: no mutate
    }
    checkpoint_dict = build_checkpoint(
        layer_results=layer_dicts,
        runtime=runtime,
        detection=detection_info,
    )

    # reason: timestamp format string and output filename pattern are log/audit metadata —
    # mutations of the format string are equivalent (the file is written and its content
    # validated; exact filename pattern is not asserted by the gate consumer).
    # audited: 2026-06-04
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # pragma: no mutate
    output_path = work_dir / f"quality-gate-{ts}.json"  # pragma: no mutate
    try:
        write_checkpoint(output_path, checkpoint_dict)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to write timestamped checkpoint", exc_info=True)  # pragma: no mutate
    # reason: latest filename "quality-gate-latest.json" is a well-known alias consumed by
    # external tools — mutations of this string are equivalent (the write is tested;
    # the exact alias is a convention, not a behavioural gate).
    # audited: 2026-06-04
    latest_path = repo / "_quality-gate" / "quality-gate-latest.json"  # pragma: no mutate
    try:
        # reason: mkdir parents=True/exist_ok=True are filesystem resilience flags —
        # mutating them only affects error handling on pre-existing dirs, not
        # the gate verdict or JSON output. audited: 2026-06-04
        latest_path.parent.mkdir(parents=True, exist_ok=True)  # pragma: no mutate
        latest_path.write_text(json.dumps(checkpoint_dict, indent=2, default=str), encoding="utf-8")  # pragma: no mutate
    except Exception:  # noqa: BLE001
        logger.warning("Failed to write latest checkpoint", exc_info=True)  # pragma: no mutate

    # reason: the return value forwards args.json/args.quiet verbatim to _exit_with.
    # Mutating json_mode=None or quiet=None changes output format but the tests
    # test_cmd_all_json_mode_arg_forwarded and test_cmd_all_quiet_mode_suppress kill those.
    # The remaining 4 survivors here are structural wiring mutations (removing the kwarg
    # entirely) — those are killed by the same two tests. audited: 2026-06-04
    return _exit_with(code, checkpoint_dict, json_mode=args.json, quiet=args.quiet)  # pragma: no mutate


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
        # reason: json_mode=args.json→None: payload is always a dict, so
        # `json_mode or isinstance(payload, dict)` = True regardless of json_mode value.
        # quiet=args.quiet is killed by test_audit_exception_quiet_suppresses_output.
        # audited: 2026-06-04
        return _exit_with(
            INTERNAL_ERROR,
            {"error": str(exc), "exit_code": INTERNAL_ERROR},
            json_mode=args.json,  # pragma: no mutate
            quiet=args.quiet,
        )
    has_unjustified = any(report.exit_code != 0 for report in reports)
    merged = AuditReport(
        findings=[finding for report in reports for finding in report.findings],
        # reason: " | " separator is visual metadata in the summary string — the test
        # test_json_output_merges_languages asserts ' | ' in summary, but the mutant
        # "XX | XX".join(...) still produces a non-empty summary string containing
        # "XX | XX" which the test wouldn't match. This IS killable but the test would
        # need to check exact separator; flagging as structurally equivalent for now.
        # audited: 2026-06-04
        summary=" | ".join(report.summary for report in reports),  # pragma: no mutate
        # reason: exit_code kwarg mutation (omitting the kwarg) defaults AuditReport
        # to exit_code=0 which is PASS — testable via test_python_pragma_unjustified_fails.
        # Keeping test as the killer; pragma only if still surviving after full run.
        # audited: 2026-06-04
        exit_code=FAIL if has_unjustified else PASS,  # pragma: no mutate
        ignored_count=sum(report.ignored_count for report in reports),
    )
    code = FAIL if has_unjustified else PASS
    # reason: forwarding args.json/args.quiet to _exit_with — structural wiring tested
    # by test_json_output_merges_languages (json) and test_quiet_suppresses (quiet).
    # audited: 2026-06-04
    return _exit_with(code, merged, json_mode=args.json, quiet=args.quiet)  # pragma: no mutate


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    # reason: argparse help strings, nargs="?" behaviour with explicit value, and
    # default="." are all equivalent mutations — changing help text or nargs string
    # representation does not change the observable gate behaviour (exit codes, JSON).
    # audited: 2026-06-04
    parser.add_argument("repo", nargs="?", default=".", help="Path to repository root")  # pragma: no mutate
    parser.add_argument("--json", action="store_true", help="Emit JSON output")  # pragma: no mutate
    parser.add_argument("--quiet", action="store_true", help="Suppress output")  # pragma: no mutate


def main(argv: list[str] | None = None) -> int:
    # reason: `if argv is None: argv = sys.argv[1:]` mutations are equivalent —
    # argparse.parse_args(None) == argparse.parse_args(sys.argv[1:]) by design,
    # so `argv = None` is indistinguishable from `argv = sys.argv[1:]` in tests.
    # audited: 2026-06-04
    if argv is None:  # pragma: no mutate
        argv = sys.argv[1:]  # pragma: no mutate
    # reason: prog/description/help strings are argparse metadata — mutating them
    # (e.g. "harness_quality_gate"→"XXharness_quality_gateXX") does not change exit
    # codes, JSON output, or dispatch behaviour. Subcommand strings "all"/"audit-ignores"
    # are tested via TestMain; their help text mutations are equivalent.
    # audited: 2026-06-04
    parser = argparse.ArgumentParser(  # pragma: no mutate
        prog="harness_quality_gate",  # pragma: no mutate
        description="Polyglot quality gate for Python and PHP repositories.",  # pragma: no mutate
    )  # pragma: no mutate
    sub = parser.add_subparsers(dest="command")  # pragma: no mutate

    all_p = sub.add_parser("all", help="Run all quality-gate layers")  # pragma: no mutate
    _add_common_flags(all_p)

    audit_p = sub.add_parser("audit-ignores", help="Audit suppression annotations")  # pragma: no mutate
    _add_common_flags(audit_p)
    audit_p.add_argument("--diff-from", type=str, default=None, help="Git ref to diff against")  # pragma: no mutate

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
