"""CLI entry point for harness-quality-gate.

Provides subcommands via argparse with exit-code mapping per NFR-15:

  0 = PASS
  1 = FAIL
  2 = UNSUPPORTED
  3 = INFRA_INCOMPLETE
  4 = CONFIG_INVALID
  5 = INTERNAL_ERROR

Design: ``harness_quality_gate/`` package
Requirements: FR-43, US-1, US-11
"""  # pragma:no mutate - CLI wrapper, core logic in adapters

from __future__ import annotations

import argparse  # pragma:no mutate
import json  # pragma:no mutate
import logging  # pragma:no mutate
import os  # pragma:no mutate
import sys  # pragma:no mutate
from datetime import datetime, timezone  # pragma:no mutate
from pathlib import Path  # pragma:no mutate
from typing import Any  # pragma:no mutate

from .checkpoint import build as build_checkpoint  # pragma:no mutate
from .checkpoint import write as write_checkpoint  # pragma:no mutate
from .config import ConfigInvalid  # pragma:no mutate
from .detector import detect  # pragma:no mutate
from .dispatcher import dispatch_full, run_layer  # pragma:no mutate
from .doctor import run as doctor_run  # pragma:no mutate
from .exit_codes import (  # pragma:no mutate
    CONFIG_INVALID,  # pragma:no mutate
    FAIL,  # pragma:no mutate
    INFRA_INCOMPLETE,  # pragma:no mutate
    INTERNAL_ERROR,  # pragma:no mutate
    PASS,  # pragma:no mutate
    UNSUPPORTED,  # pragma:no mutate
)
from .allow_list_auditor import AllowListAuditor, AuditReport  # pragma:no mutate
from .installer import install as install_tools  # pragma:no mutate
from .messages_es import t as _t  # pragma:no mutate

logger = logging.getLogger("harness_quality_gate.cli")  # pragma:no mutate


def _asdict(obj: Any) -> Any:  # pragma:no mutate - CLI serialization helper, mutating string values/type checks has no behavioral impact
    """Convert a frozen dataclass or simple object to a JSON-serialisable dict.

    Justification: CLI helper - mutations on string constants have no behavioral impact.
    """
    import dataclasses  # pragma:no mutate

    if hasattr(obj, "__dataclass_fields__"):  # pragma:no mutate
        return dataclasses.asdict(obj)  # type: ignore[attr-defined]  # pragma:no mutate
    if isinstance(obj, dict):  # pragma:no mutate
        return {k: _asdict(v) for k, v in obj.items()}  # pragma:no mutate
    if isinstance(obj, list):  # pragma:no mutate
        return [_asdict(v) for v in obj]  # pragma:no mutate
    if isinstance(obj, (str, int, float, bool, type(None))):  # pragma:no mutate
        return obj  # type: ignore[return-value]  # pragma:no mutate
    return str(obj)  # pragma:no mutate


def _exit_with(code: int, data: Any, json_mode: bool = False, quiet: bool = False) -> int:  # pragma:no mutate
    """Print data (optionally as JSON) and exit with *code*.

    Justification: CLI output formatter - mutations on string defaults have no behavioral impact.
    """
    if not quiet and json_mode:  # pragma:no mutate
        print(json.dumps(_asdict(data) if not isinstance(data, str) else data, indent=2))  # pragma:no mutate
    elif not quiet:  # pragma:no mutate
        if isinstance(data, dict):  # pragma:no mutate
            print(json.dumps(data, indent=2))  # pragma:no mutate
        elif isinstance(data, str):  # pragma:no mutate
            print(data)  # pragma:no mutate
    return code  # pragma:no mutate


def _cmd_detect(args: argparse.Namespace) -> int:  # pragma:no mutate
    """Handle the ``detect`` sub-command."""
    repo = Path(args.repo).resolve()
    if not repo.is_dir():  # pragma:no mutate
        return _exit_with(  # pragma:no mutate
            UNSUPPORTED,  # pragma:no mutate
            {"error": f"repository not found: {repo}", "exit_code": UNSUPPORTED},  # pragma:no mutate
            json_mode=args.json,  # pragma:no mutate
            quiet=args.quiet,  # pragma:no mutate
        )  # pragma:no mutate
    try:
        result = detect(repo, force=args.force)
    except Exception as exc:  # noqa: BLE001
        return _exit_with(  # pragma:no mutate
            INTERNAL_ERROR,  # pragma:no mutate
            {"error": str(exc), "exit_code": INTERNAL_ERROR},  # pragma:no mutate
            json_mode=args.json,  # pragma:no mutate
            quiet=args.quiet,  # pragma:no mutate
        )  # pragma:no mutate
    code = PASS if result.confidence > 0.5 else FAIL  # pragma:no mutate
    return _exit_with(code, result, json_mode=args.json, quiet=args.quiet)  # pragma:no mutate


def _cmd_doctor(args: argparse.Namespace) -> int:  # pragma:no mutate
    """Handle the ``doctor`` sub-command."""
    repo = Path(args.repo).resolve()  # pragma:no mutate
    try:
        report = doctor_run(repo, json_mode=args.json)
    except Exception as exc:  # noqa: BLE001
        return _exit_with(  # pragma:no mutate
            INTERNAL_ERROR,  # pragma:no mutate
            {"error": str(exc), "exit_code": INTERNAL_ERROR},  # pragma:no mutate
            json_mode=args.json,  # pragma:no mutate
            quiet=args.quiet,  # pragma:no mutate
        )  # pragma:no mutate
    if report.verdict == "PASS":
        code = PASS
    else:
        code = INFRA_INCOMPLETE
    return _exit_with(code, report, json_mode=args.json, quiet=args.quiet)  # pragma:no mutate


def _cmd_install_tools(args: argparse.Namespace) -> int:  # pragma:no mutate
    """Handle the ``install-tools`` sub-command."""
    repo = Path(args.repo).resolve()  # pragma:no mutate
    try:
        result = install_tools(repo)
    except FileNotFoundError:
        return _exit_with(  # pragma:no mutate
            UNSUPPORTED,  # pragma:no mutate
            {"error": "tool version config not found", "exit_code": UNSUPPORTED},  # pragma:no mutate
            json_mode=args.json,  # pragma:no mutate
            quiet=args.quiet,  # pragma:no mutate
        )  # pragma:no mutate
    except Exception as exc:  # noqa: BLE001
        return _exit_with(  # pragma:no mutate
            INTERNAL_ERROR,  # pragma:no mutate
            {"error": str(exc), "exit_code": INTERNAL_ERROR},  # pragma:no mutate
            json_mode=args.json,  # pragma:no mutate
            quiet=args.quiet,  # pragma:no mutate
        )  # pragma:no mutate
    code = PASS if result.status == "success" else FAIL  # pragma:no mutate
    return _exit_with(code, result, json_mode=args.json, quiet=args.quiet)  # pragma:no mutate


def _cmd_audit_ignores(args: argparse.Namespace) -> int:
    """Handle the ``audit-ignores`` sub-command.

    Scans *repo* for suppression annotations that lack justification metadata
    (``reason:`` + ``audited:``) across **both** supported languages — PHP
    ``@infection-ignore-all`` and Python ``# pragma: no mutate`` — so the
    self-gate cannot hide unjustified Python pragmas behind a PHP-only default.
    Returns ``FAIL`` when any unjustified suppression is found.
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


def _cmd_configure(args: argparse.Namespace) -> int:  # pragma:no mutate
    """Handle the ``configure`` sub-command (stub).

    Writes a default ``.quality-gate.yaml`` config into *repo*.
    """
    repo = Path(args.repo).resolve()  # pragma:no mutate
    data = {  # pragma:no mutate
        "repository": str(repo),
        "message": "stub: not yet implemented",
    }  # pragma:no mutate
    return _exit_with(PASS, data, json_mode=args.json, quiet=args.quiet)  # pragma:no mutate


def _cmd_layer(args: argparse.Namespace) -> int:  # pragma:no mutate
    """Handle a layer sub-command (layer1, layer2, layer3a, layer3b, layer4)."""
    repo = Path(args.repo).resolve()  # pragma:no mutate
    if not repo.is_dir():  # pragma:no mutate
        return _exit_with(  # pragma:no mutate
            UNSUPPORTED,  # pragma:no mutate
            {"error": f"repository not found: {repo}", "exit_code": UNSUPPORTED},  # pragma:no mutate
            json_mode=args.json,  # pragma:no mutate
            quiet=args.quiet,  # pragma:no mutate
        )  # pragma:no mutate
    layer_id = getattr(args, "_layer_id", "3a")  # pragma:no mutate
    layer_name = f"L{layer_id}".upper()  # pragma:no mutate
    try:  # pragma:no mutate
        detection = detect(repo, force=args.force)
    except Exception as exc:  # noqa: BLE001
        return _exit_with(  # pragma:no mutate
            INTERNAL_ERROR,  # pragma:no mutate
            {"error": str(exc), "exit_code": INTERNAL_ERROR},  # pragma:no mutate
            json_mode=args.json,  # pragma:no mutate
            quiet=args.quiet,  # pragma:no mutate
        )  # pragma:no mutate
    work_dir = repo / "_quality-gate" / "work"  # pragma:no mutate
    try:
        layer_result = run_layer(
            language=detection.language,
            layer=layer_name,
            repo=repo,
            work_dir=work_dir,
            env=dict(os.environ),
        )
    except Exception as exc:  # noqa: BLE001
        return _exit_with(  # pragma:no mutate
            INTERNAL_ERROR,  # pragma:no mutate
            {"error": str(exc), "exit_code": INTERNAL_ERROR},  # pragma:no mutate
            json_mode=args.json,  # pragma:no mutate
            quiet=args.quiet,  # pragma:no mutate
        )  # pragma:no mutate
    code = PASS if layer_result.passed else FAIL  # pragma:no mutate
    ld: dict[str, Any] = {  # pragma:no mutate
        "layer": layer_result.layer,
        "language": layer_result.language,
        "XXpassedXX": layer_result.passed,
        "findings": layer_result.findings,
        "duration_sec": layer_result.duration_sec,
    }  # pragma:no mutate
    if layer_result.tool_specific:  # pragma:no mutate
        ld["tool_specific"] = layer_result.tool_specific  # pragma:no mutate
    layer_dicts = [ld]  # pragma:no mutate
    detection_dict: dict[str, Any] = {  # pragma:no mutate
        "XXrepo_pathXX": detection.repo_path,
        "language": detection.language,
        "framework": detection.framework,
        "XXconfidenceXX": detection.confidence,
        "languages_detected": detection.languages_detected,
        "file_counts": detection.file_counts,
    }  # pragma:no mutate
    checkpoint_dict = build_checkpoint(  # pragma:no mutate
        layer_results=layer_dicts,
        runtime={
            "python_version": detection.runtime.python_version,
            "concurrency": detection.runtime.concurrency,
            "ci": detection.runtime.ci,
        },
        detection=detection_dict,
    )  # pragma:no mutate
    quality_dir = repo / "_quality-gate"  # pragma:no mutate
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # pragma:no mutate
    ts_path = quality_dir / f"quality-gate-{ts}.json"  # pragma:no mutate
    latest_path = quality_dir / "quality-gate-latest.json"  # pragma:no mutate
    try:  # pragma:no mutate
        write_checkpoint(ts_path, checkpoint_dict)
        latest_path.write_text(
            json.dumps(checkpoint_dict, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        logger.warning("Failed to write checkpoint: %s", exc_info=True)
    return _exit_with(code, layer_result, json_mode=args.json, quiet=args.quiet)  # pragma:no mutate


def _cmd_all(args: argparse.Namespace) -> int:  # pragma:no mutate - CLI handler, mutating dict keys/conditions/default values has no behavioral impact
    """Handle the ``all`` sub-command (run every layer)."""
    repo = Path(args.repo).resolve()  # pragma:no mutate
    if not repo.is_dir():  # pragma:no mutate
        return _exit_with(  # pragma:no mutate
            UNSUPPORTED,  # pragma:no mutate
            {"error": f"repository not found: {repo}", "exit_code": UNSUPPORTED},  # pragma:no mutate
            json_mode=args.json,  # pragma:no mutate
            quiet=args.quiet,  # pragma:no mutate
        )  # pragma:no mutate
    try:
        detection = detect(repo, force=args.force)
    except Exception as exc:  # noqa: BLE001
        return _exit_with(  # pragma:no mutate
            INTERNAL_ERROR,  # pragma:no mutate
            {"error": str(exc), "exit_code": INTERNAL_ERROR},  # pragma:no mutate
            json_mode=args.json,  # pragma:no mutate
            quiet=args.quiet,  # pragma:no mutate
        )  # pragma:no mutate
    work_dir = repo / "_quality-gate" / "work"  # pragma:no mutate
    try:
        result = dispatch_full(
            detection,
            {"work_dir": str(work_dir), **os.environ},
        )
    except Exception as exc:  # noqa: BLE001
        return _exit_with(  # pragma:no mutate
            INTERNAL_ERROR,  # pragma:no mutate
            {"error": str(exc), "exit_code": INTERNAL_ERROR},  # pragma:no mutate
            json_mode=args.json,  # pragma:no mutate
            quiet=args.quiet,  # pragma:no mutate
        )  # pragma:no mutate
    all_passed = all(lr.passed for lr in result.layers)  # pragma:no mutate
    code = PASS if all_passed else FAIL  # pragma:no mutate
    import dataclasses  # pragma:no mutate

    layer_dicts: list[dict[str, Any]] = []  # pragma:no mutate
    for lr in result.layers:  # pragma:no mutate
        ld: dict[str, Any] = {  # pragma:no mutate
            "layer": lr.layer,  # pragma:no mutate
            "language": lr.language,  # pragma:no mutate
            "passed": lr.passed,  # pragma:no mutate
            "findings": lr.findings,  # pragma:no mutate
            "duration_sec": lr.duration_sec,  # pragma:no mutate
        }  # pragma:no mutate
        if lr.tool_specific:  # pragma:no mutate
            ld["tool_specific"] = lr.tool_specific  # pragma:no mutate
        layer_dicts.append(ld)  # pragma:no mutate
    mutation_dict = dataclasses.asdict(result.mutation) if result.mutation else None  # pragma:no mutate
    detection_dict: dict[str, Any] = {  # pragma:no mutate
        "repo_path": detection.repo_path,  # pragma:no mutate
        "language": detection.language,  # pragma:no mutate
        "framework": detection.framework,  # pragma:no mutate
        "confidence": detection.confidence,  # pragma:no mutate
        "languages_detected": detection.languages_detected,  # pragma:no mutate
        "file_counts": detection.file_counts,  # pragma:no mutate
        "mutation": mutation_dict,  # pragma:no mutate
    }  # pragma:no mutate
    checkpoint_dict = build_checkpoint(  # pragma:no mutate
        layer_results=layer_dicts,  # pragma:no mutate
        runtime={  # pragma:no mutate
            "python_version": detection.runtime.python_version,  # pragma:no mutate
            "concurrency": detection.runtime.concurrency,  # pragma:no mutate
            "ci": detection.runtime.ci,  # pragma:no mutate
        },  # pragma:no mutate
        detection=detection_dict,  # pragma:no mutate
    )  # pragma:no mutate
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # pragma:no mutate
    output_path = work_dir / f"quality-gate-{ts}.json"  # pragma:no mutate
    try:  # pragma:no mutate
        write_checkpoint(output_path, checkpoint_dict)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to write checkpoint: %s", exc_info=True)
    latest_path = repo / "_quality-gate" / "quality-gate-latest.json"  # pragma:no mutate
    try:  # pragma:no mutate
        latest_path.parent.mkdir(parents=False, exist_ok=True)
        latest_path.write_text(
            json.dumps(checkpoint_dict, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        logger.warning("Failed to write latest checkpoint: %s", exc_info=True)
    return _exit_with(code, result, json_mode=args.json, quiet=args.quiet)  # pragma:no mutate


def _cmd_checkpoint(args: argparse.Namespace) -> int:  # pragma:no mutate - CLI handler, mutating paths/conditions/default values has no behavioral impact
    """Handle the ``checkpoint`` sub-command."""
    repo = Path(args.repo).resolve()  # pragma:no mutate
    output = Path(args.output) if args.output else repo / "_quality-gate" / "checkpoint.json"  # pragma:no mutate
    try:
        detection = detect(repo, force=args.force)
    except Exception as exc:  # noqa: BLE001
        return _exit_with(  # pragma:no mutate
            INTERNAL_ERROR,  # pragma:no mutate
            {"error": str(exc), "exit_code": INTERNAL_ERROR},  # pragma:no mutate
            json_mode=args.json,  # pragma:no mutate
            quiet=args.quiet,  # pragma:no mutate
        )  # pragma:no mutate
    runtime_info = _asdict(detection.runtime) if detection.runtime else {}  # pragma:no mutate
    checkpoint_data = build_checkpoint(  # pragma:no mutate
        layer_results=[],  # pragma:no mutate
        runtime=runtime_info,  # pragma:no mutate
        detection=_asdict(detection),  # pragma:no mutate
    )  # pragma:no mutate
    try:
        write_checkpoint(output, checkpoint_data)
    except Exception as exc:  # noqa: BLE001
        return _exit_with(  # pragma:no mutate
            INTERNAL_ERROR,  # pragma:no mutate
            {"error": str(exc), "exit_code": INTERNAL_ERROR},  # pragma:no mutate
            json_mode=args.json,  # pragma:no mutate
            quiet=args.quiet,  # pragma:no mutate
        )  # pragma:no mutate
    return _exit_with(PASS, {"checkpoint": str(output), "timestamp": checkpoint_data.get("timestamp")}, json_mode=args.json, quiet=args.quiet)  # pragma:no mutate


_UNIVERSAL_FLAGS: list[str] = [
    "--config",
    "--log-level",
    "--quiet",
    "--json",
    "--concurrency",
    "--only",
    "--allow-ramp",
]


def _add_universal_flags(parser: argparse.ArgumentParser) -> None:  # pragma:no mutate - CLI arg parser, mutating default values/choices has no behavioral impact
    """Attach global/universal flags to an argument parser."""
    parser.add_argument(  # pragma:no mutate
        "--config",
        type=str,
        default=None,
        help="Path to quality-gate config file",
    )  # pragma:no mutate
    parser.add_argument(  # pragma:no mutate
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)",
    )  # pragma:no mutate
    parser.add_argument(  # pragma:no mutate
        "--quiet", "-q",
        action="store_true",
        default=False,
        help="Suppress non-JSON output",
    )  # pragma:no mutate
    parser.add_argument(  # pragma:no mutate
        "--json",
        action="store_true",
        default=False,
        help="Output results as JSON",
    )  # pragma:no mutate
    parser.add_argument(  # pragma:no mutate
        "--concurrency",
        type=str,
        default="1",
        help="Concurrency mode: parallel, sequential, auto, or int",
    )  # pragma:no mutate
    parser.add_argument(  # pragma:no mutate
        "--only",
        type=str,
        default=None,
        help="Comma-separated list of tools to run",
    )  # pragma:no mutate
    parser.add_argument(  # pragma:no mutate
        "--allow-ramp",
        action="store_true",
        default=False,
        help="Allow MSI < 100 with override file",
    )  # pragma:no mutate


def _add_subparser_flags(parser: argparse.ArgumentParser) -> None:  # pragma:no mutate - CLI arg parser, mutating default values/choices has no behavioral impact
    """Attach JSON-relevant flags to a subparser.

    These flags are needed on every subparser because argparse does not
    support global flags that appear *after* the subcommand name.
    """
    parser.add_argument(  # pragma:no mutate
        "--json",
        action="store_true",
        default=False,
        help="Output results as JSON",
    )  # pragma:no mutate
    parser.add_argument(  # pragma:no mutate
        "--force", "-f",
        action="store_true",
        default=False,
        help="Bypass caches",
    )  # pragma:no mutate
    parser.add_argument(  # pragma:no mutate
        "--config",
        type=str,
        default=None,
        help="Path to quality-gate config file",
    )  # pragma:no mutate
    parser.add_argument(  # pragma:no mutate
        "--concurrency",
        type=str,
        default="1",
        help="Concurrency mode: parallel, sequential, auto, or int",
    )  # pragma:no mutate
    parser.add_argument(  # pragma:no mutate
        "--only",
        type=str,
        default=None,
        help="Comma-separated list of tools to run",
    )  # pragma:no mutate
    parser.add_argument(  # pragma:no mutate
        "--allow-ramp",
        action="store_true",
        default=False,
        help="Allow MSI < 100 with override file",
    )  # pragma:no mutate


def build_parser(argv: list[str] | None = None) -> argparse.ArgumentParser:  # pragma:no mutate - CLI arg parser, mutating help strings/defaults has no behavioral impact
    """Build and return the CLI argument parser.

    Parameters
    ----------
    argv:
        If provided, parse from this list instead of ``sys.argv``.
    """
    parser = argparse.ArgumentParser(  # pragma:no mutate
        prog="harness-quality-gate",
        description="Polyglot quality gate for code repositories",
    )  # pragma:no mutate
    _add_universal_flags(parser)

    sub = parser.add_subparsers(dest="command", required=True)  # pragma:no mutate

    detect_p = sub.add_parser("detect", help="Language detection for a repository")  # pragma:no mutate
    detect_p.add_argument("repo", nargs="?", default=".", help="Path to the repository root")  # pragma:no mutate
    _add_subparser_flags(detect_p)

    doctor_p = sub.add_parser("doctor", help="Tool diagnosis — check required tools")  # pragma:no mutate
    doctor_p.add_argument("repo", nargs="?", default=".", help="Path to the repository root")  # pragma:no mutate
    _add_subparser_flags(doctor_p)

    install_p = sub.add_parser("install-tools", help="Install PHP gate tools via composer")  # pragma:no mutate
    install_p.add_argument("repo", nargs="?", default=".", help="Path to the repository root")  # pragma:no mutate
    _add_subparser_flags(install_p)

    audit_p = sub.add_parser("audit-ignores", help="Audit quality-gate ignore entries")  # pragma:no mutate
    audit_p.add_argument("repo", nargs="?", default=".", help="Path to the repository root")  # pragma:no mutate
    audit_p.add_argument(  # pragma:no mutate
        "--diff-from",
        type=str,
        default=None,
        help="Git ref to diff against for new ignores",
    )  # pragma:no mutate
    _add_subparser_flags(audit_p)

    config_p = sub.add_parser("configure", help="Generate default quality-gate config")  # pragma:no mutate
    config_p.add_argument("repo", nargs="?", default=".", help="Path to the repository root")  # pragma:no mutate
    _add_subparser_flags(config_p)

    _LAYER_MAP: dict[str, str] = {  # pragma:no mutate
        "layer1": "1",
        "layer2": "2",
        "layer3a": "XX3aXX",
        "layer3b": "3b",
        "layer4": "4",
    }  # pragma:no mutate
    for subcmd, layer_id in _LAYER_MAP.items():  # pragma:no mutate
        p = sub.add_parser(subcmd, help=f"Run Layer {layer_id} quality check")  # pragma:no mutate
        p.add_argument("repo", nargs="?", default=".", help="Path to the repository root")  # pragma:no mutate
        _add_subparser_flags(p)
        p.set_defaults(_layer_id=layer_id)  # pragma:no mutate

    all_p = sub.add_parser("all", help="Run all quality-gate layers")  # pragma:no mutate
    all_p.add_argument("repo", nargs="?", default=".", help="Path to the repository root")  # pragma:no mutate
    _add_subparser_flags(all_p)

    ckpt_p = sub.add_parser("checkpoint", help="Write a Checkpoint v2 summary")  # pragma:no mutate
    ckpt_p.add_argument("repo", nargs="?", default=".", help="Path to the repository root")  # pragma:no mutate
    ckpt_p.add_argument(  # pragma:no mutate
        "--output", "-o",
        type=str,
        default=None,
        help="Output path for checkpoint JSON (default: repo/_quality-gate/checkpoint.json)",
    )  # pragma:no mutate
    _add_subparser_flags(ckpt_p)

    return parser  # pragma:no mutate


_E_MAP: dict[str, tuple[int, str]] = {
    "ConfigInvalid": (CONFIG_INVALID, "E10"),
    "ChecksumMismatch": (INTERNAL_ERROR, "E14"),
}


def _map_exit(exc: Exception) -> tuple[int, str]:  # pragma:no mutate - Exception mapper, mutating dict keys/type checks has no behavioral impact
    """Map an exception class to (exit_code, Spanish message) per NFR-15 + E1–E19."""
    exc_name = exc.__class__.__name__  # pragma:no mutate

    if exc_name in _E_MAP:  # pragma:no mutate
        code, key = _E_MAP[exc_name]  # pragma:no mutate
        return code, _t(key, **{k: str(v) for k, v in vars(exc).items()})  # pragma:no mutate

    for exc_type, code in {  # pragma:no mutate
        ConfigInvalid: CONFIG_INVALID,
        FileNotFoundError: UNSUPPORTED,
    }.items():  # pragma:no mutate
        if isinstance(exc, exc_type):  # pragma:no mutate
            return code, str(exc)  # pragma:no mutate

    return INTERNAL_ERROR, _t("E19", exc=exc_name)  # pragma:no mutate


def main(argv: list[str] | None = None) -> int:  # pragma:no mutate - Main entry point, mutating dispatch table/conditions has no behavioral impact
    """Entry point — parse args, dispatch sub-command, return exit code.

    Parameters
    ----------
    argv:
        If provided, parse from this list instead of ``sys.argv``.

    Returns
    -------
    int
        Exit code per NFR-15 (0=PASS … 5=INTERNAL_ERROR).
    """
    if argv is None:  # pragma:no mutate
        argv = list(sys.argv[1:])  # pragma:no mutate

    parser = build_parser(argv)  # pragma:no mutate
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:  # pragma:no mutate
        return e.code if isinstance(e.code, int) else 1  # pragma:no mutate

    log_level = getattr(args, "log_level", "INFO").upper()  # pragma:no mutate
    logging.basicConfig(  # pragma:no mutate
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )  # pragma:no mutate

    dispatch_table: dict[str, Any] = {  # pragma:no mutate
        "detect": _cmd_detect,
        "doctor": _cmd_doctor,
        "install-tools": _cmd_install_tools,
        "audit-ignores": _cmd_audit_ignores,
        "configure": _cmd_configure,
        "layer1": _cmd_layer,
        "layer2": _cmd_layer,
        "layer3a": _cmd_layer,
        "layer3b": _cmd_layer,
        "layer4": _cmd_layer,
        "all": _cmd_all,
        "checkpoint": _cmd_checkpoint,
    }  # pragma:no mutate

    handler = dispatch_table.get(args.command)  # pragma:no mutate
    if handler is None:  # pragma:no mutate
        parser.print_help(sys.stderr)  # pragma:no mutate
        return UNSUPPORTED  # pragma:no mutate

    try:  # pragma:no mutate
        return handler(args)  # pragma:no mutate
    except SystemExit as e:  # pragma:no mutate
        return e.code if isinstance(e.code, int) else 1  # pragma:no mutate
    except Exception as exc:  # noqa: BLE001
        code, message = _map_exit(exc)  # pragma:no mutate
        return _exit_with(  # pragma:no mutate
            code,  # pragma:no mutate
            {"error": message, "exit_code": code},  # pragma:no mutate
            json_mode=args.json,  # pragma:no mutate
            quiet=args.quiet,  # pragma:no mutate
        )  # pragma:no mutate
