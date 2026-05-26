# Security Tools Guide — Layer 4 PHP Reference

**Purpose:** Installation, configuration, and remediation guidance for each PHP security tool in Layer 4.

---

## Table of Contents

1. [Installation Quick Reference](#installation)
2. [Composer Audit — PHP Dependency CVEs](#composer-audit)
3. [PHP-CS-Fixer — Security Rules](#php-cs-fixer)
4. [Gitleaks — Secret Detection](#gitleaks)
5. [Semgrep — Semantic Security Rules](#semgrep)
6. [Checkov — YAML/Config Validation](#checkov)
7. [Pre-commit Integration](#pre-commit)
8. [Suppressing False Positives](#suppressing-false-positives)
9. [LLM Triage — False Positive Elimination](#llm-triage)
10. [OWASP Category Mapping](#owasp-mapping)

---

## Installation

### PHP security tools

```bash
# Composer audit (built-in)
composer audit

# PHP security checker (third-party)
composer require --dev symplify/php-security-checker

# PHP-CS-Fixer
composer require --dev friendsofphp/php-cs-fixer
```

Binary tools:
```bash
# Gitleaks
brew install gitleaks

# Trivy
brew install trivy

# Semgrep
pip install semgrep
```

---

## Composer Audit

### What it detects
Known security vulnerabilities in PHP dependencies via Packagist advisories.

### Running

```bash
# Check for known vulnerabilities
composer audit

# With JSON output
composer audit --format json
```

### Configuration

```json
// composer.json
{
    "config": {
        "audit": {
            "advisories": ["security-advisories"]
        }
    }
}
```

---

## PHP-CS-Fixer Security Rules

### What it detects
Common security anti-patterns in PHP code style:
- Variable functions (`$func()`)
- Dynamic property access
- Insecure string interpolation

### Running

```bash
php-cs-fixer fix --rules=@PSR12,+security
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
  - repo: local
    hooks:
      - id: composer-audit
        name: Composer Audit
        entry: bash -c 'composer audit --format json'
        language: system
        pass_filenames: false
  - repo: local
    hooks:
      - id: php-cs-fixer-security
        name: PHP-CS-Fixer (security rules)
        entry: vendor/bin/php-cs-fixer fix --dry-run --rules=@PSR12,+security
        language: system
        files: \.php$
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

### Composer Audit

```json
// composer.json
{
    "extra": {
        "symplify": {
            "security": {
                "ignored-advisories": ["CVE-2024-12345"]
            }
        }
    }
}
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
| Composer Audit | A06: Vulnerable Dependencies |
| PHP Security Checker | A06: Vulnerable Dependencies |
| PHP-CS-Fixer | A03: Injection, A07: Identification/Auth Failures |
| Gitleaks | A02: Cryptographic Failures (exposed credentials) |
| Semgrep | All OWASP Top 10 |
| Checkov | Infrastructure misconfiguration |
