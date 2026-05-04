# Security Tools Guide — Layer 4 Reference

**Purpose:** Installation, configuration, and remediation guidance for each security tool in Layer 4.

**When to read this file:** When a Layer 4 tool reports findings and you need remediation guidance, or when installing/configuring security tools.

---

## Table of Contents

1. [Installation Quick Reference](#installation)
2. [Bandit — Python Vulnerability Scanning](#bandit)
3. [Safety / pip-audit — Dependency CVEs](#safety)
4. [Gitleaks — Secret Detection](#gitleaks)
5. [Semgrep — Semantic Security Rules](#semgrep)
6. [Checkov — YAML/Config Validation](#checkov)
7. [Deptry — Import Consistency](#deptry)
8. [Vulture — Dead Code Detection](#vulture)
9. [Trivy — Docker Image Scanning](#trivy)
10. [Pre-commit Integration](#pre-commit)
11. [Suppressing False Positives](#suppressing-false-positives)
12. [LLM Triage — False Positive Elimination](#llm-triage)
13. [BMAD Party Mode — Security Consensus](#bmad-party-mode)
14. [Post-Deployment Security Verification](#post-deployment)
15. [OWASP Category Mapping](#owasp-mapping)

---

## Installation

### All tools at once (recommended)

```bash
pip install bandit safety pip-audit semgrep checkov deptry vulture
```

### Gitleaks (binary, not pip)

```bash
# Linux
wget -qO- https://github.com/gitleaks/gitleaks/releases/download/v8.18.4/gitleaks_8.18.4_linux_x64.tar.gz | tar xz
sudo mv gitleaks /usr/local/bin/

# macOS
brew install gitleaks

# Verify
gitleaks version
```

### Trivy (binary, not pip)

```bash
# Linux
sudo apt-get install wget apt-transport-https gnupg
wget -qO - https://aquasecurity.github.io/trivy-repo/deb/public.key | sudo apt-key add -
echo "deb https://aquasecurity.github.io/trivy-repo/deb generic main" | sudo tee /etc/apt/sources.list.d/trivy.list
sudo apt-get update
sudo apt-get install trivy

# macOS
brew install trivy

# Verify
trivy --version
```

### Pre-commit (optional framework)

```bash
pip install pre-commit
pre-commit install
```

---

## Bandit

### What it detects
Python security issues: SQL injection, hardcoded passwords/credentials, insecure file permissions, use of `eval()`/`exec()`, SSRF, XSS, insecure deserialization, weak cryptography.

### Key rules for Home Assistant projects

| Rule ID | Issue | Severity |
|---------|-------|----------|
| B608 | SQL injection via string concatenation | HIGH |
| B105 | Hardcoded password string | MEDIUM |
| B106 | Hardcoded password function argument | MEDIUM |
| B107 | Hardcoded password default argument | MEDIUM |
| B108 | Insecure file permissions (chmod 777) | MEDIUM |
| B301 | Pickle usage (insecure deserialization) | MEDIUM |
| B302 | Marshal usage | MEDIUM |
| B303 | MD5/SHA1 usage (weak hash) | LOW |
| B311 | Random module (not crypto-safe) | LOW |
| B324 | Hashlib usage without usedforsecurity | MEDIUM |
| B506 | YAML load without SafeLoader | MEDIUM |
| B602 | Subprocess shell=True | MEDIUM |
| B603 | Subprocess without shell=True | LOW |
| B605 | Starting process with shell=True | MEDIUM |
| B607 | Starting process with partial path | MEDIUM |

### Configuration

Create `.bandit.yaml` in project root:

```yaml
# .bandit.yaml
targets:
  - custom_components
  - scripts
skips:
  - B101  # assert used (OK in tests)
  - B311  # random module (OK for non-crypto)
```

### Remediation

| Finding | Fix |
|---------|-----|
| B608 SQL injection | Use parameterized queries: `cursor.execute("SELECT * FROM t WHERE id = ?", (id,))` |
| B105/B106 Hardcoded password | Use `os.environ["PASSWORD"]` or HA `secrets.yaml` |
| B506 Unsafe YAML load | Use `yaml.safe_load()` or `yaml.load(data, Loader=yaml.SafeLoader)` |
| B602 shell=True | Use list form: `subprocess.run(["cmd", arg1])` |
| B301 Pickle | Use JSON or msgpack for serialization |

---

## Safety

### What it detects
Known CVEs in Python dependencies by checking against a vulnerability database.

### Configuration

Create `safety-policy.yml` in project root:

```yaml
# safety-policy.yml
security:
  ignore-vulnerabilities:
    # Example: ignore specific CVE with justification
    # - CVE-2023-12345:
    #     reason: "Not applicable — we don't use the affected feature"
    #     expires: "2026-12-31"
```

### Remediation

1. **Update the package:** `pip install --upgrade <package>`
2. **Check if fix exists:** `pip audit --fix` (if using pip-audit)
3. **If no fix available:** Add to safety-policy.yml with justification and expiry

---

## Gitleaks

### What it detects
Hardcoded secrets: API keys, tokens, passwords, private keys, AWS credentials, database URLs, etc.

### Configuration

Create `.gitleaks.toml` in project root:

```toml
# .gitleaks.toml
[allowlist]
  paths = [
    '''tests/fixtures/.*''',
    '''tests/.*mock.*\.py$''',
  ]
  regexes = [
    '''TEST_API_KEY_[A-Z_]+''',
  ]
```

### Remediation

1. **If real secret:** Immediately rotate the credential
2. **Remove from code:** Use environment variables or HA secrets
3. **If false positive:** Add to `.gitleaks.toml` allowlist

---

## Semgrep

### What it detects
Semantic code patterns using custom rules. Covers OWASP Top 10, security anti-patterns, and project-specific rules.

### Custom HA Rules

The skill includes custom semgrep rules at `{skill-root}/references/semgrep-ha-rules.yaml` covering:

- Unsafe `hass.data` access patterns
- Blocking I/O in async HA functions
- Missing error handling in service handlers
- Unsafe `homeassistant.helpers` usage

### Configuration

Add project rules in `.semgrep/rules.yaml`:

```yaml
rules:
  - id: project-specific-rule
    patterns:
      - pattern: dangerous_function(...)
    message: "Don't use dangerous_function"
    severity: WARNING
```

### Remediation

Each finding includes the rule ID and message. Follow the specific remediation in the message.

---

## Checkov

### What it detects
Misconfigurations in YAML, JSON, Dockerfile, and other IaC files. For HA projects: validates docker-compose, Dockerfile, and configuration YAML.

### Configuration

Create `.checkov.yaml` in project root:

```yaml
# .checkov.yaml
skip-check:
  - CKV_DOCKER_2  # No health check (acceptable for dev)
  - CKV_DOCKER_3  # Running as root (HA requirement)
```

### Remediation

Each finding includes a link to the Checkov documentation with specific fix instructions.

---

## Deptry

### What it detects
- Missing dependencies (imports not in requirements)
- Unused dependencies (in requirements but never imported)
- Transitive dependencies (imported but not directly declared)

### Configuration

In `pyproject.toml`:

```toml
[tool.deptry]
extend_ignore = ["HA"]  # HA modules available at runtime
known_first_party = ["custom_components"]
```

### Remediation

| Finding | Fix |
|---------|-----|
| Missing dependency | Add to `pyproject.toml` or `requirements.txt` |
| Unused dependency | Remove from dependencies if truly unused |
| Transitive dependency | Add direct dependency to avoid relying on transitive imports |

---

## Vulture

### What it detects
Unused code: functions, classes, variables, imports, and properties that are never referenced.

### Configuration

Create `.vulture-whitelist.py` in project root:

```python
# .vulture-whitelist.py
# Whitelist for vulture false positives

# HA registers these dynamically
_.async_setup_entry  # noqa
_.async_unload_entry  # noqa
_.setup  # noqa

# Platform registrations
_.PLATFORM_SCHEMA  # noqa
```

### Remediation

1. **If truly dead:** Remove the code
2. **If dynamically used (HA patterns):** Add to `.vulture-whitelist.py`
3. **If test-only:** Move to test utilities

---

## Trivy

### What it detects
CVEs in Docker images and misconfigurations in Dockerfiles, Kubernetes manifests, and other IaC.

### Configuration

Create `.trivyignore.yaml` in project root:

```yaml
# .trivyignore.yaml
ignores:
  - id: CVE-2023-XXXXX
    until: "2026-12-31"
    statement: "Not affected — we don't use the vulnerable feature"
```

### Remediation

1. **Update base image:** Use newer tag or `latest` (with pinning)
2. **Apply specific fix:** Follow CVE advisory
3. **If not applicable:** Add to `.trivyignore.yaml` with justification

---

## Pre-commit Integration

For running security checks before every commit, add to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/PyCQA/bandit
    rev: '1.7.9'
    hooks:
      - id: bandit
        args: ["-c", ".bandit.yaml"]
        files: ^custom_components/

  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.4
    hooks:
      - id: gitleaks

  - repo: https://github.com/charliermarsh/ruff-pre-commit
    rev: 'v0.5.0'
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/returntocorp/semgrep
    rev: 'v1.80.0'
    hooks:
      - id: semgrep
        args: ['--config', 'p/security-audit', '--quiet']
```

---

## Suppressing False Positives

### Bandit
```python
content = hashlib.md5(data)  # nosec B303  # non-crypto use
```

### Semgrep
```python
dangerous_call()  # nosemgrep: rule-id
```

### Gitleaks
Add to `.gitleaks.toml` allowlist (see above).

### Vulture
Add to `.vulture-whitelist.py` (see above).

### Checkov
Add check ID to `.checkov.yaml` skip-check list (see above).

### General Rule
**Only suppress false positives.** Never suppress genuine security findings to pass the gate. If a finding is genuine but low-risk, document it as a WARNING with a justification and set an expiry date.

---

## LLM Triage

### What it does
After deterministic tools produce findings, an LLM reviews each finding with full code context and classifies it as `TRUE_POSITIVE`, `FALSE_POSITIVE`, or `NEEDS_CONSENSUS`. This eliminates ~50-70% of false positives autonomously, replacing the need for human triage in the Ralph loop.

### When it runs
Phase 3 of Layer 4, after CWE deduplication and confidence scoring. Only findings with confidence ≥ threshold are triaged.

### How it works
1. Extract code context (±20 lines) around each finding
2. Send to LLM with classification prompt (see `step-06-layer4.md` Phase 3)
3. LLM responds with verdict, confidence, reasoning, and fix suggestion

### LLM Verdicts

| Verdict | Meaning | Gate Impact |
|---------|---------|-------------|
| `TRUE_POSITIVE` | Vulnerability is exploitable in current context | **BLOCKS** gate → Phase 5 (fix validation) |
| `FALSE_POSITIVE` | Finding is not exploitable (unreachable path, sanitized input, safe context) | Downgraded to **WARNING** (non-blocking) |
| `NEEDS_CONSENSUS` | LLM uncertain — depends on runtime behavior or domain expertise | Escalated to **Phase 4** (BMAD Party Mode) |

### Known limitations
- LLM can hallucinate and mark real vulnerabilities as false positives (~5-15% error rate)
- Adds ~30-60s per finding
- Cost: ~$0.01-0.05 per finding with GPT-4-class models
- Best accuracy on well-known vulnerability patterns (SQL injection, XSS, hardcoded secrets)
- Lower accuracy on business logic vulnerabilities and novel attack patterns

### Industry references
- GitHub Copilot Autofix: LLM triage + auto-fix for CodeQL findings (Microsoft, 2024)
- Snyk AI: DeepCode AI engine for context-aware vulnerability prioritization (Snyk, 2023)
- Pixee/Dragonfly: Open-source LLM jury system for false positive reduction (2024)

---

## BMAD Party Mode

### What it does
When LLM triage cannot confidently classify a finding (`NEEDS_CONSENSUS`), multiple BMAD agents review the finding independently and reach consensus. This replaces human security review in the autonomous Ralph loop.

### When it runs
Phase 4 of Layer 4, only when LLM triage produces `NEEDS_CONSENSUS` findings.

### Agents involved

| Agent | Role | Security Focus |
|-------|------|----------------|
| **Winston** (Architect) | Architectural security evaluation | Trust boundaries, data flows, entry points |
| **Murat** (Test Architect) | Exploitability assessment | Attack surface, test coverage for security, realistic severity |
| **Amelia** (Developer) | Code-level fix feasibility | Implementation correctness, fix code generation |

### Consensus rule
A vulnerability is **confirmed** if:
- At least 2 of 3 agents agree (CONFIRMED), AND
- Adversarial review does NOT reject the finding

A vulnerability is **rejected** if:
- 3/3 agents agree it is a false positive, AND
- Adversarial reviewer concurs

If no consensus after 3 rounds → **UNCERTAIN** (WARNING, non-blocking)

### Adversarial review
After Party Mode, `bmad-review-adversarial-general` challenges findings:
- Flags false positives that agents missed
- Finds vulnerabilities that agents overlooked
- Ensures findings are actionable, not theoretical

### Fallback
If BMAD Party Mode is not available, all `NEEDS_CONSENSUS` findings default to **WARNING** (non-blocking) with note: "Could not verify autonomously — recommend manual review."

---

## Post-Deployment Security Verification

### Purpose
After Layer 4 passes and code is deployed, deeper security verification can be performed. These are **reference-only** — they do not influence the Layer 4 gate execution.

### When to use
- After major security fixes (verify that remediation is complete)
- Before releases to production (as additional verification, not a gate)
- For vulnerabilities that require runtime context to fully assess

### Pentest reference assets

The following external skills provide reference material for post-deployment verification:

| Skill | Content | How to use |
|-------|---------|------------|
| `pentest-checklist` | Structured checklist for penetration testing categories | Read when a finding needs deeper verification than tools provide |
| `pentest-commands` | Specific commands and techniques for exploitation verification | Read when confirming a fix actually prevents the attack |
| `pentest-remediation-index` | Mapping of finding types to pentest verification commands | **Primary index** for fix validation — maps each CWE to pentest commands and checklists |

### Integration pattern

```
Layer 4 tools find SQL injection (bandit B608)
  → Developer fixes with parameterized query
  → Post-deploy: consult pentest-commands for
     "how to verify the fix actually prevents SQL injection"
  → Consult pentest-checklist category A03:2021
     to ensure no reintroduction via another path
```

### Important
`pentest-checklist` and `pentest-commands` are **reference documentation**, not gate components. They do not block or unblock the quality gate. In the autonomous Ralph loop, their function is replaced by BMAD Party Mode consensus.

---

## OWASP Mapping

### Finding-to-OWASP Category Mapping

When Layer 4 detects findings, they are automatically mapped to OWASP Top 10 (2021) categories for advisory output:

| Finding Source | Rule ID | OWASP Category |
|---------------|---------|----------------|
| bandit | B608 (SQL injection) | A03:2021 - Injection |
| bandit | B105/B106 (hardcoded password) | A07:2021 - Identification and Authentication Failures |
| bandit | B506 (YAML unsafe load) | A08:2021 - Software and Data Integrity Failures |
| bandit | B602 (shell=True) | A03:2021 - Injection |
| bandit | B301 (pickle) | A08:2021 - Software and Data Integrity Failures |
| bandit | B324 (weak hash) | A02:2021 - Cryptographic Failures |
| semgrep (HA) | ha-eval-exec-usage | A03:2021 - Injection |
| semgrep (HA) | ha-log-sensitive-data | A09:2021 - Security Logging and Monitoring Failures |
| semgrep (HA) | ha-yaml-unsafe-load | A08:2021 - Software and Data Integrity Failures |
| semgrep (HA) | ha-subprocess-shell | A03:2021 - Injection |
| semgrep (JS) | js-hardcoded-secret | A07:2021 - Identification and Authentication Failures |
| semgrep (JS) | js-jwt-weak-algorithm | A02:2021 - Cryptographic Failures |
| semgrep (JS) | js-sql-injection | A03:2021 - Injection |
| semgrep (JS) | js-command-injection | A03:2021 - Injection |
| semgrep (JS) | js-disabled-tls-verify | A02:2021 - Cryptographic Failures |
| gitleaks | (any) | A07:2021 - Identification and Authentication Failures |
| safety | (CVE) | A06:2021 - Vulnerable and Outdated Components |

### How this mapping is used
- **Advisory output** in checkpoint report (non-blocking)
- **Context for LLM triage** — helps the LLM understand the security category
- **Context for Party Mode** — agents use OWASP categories to focus their review
- **NOT a gate decision** — OWASP mapping does not affect PASS/FAIL

### Semgrep JS Rules

The skill includes custom semgrep rules for JavaScript/TypeScript at `{skill-root}/references/semgrep-js-rules.yaml` covering:

- `eval()`/`Function()`/`setTimeout(string)` code injection
- Hardcoded secrets (password, apiKey, token, secret)
- HTTP URLs (not localhost) — cleartext transmission
- SQL injection via string concatenation/interpolation
- Command injection via `child_process.exec()`
- Insecure YAML load (js-yaml with custom schema)
- JWT weak algorithm (none, HS256)
- Path traversal via `path.join()` with user input
- Insecure `Math.random()` for security purposes
- Disabled TLS certificate verification
- Prototype pollution
- ReDoS vulnerable regex patterns
- Uncaught promise rejection in auth flows

These rules are **automatically included** in the semgrep scan. Semgrep only applies JS/TS rules to JS/TS files, so no cross-language false positives occur.
