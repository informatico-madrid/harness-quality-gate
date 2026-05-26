# Security Tools Guide — Layer 4 Reference

**Purpose:** Index for Layer 4 security tool documentation. Choose the language-specific guide below.

**When to read this file:** When you need to find the right security tool guide.

---

## Language-Specific Guides

| Language | Guide |
|----------|-------|
| **Python** | [security-tools-guide-python.md](security-tools-guide-python.md) |
| **PHP** | [security-tools-guide-php.md](security-tools-guide-php.md) |

---

## Language-Agnostic Tools (Both Guides)

All language guides cover these tools:
- **Semgrep** — semantic security scanning (language-agnostic)
- **Gitleaks** — secret detection
- **Checkov** — infrastructure config validation
- **Trivy** — Docker image CVE scanning
- **Pre-commit integration**

## Quick Reference

| Tool | Python | PHP | Type |
|------|--------|-----|------|
| Bandit | Y | | Python vulnerability scanning |
| Safety/pip-audit | Y | | Python dependency CVEs |
| Composer Audit | | Y | PHP dependency CVEs |
| PHP Security Checker | | Y | PHP vulnerability checker |
| Gitleaks | Y | Y | Secret detection |
| Semgrep | Y | Y | Semantic security rules |
| Checkov | Y | Y | Config validation |
| Trivy | Y | Y | Docker image scanning |
| Deptry | Y | | Python import consistency |
| Vulture | Y | | Python dead code |
| PHP-CS-Fixer | | Y | PHP code quality & security |
