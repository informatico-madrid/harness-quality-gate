"""Runtime and tool diagnosis for harness-quality-gate.

Per design.md `## Component Map` — `doctor` module.
Implements FR-26 (runtime check), FR-27 (tool check), FR-28 (PCOV+Xdebug),
FR-31 (tool path resolution order), US-11 (Spanish output).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from harness_quality_gate.models import DoctorReport, ToolCheckReport

# ---------------------------------------------------------------------------
# Spanish messages (FR-38 / TD-9: single dict, keyed by symbolic ID)
# ---------------------------------------------------------------------------
MSG: dict[str, str] = {
    "ok": "OK",
    "not_found": "no encontrado",
    "verdict_pass": "Infraestructura OK",
    "verdict_fail": "Infraestructura incompleta — fallos críticos",
    "section_runtimes": "Entorno de ejecución",
    "section_tools": "Herramientas PHP",
    "section_warnings": "Advertencias",
    "crit_missing": "Faltan herramientas críticas: {tools}",
    "pcov_xdebug": "PCOV y Xdebug ambos activos — desactive Xdebug para Infection",
    "missing_critical": "CRÍTICO",
    "missing_optional": "OPCIONAL",
    "tool_list": "  {tool}: {status} {version}",
}


def t(key: str, **kwargs: str) -> str:
    """Look up a Spanish message and apply str.format substitution."""
    text = MSG.get(key, key)
    return text.format(**kwargs)


# Critical tools per TD-4 / FR-26: hard-fail when absent
CRITICAL_TOOLS: tuple[str, ...] = (
    "phpstan",
    "phpmd",
    "php-cs-fixer",
    "psalm",
    "phpunit",
    "deptrac",
    "infection",
)


# ---------------------------------------------------------------------------
# Helper: resolve a tool path per FR-31
# ---------------------------------------------------------------------------

def _resolve_tool(
    name: str, repo: str | Path, composer_home: str | None = None,
) -> str | None:
    """Return the first path where *name* is found.

    Discovery order (FR-31):
    1. ``vendor/bin/<name>`` inside *repo*
    2. ``$COMPOSER_HOME/vendor/bin/<name>``
    3. ``which <name>``
    4. ``~/.cache/harness-quality-gate/bin/<name>.phar``
    """
    repo = str(repo)
    candidates: list[str] = []

    # 1. vendor/bin inside repo
    candidates.append(os.path.join(repo, "vendor", "bin", name))

    # 2. COMPOSER_HOME/vendor/bin
    if composer_home:
        candidates.append(
            os.path.join(composer_home, "vendor", "bin", name),
        )

    # 3. PATH
    candidates.append(str(name))  # shutil.which will handle this

    # 4. PHAR cache
    phar_path = os.path.expanduser(
        f"~/.cache/harness-quality-gate/bin/{name}.phar",
    )
    candidates.append(phar_path)

    for candidate in candidates:
        if candidate == name:
            # PATH lookup
            if shutil.which(name):
                return name
        else:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate

    return None


# ---------------------------------------------------------------------------
# Helper: run a version command and extract a version string
# ---------------------------------------------------------------------------

def _try_version(path: str | None, name: str) -> str:
    """Run *path* with --version and return the first line's version token."""
    if not path:
        return ""
    try:
        # Normalize: if it's just the bare name, let which handle it
        exe = path if os.sep in path or path.endswith(".phar") else name
        result = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout:
            first_line = result.stdout.strip().splitlines()[0]
            return first_line
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return ""


# ---------------------------------------------------------------------------
# Helper: check a single tool
# ---------------------------------------------------------------------------

def _check_tool(
    name: str, resolve: Any, repo: str | Path,
) -> ToolCheckReport:
    """Run a single tool and return a ToolCheckReport."""
    path = resolve(name, repo)
    if path:
        version_str = _try_version(path, name)
        exit_code = 0 if version_str else 0
        return ToolCheckReport(
            tool=name,
            exit_code=exit_code,
            output=version_str or None,
            error=None,
        )
    return ToolCheckReport(
        tool=name,
        exit_code=127,
        output=None,
        error=t("not_found"),
    )


# ---------------------------------------------------------------------------
# Helper: detect PHP extensions (PCOV + Xdebug)
# ---------------------------------------------------------------------------

def _detect_php_extensions() -> list[str]:
    """Return a list of warnings from PHP extension conflicts."""
    warnings: list[str] = []
    try:
        result = subprocess.run(
            ["php", "-m"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            loaded = result.stdout.splitlines()
            has_pcov = any(
                line.strip().lower() == "pcov" for line in loaded
            )
            has_xdebug = any(
                line.strip().lower().startswith("xdebug")
                for line in loaded
            )
            if has_pcov and has_xdebug:
                warnings.append(t("pcov_xdebug"))
    except (OSError, subprocess.TimeoutExpired):
        pass
    return warnings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run(
    repo: str | Path,
    json_mode: bool = False,  # noqa: FBT001, unused - kept for API compatibility
) -> DoctorReport:
    """Run runtime + tool diagnosis.

    Parameters
    ----------
    repo:
        Path to the repository root.
    json_mode:
        When *True*, emit parseable JSON to stdout and return early.

    Returns
    -------
    DoctorReport with the full diagnosis.
    """
    repo_str = str(repo)
    all_warnings: list[str] = []
    critical_missing: list[str] = []

    # -- Check critical tools --
    tools: list[ToolCheckReport] = []
    for tool_name in CRITICAL_TOOLS:
        tr = _check_tool(tool_name, _resolve_tool, repo_str)
        tools.append(tr)
        if tr.error == t("not_found"):
            critical_missing.append(tool_name)

    # -- Check PHP extensions --
    all_warnings.extend(_detect_php_extensions())

    # -- Check runtime versions --
    python_version = ""
    for cmd in ("python", "python3"):
        if shutil.which(cmd):
            python_version = _try_version(cmd, cmd)
            break

    php_version = ""
    if shutil.which("php"):
        php_version = _try_version("php", "php")

    composer_version = ""
    if shutil.which("composer"):
        composer_version = _try_version("composer", "composer")

    # -- Determine verdict --
    if critical_missing:
        verdict = "INFRA_INCOMPLETE"
    else:
        verdict = "PASS"

    report = DoctorReport(
        verdict=verdict,
        python_version=python_version,
        php_version=php_version,
        composer_version=composer_version,
        tools=tools,
        warnings=all_warnings,
    )

    # -- Output: delegate JSON printing to _exit_with in cli.py --
    if not json_mode:
        # Human-readable
        _print_human(report, critical_missing)
    return report


def asdict(report: DoctorReport) -> dict[str, Any]:
    """Convert DoctorReport to a JSON-serialisable dict."""
    return {
        "verdict": report.verdict,
        "python_version": report.python_version,
        "php_version": report.php_version,
        "composer_version": report.composer_version,
        "tools": [
            {
                "tool": t.tool,
                "exit_code": t.exit_code,
                "output": t.output,
                "error": t.error,
            }
            for t in report.tools
        ],
        "warnings": report.warnings,
    }


def _print_human(report: DoctorReport, critical_missing: list[str]) -> None:
    """Print the diagnosis in a human-readable format (Spanish)."""
    color_ok = "\033[92m"
    color_fail = "\033[91m"
    color_reset = "\033[0m"

    verdict_str = report.verdict
    if report.verdict == "PASS":
        verdict_str = t("verdict_pass")
    else:
        verdict_str = t("verdict_fail")

    print("=== Diagnóstico de Infraestructura ===")
    print(f"Veredicto: {verdict_str}")
    print()

    # Runtimes
    print(f"  {t('section_runtimes')}:")
    print(f"    python : {report.python_version or t('not_found')}")
    print(f"    php    : {report.php_version or t('not_found')}")
    print(f"    composer: {report.composer_version or t('not_found')}")
    print()

    # Tools
    print(f"  {t('section_tools')}:")
    for tr in report.tools:
        if tr.error:
            marker = f" {color_fail}{t('missing_critical')}{color_reset}"
            status = f"{tr.error}"
        else:
            marker = f" {color_ok}{t('ok')}{color_reset}"
            status = tr.output or t("ok")
        print(f"  {tr.tool}: {status}{marker}")
    print()

    # Warnings
    if report.warnings:
        print(f"  {t('section_warnings')}:")
        for w in report.warnings:
            print(f"    ⚠ {w}")
        print()

    # Missing critical summary
    if critical_missing:
        print(
            t("crit_missing", tools=", ".join(critical_missing)),
        )

    print()
