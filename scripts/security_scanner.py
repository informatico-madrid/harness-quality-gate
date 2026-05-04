#!/usr/bin/env python3
"""
Unified Security Scanner for Quality Gate Layer 4.

Orchestrates multiple security tools and produces structured JSON output
compatible with the quality-gate checkpoint format.

Tools (by priority):
  REQUIRED:     bandit, safety/pip-audit, gitleaks
  RECOMMENDED:  semgrep, checkov, deptry, vulture
  OPTIONAL:     trivy (Docker images)

Usage:
  python3 security_scanner.py <project-root> [options]

Options:
  --tools <tool1,tool2,...>   Comma-separated list of tools to run (default: all available)
  --severity-threshold <level> Minimum severity to fail: critical, high, medium, low (default: high)
  --output <path>             Write JSON results to file (default: stdout)
  --skip <tool1,tool2,...>    Comma-separated list of tools to skip
  --config <path>             Path to quality-gate.yaml for thresholds
  --verbose                   Show tool stdout in real-time

Exit codes:
  0 = All scans PASS (or only warnings below threshold)
  1 = One or more scans FAIL (findings at or above severity threshold)
  2 = Configuration or runtime error
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def weight(self) -> int:
        return {Severity.CRITICAL: 4, Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1, Severity.INFO: 0}[self]


class ToolPriority(str, Enum):
    REQUIRED = "required"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"


@dataclass
class Finding:
    """Single security finding."""
    tool: str
    rule_id: str
    severity: Severity
    file: str
    line: int | None
    message: str
    category: str = ""
    cwe: str = ""
    confidence: str = ""
    confidence_score: float = 0.0  # Phase 2: composite confidence (0.0-1.0)
    is_duplicate: bool = False     # Phase 2: marked during dedup
    dedup_keep: bool = True        # Phase 2: True = primary finding, False = duplicate
    llm_verdict: str = ""          # Phase 3: TRUE_POSITIVE / FALSE_POSITIVE / NEEDS_CONSENSUS
    llm_reasoning: str = ""        # Phase 3: LLM explanation
    llm_fix_suggestion: str = ""   # Phase 3: LLM fix code


@dataclass
class ToolResult:
    """Result from a single security tool."""
    tool: str
    status: str  # PASS, FAIL, SKIPPED, ERROR
    priority: ToolPriority
    findings: list[Finding] = field(default_factory=list)
    raw_output: str = ""
    error_output: str = ""
    duration_s: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def severity_counts(self) -> dict[str, int]:
        counts = {s.value: 0 for s in Severity}
        for f in self.findings:
            counts[f.severity.value] += 1
        return counts


# ---------------------------------------------------------------------------
# CWE Mapping Table (bandit rule IDs → CWE IDs)
# ---------------------------------------------------------------------------

BANDIT_CWE_MAP: dict[str, str] = {
    "B608": "CWE-89",   # SQL injection
    "B105": "CWE-798",  # Hardcoded password
    "B106": "CWE-798",  # Hardcoded password function arg
    "B107": "CWE-798",  # Hardcoded password default arg
    "B108": "CWE-732",  # Insecure file permissions
    "B301": "CWE-502",  # Pickle deserialization
    "B302": "CWE-502",  # Marshal deserialization
    "B303": "CWE-328",  # Weak hash (MD5/SHA1)
    "B311": "CWE-338",  # Insecure random
    "B324": "CWE-327",  # Broken crypto algorithm
    "B506": "CWE-502",  # YAML unsafe load
    "B602": "CWE-78",   # Subprocess shell=True
    "B603": "CWE-78",   # Subprocess without shell=True
    "B605": "CWE-78",   # Starting process with shell=True
    "B607": "CWE-78",   # Starting process with partial path
    "B609": "CWE-78",   # Subprocess wildcard import
    "B612": "CWE-327",  # Log4j usage
    "B701": "CWE-94",   # Jinja2 autoescape=False
    "B702": "CWE-94",   # Use of mako templates
    "B703": "CWE-94",   # Django mark_safe
}

# Semgrep rule ID prefix → CWE mapping (for custom rules)
SEMGREP_CWE_MAP: dict[str, str] = {
    "ha-eval-exec-usage": "CWE-94",
    "ha-yaml-unsafe-load": "CWE-502",
    "ha-subprocess-shell": "CWE-78",
    "ha-pickle-usage": "CWE-502",
    "ha-insecure-tempfile": "CWE-377",
    "ha-http-url": "CWE-319",
    "ha-log-sensitive-data": "CWE-532",
    "js-eval-usage": "CWE-94",
    "js-hardcoded-secret": "CWE-798",
    "js-http-url": "CWE-319",
    "js-sql-injection": "CWE-89",
    "js-command-injection": "CWE-78",
    "js-yaml-unsafe-load": "CWE-502",
    "js-jwt-weak-algorithm": "CWE-327",
    "js-path-traversal": "CWE-22",
    "js-insecure-random": "CWE-338",
    "js-disabled-tls-verify": "CWE-295",
    "js-prototype-pollution": "CWE-1321",
    "js-redos-vulnerable-regex": "CWE-1333",
    "js-uncaught-promise-auth": "CWE-755",
}

GITLEAKS_CWE = "CWE-798"  # All gitleaks findings are hardcoded credentials


def resolve_cwe(finding: Finding) -> str:
    """Resolve a finding to its CWE ID."""
    # 1. If CWE already set on the finding, use it
    if finding.cwe:
        return finding.cwe

    # 2. Bandit rule ID mapping
    if finding.tool == "bandit" and finding.rule_id in BANDIT_CWE_MAP:
        return BANDIT_CWE_MAP[finding.rule_id]

    # 3. Semgrep custom rule mapping
    if finding.tool == "semgrep":
        # Check exact match first
        if finding.rule_id in SEMGREP_CWE_MAP:
            return SEMGREP_CWE_MAP[finding.rule_id]
        # Check prefix match (semgrep prepends config path)
        for rule_prefix, cwe in SEMGREP_CWE_MAP.items():
            if finding.rule_id.endswith(rule_prefix):
                return cwe

    # 4. Gitleaks
    if finding.tool == "gitleaks":
        return GITLEAKS_CWE

    # 5. Safety/pip-audit
    if finding.tool in ("safety", "pip-audit"):
        return "CWE-1104"  # Use of unmaintained/vulnerable third party component

    # 6. Fallback: unknown CWE
    return "CWE-UNKNOWN"


# ---------------------------------------------------------------------------
# Phase 2: CWE Deduplication + Confidence Scoring
# ---------------------------------------------------------------------------

def dedup_findings(results: list[ToolResult], line_tolerance: int = 5) -> list[ToolResult]:
    """Deduplicate findings across tools based on CWE + file + line proximity.

    When two findings share the same CWE and file with overlapping line ranges,
    keep the one from the higher-priority tool (REQUIRED > RECOMMENDED > OPTIONAL),
    or the higher severity if same priority.
    """
    # Collect all findings with their CWE resolved
    all_findings: list[tuple[Finding, ToolResult, str]] = []
    for result in results:
        for finding in result.findings:
            cwe = resolve_cwe(finding)
            finding.cwe = cwe  # Update the finding in-place
            all_findings.append((finding, result, cwe))

    # Group by (file, cwe)
    from collections import defaultdict
    groups: dict[tuple[str, str], list[tuple[Finding, ToolResult, str]]] = defaultdict(list)
    for finding, result, cwe in all_findings:
        key = (finding.file, cwe)
        groups[key].append((finding, result, cwe))

    # For each group, find duplicates
    for (file, cwe), group in groups.items():
        if len(group) <= 1:
            continue

        # Sort by priority (REQUIRED first) then severity (highest first)
        priority_order = {ToolPriority.REQUIRED: 0, ToolPriority.RECOMMENDED: 1, ToolPriority.OPTIONAL: 2}
        group.sort(key=lambda x: (
            priority_order.get(x[1].priority, 99),
            -x[0].severity.weight,
        ))

        # Keep the first (highest priority/severity), mark rest as duplicates
        kept_line = group[0][0].line
        for i, (finding, result, _) in enumerate(group):
            if i == 0:
                finding.dedup_keep = True
                finding.is_duplicate = False
            else:
                # Check line proximity
                if kept_line and finding.line and abs(finding.line - kept_line) <= line_tolerance:
                    finding.is_duplicate = True
                    finding.dedup_keep = False
                else:
                    # Same CWE, same file, but different location — not a duplicate
                    finding.dedup_keep = True
                    finding.is_duplicate = False

    return results


def compute_confidence_scores(
    results: list[ToolResult],
    cross_validation_bonus: float = 0.3,
    known_pattern_bonus: float = 0.2,
) -> list[ToolResult]:
    """Compute confidence score for each finding.

    confidence = base_score × cross_validation_multiplier

    base_score: CRITICAL=1.0, HIGH=0.9, MEDIUM=0.7, LOW=0.5, INFO=0.3
    cross_validation: +0.3 if ≥2 tools report same CWE in same file (capped at 1.0)
    known_pattern: +0.2 if in known-vulnerable pattern (capped at 1.0)
    """
    # Build lookup: (file, cwe) → count of tools reporting
    from collections import defaultdict
    cwe_file_counts: dict[tuple[str, str], set[str]] = defaultdict(set)
    for result in results:
        for finding in result.findings:
            if finding.cwe and not finding.is_duplicate:
                cwe_file_counts[(finding.file, finding.cwe)].add(result.tool)

    # Known vulnerable patterns (CWEs that are commonly exploitable)
    KNOWN_EXPLOITABLE_CWES = {
        "CWE-89",   # SQL injection
        "CWE-78",   # OS command injection
        "CWE-94",   # Code injection
        "CWE-502",  # Deserialization
        "CWE-798",  # Hardcoded credentials
    }

    # Compute scores
    severity_base = {
        Severity.CRITICAL: 1.0,
        Severity.HIGH: 0.9,
        Severity.MEDIUM: 0.7,
        Severity.LOW: 0.5,
        Severity.INFO: 0.3,
    }

    for result in results:
        for finding in result.findings:
            if finding.is_duplicate:
                finding.confidence_score = 0.0
                continue

            base = severity_base.get(finding.severity, 0.5)

            # Cross-validation multiplier
            key = (finding.file, finding.cwe)
            tool_count = len(cwe_file_counts.get(key, set()))
            multiplier = 1.0
            if tool_count >= 2:
                multiplier += cross_validation_bonus

            # Known pattern bonus
            if finding.cwe in KNOWN_EXPLOITABLE_CWES:
                multiplier += known_pattern_bonus

            # Cap at 1.0
            finding.confidence_score = min(base * multiplier, 1.0)

    return results


def get_unique_findings(results: list[ToolResult], min_confidence: float = 0.0) -> list[Finding]:
    """Get all unique (non-duplicate) findings with confidence ≥ min_confidence."""
    findings = []
    for result in results:
        for finding in result.findings:
            if not finding.is_duplicate and finding.confidence_score >= min_confidence:
                findings.append(finding)
    return findings


@dataclass
class ScanResult:
    """Aggregated result from all security tools."""
    timestamp: str
    project_root: str
    overall_pass: bool = True
    severity_threshold: str = "high"
    confidence_threshold: float = 0.7
    tools: list[ToolResult] = field(default_factory=list)
    phases_completed: list[str] = field(default_factory=list)
    findings_deduplicated: int = 0
    findings_false_positive: int = 0
    findings_confirmed: int = 0
    findings_uncertain: int = 0

    @property
    def total_findings(self) -> int:
        return sum(len(t.findings) for t in self.tools)

    @property
    def unique_findings(self) -> int:
        return sum(
            1 for t in self.tools for f in t.findings
            if not f.is_duplicate
        )

    @property
    def findings_by_severity(self) -> dict[str, int]:
        counts = {s.value: 0 for s in Severity}
        for t in self.tools:
            for f in t.findings:
                if not f.is_duplicate:
                    counts[f.severity.value] += 1
        return counts

    def to_checkpoint_dict(self) -> dict[str, Any]:
        """Convert to quality-gate checkpoint format."""
        layer4: dict[str, Any] = {
            "PASS": self.overall_pass,
            "phases_completed": self.phases_completed,
            "findings_deduplicated": self.findings_deduplicated,
            "findings_false_positive": self.findings_false_positive,
            "findings_confirmed": self.findings_confirmed,
            "findings_uncertain": self.findings_uncertain,
        }
        summary_additions: dict[str, Any] = {
            "security_total_findings": self.total_findings,
            "security_unique_findings": self.unique_findings,
            "security_findings_by_severity": self.findings_by_severity,
            "security_tools_run": [],
            "security_tools_skipped": [],
            "security_tools_error": [],
        }
        for t in self.tools:
            entry: dict[str, Any] = {
                "status": t.status,
                "priority": t.priority.value,
                "duration_s": round(t.duration_s, 2),
                "findings_count": len([f for f in t.findings if not f.is_duplicate]),
                "severity_counts": t.severity_counts,
                "metadata": t.metadata,
            }
            if t.findings:
                entry["details"] = [
                    {
                        "rule_id": f.rule_id,
                        "severity": f.severity.value,
                        "file": f.file,
                        "line": f.line,
                        "message": f.message,
                        "category": f.category,
                        "cwe": f.cwe,
                        "confidence_score": round(f.confidence_score, 2),
                        "llm_verdict": f.llm_verdict,
                    }
                    for f in t.findings
                    if not f.is_duplicate  # Skip duplicates in output
                ][:50]  # Cap at 50 findings per tool
            if t.status == "ERROR":
                entry["error"] = t.error_output[:500]
            layer4[t.tool] = entry

            if t.status in ("PASS", "FAIL"):
                summary_additions["security_tools_run"].append(t.tool)
            elif t.status == "SKIPPED":
                summary_additions["security_tools_skipped"].append(t.tool)
            elif t.status == "ERROR":
                summary_additions["security_tools_error"].append(t.tool)

        return {"layer4_security_defense": layer4, "summary_l4_additions": summary_additions}


# ---------------------------------------------------------------------------
# Tool runners
# ---------------------------------------------------------------------------

def _run(cmd: list[str], cwd: str, timeout: int = 300, verbose: bool = False) -> tuple[int, str, str, float]:
    """Run a subprocess and capture output."""
    import time
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.monotonic() - start
        if verbose:
            if proc.stdout:
                print(proc.stdout[:2000], file=sys.stderr)
        return proc.returncode, proc.stdout, proc.stderr, elapsed
    except FileNotFoundError:
        elapsed = time.monotonic() - start
        return -1, "", f"Tool not found: {cmd[0]}", elapsed
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        return -2, "", f"Timeout after {timeout}s", elapsed


def _severity_from_bandit(level: str) -> Severity:
    mapping = {"HIGH": Severity.HIGH, "MEDIUM": Severity.MEDIUM, "LOW": Severity.LOW}
    return mapping.get(level.upper(), Severity.INFO)


def _severity_from_safety(level: str) -> Severity:
    mapping = {"critical": Severity.CRITICAL, "high": Severity.HIGH, "medium": Severity.MEDIUM, "low": Severity.LOW}
    return mapping.get(level.lower(), Severity.HIGH)


def _severity_from_semgrep(level: str) -> Severity:
    mapping = {"ERROR": Severity.HIGH, "WARNING": Severity.MEDIUM, "INFO": Severity.LOW}
    return mapping.get(level.upper(), Severity.MEDIUM)


def _severity_from_checkov(level: str) -> Severity:
    mapping = {"CRITICAL": Severity.CRITICAL, "HIGH": Severity.HIGH, "MEDIUM": Severity.MEDIUM, "LOW": Severity.LOW}
    return mapping.get(level.upper(), Severity.MEDIUM)


def _severity_from_trivy(level: str) -> Severity:
    mapping = {"CRITICAL": Severity.CRITICAL, "HIGH": Severity.HIGH, "MEDIUM": Severity.MEDIUM, "LOW": Severity.LOW, "UNKNOWN": Severity.INFO}
    return mapping.get(level.upper(), Severity.MEDIUM)


# --- Bandit ---

def run_bandit(project_root: str, verbose: bool = False, config: dict | None = None) -> ToolResult:
    """Run bandit security linter on Python source code."""
    result = ToolResult(tool="bandit", status="SKIPPED", priority=ToolPriority.REQUIRED)

    # Determine target paths
    targets = []
    for candidate in ["custom_components", "src", "scripts"]:
        p = Path(project_root) / candidate
        if p.exists():
            targets.append(str(p))

    # Also scan root-level Python files
    for py_file in Path(project_root).glob("*.py"):
        targets.append(str(py_file))

    if not targets:
        result.status = "SKIPPED"
        result.error_output = "No Python source directories found"
        return result

    cmd = [
        sys.executable, "-m", "bandit",
        "-r", *targets,
        "-f", "json",
        "--severity-level", "low",
        "--confidence-level", "low",
    ]

    # Add config file if available
    bandit_config = Path(project_root) / ".bandit.yaml"
    if bandit_config.exists():
        cmd.extend(["-c", str(bandit_config)])

    rc, stdout, stderr, elapsed = _run(cmd, project_root, timeout=120, verbose=verbose)
    result.duration_s = elapsed

    if rc == -1:
        result.status = "SKIPPED"
        result.error_output = "bandit not installed. Install: pip install bandit"
        return result

    if rc == -2:
        result.status = "ERROR"
        result.error_output = stderr
        return result

    try:
        data = json.loads(stdout) if stdout.strip() else {}
        for issue in data.get("results", []):
            result.findings.append(Finding(
                tool="bandit",
                rule_id=issue.get("test_id", "UNKNOWN"),
                severity=_severity_from_bandit(issue.get("issue_severity", "LOW")),
                file=issue.get("filename", ""),
                line=issue.get("line_number"),
                message=issue.get("issue_text", ""),
                category=issue.get("test_name", ""),
                confidence=issue.get("issue_confidence", ""),
            ))
        result.metadata = {
            "files_scanned": len({f.file for f in result.findings}) if result.findings else "N/A",
            "metrics": data.get("metrics", {}),
        }
    except json.JSONDecodeError:
        result.error_output = f"Failed to parse bandit JSON output: {stdout[:500]}"

    return result


# --- Safety / pip-audit ---

def run_safety(project_root: str, verbose: bool = False, config: dict | None = None) -> ToolResult:
    """Run safety (or pip-audit as fallback) for dependency vulnerability scanning."""
    result = ToolResult(tool="safety", status="SKIPPED", priority=ToolPriority.REQUIRED)

    # Try safety first
    cmd = [sys.executable, "-m", "safety", "check", "--json"]
    # Try with requirements.txt if exists
    req_file = Path(project_root) / "requirements.txt"
    if req_file.exists():
        cmd = [sys.executable, "-m", "safety", "check", "-r", str(req_file), "--json"]

    rc, stdout, stderr, elapsed = _run(cmd, project_root, timeout=120, verbose=verbose)
    result.duration_s = elapsed

    if rc == -1:
        # Try pip-audit as fallback
        return _run_pip_audit_fallback(project_root, verbose, elapsed)

    if rc == -2:
        result.status = "ERROR"
        result.error_output = stderr
        return result

    try:
        # safety check --json outputs vulnerabilities as JSON array
        data = json.loads(stdout) if stdout.strip() else []
        if isinstance(data, dict):
            vulns = data.get("vulnerabilities", data.get("scanned", []))
        elif isinstance(data, list):
            vulns = data
        else:
            vulns = []

        for vuln in vulns:
            if isinstance(vuln, dict):
                result.findings.append(Finding(
                    tool="safety",
                    rule_id=vuln.get("vulnerability_id", vuln.get("id", "UNKNOWN")),
                    severity=_severity_from_safety(vuln.get("severity", "high")),
                    file="requirements.txt",
                    line=None,
                    message=vuln.get("advisory", vuln.get("description", "")),
                    category="dependency_vulnerability",
                ))
        result.metadata = {"tool": "safety", "vulnerabilities_found": len(result.findings)}
    except json.JSONDecodeError:
        # safety may output non-JSON on certain versions
        result.metadata = {"tool": "safety", "raw_output": stdout[:500]}

    return result


def _run_pip_audit_fallback(project_root: str, verbose: bool, elapsed: float) -> ToolResult:
    """Fallback to pip-audit if safety is not available."""
    result = ToolResult(tool="safety", status="SKIPPED", priority=ToolPriority.REQUIRED)

    cmd = [sys.executable, "-m", "pip_audit", "--format", "json"]
    rc, stdout, stderr, elapsed2 = _run(cmd, project_root, timeout=120, verbose=verbose)
    result.duration_s = elapsed + elapsed2

    if rc == -1:
        result.status = "SKIPPED"
        result.error_output = "Neither safety nor pip-audit installed. Install: pip install safety"
        return result

    if rc == -2:
        result.status = "ERROR"
        result.error_output = stderr
        return result

    try:
        data = json.loads(stdout) if stdout.strip() else {}
        deps = data.get("dependencies", [])
        for dep in deps:
            for vuln in dep.get("vulns", []):
                result.findings.append(Finding(
                    tool="pip-audit",
                    rule_id=vuln.get("id", "UNKNOWN"),
                    severity=Severity.HIGH,
                    file="requirements.txt",
                    line=None,
                    message=vuln.get("description", ""),
                    category="dependency_vulnerability",
                ))
        result.metadata = {"tool": "pip-audit", "vulnerabilities_found": len(result.findings)}
    except json.JSONDecodeError:
        result.metadata = {"tool": "pip-audit", "raw_output": stdout[:500]}

    return result


# --- Gitleaks ---

def run_gitleaks(project_root: str, verbose: bool = False, config: dict | None = None) -> ToolResult:
    """Run gitleaks to detect secrets and credentials in code."""
    result = ToolResult(tool="gitleaks", status="SKIPPED", priority=ToolPriority.REQUIRED)

    # Check if gitleaks is available
    gitleaks_path = shutil.which("gitleaks")
    if not gitleaks_path:
        result.status = "SKIPPED"
        result.error_output = "gitleaks not installed. Install: https://github.com/gitleaks/gitleaks#installing"
        return result

    report_path = Path(project_root) / "_bmad-output" / "quality-gate" / "gitleaks-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        gitleaks_path, "detect",
        "--source", project_root,
        "--report-format", "json",
        "--report-path", str(report_path),
        "--no-banner",
    ]

    # gitleaks exits with 1 if leaks found, 0 if clean
    rc, stdout, stderr, elapsed = _run(cmd, project_root, timeout=120, verbose=verbose)
    result.duration_s = elapsed

    if rc == -2:
        result.status = "ERROR"
        result.error_output = stderr
        return result

    try:
        if report_path.exists():
            with open(report_path) as f:
                leaks = json.load(f)
            for leak in leaks:
                result.findings.append(Finding(
                    tool="gitleaks",
                    rule_id=leak.get("RuleID", "UNKNOWN"),
                    severity=Severity.CRITICAL,  # Secrets are always critical
                    file=leak.get("File", ""),
                    line=leak.get("StartLine"),
                    message=f"Potential secret detected: {leak.get('RuleID', 'unknown rule')}",
                    category="secret_exposure",
                ))
            # Clean up report file
            report_path.unlink(missing_ok=True)
    except json.JSONDecodeError:
        result.error_output = "Failed to parse gitleaks report"

    result.metadata = {"secrets_found": len(result.findings)}
    return result


# --- Semgrep ---

def run_semgrep(project_root: str, verbose: bool = False, config: dict | None = None) -> ToolResult:
    """Run semgrep with security rules (OWASP + HA-specific)."""
    result = ToolResult(tool="semgrep", status="SKIPPED", priority=ToolPriority.RECOMMENDED)

    # Check if semgrep is available
    try:
        subprocess.run([sys.executable, "-m", "semgrep", "--version"], capture_output=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        result.status = "SKIPPED"
        result.error_output = "semgrep not installed. Install: pip install semgrep"
        return result

    # Build config: p/security-audit + p/owasp-top-ten + custom HA rules + JS rules
    configs = ["p/security-audit", "p/owasp-top-ten"]

    # Check for custom HA rules in skill references
    custom_rules = Path(__file__).parent.parent / "references" / "semgrep-ha-rules.yaml"
    if custom_rules.exists():
        configs.append(str(custom_rules))

    # Check for JS/TS rules in skill references
    js_rules = Path(__file__).parent.parent / "references" / "semgrep-js-rules.yaml"
    if js_rules.exists():
        configs.append(str(js_rules))

    # Check for project-level rules
    project_rules = Path(project_root) / ".semgrep" / "rules.yaml"
    if project_rules.exists():
        configs.append(str(project_rules))

    cmd = [
        sys.executable, "-m", "semgrep",
        "--config", ",".join(configs),
        "--json",
        "--quiet",
        project_root,
    ]

    rc, stdout, stderr, elapsed = _run(cmd, project_root, timeout=300, verbose=verbose)
    result.duration_s = elapsed

    if rc == -2:
        result.status = "ERROR"
        result.error_output = stderr
        return result

    try:
        data = json.loads(stdout) if stdout.strip() else {}
        for finding in data.get("results", []):
            result.findings.append(Finding(
                tool="semgrep",
                rule_id=finding.get("check_id", "UNKNOWN"),
                severity=_severity_from_semgrep(finding.get("extra", {}).get("severity", "WARNING")),
                file=finding.get("path", ""),
                line=finding.get("start", {}).get("line"),
                message=finding.get("extra", {}).get("message", ""),
                category=finding.get("extra", {}).get("metadata", {}).get("category", ""),
            ))
        result.metadata = {
            "rules_loaded": len(data.get("errors", [])) + len(data.get("results", [])),
            "paths_scanned": data.get("paths", {}).get("scanned", []),
        }
    except json.JSONDecodeError:
        result.error_output = f"Failed to parse semgrep JSON: {stdout[:500]}"

    return result


# --- Checkov ---

def run_checkov(project_root: str, verbose: bool = False, config: dict | None = None) -> ToolResult:
    """Run checkov for YAML/JSON configuration validation (HA config, Docker, etc.)."""
    result = ToolResult(tool="checkov", status="SKIPPED", priority=ToolPriority.RECOMMENDED)

    # Check if checkov is available
    try:
        subprocess.run([sys.executable, "-m", "checkov", "--version"], capture_output=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        result.status = "SKIPPED"
        result.error_output = "checkov not installed. Install: pip install checkov"
        return result

    # Scan the entire project directory
    cmd = [
        sys.executable, "-m", "checkov",
        "-d", project_root,
        "--framework", "dockerfile", "yaml", "json",
        "--output", "json",
        "--compact",
        "--quiet",
    ]

    # Skip directories that cause false positives
    skip_dirs = [".git", "__pycache__", "node_modules", ".venv", ".mypy_cache", "_bmad-output"]
    cmd.extend(["--skip-path", ",".join(skip_dirs)])

    rc, stdout, stderr, elapsed = _run(cmd, project_root, timeout=180, verbose=verbose)
    result.duration_s = elapsed

    if rc == -2:
        result.status = "ERROR"
        result.error_output = stderr
        return result

    try:
        # checkov outputs JSON with results structure
        data = json.loads(stdout) if stdout.strip() else {}
        results = data.get("results", {})

        for framework, checks in results.get("failed_checks", {}).items() if isinstance(results.get("failed_checks"), dict) else [("all", results.get("failed_checks", []))]:
            if isinstance(checks, list):
                for check in checks:
                    result.findings.append(Finding(
                        tool="checkov",
                        rule_id=check.get("check_id", "UNKNOWN"),
                        severity=_severity_from_checkov(check.get("severity", "MEDIUM")),
                        file=check.get("file_path", ""),
                        line=check.get("resource", ""),
                        message=check.get("check_name", ""),
                        category=check.get("check_type", framework),
                    ))
        result.metadata = {
            "passed_checks": len(results.get("passed_checks", [])),
            "failed_checks": len(result.findings),
            "skipped_checks": len(results.get("skipped_checks", [])),
        }
    except json.JSONDecodeError:
        result.error_output = f"Failed to parse checkov JSON: {stdout[:500]}"

    return result


# --- Deptry ---

def run_deptry(project_root: str, verbose: bool = False, config: dict | None = None) -> ToolResult:
    """Run deptry to check import consistency vs declared dependencies."""
    result = ToolResult(tool="deptry", status="SKIPPED", priority=ToolPriority.RECOMMENDED)

    # Check if deptry is available
    try:
        subprocess.run([sys.executable, "-m", "deptry", "--version"], capture_output=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        result.status = "SKIPPED"
        result.error_output = "deptry not installed. Install: pip install deptry"
        return result

    cmd = [sys.executable, "-m", "deptry", project_root, "--json", project_root]

    rc, stdout, stderr, elapsed = _run(cmd, project_root, timeout=120, verbose=verbose)
    result.duration_s = elapsed

    if rc == -2:
        result.status = "ERROR"
        result.error_output = stderr
        return result

    # deptry exits 0 if no issues, 1 if issues found
    # Parse output for missing/unused/transitive deps
    output = stdout + stderr
    missing_deps = []
    unused_deps = []
    transitive_deps = []

    for line in output.splitlines():
        line = line.strip()
        if "missing" in line.lower() and "dependenc" in line.lower():
            missing_deps.append(line)
        elif "unused" in line.lower() and "dependenc" in line.lower():
            unused_deps.append(line)
        elif "transitive" in line.lower():
            transitive_deps.append(line)

    for dep in missing_deps:
        result.findings.append(Finding(
            tool="deptry",
            rule_id="DEP001",
            severity=Severity.HIGH,
            file="pyproject.toml",
            line=None,
            message=f"Missing dependency: {dep}",
            category="missing_dependency",
        ))

    for dep in unused_deps:
        result.findings.append(Finding(
            tool="deptry",
            rule_id="DEP002",
            severity=Severity.MEDIUM,
            file="pyproject.toml",
            line=None,
            message=f"Unused dependency: {dep}",
            category="unused_dependency",
        ))

    for dep in transitive_deps:
        result.findings.append(Finding(
            tool="deptry",
            rule_id="DEP003",
            severity=Severity.LOW,
            file="pyproject.toml",
            line=None,
            message=f"Transitive dependency: {dep}",
            category="transitive_dependency",
        ))

    result.metadata = {
        "missing_deps": len(missing_deps),
        "unused_deps": len(unused_deps),
        "transitive_deps": len(transitive_deps),
    }

    return result


# --- Vulture ---

def run_vulture(project_root: str, verbose: bool = False, config: dict | None = None) -> ToolResult:
    """Run vulture to detect dead code."""
    result = ToolResult(tool="vulture", status="SKIPPED", priority=ToolPriority.RECOMMENDED)

    # Check if vulture is available
    try:
        subprocess.run([sys.executable, "-m", "vulture", "--version"], capture_output=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        result.status = "SKIPPED"
        result.error_output = "vulture not installed. Install: pip install vulture"
        return result

    # Determine target paths
    targets = []
    for candidate in ["custom_components", "src", "scripts"]:
        p = Path(project_root) / candidate
        if p.exists():
            targets.append(str(p))

    if not targets:
        result.status = "SKIPPED"
        result.error_output = "No Python source directories found"
        return result

    # Check for whitelist file
    whitelist = Path(project_root) / ".vulture-whitelist.py"

    cmd = [sys.executable, "-m", "vulture", *targets, "--min-confidence", "80"]
    if whitelist.exists():
        cmd.append(str(whitelist))

    rc, stdout, stderr, elapsed = _run(cmd, project_root, timeout=120, verbose=verbose)
    result.duration_s = elapsed

    if rc == -2:
        result.status = "ERROR"
        result.error_output = stderr
        return result

    # vulture outputs one finding per line: "file.py:42: Unused function 'foo' (60% confidence)"
    for line in (stdout + stderr).splitlines():
        line = line.strip()
        if not line or line.startswith("Found"):
            continue
        parts = line.split(":", 2)
        if len(parts) >= 3:
            file_path = parts[0].strip()
            try:
                line_num = int(parts[1].strip())
            except ValueError:
                line_num = None
            message = parts[2].strip()
            result.findings.append(Finding(
                tool="vulture",
                rule_id="DEAD001",
                severity=Severity.MEDIUM,
                file=file_path,
                line=line_num,
                message=message,
                category="dead_code",
            ))

    result.metadata = {"dead_code_items": len(result.findings)}
    return result


# --- Trivy ---

def run_trivy(project_root: str, verbose: bool = False, config: dict | None = None) -> ToolResult:
    """Run trivy to scan Docker images for CVEs (only if Dockerfile exists)."""
    result = ToolResult(tool="trivy", status="SKIPPED", priority=ToolPriority.OPTIONAL)

    # Check if Dockerfile exists
    dockerfile = Path(project_root) / "Dockerfile.custom"
    if not dockerfile.exists():
        dockerfile = Path(project_root) / "Dockerfile"
    if not dockerfile.exists():
        result.metadata = {"reason": "No Dockerfile found — skipped"}
        return result

    # Check if trivy is available
    trivy_path = shutil.which("trivy")
    if not trivy_path:
        result.status = "SKIPPED"
        result.error_output = "trivy not installed. Install: https://aquasecurity.github.io/trivy/latest/getting-started/installation/"
        return result

    # Scan the Dockerfile for misconfigurations
    cmd = [
        trivy_path, "config",
        "--format", "json",
        "--quiet",
        str(dockerfile.parent),
    ]

    rc, stdout, stderr, elapsed = _run(cmd, project_root, timeout=180, verbose=verbose)
    result.duration_s = elapsed

    if rc == -2:
        result.status = "ERROR"
        result.error_output = stderr
        return result

    try:
        data = json.loads(stdout) if stdout.strip() else {}
        for result_item in data.get("Results", []):
            for misconf in result_item.get("Misconfigurations", []):
                result.findings.append(Finding(
                    tool="trivy",
                    rule_id=misconf.get("AVDID", misconf.get("ID", "UNKNOWN")),
                    severity=_severity_from_trivy(misconf.get("Severity", "MEDIUM")),
                    file=misconf.get("Cause", {}).get("Provider", ""),
                    line=None,
                    message=misconf.get("Message", misconf.get("Title", "")),
                    category="docker_misconfiguration",
                ))
        result.metadata = {"dockerfile_scanned": str(dockerfile)}
    except json.JSONDecodeError:
        result.error_output = f"Failed to parse trivy JSON: {stdout[:500]}"

    return result


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

TOOL_RUNNERS = {
    "bandit": (run_bandit, ToolPriority.REQUIRED),
    "safety": (run_safety, ToolPriority.REQUIRED),
    "gitleaks": (run_gitleaks, ToolPriority.REQUIRED),
    "semgrep": (run_semgrep, ToolPriority.RECOMMENDED),
    "checkov": (run_checkov, ToolPriority.RECOMMENDED),
    "deptry": (run_deptry, ToolPriority.RECOMMENDED),
    "vulture": (run_vulture, ToolPriority.RECOMMENDED),
    "trivy": (run_trivy, ToolPriority.OPTIONAL),
}


def determine_pass_fail(
    results: list[ToolResult],
    severity_threshold: Severity,
    confidence_threshold: float = 0.7,
    config: dict | None = None,
) -> bool:
    """Determine if the overall scan passes based on findings, severity, and confidence.

    A finding blocks the gate if:
    - Its severity weight >= severity_threshold weight, AND
    - Its confidence_score >= confidence_threshold, AND
    - It is not a duplicate, AND
    - It has not been marked as FALSE_POSITIVE by LLM triage, AND
    - It comes from a REQUIRED or RECOMMENDED tool
    """
    threshold_weight = severity_threshold.weight

    for result in results:
        if result.status == "SKIPPED":
            # REQUIRED tools that are skipped = FAIL
            if result.priority == ToolPriority.REQUIRED:
                return False
            continue

        if result.status == "ERROR":
            # REQUIRED tools that errored = FAIL
            if result.priority == ToolPriority.REQUIRED:
                return False
            continue

        # Check findings against severity + confidence thresholds
        for finding in result.findings:
            # Skip duplicates
            if finding.is_duplicate:
                continue
            # Skip LLM-confirmed false positives
            if finding.llm_verdict == "FALSE_POSITIVE":
                continue
            # Check severity + confidence
            if finding.severity.weight >= threshold_weight and finding.confidence_score >= confidence_threshold:
                if result.priority in (ToolPriority.REQUIRED, ToolPriority.RECOMMENDED):
                    return False

    return True


def _get_config_value(config: dict | None, *keys: str, default: Any = None) -> Any:
    """Navigate nested config dict safely."""
    if config is None:
        return default
    current = config
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def run_all_scans(
    project_root: str,
    tools: list[str] | None = None,
    skip_tools: list[str] | None = None,
    severity_threshold: str = "high",
    confidence_threshold: float = 0.7,
    verbose: bool = False,
    config: dict | None = None,
) -> ScanResult:
    """Run all security scans and return aggregated result.

    Phase 1: Deterministic scan (all tools)
    Phase 2: CWE dedup + confidence scoring
    Phases 3-5 are handled by the step-06-layer4.md workflow (not this script)
    """
    threshold = Severity(severity_threshold)

    # Read config overrides if available
    dedup_config = _get_config_value(config, "layer4", "dedup", default={})
    cross_val_bonus = dedup_config.get("cross_validation_bonus", 0.3) if isinstance(dedup_config, dict) else 0.3
    known_pattern_bonus = dedup_config.get("known_pattern_bonus", 0.2) if isinstance(dedup_config, dict) else 0.2
    line_tolerance = dedup_config.get("line_range_tolerance", 5) if isinstance(dedup_config, dict) else 5

    scan_result = ScanResult(
        timestamp=datetime.now(timezone.utc).isoformat(),
        project_root=project_root,
        severity_threshold=severity_threshold,
        confidence_threshold=confidence_threshold,
    )

    # --- Phase 1: Deterministic Scan ---
    scan_result.phases_completed.append("deterministic")
    tools_to_run = tools or list(TOOL_RUNNERS.keys())
    skip_set = set(skip_tools or [])

    for tool_name in tools_to_run:
        if tool_name in skip_set:
            runner, priority = TOOL_RUNNERS[tool_name]
            result = ToolResult(tool=tool_name, status="SKIPPED", priority=priority)
            result.metadata = {"reason": "Explicitly skipped"}
            scan_result.tools.append(result)
            continue

        if tool_name not in TOOL_RUNNERS:
            print(f"Warning: Unknown tool '{tool_name}', skipping", file=sys.stderr)
            continue

        runner, priority = TOOL_RUNNERS[tool_name]
        print(f"Running {tool_name}...", file=sys.stderr)

        try:
            result = runner(project_root, verbose=verbose, config=config)
        except Exception as e:
            result = ToolResult(tool=tool_name, status="ERROR", priority=priority)
            result.error_output = f"Unexpected error: {e}"

        scan_result.tools.append(result)

    # --- Phase 2: CWE Dedup + Confidence Scoring ---
    scan_result.phases_completed.append("dedup_confidence")
    print("Phase 2: CWE deduplication + confidence scoring...", file=sys.stderr)

    # Resolve CWE IDs for all findings
    for result in scan_result.tools:
        for finding in result.findings:
            if not finding.cwe:
                finding.cwe = resolve_cwe(finding)

    # Deduplicate
    scan_result.tools = dedup_findings(scan_result.tools, line_tolerance=line_tolerance)
    dup_count = sum(1 for t in scan_result.tools for f in t.findings if f.is_duplicate)
    scan_result.findings_deduplicated = dup_count

    # Compute confidence scores
    scan_result.tools = compute_confidence_scores(
        scan_result.tools,
        cross_validation_bonus=cross_val_bonus,
        known_pattern_bonus=known_pattern_bonus,
    )

    # Determine overall pass/fail (using confidence-aware logic)
    scan_result.overall_pass = determine_pass_fail(
        scan_result.tools, threshold, confidence_threshold, config
    )

    # Update individual tool statuses based on findings (confidence-aware)
    for result in scan_result.tools:
        if result.status not in ("SKIPPED", "ERROR"):
            has_blocking = any(
                f.severity.weight >= threshold.weight
                and f.confidence_score >= confidence_threshold
                and not f.is_duplicate
                and f.llm_verdict != "FALSE_POSITIVE"
                for f in result.findings
            )
            result.status = "FAIL" if has_blocking else "PASS"

    # Count findings above confidence threshold (for Phase 3 escalation info)
    high_conf_findings = get_unique_findings(scan_result.tools, min_confidence=confidence_threshold)
    if high_conf_findings:
        print(f"Phase 2 result: {len(high_conf_findings)} findings with confidence ≥ {confidence_threshold} → escalate to Phase 3 (LLM triage)", file=sys.stderr)
    else:
        print(f"Phase 2 result: No findings above confidence threshold → PASS", file=sys.stderr)

    return scan_result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Unified Security Scanner for Quality Gate Layer 4",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("project_root", nargs="?", default=".", help="Path to the project root directory")
    parser.add_argument("--tools", help="Comma-separated list of tools to run (default: all)")
    parser.add_argument("--skip", help="Comma-separated list of tools to skip")
    parser.add_argument("--severity-threshold", default="high",
        choices=["critical", "high", "medium", "low"],
        help="Minimum severity to fail (default: high)")
    parser.add_argument("--confidence-threshold", type=float, default=0.7,
        help="Minimum confidence score to block gate, 0.0-1.0 (default: 0.7)")
    parser.add_argument("--output", help="Write JSON results to file")
    parser.add_argument("--config", help="Path to quality-gate.yaml")
    parser.add_argument("--verbose", action="store_true", help="Show tool output")
    parser.add_argument("--list-tools", action="store_true", help="List available tools and exit")

    args = parser.parse_args()

    if args.list_tools:
        print("Available security tools:")
        for name, (runner, priority) in TOOL_RUNNERS.items():
            print(f"  {name:12s} [{priority.value}]")
        return 0

    project_root = str(Path(args.project_root).resolve())
    if not Path(project_root).exists():
        print(f"Error: Project root does not exist: {project_root}", file=sys.stderr)
        return 2

    tools = args.tools.split(",") if args.tools else None
    skip_tools = args.skip.split(",") if args.skip else None

    # Load config if provided
    config = None
    if args.config:
        config_path = Path(args.config)
        if config_path.exists():
            try:
                import yaml
                with open(config_path) as f:
                    config = yaml.safe_load(f)
            except ImportError:
                print("Warning: PyYAML not installed, config not loaded", file=sys.stderr)

    # Read confidence threshold from config if not explicitly set
    conf_threshold = args.confidence_threshold
    if config:
        config_conf = _get_config_value(config, "layer4", "confidence_threshold", default=None)
        if config_conf is not None and args.confidence_threshold == 0.7:
            conf_threshold = float(config_conf)

    scan_result = run_all_scans(
        project_root=project_root,
        tools=tools,
        skip_tools=skip_tools,
        severity_threshold=args.severity_threshold,
        confidence_threshold=conf_threshold,
        verbose=args.verbose,
        config=config,
    )

    # Output results
    output = scan_result.to_checkpoint_dict()

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"Results written to {args.output}", file=sys.stderr)
    else:
        print(json.dumps(output, indent=2, default=str))

    # Print summary to stderr
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"SECURITY SCAN SUMMARY", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    for t in scan_result.tools:
        unique = len([f for f in t.findings if not f.is_duplicate])
        status_icon = "✓" if t.status == "PASS" else ("✗" if t.status == "FAIL" else "⊘" if t.status == "SKIPPED" else "⚠")
        print(f" {status_icon} {t.tool:12s} [{t.priority.value:12s}] {t.status:8s} ({unique} unique, {t.duration_s:.1f}s)", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f" Phase 2: {scan_result.findings_deduplicated} duplicates removed", file=sys.stderr)
    print(f" Unique findings: {scan_result.unique_findings}", file=sys.stderr)
    print(f" Confidence threshold: {scan_result.confidence_threshold}", file=sys.stderr)
    high_conf = get_unique_findings(scan_result.tools, min_confidence=scan_result.confidence_threshold)
    print(f" Findings ≥ confidence: {len(high_conf)}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    overall = "PASS" if scan_result.overall_pass else "FAIL"
    print(f" OVERALL: {overall}", file=sys.stderr)
    print(f" By severity: {scan_result.findings_by_severity}", file=sys.stderr)
    print(f" Phases completed: {', '.join(scan_result.phases_completed)}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    return 0 if scan_result.overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
