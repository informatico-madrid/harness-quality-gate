# Step 06: Layer 4 — Security & Defense (Autonomous)

**Goal:** Execute comprehensive security verification across deterministic tools, LLM-based triage, and multi-agent consensus to detect vulnerabilities, exposed secrets, dependency CVEs, dead code, and configuration issues. Generate Layer 4 results for the checkpoint.

**Duration:** ~5-15 min (depends on tool availability, findings count, and consensus rounds)

**Precondition:** Layer 3B (Tier B BMAD) must have passed or been skipped. Layer 4 runs as the final gate before checkpoint generation.

---

## ⚠️ PRECONDITION: Layers L3A, L1, L2 Must Pass First

**Layer 4 only executes if all previous layers passed (L3A, L1, L2). L3B can be PASS or SKIPPED.**

If any earlier layer failed, the workflow should have already stopped before reaching this step.

**Rationale:** Security scanning is the final gate. There's no point scanning code that already fails quality or test checks.

---

## Layer 4 Architecture (Autonomous Ralph Loop)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Layer 4: SECURITY & DEFENSE — Autonomous (~5-15 min)                  │
│                                                                         │
│ PHASE 1: DETERMINISTIC SCAN (~2-5 min)                                 │
│ ├── 4.1 bandit → Python vulnerability scanning          [REQUIRED]     │
│ ├── 4.2 safety/pip-audit → Dependency CVE scanning      [REQUIRED]     │
│ ├── 4.3 gitleaks → Secret/API key detection             [REQUIRED]     │
│ ├── 4.4 semgrep → Semantic rules (OWASP+HA+JS)          [RECOMMENDED]  │
│ ├── 4.5 checkov → YAML/HA config validation             [RECOMMENDED]  │
│ ├── 4.6 deptry → Import consistency vs requirements     [RECOMMENDED]  │
│ ├── 4.7 vulture → Dead code detection                   [RECOMMENDED]  │
│ └── 4.8 trivy → Docker image CVE scanning               [OPTIONAL]     │
│                                                                         │
│ PHASE 2: CWE DEDUP + CONFIDENCE SCORING (~30s)                        │
│ ├── Normalize findings to CWE IDs                                       │
│ ├── Deduplicate across tools (same file + CWE)                         │
│ ├── Compute confidence score per finding                                │
│ └── If no findings ≥ confidence threshold → PASS (skip Phase 3)       │
│                                                                         │
│ PHASE 3: LLM TRIAGE — False Positive Elimination (~2-5 min)           │
│ ├── For each finding with confidence ≥ threshold                       │
│ ├── LLM reviews finding with full code context                         │
│ ├── Classifies: TRUE_POSITIVE / FALSE_POSITIVE / NEEDS_CONSENSUS       │
│ ├── TRUE_POSITIVE → confirmed, blocks gate                             │
│ ├── FALSE_POSITIVE → downgraded to WARNING                             │
│ └── NEEDS_CONSENSUS → escalates to Phase 4                            │
│                                                                         │
│ PHASE 4: BMAD PARTY MODE — Security Consensus (~5-10 min)             │
│ ├── Spawn 3 security-focused agents in parallel                        │
│ ├── Each agent evaluates escalated findings independently              │
│ ├── Adversarial review challenges findings                             │
│ ├── Consensus rule: 2/3 agents + adversarial confirms                  │
│ ├── If consensus reached → apply verdict                               │
│ └── If no consensus → additional round (max 3 rounds)                 │
│                                                                         │
│ PHASE 5: FIX VALIDATION LOOP (if findings confirmed)                  │
│ ├── LLM generates fix suggestion for confirmed findings               │
│ ├── Apply fix to code                                                  │
│ ├── Re-run Phase 1 (deterministic scan only)                           │
│ ├── If fix resolves finding → PASS                                     │
│ └── If fix fails after 2 attempts → FAIL with manual remediation      │
│                                                                         │
│ Severity Threshold: configurable (default: HIGH)                       │
│ Confidence Threshold: configurable (default: 0.7)                      │
│ Findings at or above both thresholds → FAIL                           │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Design Principles

1. **No human intervention required** — The Ralph loop must operate autonomously
2. **Progressive escalation** — Each phase adds cost but increases accuracy
3. **False positive elimination** — LLM triage + multi-agent consensus replaces human review
4. **Fix validation** — Confirmed vulnerabilities get auto-fixed and re-verified
5. **Consensus over authority** — No single agent decides; majority rules

---

## 4.0 Verify Security Tools Availability

Before running scans, check which security tools are installed:

```bash
python3 -c "import bandit" 2>/dev/null && echo "bandit=OK" || echo "bandit=MISSING"
python3 -c "import safety" 2>/dev/null && echo "safety=OK" || echo "safety=MISSING"
python3 -c "import pip_audit" 2>/dev/null && echo "pip-audit=OK" || echo "pip-audit=MISSING"
which gitleaks 2>/dev/null && echo "gitleaks=OK" || echo "gitleaks=MISSING"
python3 -c "import semgrep" 2>/dev/null && echo "semgrep=OK" || echo "semgrep=MISSING"
python3 -c "import checkov" 2>/dev/null && echo "checkov=OK" || echo "checkov=MISSING"
python3 -c "import deptry" 2>/dev/null && echo "deptry=OK" || echo "deptry=MISSING"
python3 -c "import vulture" 2>/dev/null && echo "vulture=OK" || echo "vulture=MISSING"
which trivy 2>/dev/null && echo "trivy=OK" || echo "trivy=MISSING"
```

**If REQUIRED tools are MISSING:**
- Bandit, safety/pip-audit, or gitleaks missing → Layer 4 **FAILS**
- Report to user: "Install missing REQUIRED security tools. See `{skill-root}/references/security-tools-guide.md` for installation instructions."

**If RECOMMENDED tools are MISSING:**
- Mark as SKIPPED, does not affect PASS/FAIL
- Log a warning with installation instructions

---

## 4.1 Phase 1: Run Unified Security Scanner

Execute the unified security scanner script:

```bash
python3 {skill-root}/scripts/security_scanner.py {project-root} \
  --severity-threshold {threshold_from_config} \
  --config {skill-root}/config/quality-gate.yaml \
  --output {project-root}/_bmad-output/quality-gate/security-scan-results.json \
  --verbose 2>&1
```

The `--severity-threshold` value comes from `{skill-root}/config/quality-gate.yaml` under `layer4.severity_threshold` (default: `high`).

**If the script fails to execute:**
1. Check Python version (requires 3.11+)
2. Check if script path is correct
3. Fall back to running individual tools manually (see sections 4.1.1–4.1.8)

### 4.1.1 Alternative: Run Individual Tools Manually

If the unified scanner is unavailable, run each tool individually:

#### Bandit (REQUIRED)

```bash
cd {project-root} && python3 -m bandit -r custom_components/ -f json 2>&1
```

#### Safety (REQUIRED)

```bash
cd {project-root} && python3 -m safety check --json 2>&1
```

Or with requirements file:
```bash
cd {project-root} && python3 -m safety check -r requirements.txt --json 2>&1
```

**Fallback:** If safety not available, try pip-audit:
```bash
cd {project-root} && python3 -m pip_audit --format json 2>&1
```

#### Gitleaks (REQUIRED)

```bash
cd {project-root} && gitleaks detect --source . --report-format json --no-banner 2>&1
```

#### Semgrep (RECOMMENDED)

```bash
cd {project-root} && python3 -m semgrep \
  --config p/security-audit \
  --config p/owasp-top-ten \
  --config {skill-root}/references/semgrep-ha-rules.yaml \
  --config {skill-root}/references/semgrep-js-rules.yaml \
  --json . 2>&1
```

**Note:** `semgrep-js-rules.yaml` is included automatically. Semgrep will only apply JS/TS rules to JS/TS files, so no cross-language false positives.

#### Checkov (RECOMMENDED)

```bash
cd {project-root} && python3 -m checkov -d . --framework dockerfile yaml json --output json --compact 2>&1
```

#### Deptry (RECOMMENDED)

```bash
cd {project-root} && python3 -m deptry . 2>&1
```

#### Vulture (RECOMMENDED)

```bash
cd {project-root} && python3 -m vulture custom_components/ --min-confidence 80 2>&1
```

#### Trivy (OPTIONAL)

```bash
cd {project-root} && trivy config --format json . 2>&1
```

Only if `Dockerfile` or `Dockerfile.custom` exists.

---

## 4.2 Phase 2: CWE Deduplication + Confidence Scoring

After Phase 1 produces findings, normalize and deduplicate:

### CWE Normalization

Map each finding's rule ID to a CWE ID:

| Tool | Rule ID Format | CWE Mapping |
|------|---------------|-------------|
| bandit | B608, B105, etc. | Built-in CWE in bandit output |
| semgrep | ha-eval-exec-usage, js-sql-injection, etc. | From rule metadata `cwe` field |
| gitleaks | RuleID | CWE-798 (hardcoded credentials) |
| checkov | CKV_* | Built-in CWE in checkov output |

### Deduplication Rule

Two findings are **duplicates** if they share:
- Same file path
- Overlapping line range (±5 lines)
- Same CWE ID

**When duplicates found:** Keep the finding from the tool with higher priority (REQUIRED > RECOMMENDED > OPTIONAL), or higher severity if same priority.

### Confidence Scoring

Each finding gets a composite confidence score:

```
confidence = base_score × cross_validation_multiplier

base_score:
  CRITICAL = 1.0
  HIGH     = 0.9
  MEDIUM   = 0.7
  LOW      = 0.5
  INFO     = 0.3

cross_validation_multiplier:
  2+ tools report same CWE in same file = 1.3 (capped at 1.0)
  1 tool only                           = 1.0
  Finding in known-vulnerable pattern    = 1.2 (capped at 1.0)
```

**Confidence threshold** comes from `{skill-root}/config/quality-gate.yaml` under `layer4.confidence_threshold` (default: `0.7`).

### Phase 2 Decision

- **No findings with confidence ≥ threshold** → Layer 4 **PASS** (skip to 4.5)
- **Findings with confidence ≥ threshold** → proceed to Phase 3

---

## 4.3 Phase 3: LLM Triage (False Positive Elimination)

For each finding with confidence ≥ threshold, perform LLM-based triage:

### Step 3.1: Build Finding Context

For each finding, extract:
- The finding metadata (tool, rule_id, severity, message)
- The source code around the finding (±20 lines)
- The file's imports and function signatures
- Any related test files

### Step 3.2: LLM Classification

Use the following prompt structure for each finding:

```
You are a security code reviewer. Classify this security finding.

## Finding
- Tool: {tool}
- Rule: {rule_id}
- Severity: {severity}
- Message: {message}
- File: {file}:{line}

## Code Context
```{language}
{code_context_±20_lines}
```

## Classification Task
Determine if this is a TRUE_POSITIVE, FALSE_POSITIVE, or NEEDS_CONSENSUS.

Respond with JSON:
{
  "verdict": "TRUE_POSITIVE" | "FALSE_POSITIVE" | "NEEDS_CONSENSUS",
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation of why",
  "exploit_scenario": "If TRUE_POSITIVE, how could this be exploited?",
  "fix_suggestion": "If TRUE_POSITIVE, suggested fix code"
}

Rules:
- FALSE_POSITIVE only if the code path is unreachable, the input is sanitized, or the pattern is safe in this specific context
- NEEDS_CONSENSUS if you're uncertain or the vulnerability depends on runtime behavior
- TRUE_POSITIVE if the vulnerability is exploitable in the current code context
```

### Step 3.3: Process LLM Verdicts

| LLM Verdict | Action |
|-------------|--------|
| `TRUE_POSITIVE` | Finding confirmed → blocks gate. Proceed to Phase 5 (fix validation) |
| `FALSE_POSITIVE` | Finding downgraded to WARNING (non-blocking). Log reasoning |
| `NEEDS_CONSENSUS` | Escalate to Phase 4 (BMAD Party Mode) |

**If all findings are FALSE_POSITIVE or WARNING** → Layer 4 **PASS**

**If any TRUE_POSITIVE** → proceed to Phase 5 (fix validation)

**If any NEEDS_CONSENSUS** → proceed to Phase 4

---

## 4.4 Phase 4: BMAD Party Mode — Security Consensus

When LLM triage produces `NEEDS_CONSENSUS` findings, escalate to multi-agent review.

### Step 4.1: Generate Security Review Context

Compile all `NEEDS_CONSENSUS` findings with their full code context into a review document:

```json
{
  "security_review_context": {
    "findings_escalated": [
      {
        "tool": "bandit",
        "rule_id": "B608",
        "severity": "HIGH",
        "file": "custom_components/ev_trip_planner/emhass_adapter.py",
        "line": 142,
        "message": "SQL injection via string concatenation",
        "code_context": "...",
        "llm_reasoning": "The query uses f-string but the source of the variable is unclear"
      }
    ],
    "project_context": "Home Assistant EV Trip Planner integration with EMHASS",
    "owasp_categories_affected": ["A03:2021 - Injection"]
  }
}
```

### Step 4.2: Invoke BMAD Party Mode (Sequential Rounds)

Activate the `bmad-party-mode` skill. **Important:** Party Mode runs in **sequential rounds**, NOT in parallel. Each agent sees the previous agents' verdicts before voting.

**Agents and order:**
1. **Winston** (Architect) — Round 1: Evaluates architectural security implications, trust boundaries, and data flow
2. **Murat** (Test Architect) — Round 2: Sees Winston's verdict, evaluates exploitability and attack surface
3. **Amelia** (Developer) — Round 3: Sees Winston's and Murat's verdicts, evaluates fix feasibility

**Round flow:**
```
Round 1: Winston evaluates NEEDS_CONSENSUS findings → veredicto
         → [Winston produces verdict]
Round 2: Murat sees Winston's verdict → adds own veredicto
         → [Murat produces verdict based on Winston's input]
Round 3: Amelia sees Winston's + Murat's verdicts → adds own veredicto
         → [Amelia produces verdict based on both previous inputs]
```

**Consensus rule:** A finding is CONFIRMED if ≥2 of 3 agents agree.

**Loop protection:** Maximum 2 rounds total. After Round 2, if no consensus 2/3 → veredicto final: **ESCALATE_TO_FAIL** (blocking, any NEEDS_CONSENSUS sin consenso → bloquea el gate).

**Prompt for each agent:**

```
You are reviewing security findings that an LLM triage could not classify with confidence.

{security_review_context from Step 4.1}

For each finding, evaluate:
1. Is this a TRUE vulnerability? (Can it be exploited in the current code context?)
2. What is the realistic severity? (Consider actual attack surface, not theoretical)
3. What is the recommended fix? (Specific code change, not generic advice)
4. Are there related vulnerabilities in the same code path that tools missed?

Respond with JSON:
{
  "findings": [
    {
      "rule_id": "B608",
      "verdict": "CONFIRMED" | "REJECTED" | "UNCERTAIN",
      "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW",
      "reasoning": "Why you believe this is confirmed/rejected",
      "fix_code": "Specific code fix if CONFIRMED",
      "missed_vulnerabilities": ["Any related vulns the tools missed"]
    }
  ]
}
```

### Step 4.3: Invoke Adversarial Review

After Party Mode produces findings, activate `bmad-review-adversarial-general`:

**Content to review:** The combined security findings from all Party Mode agents.

The adversarial reviewer will:
- Challenge false positives (flagged vulnerabilities that aren't real)
- Find missed vulnerabilities that agents overlooked
- Ensure findings are actionable, not theoretical

### Step 4.4: Build Consensus

| Source | Role | Weight |
|--------|------|--------|
| Party Mode agents | Independent security evaluation | Primary findings |
| Adversarial Review | Challenge and refine findings | Removes false positives |

**Consensus rule:** A vulnerability is confirmed if:
- At least 2 of 3 Party Mode agents agree (CONFIRMED), AND
- Adversarial review does NOT reject the finding

**If no consensus after first round:**
- Run a second round with the disagreement as context
- Maximum 2 rounds total (not 3)
- If still no consensus after 2 rounds → veredicto final: **ESCALATE_TO_FAIL** (any NEEDS_CONSENSUS sin consenso 2/3 → bloquea el gate)

### Tier B Override (Security)

If Party Mode consensus explicitly identifies a Phase 1 finding as a **false positive**, the verdict can be **downgraded to WARNING** (non-blocking). This requires 3/3 agents agreeing it is a false positive AND adversarial reviewer concurring.

**Fallback:** If BMAD Party Mode is not available, all `NEEDS_CONSENSUS` findings default to **WARNING** (non-blocking) with a note: "Could not verify autonomously — recommend manual review."

---

## 4.5 Phase 5: Fix Validation Loop

When findings are confirmed (TRUE_POSITIVE from Phase 3 or CONFIRMED from Phase 4):

### Step 5.1: Generate Fix

For each confirmed finding, use the LLM fix suggestion (from Phase 3) or the Party Mode fix code (from Phase 4) to generate a code fix.

### Step 5.2: Apply Fix

Apply the fix to the source code. If the fix requires changes to multiple files, apply all changes.

### Step 5.3: Re-run Phase 1 (Deterministic Scan Only)

```bash
python3 {skill-root}/scripts/security_scanner.py {project-root} \
  --severity-threshold {threshold_from_config} \
  --config {skill-root}/config/quality-gate.yaml \
  --output {project-root}/_bmad-output/quality-gate/security-scan-results-rerun.json \
  --verbose 2>&1
```

### Step 5.4: Verify Fix

- **If the original finding is no longer present** → Fix successful, finding removed
- **If the original finding persists** → Fix failed, try alternative fix (max 2 attempts)
- **If new findings introduced by the fix** → Evaluate new findings through Phase 2-3

### Step 5.5: Fix Loop Limits

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Max fix attempts per finding | 2 | Avoid infinite loops |
| Max total fix attempts per Layer 4 run | 5 | Bound total time |
| If fix limit exceeded | FAIL with remediation guidance | Human intervention needed |

---

## 4.6 Process Results

### Severity Classification

| Severity | Weight | Default Action |
|----------|--------|----------------|
| CRITICAL | 4 | **BLOCK** — must fix before commit |
| HIGH | 3 | **BLOCK** — must fix before commit |
| MEDIUM | 2 | **WARNING** — logged, configurable |
| LOW | 1 | **INFO** — logged, non-blocking |
| INFO | 0 | **INFO** — logged, non-blocking |

### Pass/Fail Logic

**Layer 4 PASS = true ONLY if:**
1. All REQUIRED tools ran successfully (not SKIPPED, not ERROR)
2. No confirmed findings (TRUE_POSITIVE or CONFIRMED) at or above severity threshold
3. All fix validation attempts succeeded (if Phase 5 was triggered)

**Layer 4 PASS = false if:**
- Any REQUIRED tool is MISSING (not installed)
- Any confirmed finding at or above severity threshold remains after fix validation
- Fix validation loop exhausted max attempts without resolving findings

**SKIPPED tools:**
- RECOMMENDED tools that are not installed → SKIPPED, does not affect gate
- OPTIONAL tools → SKIPPED, does not affect gate
- REQUIRED tools that are not installed → **FAIL** (blocking)

---

## 4.7 Update Checkpoint State

Update in-memory state with Layer 4 results:

```json
{
  "layer4_security_defense": {
    "PASS": true,
    "phases_completed": ["deterministic", "dedup", "llm_triage"],
    "phase4_consensus_rounds": 0,
    "phase5_fix_attempts": 0,
    "findings_deduplicated": 3,
    "findings_false_positive": 1,
    "findings_confirmed": 0,
    "findings_uncertain": 0,
    "bandit": {
      "status": "PASS",
      "priority": "required",
      "findings_count": 0,
      "severity_counts": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0},
      "duration_s": 0.0,
      "details": []
    },
    "safety": { "...": "..." },
    "gitleaks": { "...": "..." },
    "semgrep": { "...": "..." },
    "checkov": { "...": "..." },
    "deptry": { "...": "..." },
    "vulture": { "...": "..." },
    "trivy": { "...": "..." },
    "llm_triage": {
      "findings_reviewed": 3,
      "true_positive": 0,
      "false_positive": 1,
      "needs_consensus": 2,
      "duration_s": 45.0
    },
    "party_mode_consensus": {
      "rounds": 1,
      "agents_consulted": ["Winston", "Murat", "Amelia"],
      "adversarial_review": true,
      "confirmed": 0,
      "rejected": 1,
      "uncertain": 1,
      "duration_s": 180.0
    }
  }
}
```

---

## 4.8 Report Findings to User

Present a summary of security findings:

```
╔═══════════════════════════════════════════════════════════════════════╗
║ Layer 4: Security & Defense — Autonomous                              ║
╠═══════════════════════════════════════════════════════════════════════╣
║ PHASE 1: Deterministic Scan                                           ║
║ REQUIRED:                                                             ║
║   bandit:    ✓ PASS (0 findings, 0.5s)                               ║
║   safety:    ✓ PASS (0 CVEs, 0.3s)                                   ║
║   gitleaks:  ✓ PASS (0 secrets, 0.2s)                                ║
║ RECOMMENDED:                                                          ║
║   semgrep:   ✗ FAIL (3 findings, 12.3s)                              ║
║   checkov:   ⊘ SKIPPED (not installed)                               ║
║   deptry:    ✓ PASS (0 findings, 0.4s)                               ║
║   vulture:   ✓ PASS (0 dead code, 0.8s)                              ║
║ OPTIONAL:                                                             ║
║   trivy:     ⊘ SKIPPED (no Dockerfile)                               ║
║                                                                       ║
║ PHASE 2: CWE Dedup + Confidence                                       ║
║   3 findings → 2 unique (1 deduplicated)                             ║
║   Confidence ≥ 0.7: 2 findings → escalate to Phase 3                 ║
║                                                                       ║
║ PHASE 3: LLM Triage                                                   ║
║   TRUE_POSITIVE:  0  → (none confirmed)                              ║
║   FALSE_POSITIVE: 1  → downgraded to WARNING                         ║
║   NEEDS_CONSENSUS: 1 → escalated to Phase 4                          ║
║                                                                       ║
║ PHASE 4: BMAD Party Mode Consensus                                    ║
║   Agents: Winston, Murat, Amelia (1 round)                           ║
║   Adversarial review: ✓                                               ║
║   CONFIRMED: 0  REJECTED: 1  UNCERTAIN: 0                            ║
║                                                                       ║
║ Findings Summary:                                                     ║
║   CRITICAL: 0  HIGH: 0  MEDIUM: 1 (WARNING)  LOW: 0  INFO: 0       ║
║                                                                       ║
║ → Layer 4: PASS (no confirmed findings at or above threshold)        ║
╠═══════════════════════════════════════════════════════════════════════╣
║ Advisory Notes:                                                       ║
║ • semgrep ha-http-url: WARNING — HTTP URL in config (false positive) ║
║   OWASP Category: A02:2021 - Cryptographic Failures                  ║
║   See: {skill-root}/references/security-tools-guide.md               ║
╚═══════════════════════════════════════════════════════════════════════╝
```

---

## 4.9 Recovery Actions

| Finding Type | Action |
|-------------|--------|
| **Secret exposed** (gitleaks) | Immediately rotate the credential. Remove from code. Add to .gitleaksignore if false positive. |
| **SQL injection** (bandit B608) | Use parameterized queries. Never concatenate user input into SQL. |
| **Hardcoded password** (bandit B105) | Move to environment variables or HA secrets.yaml |
| **Dependency CVE** (safety) | Update the vulnerable package to patched version |
| **Missing dependency** (deptry) | Add to pyproject.toml or requirements.txt |
| **Dead code** (vulture) | Remove unused code or add to .vulture-whitelist.py |
| **Docker misconfig** (trivy) | Fix Dockerfile per trivy recommendation |
| **YAML misconfig** (checkov) | Fix configuration per checkov recommendation |
| **JS/TS vulnerability** (semgrep-js) | See specific rule message for remediation |

For detailed remediation guidance, read: `{skill-root}/references/security-tools-guide.md`

For pentest verification guidance (post-gate, non-blocking), read:
- `{skill-root}/references/pentest-remediation-index.md` — **Primary index** mapping each finding type to verification commands
- `{skill-root}/references/security-tools-guide.md` Section 12 — Original pentest assets documentation

### BMAD Party Mode Consensus on Asset Integration

During the Layer 4 design review, Murat (Test Architect), Amelia (Developer), and Paige (Tech Writer) reached consensus on the role of pentest assets:

| Asset | Role | Consensus Decision |
|-------|------|-------------------|
| `pentest-checklist` | Cookbook de remediation post-gate | Reference only — NOT a gate component |
| `pentest-commands` | Fix validation commands | Reference only — used in Phase 5 (Fix Validation Loop) |
| `pentest-remediation-index` | **NEW** Central index mapping findings → commands | **Primary navigation** for fix validation |

**Amelia's insight:** Pentest commands should be part of the fix validation loop — the fix validation should use pentest-commands to verify the fix actually blocks the attack.

**Paige's insight:** `pentest-remediation-index.md` converts pentest assets from documentation nobody reads into a consultable dictionary indexed by CWE/finding type.

---

## 4.10 OWASP Category Mapping (Advisory)

When findings are detected, map them to OWASP Top 10 categories for advisory output:

| Finding Source | OWASP Category |
|---------------|----------------|
| bandit B608 (SQL injection) | A03:2021 - Injection |
| bandit B105/B106 (hardcoded password) | A07:2021 - Identification and Authentication Failures |
| bandit B506 (YAML unsafe load) | A08:2021 - Software and Data Integrity Failures |
| bandit B602 (shell=True) | A03:2021 - Injection |
| semgrep ha-eval-exec-usage | A03:2021 - Injection |
| semgrep ha-log-sensitive-data | A09:2021 - Security Logging and Monitoring Failures |
| semgrep js-hardcoded-secret | A07:2021 - Identification and Authentication Failures |
| semgrep js-jwt-weak-algorithm | A02:2021 - Cryptographic Failures |
| gitleaks (any) | A07:2021 - Identification and Authentication Failures |
| safety (CVE) | A06:2021 - Vulnerable and Outdated Components |

This mapping is **advisory only** — it helps the Ralph loop understand the security posture but does not affect the PASS/FAIL decision.

---

## 4.11 Next Step

After Layer 4 completes (PASS or FAIL):

Load and follow: `./steps/step-05-checkpoint.md`

The checkpoint will now include Layer 4 results in the global PASS/FAIL determination.
