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
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from .checkpoint import build as build_checkpoint
from .checkpoint import write as write_checkpoint
from .config import ConfigInvalid
from .detector import detect
from .dispatcher import dispatch_full, run_layer
from .doctor import run as doctor_run
from .exit_codes import (
    CONFIG_INVALID,
    FAIL,
    INFRA_INCOMPLETE,
    INTERNAL_ERROR,
    PASS,
    UNSUPPORTED,
)
from .installer import install as install_tools

logger = logging.getLogger("harness_quality_gate.cli")

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _asdict(obj: Any) -> Any:
    """Convert a frozen dataclass or simple object to a JSON-serialisable dict."""
    import dataclasses

    if hasattr(obj, "__dataclass_fields__"):
        return dataclasses.asdict(obj)  # type: ignore[attr-defined]
    if isinstance(obj, dict):
        return {k: _asdict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_asdict(v) for v in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj  # type: ignore[return-value]
    return str(obj)


def _exit_with(code: int, data: Any, json_mode: bool = False, quiet: bool = False) -> int:
    """Print data (optionally as JSON) and exit with *code*."""
    if not quiet and json_mode:
        print(json.dumps(_asdict(data) if not isinstance(data, str) else data, indent=2))
    elif not quiet:
        if isinstance(data, dict):
            print(json.dumps(data, indent=2))
        elif isinstance(data, str):
            print(data)
    return code


# ------------------------------------------------------------------
# Sub-command handlers
# ------------------------------------------------------------------

def _cmd_detect(args: argparse.Namespace) -> int:
    """Handle the ``detect`` sub-command."""
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        return _exit_with(
            UNSUPPORTED,
            {"error": f"repository not found: {repo}", "exit_code": UNSUPPORTED},
            json_mode=args.json,
            quiet=args.quiet,
        )
    try:
        result = detect(repo, force=args.force)
    except Exception as exc:  # noqa: BLE001
        return _exit_with(
            INTERNAL_ERROR,
            {"error": str(exc), "exit_code": INTERNAL_ERROR},
            json_mode=args.json,
            quiet=args.quiet,
        )
    code = PASS if result.confidence > 0.5 else FAIL
    return _exit_with(code, result, json_mode=args.json, quiet=args.quiet)


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Handle the ``doctor`` sub-command."""
    repo = Path(args.repo).resolve()
    try:
        report = doctor_run(repo, json_mode=args.json)
    except Exception as exc:  # noqa: BLE001
        return _exit_with(
            INTERNAL_ERROR,
            {"error": str(exc), "exit_code": INTERNAL_ERROR},
            json_mode=args.json,
            quiet=args.quiet,
        )
    if report.verdict == "PASS":
        code = PASS
    else:
        code = INFRA_INCOMPLETE
    return _exit_with(code, report, json_mode=args.json, quiet=args.quiet)


def _cmd_install_tools(args: argparse.Namespace) -> int:
    """Handle the ``install-tools`` sub-command."""
    repo = Path(args.repo).resolve()
    try:
        result = install_tools(repo)
    except FileNotFoundError:
        return _exit_with(
            UNSUPPORTED,
            {"error": "tool version config not found", "exit_code": UNSUPPORTED},
            json_mode=args.json,
            quiet=args.quiet,
        )
    except Exception as exc:  # noqa: BLE001
        return _exit_with(
            INTERNAL_ERROR,
            {"error": str(exc), "exit_code": INTERNAL_ERROR},
            json_mode=args.json,
            quiet=args.quiet,
        )
    code = PASS if result.status == "success" else FAIL
    return _exit_with(code, result, json_mode=args.json, quiet=args.quiet)


def _cmd_audit_ignores(args: argparse.Namespace) -> int:
    """Handle the ``audit-ignores`` sub-command (stub).

    Audits the ``.quality-gate-ignores`` file and prints outdated entries.
    """
    repo = Path(args.repo).resolve()
    data = {
        "repository": str(repo),
        "ignores": [],
        "message": "stub: not yet implemented",
    }
    return _exit_with(PASS, data, json_mode=args.json, quiet=args.quiet)


def _cmd_configure(args: argparse.Namespace) -> int:
    """Handle the ``configure`` sub-command (stub).

    Writes a default ``.quality-gate.yaml`` config into *repo*.
    """
    repo = Path(args.repo).resolve()
    data = {
        "repository": str(repo),
        "message": "stub: not yet implemented",
    }
    return _exit_with(PASS, data, json_mode=args.json, quiet=args.quiet)


def _cmd_layer(args: argparse.Namespace) -> int:
    """Handle a layer sub-command (layer1, layer2, layer3a, layer3b, layer4)."""
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        return _exit_with(
            UNSUPPORTED,
            {"error": f"repository not found: {repo}", "exit_code": UNSUPPORTED},
            json_mode=args.json,
            quiet=args.quiet,
        )
    layer_id = getattr(args, "_layer_id", "3a")
    layer_name = f"L{layer_id}".upper()
    try:
        detection = detect(repo, force=args.force)
    except Exception as exc:  # noqa: BLE001
        return _exit_with(
            INTERNAL_ERROR,
            {"error": str(exc), "exit_code": INTERNAL_ERROR},
            json_mode=args.json,
            quiet=args.quiet,
        )
    work_dir = repo / "_quality-gate" / "work"
    try:
        layer_result = run_layer(
            language=detection.language,
            layer=layer_name,
            repo=repo,
            work_dir=work_dir,
            env={},
        )
    except Exception as exc:  # noqa: BLE001
        return _exit_with(
            INTERNAL_ERROR,
            {"error": str(exc), "exit_code": INTERNAL_ERROR},
            json_mode=args.json,
            quiet=args.quiet,
        )
    code = PASS if layer_result.passed else FAIL
    return _exit_with(code, layer_result, json_mode=args.json, quiet=args.quiet)


def _cmd_all(args: argparse.Namespace) -> int:
    """Handle the ``all`` sub-command (run every layer)."""
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        return _exit_with(
            UNSUPPORTED,
            {"error": f"repository not found: {repo}", "exit_code": UNSUPPORTED},
            json_mode=args.json,
            quiet=args.quiet,
        )
    try:
        detection = detect(repo, force=args.force)
    except Exception as exc:  # noqa: BLE001
        return _exit_with(
            INTERNAL_ERROR,
            {"error": str(exc), "exit_code": INTERNAL_ERROR},
            json_mode=args.json,
            quiet=args.quiet,
        )
    try:
        result = dispatch_full(detection, {"work_dir": str(repo / "_quality-gate" / "work")})
    except Exception as exc:  # noqa: BLE001
        return _exit_with(
            INTERNAL_ERROR,
            {"error": str(exc), "exit_code": INTERNAL_ERROR},
            json_mode=args.json,
            quiet=args.quiet,
        )
    # Determine overall pass: all layers passed
    all_passed = all(lr.passed for lr in result.layers)
    code = PASS if all_passed else FAIL
    return _exit_with(code, result, json_mode=args.json, quiet=args.quiet)


def _cmd_checkpoint(args: argparse.Namespace) -> int:
    """Handle the ``checkpoint`` sub-command."""
    repo = Path(args.repo).resolve()
    output = Path(args.output) if args.output else repo / "_quality-gate" / "checkpoint.json"
    try:
        detection = detect(repo, force=args.force)
    except Exception as exc:  # noqa: BLE001
        return _exit_with(
            INTERNAL_ERROR,
            {"error": str(exc), "exit_code": INTERNAL_ERROR},
            json_mode=args.json,
            quiet=args.quiet,
        )
    runtime_info = _asdict(detection.runtime) if detection.runtime else {}
    checkpoint_data = build_checkpoint(
        layer_results=[],
        runtime=runtime_info,
        detection=_asdict(detection),
    )
    try:
        write_checkpoint(output, checkpoint_data)
    except Exception as exc:  # noqa: BLE001
        return _exit_with(
            INTERNAL_ERROR,
            {"error": str(exc), "exit_code": INTERNAL_ERROR},
            json_mode=args.json,
            quiet=args.quiet,
        )
    return _exit_with(PASS, {"checkpoint": str(output), "timestamp": checkpoint_data.get("timestamp")}, json_mode=args.json, quiet=args.quiet)


# ------------------------------------------------------------------
# Parser builder
# ------------------------------------------------------------------

_UNIVERSAL_FLAGS: list[str] = [
    "--config",
    "--log-level",
    "--quiet",
    "--json",
    "--concurrency",
    "--only",
    "--allow-ramp",
]


def _add_universal_flags(parser: argparse.ArgumentParser) -> None:
    """Attach global/universal flags to an argument parser."""
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to quality-gate config file",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        default=False,
        help="Suppress non-JSON output",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output results as JSON",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Max concurrent workers (default: 1)",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="Comma-separated list of tools to run",
    )
    parser.add_argument(
        "--allow-ramp",
        action="store_true",
        default=False,
        help="Allow MSI < 100 with override file",
    )


def _add_subparser_flags(parser: argparse.ArgumentParser) -> None:
    """Attach JSON-relevant flags to a subparser.

    These flags are needed on every subparser because argparse does not
    support global flags that appear *after* the subcommand name.
    """
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output results as JSON",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        default=False,
        help="Bypass caches",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to quality-gate config file",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Max concurrent workers (default: 1)",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="Comma-separated list of tools to run",
    )
    parser.add_argument(
        "--allow-ramp",
        action="store_true",
        default=False,
        help="Allow MSI < 100 with override file",
    )


def build_parser(argv: list[str] | None = None) -> argparse.ArgumentParser:
    """Build and return the CLI argument parser.

    Parameters
    ----------
    argv:
        If provided, parse from this list instead of ``sys.argv``.
    """
    parser = argparse.ArgumentParser(
        prog="harness-quality-gate",
        description="Polyglot quality gate for code repositories",
    )
    _add_universal_flags(parser)

    sub = parser.add_subparsers(dest="command", required=True)

    # -- detect --
    detect_p = sub.add_parser("detect", help="Language detection for a repository")
    detect_p.add_argument("repo", nargs="?", default=".", help="Path to the repository root")
    _add_subparser_flags(detect_p)

    # -- doctor --
    doctor_p = sub.add_parser("doctor", help="Tool diagnosis — check required tools")
    doctor_p.add_argument("repo", nargs="?", default=".", help="Path to the repository root")
    _add_subparser_flags(doctor_p)

    # -- install-tools --
    install_p = sub.add_parser("install-tools", help="Install PHP gate tools via composer")
    install_p.add_argument("repo", nargs="?", default=".", help="Path to the repository root")
    _add_subparser_flags(install_p)

    # -- audit-ignores --
    audit_p = sub.add_parser("audit-ignores", help="Audit quality-gate ignore entries")
    audit_p.add_argument("repo", nargs="?", default=".", help="Path to the repository root")
    _add_subparser_flags(audit_p)

    # -- configure --
    config_p = sub.add_parser("configure", help="Generate default quality-gate config")
    config_p.add_argument("repo", nargs="?", default=".", help="Path to the repository root")
    _add_subparser_flags(config_p)

    # -- layer sub-commands (layer1, layer2, layer3a, layer3b, layer4) --
    _LAYER_MAP: dict[str, str] = {
        "layer1": "1",
        "layer2": "2",
        "layer3a": "3a",
        "layer3b": "3b",
        "layer4": "4",
    }
    for subcmd, layer_id in _LAYER_MAP.items():
        p = sub.add_parser(subcmd, help=f"Run Layer {layer_id} quality check")
        p.add_argument("repo", nargs="?", default=".", help="Path to the repository root")
        _add_subparser_flags(p)
        p.set_defaults(_layer_id=layer_id)

    # -- all --
    all_p = sub.add_parser("all", help="Run all quality-gate layers")
    all_p.add_argument("repo", nargs="?", default=".", help="Path to the repository root")
    _add_subparser_flags(all_p)

    # -- checkpoint --
    ckpt_p = sub.add_parser("checkpoint", help="Write a Checkpoint v2 summary")
    ckpt_p.add_argument("repo", nargs="?", default=".", help="Path to the repository root")
    ckpt_p.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output path for checkpoint JSON (default: repo/_quality-gate/checkpoint.json)",
    )
    _add_subparser_flags(ckpt_p)

    return parser


# ------------------------------------------------------------------
# Exception -> exit-code mapping (NFR-15)
# ------------------------------------------------------------------

_EXIT_MAP: dict[type[Exception], int] = {
    ConfigInvalid: CONFIG_INVALID,
    FileNotFoundError: UNSUPPORTED,
}


def _map_exit(exc: Exception) -> int:
    """Map an exception class to the appropriate NFR-15 exit code."""
    for exc_type, code in _EXIT_MAP.items():
        if isinstance(exc, exc_type):
            return code
    return INTERNAL_ERROR


# ------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
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
    if argv is None:
        argv = list(sys.argv[1:])

    parser = build_parser(argv)
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        # argparse calls sys.exit on error / --help; propagate the code.
        return e.code if isinstance(e.code, int) else 1

    # Configure logging from universal flags
    log_level = getattr(args, "log_level", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Dispatch to sub-command handler
    dispatch_table: dict[str, Any] = {
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
    }

    handler = dispatch_table.get(args.command)
    if handler is None:
        parser.print_help(sys.stderr)
        return UNSUPPORTED

    try:
        return handler(args)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    except Exception as exc:  # noqa: BLE001
        code = _map_exit(exc)
        return _exit_with(
            code,
            {"error": str(exc), "exit_code": code},
            json_mode=args.json,
            quiet=args.quiet,
        )

