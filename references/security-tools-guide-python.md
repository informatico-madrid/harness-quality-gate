# Security Tools Guide — Layer 4 Python Reference

**Purpose:** Installation, configuration, and remediation guidance for each Python security tool in Layer 4.

---

## Table of Contents

1. [Installation Quick Reference](#installation)
2. [Bandit — Python Vulnerability Scanning](#bandit)
3. [Safety / pip-audit — Dependency CVEs](#safety)
4. [Deptry — Import Consistency](#deptry)
5. [Vulture — Dead Code Detection](#vulture)
6. [Common Tools (Language-Agnostic)](#common-tools)
7. [Pre-commit Integration](#pre-commit)
8. [Suppressing False Positives](#suppressing-false-positives)
9. [LLM Triage — False Positive Elimination](#llm-triage)
10. [OWASP Category Mapping](#owasp-mapping)

---

## Installation

```bash
pip install bandit safety deptry vulture
pip install pip-audit  # alternative to safety
```

Binary tools:
```bash
# Gitleaks
brew install gitleaks  # macOS
# or download from GitHub releases

# Trivy
brew install trivy
# or follow https://aquasecurity.github.io/trivy/
```

---

## Bandit

### What it detects
Python security issues: SQL injection, hardcoded passwords, insecure file permissions, `eval()`/`exec()`, SSRF, XSS, insecure deserialization, weak cryptography.

### Key rules

| Rule ID | Issue | Severity |
|---------|-------|----------|
| B608 | SQL injection via string concatenation | HIGH |
| B105 | Hardcoded password string | MEDIUM |
| B106 | Hardcoded password function argument | MEDIUM |
| B301 | Pickle usage (insecure deserialization) | MEDIUM |
| B311 | Random module (not crypto-safe) | LOW |
| B506 | YAML load without SafeLoader | MEDIUM |
| B602 | Subprocess shell=True | MEDIUM |

### Configuration

```yaml
# .bandit.yaml
targets:
  - src
  - scripts
skips:
  - B101  # assert used (OK in tests)
  - B311  # random module (OK for non-crypto)
```

### Running

```bash
bandit -r src/ -f json
bandit -c .bandit.yaml -r src/ -f json
```

---

## Safety / pip-audit

### What it detects
Known vulnerabilities in Python dependencies via CVE databases.

### Running

```bash
safety check --json
pip-audit --format json
```

---

## Deptry

### What it detects
Inconsistent imports vs declared dependencies in `pyproject.toml`.

### Running

```bash
deptry .
```

---

## Vulture

### What it detects
Unused Python code (functions, classes, variables).

### Running

```bash
vulture src/ --min-confidence 80
```

---

## Common Tools (Language-Agnostic)

```bash
# Semgrep
python3 -m semgrep --config p/security-audit --config p/owasp-top-ten --json .

# Checkov
pip install checkov && checkov -d . --framework dockerfile yaml json --output json

# Gitleaks
gitleaks detect --source . --report-format json --no-banner

# Trivy
trivy config --format json .
```

---

## Pre-commit Integration

```yaml
repos:
  - repo: https://github.com/PyCQA/bandit
    rev: 1.7.9
    hooks:
      - id: bandit
        args: ["-r", "src/", "-f", "json"]
        exclude: tests/
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.4
    hooks:
      - id: gitleaks
  - repo: https://github.com/bridgecrewio/checkov
    rev: 3.2.0
    hooks:
      - id: checkov
        args: ["-d", ".", "--framework", "dockerfile,yaml,json"]
```

---

## Suppressing False Positives

### Bandit inline skip

```python
cursor.execute(f"SELECT * FROM {table}")  # B608 NOSEC
```

### Safety

```bash
safety check --ignore CVE-2024-12345
```

---

## LLM Triage

When a tool reports findings:
1. Verify the finding is real (check line + context)
2. If real -- fix and re-scan
3. If false positive -- add suppression + document why
4. Use LLM to generate remediation code

---

## OWASP Category Mapping

| Tool | OWASP Category |
|------|----------------|
| Bandit | A03: Injection, A09: Security Misconfiguration |
| Safety | A06: Vulnerable Dependencies |
| Gitleaks | A02: Cryptographic Failures (exposed credentials) |
| Semgrep | All OWASP Top 10 |
| Checkov | Infrastructure misconfiguration |
| Vulture | Code quality (not security) |
