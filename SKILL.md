---
name: quality-gate
description: Execute deterministic code quality validations as a quality gate for smart-ralph task execution. Runs Layer 3A smoke test (Tier A AST, <1 min), Layer 1 (test execution), Layer 2 (test quality analysis), Layer 3B (Tier B BMAD Party Mode, ~15 min), and Layer 4 (Security & Defense, ~2-5 min). Uses Two-Tier approach: Tier A (AST deterministic) + Tier B (BMAD Party Mode consensus). Layer 4 covers 8 security tools: bandit, safety/pip-audit, gitleaks, semgrep, checkov, deptry, vulture, trivy. Generates a checkpoint JSON consumed by smart-ralph VERIFY steps. Use when you need to validate that code meets quality and security standards before COMMIT.
---

## When to Use This Skill

Activate this skill when:
- Running smart-ralph `[VERIFY]` steps
- Validating code quality before `COMMIT`
- Performing pre-merge quality checks
- Executing sprint quality gates
- Running security scans before deployment

## When NOT to Use This Skill

Do NOT activate this skill when:
- Writing new code (use dev story skill instead)
- Just exploring the codebase
- Running single unit tests (pytest alone is sufficient)
- Only need one security tool (run it directly instead)

## Inputs Required

- `{project-root}`: The repository working directory (must contain `src/` or `custom_components/` and `tests/`)
- `{project-root}/tests/`: Python test directory to analyze
- `{project-root}/tests/e2e/`: End-to-end test directory (Playwright E2E tests)
- `{project-root}/Makefile`: Must contain `make e2e` target

## Conventions

- `{skill-root}` resolves to this workflow skill's installed directory.
- `{project-root}` resolves to the repository working directory.
- Resolve sibling workflow files such as `instructions.md`, `checklist.md`, `steps/...`, and templates from `{skill-root}`, not from the workspace root.

---

## Workflow Architecture

The quality gate uses a **5-layer validation approach** (L3A→L1→L2→L3B→L4):

```
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 3A: SMOKE TEST (Tier A AST, <1 min)                         │
│  ├── ruff check + format check                                      │
│  ├── pyright type check                                             │
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
│  ├── pytest                                                         │
│  ├── coverage check                                                │
│  ├── mutation testing (per-module gate)                             │
│  └── E2E tests (make e2e) [MANDATORY]                              │
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
│  ├── 4.1 bandit          → Python vulnerability scanning            │
│  ├── 4.2 safety/pip-audit → Dependency CVE scanning                │
│  └── 4.3 gitleaks        → Secret/API key detection                │
│  RECOMMENDED (blocks gate if findings ≥ threshold):                 │
│  ├── 4.4 semgrep         → Semantic security rules (OWASP + HA)    │
│  ├── 4.5 checkov         → YAML/HA config validation               │
│  ├── 4.6 deptry          → Import consistency vs requirements       │
│  └── 4.7 vulture         → Dead code detection                     │
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

### E2E Tests (MANDATORY)

E2E tests are **OBLIGATORY** in Layer 1 and must be executed via `make e2e`.
This command automatically starts Home Assistant if needed and runs Playwright E2E tests.

**If `make e2e` fails, Layer 1 FAILS** — no exceptions.

---

## On Activation

1. Read `{skill-root}/workflow.md` and follow it exactly.
2. The workflow will guide you through all 5 layers sequentially: L3A → L1 → L2 → L3B → L4.
3. L3A is the smoke test — if it fails, stop immediately without running L1/L2/L3B/L4.
4. L4 is the security gate — runs after all quality/test layers pass.
5. Each layer produces a PASS/FAIL result stored in the checkpoint JSON.
6. The final checkpoint is consumed by smart-ralph `[COMMIT]` decision.

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
python3 {skill-root}/scripts/security_scanner.py {project-root} --severity-threshold high --verbose
```

**Individual tools** (if unified scanner unavailable):
```bash
# REQUIRED
python3 -m bandit -r custom_components/ -f json
python3 -m safety check --json
gitleaks detect --source . --report-format json --no-banner

# RECOMMENDED
python3 -m semgrep --config p/security-audit --config p/owasp-top-ten --json .
python3 -m checkov -d . --framework dockerfile yaml json --output json
python3 -m deptry .
python3 -m vulture custom_components/ --min-confidence 80

# OPTIONAL
trivy config --format json .
```

### Layer 4 References

| File | When to read |
|------|-------------|
| `references/security-tools-guide.md` | When a tool reports findings and you need remediation guidance, or when installing tools |
| `references/semgrep-ha-rules.yaml` | Custom semgrep rules for Home Assistant integrations (12 rules covering HA-specific patterns) |
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
| `scripts/solid_metrics.py` | Fast AST-based SOLID check (Tier A) |
| `scripts/llm_solid_judge.py` | SOLID context generator for BMAD agents (Tier B) |
| `scripts/weak_test_detector.py` | Weak test detection (A1-A8 rules) |
| `scripts/antipattern_checker.py` | 50 antipatterns: 25 Tier A (AST) + 25 Tier B (BMAD) |
| `scripts/antipattern_judge.py` | Tier B antipattern context generator for BMAD agents |
| `scripts/principles_checker.py` | DRY, KISS, YAGNI, LoD, CoI |
| `scripts/mutation_analyzer.py` | Mutation kill-map analysis + per-module gate (OK/NOK) |
| `scripts/diversity_metric.py` | Test diversity scoring (Levenshtein edit distance) |
| `scripts/security_scanner.py` | Unified security scanner (Layer 4, 8 tools) |
| `references/security-tools-guide.md` | Tool installation, config & remediation guide |
| `references/semgrep-ha-rules.yaml` | Custom semgrep rules for Home Assistant |

---

## Two-Tier Systems

Both SOLID and Antipatterns use a Two-Tier approach for maximum accuracy:

### Tier A: Fast AST Rules (Always Runs in L3A)
Deterministic checks using AST parsing — no external dependencies.

### Tier B: BMAD Multi-Agent Consensus (Runs in L3B)
For patterns needing semantic understanding:
- Uses context generators (`llm_solid_judge.py`, `antipattern_judge.py`)
- Spawns BMAD Party Mode with Winston (Architect) + Murat (Test Architect)
- Runs BMAD Adversarial Review to eliminate false positives
- Reaches consensus: violation confirmed if 2/3 agents agree

**Fallback:** If BMAD Party Mode is not available, Tier B patterns are marked as `SKIPPED`
and do not affect the global PASS/FAIL. Only Tier A results determine the outcome.

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

### When Gate Fails (NOK)

If mutation testing FAILS, the agent should:
1. Report which modules failed and their scores vs thresholds
2. **RECOMMEND** activating the `mutation-testing` skill for guidance on improving weak tests

---

## Output Format

The checkpoint JSON follows this structure:

```json
{
  "checkpoint": "quality-gate",
  "timestamp": "2026-04-30T12:00:00Z",
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
    "layer1_test_execution": { "PASS": true, ... },
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
