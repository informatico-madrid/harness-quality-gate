---
name: harness-quality-gate
description: A polyglot quality harness for autonomous coding agents (Ralph Loop pattern). Detects and validates Python or PHP code produced by AI agents through a 5-layer quality gate with L3A, L1, L2, L3B and L4 stages. Uses Two-Tier design using Tier A (AST deterministic, under one minute) and Tier B (BMAD Party Mode consensus, roughly fifteen minutes). Layer 4 covers 8 security tools. Creates checkpoint JSON for agent self-verification before commit. Select this skill when you need to validate code quality and security standards without manual intervention within Ralph Loop workflows.
---

## When to Use This Skill

Activate this skill when:
- Autonomous coding agents need to verify their own output (Ralph Loop pattern)
- Running agent `[VERIFY]` steps in Ralph Loop workflows
- Validating code quality before `COMMIT` in autonomous agent loops
- Performing pre-merge quality checks
- Executing sprint quality gates
- Running security scans before deployment

## When NOT to Use This Skill

Do NOT activate this skill when:
- Writing new code (use dev story skill instead)
- Just exploring the codebase
- Running single unit tests (pytest / PHPUnit alone is sufficient)
- Only need one security tool (run it directly instead)
- Not using Ralph Loop or similar autonomous coding patterns

## Inputs Required

- `{project-root}`: The repository working directory (must contain `src/` and `tests/`)
- Language is auto-detected: Python (via `pyproject.toml` / `setup.py`) or PHP (via `composer.json`)

## Conventions

- `{skill-root}` resolves to this skill's installed directory. The skill is
  agent-agnostic: in Claude Code that is `${CLAUDE_SKILL_DIR}`; in other
  agents or CI systems it is wherever the skill files were installed.
- `{project-root}` resolves to the repository working directory.
- Resolve sibling workflow files such as `workflow.md`, `steps/...`,
  `config/...` and `references/...` from `{skill-root}`, not from the
  workspace root.

---

## Workflow Architecture

The quality gate uses a **5-layer validation approach** (L3A→L1→L2→L3B→L4) with **language-aware tool dispatch**:

- **Python**: ruff, pyright, pytest, mutmut, bandit, vulture, deptry, gitleaks, semgrep
- **PHP**: PHP-CS-Fixer, phpstan, phpunit, infection (MSI 100/100 gate), phpmd,
  deptrac (architecture, L3B), psalm --taint-analysis (L4), composer audit (L4),
  local-php-security-checker, shipmonk/dead-code-detector,
  shipmonk/composer-dependency-analyser, gitleaks, semgrep

> **Detection policy:** a repo containing `composer.json` is treated as
> **PHP-only**; anything else is treated as Python. Hybrid Python+PHP repos
> are deliberately not supported (decision 69b05df, ratified): no 3-tier
> detection, no detection cache, no hybrid dispatch.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 3A: SMOKE TEST (Tier A AST, <1 min)                         │
│  ├── <python> ruff check + format check                             │
│  ├── <python> pyright type check                                    │
│  ├── <php> PHP-CS-Fixer check                                       │
│  ├── <php> phpstan --version                                        │
│  ├── check_headers                                                  │
│  ├── SOLID Tier A (fast AST)                                        │
│  ├── Principles (DRY/KISS/YAGNI/LoD/CoI)                           │
│  └── Antipatterns Tier A (25 patterns, AST-based)                  │
│                              │                                      │
│              ┌───────────────┴───────────────┐                     │
│              ▼                               ▼                     │
│        L3A FAIL                           L3A PASS                  │
│        (STOP - fail-fast)                  │                       │
│                                             ▼                       │
└─────────────────────────────────────────────────────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 1: TEST EXECUTION (~15 min)                                 │
│  ├── <python> pytest                                                │
│  ├── <python> coverage check                                        │
│  ├── <php> phpunit                                                  │
│  ├── <php> infection (MSI 100/100 gate)                            │
│  ├── mutation testing (per-module gate)                             │
│  └── E2E tests (make e2e) [OPTIONAL]                              │
│                              │                                      │
│              ┌───────────────┴───────────────┐                     │
│              ▼                               ▼                     │
│        L1 FAIL                           L1 PASS                   │
│        (refactor tests)                    │                       │
│                                             ▼                       │
└─────────────────────────────────────────────────────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 2: TEST QUALITY (~2 min)                                     │
│  ├── Weak test detection (A1-A8 rules)                              │
│  ├── Mutation kill-map analysis                                     │
│  └── Test diversity metric                                         │
│                              │                                      │
│              ┌───────────────┴───────────────┐                     │
│              ▼                               ▼                     │
│        L2 FAIL                           L2 PASS                   │
│        (improve tests)                     │                       │
│                                             ▼                       │
└─────────────────────────────────────────────────────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 3B: DEEP QUALITY (Tier B BMAD Party Mode, ~15 min)           │
│  ├── SOLID Tier B (BMAD multi-agent consensus)                      │
│  └── Antipatterns Tier B (BMAD multi-agent consensus)              │
│                              │                                      │
│              ┌───────────────┴───────────────┐                     │
│              ▼                               ▼                     │
│        L3B FAIL                           L3B PASS                  │
│        (refactor → L3A)                   │                         │
│        NO go to L1                        ▼                         │
└─────────────────────────────────────────────────────────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 4: SECURITY & DEFENSE (~2-5 min)                             │
│  REQUIRED (blocks gate if missing/failing):                         │
│  ├── <python> 4.1 bandit       → Python vulnerability scanning      │
│  ├── <python> 4.2 safety       → Python dependency CVE scanning     │
│  ├── <php> 4.1 composer-audit  → PHP dependency CVE scanning        │
│  └── 4.3 gitleaks              → Secret/API key detection           │
│  RECOMMENDED (blocks gate if findings ≥ threshold):                 │
│  ├── 4.4 semgrep → Semantic security rules (language-agnostic)     │
│  ├── 4.5 checkov → YAML/HA config validation                       │
│  ├── <python> 4.6 deptry  → Import consistency vs requirements      │
│  ├── <python> 4.7 vulture → Dead code detection                    │
│  └── <php> composer-security-checker → PHP security advisory scan  │
│  OPTIONAL (never blocks gate):                                      │
│  └── 4.8 trivy           → Docker image CVE scanning               │
│                              │                                      │
│              ┌───────────────┴───────────────┐                     │
│              ▼                               ▼                     │
│        L4 FAIL                           L4 PASS                    │
│        (fix vulns → L4)                  (COMPLETE)                │
└─────────────────────────────────────────────────────────────────────┘
```

### Fail-Fast: L3A as Smoke Test

**L3A acts as a smoke test — if code quality fails, don't waste time on mutation testing (~15 min), BMAD Party Mode (~15 min), or security scanning (~2-5 min).**

| If L3A FAILS | Action |
|--------------|--------|
| Refactorizar código | Go back to L3A |
| Maximum retries | 3 |
| If still failing | Block iteration |

### Recovery Playbook

| When | Action |
|------|--------|
| L3A FAIL | Refactorizar código → volver a L3A (máximo 3 reintentos) |
| L1 FAIL | Arreglar tests → volver a L1 |
| L2 FAIL | Mejorar tests → volver a L2 |
| L3B FAIL | Refactorizar código → volver a L3A (NO a L1) |
| L4 FAIL | Corregir vulnerabilidades → volver a L4 (no re-run L1-L3B) |

### E2E Tests (OPTIONAL)

E2E tests are **OPTIONAL** in Layer 1. If `make e2e` is not available or fails, the step is marked as `SKIPPED` or `WARNING` and does not block Layer 1 PASS.

---

## On Activation

### First Time Setup

No configurator step is needed (the standalone configurator was deliberately
removed — decision 69b05df). Language detection is automatic and the gate
runs with sane defaults:

```bash
$PYTHON_RUNNER -m harness_quality_gate all {project-root} --json
```

> **PYTHON_RUNNER:** This variable is resolved in `steps/step-01-init.md` to
> `{project-root}/.venv/bin/python` when a venv exists, or `python3` otherwise.
> **Never** use bare `python3` — it resolves to the system interpreter which
> may lack the project's dev dependencies, causing false FAILs.

Optional: a v2 config file (`.quality-gate.yaml`, `config/quality-gate.yaml`
or `quality-gate.yaml` with `schema_version: 2`) can tune thresholds. v1
config files are a **hard error** (exit 4). Missing critical PHP tools
(php, phpunit, phpstan, infection) produce exit 3 (INFRA_INCOMPLETE) with
the missing list in the JSON payload.

### Normal Workflow

1. Read `{skill-root}/workflow.md` and follow it exactly.
2. If a custom configuration exists at `{project-root}/_quality-gate/quality-gate.yaml`, it will be used. Otherwise, defaults are used from `{skill-root}/config/quality-gate.yaml`.
3. The workflow will guide you through all 5 layers sequentially: L3A → L1 → L2 → L3B → L4.
4. L3A is the smoke test — if it fails, stop immediately without running L1/L2/L3B/L4.
5. L4 is the security gate — runs after all quality/test layers pass.
6. Each layer produces a PASS/FAIL result stored in the checkpoint JSON.
7. The checkpoint enables agents to verify their own output before proceeding

---

## Layer 4: Security & Defense Details

### Tool Priority

| Priority | Behavior | Examples |
|----------|----------|---------|
| **REQUIRED** | Blocks gate if tool is missing or has findings ≥ threshold | bandit, safety, gitleaks |
| **RECOMMENDED** | Blocks gate if findings ≥ threshold; SKIPPED if not installed | semgrep, checkov, deptry, vulture |
| **OPTIONAL** | Never blocks gate; SKIPPED if not installed | trivy |

### Severity Threshold

Configurable in `config/quality-gate.yaml` under `layer4.severity_threshold` (default: `high`).

| Severity | Default Action |
|----------|----------------|
| CRITICAL | BLOCK — must fix immediately |
| HIGH | BLOCK — must fix (default threshold) |
| MEDIUM | WARNING — logged, non-blocking |
| LOW | INFO — logged, non-blocking |

### Running Security Scans

**Unified scanner (recommended):**
```bash
$PYTHON_RUNNER -m harness_quality_gate.full {project-root} --layer l4 --severity-threshold high --verbose
```

**Individual tools** (if unified scanner unavailable):
```bash
# REQUIRED
$PYTHON_RUNNER -m bandit -r src/ -f json
$PYTHON_RUNNER -m safety check --json
gitleaks detect --source . --report-format json --no-banner

# RECOMMENDED
$PYTHON_RUNNER -m semgrep --config p/security-audit --config p/owasp-top-ten --json .
$PYTHON_RUNNER -m checkov -d . --framework dockerfile yaml json --output json
$PYTHON_RUNNER -m deptry .
$PYTHON_RUNNER -m vulture src/ --min-confidence 80

# OPTIONAL
trivy config --format json .
```

### Layer 4 References

| File | When to read |
|------|-------------|
| `references/security-tools-guide.md` | When a tool reports findings and you need remediation guidance, or when installing tools |
| `references/home-assistant/semgrep-ha-rules.yaml` | Custom semgrep rules for Home Assistant integrations (12 rules, opt-in: pass them to semgrep manually) |
| `references/semgrep-js-rules.yaml` | Custom semgrep rules for JavaScript/TypeScript (13 rules, provenance metadata included) |
| `references/pentest-remediation-index.md` | **Primary index** mapping finding types to pentest verification commands and checklists |

---

## Key Files

| File | Purpose |
|------|---------|
| `workflow.md` | Main orchestrator with layer overview |
| `steps/step-01-init.md` | Initialization and state setup |
| `steps/step-03a-layer3a.md` | Layer 3A: Tier A smoke test (first after init) |
| `steps/step-02-layer1.md` | Layer 1: Test execution |
| `steps/step-03-layer2.md` | Layer 2: Test quality analysis |
| `steps/step-04-layer3b.md` | Layer 3B: Tier B deep quality |
| `steps/step-06-layer4.md` | Layer 4: Security & Defense |
| `steps/step-05-checkpoint.md` | Final checkpoint generation |
| `config/quality-gate.yaml` | All configurable thresholds (including L4) |
| `harness_quality_gate.adapters.python.solid_metrics` | Fast AST-based SOLID check (Tier A) |
| `harness_quality_gate/bmad/` | SOLID context generator for BMAD agents (Tier B) — deferred |
| `harness_quality_gate.adapters.python.weak_test` | Weak test detection (A1-A8 rules) |
| `harness_quality_gate.adapters.python.antipattern_tier_a` | 25 deterministic Tier A antipatterns (AST) |
| `harness_quality_gate.bmad.antipattern_judge` | 25 Tier B antipatterns — defined with context generator for BMAD review |
| `harness_quality_gate.adapters.python.principles` | DRY, KISS, YAGNI, LoD, CoI |
| `harness_quality_gate.bmad.mutation_analyzer` | Mutation kill-map analysis + per-module gate (OK/NOK) |
| N/A | Test diversity scoring — deferred to future iteration |
| `harness_quality_gate.adapters.shared` | Security scanners (gitleaks, checkov, trivy, semgrep) |
| `references/security-tools-guide.md` | Tool installation, config & remediation guide |
| `references/home-assistant/semgrep-ha-rules.yaml` | Custom semgrep rules for Home Assistant (opt-in) |

---

## External Skills & Dependencies

The quality gate skill has **soft dependencies** on other skills. They are NOT required but enhance functionality when available.

### Skill Dependencies

| Skill | Type | When Recommended | What It Does |
|-------|------|------------------|--------------|
| `mutation-testing` (`mutation-testing-guide`) | MANDATORY | When mutation testing fails | Full mutation killing protocol (§0–§7); injected into sub-agent prompts |
| `bmad-party-mode` | OPTIONAL | For Tier B deep quality (L3B) | Multi-agent consensus for SOLID Tier B and Antipatterns Tier B |
| `pentest-commands` | REFERENCE | Post-gate fix validation | Specific commands to verify security fixes actually work |
| `pentest-checklist` | REFERENCE | Post-gate verification | Structured checklists for penetration testing categories |

### How Dependencies Work

1. **mutation-testing** (`mutation-testing-guide`) skill:
    - When mutation testing FAILS (NOK), the skill is **MANDATORY — not optional**.
    - The coordinator MUST load `MUTANT_KILLING_GUIDE_SKILL.md` and forward its
      full content to ANY agent/sub-agent tasked with killing survivors.
    - No sub-agent may kill mutants without this skill loaded in its prompt.
    - If not loaded, the gate stays FAIL until agents kill survivors independently
      using the protocol described in this document.

2. **bmad-party-mode** skill:
   - Tier B (L3B) uses this if available; if not, Tier B is marked SKIPPED
   - SKIPPED does NOT block the gate — only Tier A results determine PASS/FAIL
   - Graceful degradation: quality gate still functions without BMAD

3. **pentest-commands** and **pentest-checklist**:
   - These are REFERENCE documentation, NOT gate components
   - Used in Layer 4 Phase 5 (Fix Validation Loop) to verify security fixes
   - Can be consulted manually but don't block/unblock the gate

### Agent Integration

This skill is designed to be consumed by **any autonomous agent or CI/CD system**:

- Layer L3A → L1 → L2 → L3B → L4 executes sequentially
- Each layer produces PASS/FAIL stored in checkpoint JSON
- **Checkpoint JSON is format-agnostic** - it is a standard JSON file that any system can parse
- Agents use the checkpoint to verify their own output before proceeding
- If checkpoint.PASS = true → agent can proceed with the next step

### Skill Availability Notifications

When optional skills are not available, the user is informed:

| Skill Missing | Notification | Action |
|--------------|--------------|--------|
| `bmad-party-mode` | `⚠️ WARNING: Running Simulated Party Mode...` | Run basic heuristics, flag findings as LOW confidence |
| `mutation-testing-guide` | `⚠️ ERROR: mutation guide not available. The gate CANNOT proceed.` | Load `MUTANT_KILLING_GUIDE_SKILL.md` from the skill repository. The gate does NOT continue without it. |
| `pentest-commands` | `ℹ️ INFO: pentest-commands not available...` | Use references/security-tools-guide.md instead |
| `pentest-checklist` | `ℹ️ INFO: pentest-checklist not available...` | Use references/owasp-checklist.md instead |

**The gate continues** with degraded functionality, with user notification.

### BMAD Party Mode Agents

BMAD Party Mode (when available) spawns these agents for consensus:

| Agent | Role |
|-------|------|
| Winston | Architect — trust boundaries, data flows |
| Murat | Test Architect — exploitability, attack surface |
| Amelia | Developer — fix feasibility, implementation |

---

## Two-Tier Systems

Both SOLID and Antipatterns use a Two-Tier approach for maximum accuracy:

### Tier A: Fast AST Rules (Always Runs in L3A)
Deterministic checks using AST parsing — no external dependencies.

### Tier B: BMAD Multi-Agent Consensus (Runs in L3B)
For patterns needing semantic understanding. Uses `bmad-party-mode` skill when available. If not available, Tier B patterns are marked as `SKIPPED` and do not affect global PASS/FAIL. Only Tier A results determine the outcome.

---

## Mutation Testing Gate

Mutation testing uses **per-module thresholds** defined in `{project-root}/pyproject.toml` under `[tool.quality-gate.mutation]`.

### How it works

1. **Layer 1 (step-02)** runs `mutation_analyzer.py --gate` which:
   - Parses `.mutmut/index.html` for kill statistics per file
   - Reads `pyproject.toml` `[tool.quality-gate.mutation]` for per-module thresholds
   - Compares each module's kill rate against its threshold
   - Outputs OK/NOK gate result with per-module table

2. **Layer 2 (step-03)** runs `mutation_analyzer.py` (original mode) for detailed kill-map analysis

### Managing Thresholds

Edit `pyproject.toml` `[tool.quality-gate.mutation]` section to:
- Set `global_kill_threshold` (fallback for modules without specific target)
- Set per-module `kill_threshold` under `[tool.quality-gate.mutation.modules.<name>]`
- Track module `status` (`"in_progress"`, `"passing"`, `"planned"`, `"future"`)
- Configure incremental strategy (`increment_step`, `target_final`)

### When Gate Fails (NOK) — **MANDATORY MUTATION KILLING PROTOCOL**

If mutation testing FAILS, the mutation killing phase is **MANDATORY, not optional.** Every survivor MUST be addressed before the gate can pass.

**STEP 1 — Load the `mutation-testing-guide` skill:**

The coordinator MUST load `{skill-root}/MUTANT_KILLING_GUIDE_SKILL.md` (name: `mutation-testing-guide`) and forward its full content to ANY agent/sub-agent that is tasked with killing survivors. **There is no shortcut — no sub-agent may kill mutants without this skill loaded in its prompt.**

This skill contains 7 mandatory sections (§0–§7):
- **§0:** Priority chain — `test > refactor > pragma` (pragma is the absolute last resort, requires `# reason:` + `# audited:`)
- **§1:** Per-survivor loop (`mutmut show` → classify → kill → verify)
- **§2:** What mutmut mutates → what assertion kills each mutation type
- **§3:** Triage before acting (observable from outside → weak test; observable only inside → spy/mock; unobservable → equivalent, goto §5)
- **§4:** Catalog of kill techniques (dense assertions, boundaries, spies, break/continue, accumulation)
- **§5:** Equivalence taxonomy (Types A–I) — every equivalent MUST be proven, not assumed
- **§6:** Hard cases with real repo survivors (H1–H12)
- **§7:** Pragma policy — must include `# reason:` and `# audited:` in the 5 lines above, or the gate rejects it

**STEP 2 — Load the sharded guide index:**

The coordinator MUST also reference `{skill-root}/MUTANT_KILLING_GUIDE.md` and the `MUTANT_KILLING_GUIDE/` directory. Agents MUST load specific shards based on their survivor type:
- **h14** — Trampa del XX-wrap: `"foo" in out` NUNCA mata `"XXfooXX"` (use `==` or anchored literal)
- **h15** — Gemelos falsy: `""` vs `None` indistinguibles con `if x:`, cambia a `is not None`
- **3-triage** — Clasifica TODO mutante ANTES de escribir cualquier test
- **7-politica-de-pragmas** — Pragma sin `# reason:` + `# audited:` = RECHAZADO

**STEP 3 — Delegate with skill in prompt:**

When the coordinator dispatches `python-development__python-pro`, `rust-pro`, or any other agent to kill survivors, the FULL text of `MUTANT_KILLING_GUIDE_SKILL.md` MUST be copied into that agent's prompt. **Never delegate mutation kills without the guide.**

**Report to user:**
- Which modules failed and their scores vs thresholds
- List of surviving mutants per failed module
- Which MUTANT_KILLING_GUIDE_SKILL.md sections (§X) guide each kill decision
- Final MSI target: **100%** (no threshold tolerance — every survivor MUST be killed or proven equivalent with a valid pragma)

---

## Output Format

The checkpoint JSON follows this structure:

```json
{
  "checkpoint": "quality-gate",
  "timestamp": "2026-04-30T12:00:00Z",
  "language": "python|php",
  "PASS": true,
  "layers": {
    "layer3a_smoke_test": {
      "PASS": true,
      "ruff": {"status": "PASS", "violations": 0},
      "pyright": {"status": "PASS", "errors": 0},
      "check_headers": {"status": "PASS"},
      "SOLID_tier_a": {"S": "PASS", "O": "PASS", "L": "PASS", "I": "PASS", "D": "PASS"},
      "principles": {"DRY": "PASS", "KISS": "PASS", "YAGNI": "PASS", "LoD": "PASS", "CoI": "PASS"},
      "antipatterns_tier_a": {"passed": 23, "failed": 2}
    },
    "layer1_test_execution": {
      "PASS": true,
      "python": {"pytest": {"total": 150, "passed": 150}, "coverage": {"rate": 0.98}, "infection": {"msi": 1.0}},
      "php": {"phpunit": {"total": 100, "passed": 100}, "infection": {"msi": 1.0, "covered_msi": 1.0}}
    },
    "layer2_test_quality": { "PASS": true, ... },
    "layer3b_deep_quality": {
      "PASS": true,
      "SOLID_tier_b": { "status": "PASS", "violations": [] },
      "antipatterns_tier_b": { "status": "SKIPPED" }
    },
    "layer4_security_defense": {
      "PASS": true,
      "bandit": {"status": "PASS", "findings_count": 0, "severity_counts": {"critical": 0, "high": 0, "medium": 2, "low": 5}},
      "safety": {"status": "PASS", "findings_count": 0, "severity_counts": {}},
      "gitleaks": {"status": "PASS", "findings_count": 0, "severity_counts": {}},
      "semgrep": {"status": "PASS", "findings_count": 0, "severity_counts": {}},
      "checkov": {"status": "SKIPPED", "findings_count": 0},
      "deptry": {"status": "PASS", "findings_count": 0, "severity_counts": {}},
      "vulture": {"status": "PASS", "findings_count": 0, "severity_counts": {}},
      "trivy": {"status": "SKIPPED", "findings_count": 0}
    }
  },
  "summary": {
    "total_tests": 150,
    "weak_test_count": 2,
    "SOLID_violations_tier_a": 0,
    "SOLID_violations_tier_b": 0,
    "principle_violations": 1,
    "antipattern_violations_tier_a": 3,
    "antipattern_violations_tier_b": 0,
    "security_total_findings": 7,
    "security_findings_by_severity": {"critical": 0, "high": 0, "medium": 2, "low": 5, "info": 0}
  }
}
```
