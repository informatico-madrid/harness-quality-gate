"""Deptry dependency checker adapter.

Wraps ``deptry .`` into :class:`Finding[]`.

Design: Component Responsibilities / deptry_adapter.
Requirements: FR-29, US-3.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Mapping

from ...models import Finding
from ..base import ToolAdapter, ToolInvocation

# deptry >= 0.12 violation codes; DEP001 (imported but undeclared) is a
# packaging bug, the rest are hygiene (parity with the legacy severity map).
_CODE_SEVERITY = {"DEP001": "error"}


class DeptryAdapter(ToolAdapter):
    """Wraps ``deptry`` and parses JSON output into dependency findings."""

    _name = "deptry"

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        binary = shutil.which("deptry")
        if binary is None:
            raise RuntimeError("deptry not found on PATH")
        result = self._run([binary, "--version"], cwd=repo, env=env)
        return result.stdout.strip() or "unknown"

    def invoke(
        self,
        repo: Path,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 300.0,
    ) -> ToolInvocation:
        binary = shutil.which("deptry")
        if binary is None:
            return ToolInvocation(stderr="deptry not found on PATH", exitcode=3)
        # deptry only emits JSON via ``--json-output <file>`` (``--output``
        # does not exist — the usage error made this gate vacuous, F9).
        # Same temp-file pattern as the pytest JUnit report (H8).
        # Mutation artifacts are excluded explicitly (H10): deptry walks the
        # whole project and mutants/ holds a full copy of the sources.
        fd, json_name = tempfile.mkstemp(prefix="hqg-deptry-", suffix=".json")
        os.close(fd)
        json_path = Path(json_name)
        cmd = [binary, "--json-output", str(json_path),
               "--extend-exclude", "mutants",
               "--extend-exclude", r"\.mutmut", "."]
        if args:
            cmd.extend(args)
        try:
            result = self._run(cmd, cwd=repo, env=env, timeout=timeout)
            report = (
                json_path.read_bytes().decode()
                if json_path.exists() and json_path.stat().st_size
                else ""
            )
            return ToolInvocation(
                stdout=report,
                stderr=result.stderr,
                exitcode=result.exitcode,
                duration_seconds=result.duration_seconds,
            )
        finally:
            json_path.unlink(missing_ok=True)

    def parse(  # type: ignore[override]
        self,
        stdout: str,
        *_compat: object,
    ) -> list[Finding]:
        """Parse deptry JSON output into :class:`Finding` objects.

        Accepts the real deptry (>= 0.12) ``--json-output`` list format —
        ``[{"error": {"code", "message"}, "module", "location"}]`` — plus
        the legacy dict format
        ``{"errors": {"unused_imports": [...], ...}}`` for robustness.
        """
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return findings

        if isinstance(data, list):
            return self._parse_violation_list(data)

        if not isinstance(data, dict):
            return findings

        errors = (data.get("errors") or {}) if isinstance(data.get("errors"), dict) else {}

        category_severity = {
            "unused_imports": "warning",
            "missing_imports": "error",
            "incorrectly_placed_imports": "warning",
            "type_fragment_without_import": "warning",
        }

        for category, items in errors.items():
            severity = category_severity.get(category, "info")
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    module = item.get("module", item.get("name", ""))
                    filepath = item.get("filepath") or ""
                    line = item.get("line") or item.get("line_no") or 0
                    desc = f"{category}: {module}"
                    detail = desc
                    if filepath:
                        detail = f"{filepath}:{line}" if line else f"{filepath}"
                        detail += f" — {desc}"
                    node = filepath or module or "<unknown>"
                else:
                    # plain string entries carry no location data
                    module = str(item)
                    desc = f"{category}: {module}"
                    detail = desc
                    node = module or "<unknown>"

                findings.append(
                    Finding(
                        node=node,
                        severity=severity,
                        message=detail,
                        fix_hint=f"Review {category} for '{module}'",
                        tool="deptry",
                        layer="L4",
                        language="python",
                        rule_id=category,
                    )
                )

        return findings

    @staticmethod
    def _parse_violation_list(data: list) -> list[Finding]:
        """Parse the real deptry (>= 0.12) JSON list format (self-eval F9).

        Each item: ``{"error": {"code", "message"}, "module", "location":
        {"file", "line", "column"} | null}``.
        """
        findings: list[Finding] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            raw_error = item.get("error")
            error = raw_error if isinstance(raw_error, dict) else {}
            code = error.get("code") or "DEP"
            message = error.get("message") or ""
            module = item.get("module") or ""
            raw_loc = item.get("location")
            loc = raw_loc if isinstance(raw_loc, dict) else {}
            filepath = loc.get("file") or ""
            line = loc.get("line")

            detail = message
            if filepath:
                prefix = f"{filepath}:{line}" if line else filepath
                detail = f"{prefix} — {message}"

            findings.append(
                Finding(
                    node=filepath or module or "<unknown>",
                    severity=_CODE_SEVERITY.get(code, "warning"),
                    message=detail,
                    fix_hint=f"Review {code} for '{module}'",
                    tool="deptry",
                    layer="L4",
                    language="python",
                    rule_id=code,
                )
            )
        return findings
