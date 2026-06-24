"""PCOV coverage adapter with Xdebug fallback.

Wraps ``php -m`` to detect which coverage driver is loaded.
If PCOV is absent but Xdebug is present, emits a WARNING and
falls back to ``xdebug`` as the driver name.

Design: Component Responsibilities / pcov_adapter, E11
Requirements: FR-28, US-11
"""

from __future__ import annotations

import glob
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Mapping

from ...models import Finding, LayerResult
from ..base import ToolAdapter, ToolInvocation

# reason: logger name mutation does not change observability; only the __name__ label differs.
# audited: 2026-06-04
logger = logging.getLogger(__name__)


class PcovAdapter(ToolAdapter):
    """Detects PCOV / Xdebug coverage driver via ``php -m``."""

    _name = "pcov"

    # -- abstract interface -----------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    def version(
        self,
        repo: Path,
        env: Mapping[str, str] | None = None,
    ) -> str:
        raise NotImplementedError("pcov version detection not implemented (POC)")

    def invoke(self, repo: Path, args: list[str], **_compat: object) -> ToolInvocation:
        raise NotImplementedError("pcov invocation not implemented (POC)")

    def parse(
        self,
        stdout: str,
        stderr: str,
        exitcode: int,
    ) -> list[Finding]:
        return []

    # -- public API -------------------------------------------------------

    def probe(self, repo: Path | None = None) -> str:
        """Detect active PHP coverage driver.

        Checks ``php -m`` for ``pcov`` first; if absent checks for
        ``xdebug``.  Raises ``RuntimeError`` when neither is found.

        Returns
            ``"pcov"`` when PCOV is loaded, ``"xdebug"`` when only
            Xdebug is present (with a WARNING), or raises if neither
            driver is available.
        """
        php = shutil.which("php")
        if php is None:
            raise RuntimeError("php not found on PATH")

        try:
            result = subprocess.run(
                [php, "-m"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"Failed to run ``php -m``: {exc}") from exc

        if result.returncode != 0:
            raise RuntimeError(
                f"``php -m`` failed (exit {result.returncode}): {result.stderr.strip()}"
            )

        loaded_modules: set[str] = set()
        for line in result.stdout.splitlines():
            stripped = line.strip().lower()
            if stripped:
                loaded_modules.add(stripped)

        has_pcov = "pcov" in loaded_modules
        has_xdebug = any(m.startswith("xdebug") for m in loaded_modules)

        if has_pcov:
            return "pcov"

        # PCOV not system-loaded: check for pcov.so in well-known locations.
        # This covers cases where pcov was extracted from the package but not
        # installed system-wide (e.g. /tmp/pcov-extract or /usr/lib/php/*/).
        so_candidates = [
            "/tmp/pcov-extract/usr/lib/php/*/pcov.so",
            "/usr/lib/php/*/pcov.so",
        ]
        for pattern in so_candidates:
            found = glob.glob(pattern)
            if found:
                logger.info("PCOV available as shared extension: %s", found[0])
                return "pcov"

        if has_xdebug:
            logger.warning(
                "PCOV not available; falling back to Xdebug as coverage driver"
            )
            return "xdebug"

        raise RuntimeError(
            "No coverage driver found — neither PCOV nor Xdebug is loaded"
        )

    def probe_layer_result(
        self,
        repo: Path,
        env: Mapping[str, str] | None = None,
    ) -> LayerResult:
        """Run ``probe()`` and return a ``LayerResult`` with driver info.

        When only Xdebug is detected a warning Finding is included so
        callers can surface the ``coverage_driver`` information.
        """
        try:
            driver = self.probe(repo)
        except (OSError, RuntimeError) as exc:
            return LayerResult(
                layer="L1",
                language="php",
                passed=False,
                findings=[
                    Finding(
                        node="pcov",
                        severity="error",
                        message=f"Coverage driver probe failed: {exc}",
                    )
                ],
                duration_sec=0.0,
            )

        findings: list[Finding] = []
        if driver == "xdebug":
            findings.append(
                Finding(
                    node="pcov",
                    severity="warning",
                    message=(
                        "coverage_driver=xdebug; "
                        "Xdebug is a debugger, not a coverage tool — "
                        "disable Xdebug and install PCOV for reliable mutation testing"
                    ),
                )
            )

        return LayerResult(
            layer="L1",
            language="php",
            passed=True,
            findings=findings,
            duration_sec=0.0,
        )
