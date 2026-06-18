"""Vulture dead-code detector adapter.

Wraps plain ``vulture`` text output into :class:`Finding[]`.

vulture has no JSON output mode; it prints one finding per line::

    path.py:12: unused function 'helper' (60% confidence)

The previous implementation passed ``--format json`` (a nonexistent flag,
usage error -> empty stdout) and parsed JSON the tool never emits — the
L4 dead-code gate was vacuous (self-eval F8).

Design: Component Responsibilities / vulture_adapter.
Requirements: FR-29, US-3.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping

from ...bootstrap import resolve_tool, ToolNotAvailable
from ...models import Finding
from ..base import ToolAdapter, ToolInvocation, source_targets

_LINE_RE = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+): (?P<desc>.+?) \(\d+% confidence\)\s*$"
)


class VultureAdapter(ToolAdapter):
    """Wraps ``vulture`` and parses its text output into dead-code findings."""

    _name = "vulture"

    @property
    def name(self) -> str:
        return self._name

    def version(self, repo: Path, env: Mapping[str, str] | None = None) -> str:
        try:
            binary = str(resolve_tool("vulture", repo))
        except ToolNotAvailable:
            raise RuntimeError("vulture not found on PATH or .venv")
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
        try:
            binary = str(resolve_tool("vulture", repo))
        except ToolNotAvailable:
            return ToolInvocation(stderr="vulture not found on PATH or .venv", exitcode=3)
        # Scan the source dirs only (src/ or root packages, never tests);
        # the whole repo would sweep mutation artifacts too (H10/F2).
        targets = source_targets(repo, "src") or [str(repo)]
        cmd = [binary]
        if args:
            cmd.extend(args)
        cmd.extend(targets)
        return self._run(cmd, cwd=repo, env=env, timeout=timeout)

    def parse(  # type: ignore[override]
        self,
        stdout: str,
        *_compat: object,
    ) -> list[Finding]:
        """Parse vulture text lines into :class:`Finding` objects.

        Non-empty output where no line matches the vulture format yields a
        single parse-error finding — silently returning ``[]`` would hide
        real findings behind format drift (self-eval F8).
        """
        findings: list[Finding] = []
        if not stdout.strip():
            return findings

        for line in stdout.splitlines():
            # rstrip() redundant: regex ends with \s*$, absorbing trailing ws.
            # Tipo C equivalente: lstrip anche funziona perche' il regex matcha
            # lo spazio finale.
            m = _LINE_RE.match(line.rstrip())  # pragma: no mutate
            if m is None:
                continue
            path = m.group("path")
            line_no = m.group("line")
            desc = m.group("desc")
            findings.append(
                Finding(
                    node=path,
                    severity="warning",
                    message=f"{path}:{line_no} — {desc}",
                    fix_hint=f"Remove dead code at {path}:{line_no}: {desc}",
                    tool="vulture",
                    layer="L4",
                    language="python",
                    rule_id="dead-code",
                )
            )

        if not findings:
            findings.append(
                Finding(
                    node="vulture",
                    severity="error",
                    message="vulture produced output with no parseable findings",
                    fix_hint="Run vulture manually in the repo to inspect "
                             "the output (usage error or format drift).",
                    tool="vulture",
                    layer="L4",
                    language="python",
                    rule_id="parse-error",
                )
            )
        return findings
