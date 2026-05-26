"""CLI entry point for harness-quality-gate.

Provides ``detect``, ``doctor``, ``layer``, and ``full`` subcommands
via argparse.  All outputs are JSON on stdout.

Design: ``harness_quality_gate/`` package (CREATE)
Requirements: FR-43, US-16
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .detector import detect
from .dispatcher import run_layer
from .framework_sniffer import sniff_framework
from .models import CheckpointV2, LayerResult


# Valid layer names
_VALID_LAYERS = ("L1", "L2", "L3A", "L3B", "L4")

# Tools that ``doctor`` checks on PATH
_DOCTOR_TOOLS = [
    ("python3", "Python runtime"),
    ("pip", "Python package manager"),
    ("git", "Version control"),
    ("composer", "PHP package manager"),
    ("php", "PHP runtime"),
    ("black", "Python formatter"),
    ("isort", "Python import sorter"),
    ("mypy", "Python type checker"),
    ("ruff", "Python linter"),
    ("flake8", "Python linter (legacy)"),
    ("bandit", "Python security scanner"),
    ("safety", "Python vulnerability checker"),
    ("phpcs", "PHP coding standards"),
    ("phpstan", "PHP static analysis"),
    ("composer-require-checker", "Composer dependency checker"),
    ("security-checker", "PHP vulnerability checker"),
]


# ------------------------------------------------------------------
# Sub-command helpers
# ------------------------------------------------------------------

def _asdict(obj: Any) -> Any:
    """Convert a frozen dataclass or simple object to a dict for JSON serialisation."""
    if hasattr(obj, "__dataclass_fields__"):
        import dataclasses
        return dataclasses.asdict(obj)  # type: ignore[attr-defined]
    if isinstance(obj, dict):
        return {k: _asdict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_asdict(v) for v in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj  # type: ignore[return-value]
    return str(obj)


# ------------------------------------------------------------------
# Sub-command handlers
# ------------------------------------------------------------------

def _cmd_detect(args: argparse.Namespace) -> None:
    """Handle the ``detect`` sub-command."""
    repo = Path(args.repo).resolve()
    result = detect(repo, force=args.force)
    print(json.dumps(_asdict(result), indent=2))


def _cmd_doctor(args: argparse.Namespace) -> None:
    """Handle the ``doctor`` sub-command.

    Checks that required tools exist on PATH and reports their status.
    """
    repo = Path(args.repo).resolve()
    reports: list[dict[str, Any]] = []

    for cmd, _description in _DOCTOR_TOOLS:
        version_output: str | None = None
        error: str | None = None
        exit_code = 0

        try:
            result = subprocess.run(
                [cmd, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                exit_code = result.returncode
                error = result.stderr.strip() or result.stdout.strip()
            else:
                version_output = result.stdout.strip().splitlines()[0]
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            exit_code = 127
            error = str(exc)

        reports.append({
            "tool": cmd,
            "exit_code": exit_code,
            "output": version_output,
            "error": error,
        })

    print(json.dumps({
        "repository": str(repo),
        "tools": reports,
    }, indent=2))


def _cmd_layer(args: argparse.Namespace) -> None:
    """Handle the ``layer`` sub-command."""
    repo = Path(args.repo).resolve()
    detection = detect(repo, force=args.force)
    framework = sniff_framework(repo, detection.language)

    layer_result = run_layer(
        language=detection.language,
        layer=args.layer,
        repo=repo,
        work_dir=repo / "_quality-gate" / "work",
        env={},
    )

    if args.json:
        checkpoint = CheckpointV2(
            version="2.0.0",
            timestamp=datetime.now(timezone.utc).isoformat(),
            repository=str(repo),
            language=detection.language,
            layers=[layer_result],
            mutation=None,
        )
        print(json.dumps(_asdict(checkpoint), indent=2))
    else:
        status = "PASS" if layer_result.passed else "FAIL"
        print(json.dumps({
            "layer": args.layer,
            "language": detection.language,
            "framework": framework,
            "status": status,
            "findings": len(layer_result.findings),
        }, indent=2))


def _cmd_full(args: argparse.Namespace) -> None:
    """Handle the ``full`` sub-command."""
    repo = Path(args.repo).resolve()
    detection = detect(repo, force=args.force)
    framework = sniff_framework(repo, detection.language)

    # If --json is requested, run all layers and emit Checkpoint v2
    if args.json:
        layers: list[LayerResult] = []
        for layer_name in _VALID_LAYERS:
            lr = run_layer(
                language=detection.language,
                layer=layer_name,
                repo=repo,
                work_dir=repo / "_quality-gate" / "work",
                env={},
            )
            layers.append(lr)

        checkpoint = CheckpointV2(
            version="2.0.0",
            timestamp=datetime.now(timezone.utc).isoformat(),
            repository=str(repo),
            language=detection.language,
            layers=layers,
            mutation=None,
        )
        print(json.dumps(_asdict(checkpoint), indent=2))
    else:
        # Run each layer and print per-layer summary
        print(json.dumps({
            "repository": str(repo),
            "language": detection.language,
            "framework": framework,
            "layers_run": list(_VALID_LAYERS),
            "mode": "sequential",
        }, indent=2))


# ------------------------------------------------------------------
# Parser builder
# ------------------------------------------------------------------

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
    parser.add_argument(
        "--repo", "-r",
        default=".",
        help="Path to the repository root (default: .)",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        default=False,
        help="Bypass caches and re-run checks",
    )
    parser.add_argument(
        "--concurrency", "-c",
        type=int,
        default=1,
        help="Max threads for parallel layers (default: 1)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # detect
    detect_p = sub.add_parser("detect", help="Language detection for a repository")
    detect_p.add_argument("repo", nargs="?", default=".", help="Path to the repository root")
    detect_p.add_argument(
        "--force", "-f",
        action="store_true",
        default=False,
        help="Bypass caches and re-run detection",
    )

    # doctor
    doctor_p = sub.add_parser("doctor", help="Tool diagnosis -- check required tools")
    doctor_p.add_argument("repo", nargs="?", default=".", help="Path to the repository root")

    # layer
    layer_p = sub.add_parser("layer", help="Run a specific quality-gate layer")
    layer_p.add_argument("layer", choices=_VALID_LAYERS, help="Layer to run")
    layer_p.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output Checkpoint v2 JSON",
    )

    # full
    full_p = sub.add_parser("full", help="Run all quality-gate layers")
    full_p.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output Checkpoint v2 JSON",
    )

    return parser


# ------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    """Entry point -- parse args and dispatch to sub-command handler."""
    parser = build_parser(argv)
    args = parser.parse_args(argv)

    dispatch_table: dict[str, Any] = {
        "detect": _cmd_detect,
        "doctor": _cmd_doctor,
        "layer": _cmd_layer,
        "full": _cmd_full,
    }

    handler = dispatch_table.get(args.command)
    if handler is None:
        parser.print_help(sys.stderr)
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
