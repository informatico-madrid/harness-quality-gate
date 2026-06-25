# Quality Gate Skill

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**A quality harness for autonomous coding agents (Ralph Loop pattern).** Validates code produced by AI agents running in autonomous loops, generating checkpoints that enable agents to verify their own output before commit.

### Key Features

- 🔒 **Fail-Fast Security** — Catches issues in <1 min before expensive mutation testing
- 🤖 **Agent-Native** — Checkpoints designed for autonomous self-verification
- 📊 **5-Layer Coverage** — From linting to security scans, SOLID to antipatterns
- 🔄 **Self-Correction** — Recovery playbooks guide agents back to the right layer
- 🎯 **Format-Agnostic** — JSON checkpoint works with any CI/CD or agent framework

## Table of Contents

1. [Overview](#overview)
2. [5-Layer Architecture](#5-layer-architecture)
3. [Two-Tier Analysis System](#two-tier-analysis-system)
4. [Execution Flow](#execution-flow)
5. [Key Files](#key-files)
6. [Configuration](#configuration)
7. [Checkpoint Output](#checkpoint-output)
8. [Tool Dependencies](#tool-dependencies)
9. [External Skill Dependencies](#external-skill-dependencies)
10. [Installation](#installation)
11. [Usage](#usage)
12. [Contributing](#contributing)
13. [Mutation Testing Workflow](MUTATION_TESTING.md) — how to run mutmut, read `mutmut results` vs `mutmut-cicd-stats.json`, close survivors honestly
14. [Mutant Killing Guide (Python)](MUTANT_KILLING_GUIDE.md) — **operative handbook for subagents**: techniques to kill mutmut mutants (dense assertions, boundary testing, spies), equivalence classification A-I with refactor solutions, 12 hard cases from real survivors
15. [Mutant Killing Guide (PHP)](MUTANT_KILLING_GUIDE_PHP.md) — **PHP-native handbook for the L1 Infection 100/100 gate**: Infection mutator table, the assertSame/assertEquals trap, strict mock expectations, visibility mutants as design feedback, `@infection-ignore-all` audit policy
14. [License](#license)

---

## Overview

This skill implements a **multi-layer quality gate harness** for autonomous coding agents. It validates **Python or PHP** code produced by AI agents through:

- **Static linting** (Python: ruff, pyright · PHP: phpstan, phpmd, php-cs-fixer)
- **Unit testing, coverage and mutation gate** (Python: pytest + mutmut · PHP: phpunit/pest + PCOV + Infection with the **MSI 100/100 hard gate**)
- **Test quality** (weak-test detection A1-A9 + diversity metrics, both languages)
- **Code quality analysis** (SOLID principles, design principles, antipatterns; PHP adds deptrac architecture validation in L3B)
- **Security scanning** (Python: bandit, vulture, deptry, gitleaks, semgrep, checkov, trivy · PHP: psalm --taint-analysis, composer audit, local-php-security-checker, shipmonk/dead-code-detector, shipmonk/composer-dependency-analyser)

Language detection is automatic and deliberately simple: a repo with `composer.json` is treated as **PHP-only**, anything else as Python. Hybrid repos are not supported.

The output is a **checkpoint JSON** that agents can parse to verify their own output before committing.

### Why a Harness?

Autonomous coding agents generate code rapidly, but without validation they often produce code that passes tests but contains quality issues, security vulnerabilities, or design flaws. This skill acts as a **harness** — a structured validation framework designed for the **Ralph Loop pattern**:

1. **Catches issues early** with fail-fast smoke tests
2. **Provides actionable feedback** with per-layer checkpoints
3. **Enables self-correction** through recovery playbooks
4. **Maintains quality standards** across autonomous coding sessions

### Design Philosophy

- **Fail-Fast**: Layer L3A (smoke test, <1 min) executes first. If it fails, time is not wasted on mutation testing (~15 min).
- **Anti-Evasion Policy**: No excuses for non-compliant code. No "pre-existing problems" or "known limitations" without tracking.
- **Two-Tier System**: Tier A (AST, fast, deterministic) + Tier B (BMAD Party Mode, multi-agent consensus).
- **Agent-First**: Checkpoints are designed for agents to consume and act upon autonomously.

---

## 5-Layer Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        QUALITY GATE WORKFLOW                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐    │
│  │   LAYER 3A       │     │   LAYER 1        │     │   LAYER 2        │    │
│  │   SMOKE TEST     │     │   TEST EXECUTION │     │   TEST QUALITY   │    │
│  │   (<1 min)       │     │   (~15 min)      │     │   (~2 min)       │    │
│  ├──────────────────┤     ├──────────────────┤     ├──────────────────┤    │
│  │ • ruff check     │     │ • pytest         │     │ • weak-test det. │    │
│  │ • ruff format    │     │ • coverage       │     │ • mutation kill  │    │
│  │ • pyright        │     │ • mutation test  │     │ • diversity      │    │
│  │ • check_headers  │     │ • E2E (optional) │     │                  │    │
│  │ • SOLID Tier A   │     │                  │     │                  │    │
│  │ • Principles     │     │                  │     │                  │    │
│  │ • Antipatterns A │     │                  │     │                  │    │
│  └────────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘    │
│           │ FAIL-FAST              │                         │              │
│           v                        │                         │              │
│  ┌────────────────────────────────┴─────────────────────────┴────────────┐ │
│  │                         LAYER 3B (TIER B)                              │ │
│  │                    DEEP QUALITY (~15 min)                              │ │
│  ├─────────────────────────────────────────────────────────────────────────┤ │
│  │ • SOLID Tier B (BMAD Party Mode)                                        │ │
│  │ • Antipatterns Tier B (BMAD Party Mode)                                 │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                        │
│                                    v                                        │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                         LAYER 4: SECURITY                                ││
│  │                         (~5-15 min)                                      ││
│  ├─────────────────────────────────────────────────────────────────────────┤ │
│  │ REQUIRED:                                                               │ │
│  │ • bandit (Python vulnerabilities)                                      │ │
│  │ • safety/pip-audit (dependency CVEs)                                    │ │
│  │ • gitleaks (secrets/API keys)                                           │ │
│  │ RECOMMENDED:                                                            │ │
│  │ • semgrep (OWASP rules + custom)                                        │ │
│  │ • checkov (YAML/JSON validation)                                         │ │
│  │ • deptry (import consistency)                                            │ │
│  │ • vulture (dead code)                                                    │ │
│  │ OPTIONAL:                                                               │ │
│  │ • trivy (Docker CVEs)                                                   │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                        │
│                                    v                                        │
│                      ┌──────────────────────────┐                          │
│                      │   CHECKPOINT JSON         │                          │
│                      │   (format-agnostic,       │                          │
│                      │    consumable by any      │                          │
│                      │    CI/CD system)           │                          │
│                      └──────────────────────────┘                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Layer Details

| Layer | Contents | Duration | Blocks on Failure |
|-------|----------|----------|-------------------|
| **L3A** | ruff, pyright, check_headers, SOLID Tier A, Principles, Antipatterns A | <1 min | Yes (FAIL-FAST) |
| **L1** | pytest, coverage, mutation testing, E2E | ~15 min | Yes |
| **L2** | weak-test detection, kill-map, diversity | ~2 min | Yes |
| **L3B** | SOLID Tier B, Antipatterns Tier B (BMAD) | ~15 min | Yes |
| **L4** | 8 security tools | ~2-5 min | Yes |

---

## Two-Tier Analysis System

This skill implements a **two-tier system** for code quality analysis:

### Tier A: AST Analysis (Deterministic)

- **Execution**: Always runs in Layer L3A
- **Method**: Python scripts using `ast.NodeVisitor`
- **Advantages**: Fast (<1 min), deterministic, no LLM required
- **Limitations**: Cannot evaluate complex semantics

### Tier B: BMAD Party Mode (Multi-Agent Consensus)

- **Execution**: Only if Tier A has findings or in Layer L3B
- **Method**: Winston (Architect), Murat (Test Architect), Amelia (Developer) + Adversarial Review
- **Advantages**: Can evaluate intent, design, business context
- **Limitations**: Slow (~15 min), requires LLM access, non-deterministic

### Patterns by Tier

**SOLID Principles:**
| Principle | Tier A (L3A) | Tier B (L3B) |
|-----------|--------------|--------------|
| SRP | Quantitative metrics | Conceptual responsibility evaluation |
| OCP | ABC/Protocol usage | Actual extensibility |
| LSP | Type hint coverage | Semantic substitutability |
| ISP | Unused methods ratio | Interface cohesion |
| DIP | Import depth, cycles | Correct abstractions |

**Antipatterns (50 total):**
- **Tier A (25 patterns)**: AP01-AP13, AP17-AP26, AP30-AP31, AP39
- **Tier B (25 patterns)**: AP14-AP16, AP19, AP27-AP29, AP32-AP38, AP40-AP50

---

## Execution Flow

### Sequence: L3A → L1 → L2 → L3B → L4 → Checkpoint

1. **Initialization** (`step-01-init.md`)
   - Load configuration
   - Create output directory
   - Verify tool availability
   - Initialize checkpoint state

2. **Layer L3A: Smoke Test** (`step-03a-layer3a.md`)
   - ruff check + format
   - pyright type check
   - check_headers (Constitution)
   - SOLID Tier A
   - Principles (DRY, KISS, YAGNI, LoD, CoI)
   - Antipatterns Tier A
   - **FAIL-FAST**: If this fails, stop here

3. **Layer L1: Test Execution** (`step-02-layer1.md`)
   - pytest
   - coverage check (≥85%)
   - mutation testing gate
   - E2E tests (optional)

4. **Layer L2: Test Quality** (`step-03-layer2.md`)
   - Weak test detection (A1-A8)
   - Mutation kill-map analysis
   - Test diversity metric

5. **Layer L3B: Deep Quality** (`step-04-layer3b.md`)
   - SOLID Tier B (BMAD Party Mode)
   - Antipatterns Tier B (BMAD Party Mode)

6. **Layer L4: Security** (`step-06-layer4.md`)
   - Phase 1: Deterministic scan
   - Phase 2: CWE deduplication + confidence scoring
   - Phase 3: LLM triage
   - Phase 4: BMAD Party Mode consensus
   - Phase 5: Fix validation loop

7. **Checkpoint** (`step-05-checkpoint.md`)
   - Calculate summary
   - Determine global PASS/FAIL
   - Write JSON

### Recovery Playbook

| On Failure | Action |
|------------|--------|
| L3A | Refactor → return to L3A |
| L1 | Fix tests → return to L1 |
| L2 | Improve tests → return to L2 |
| L3B | Refactor → return to L3A (NOT L1) |
| L4 | Fix vulnerabilities → return to L4 |

**Note**: When L3B fails after L1+L2 passed, we go to L3A (not L1) because refactoring may have broken code quality (detectable by L3A's fast AST checks) without breaking tests. This saves ~15 min of mutation testing per cycle.

---

## Key Files

### Entrypoint
| File | Purpose |
|------|---------|
| `SKILL.md` | Main skill entry point |

### Workflow
| File | Purpose |
|------|---------|
| `workflow.md` | Workflow document |
| `steps/step-01-init.md` | Initialization |
| `steps/step-03a-layer3a.md` | Layer L3A: Smoke test |
| `steps/step-02-layer1.md` | Layer L1: Test execution |
| `steps/step-03-layer2.md` | Layer L2: Test quality |
| `steps/step-04-layer3b.md` | Layer L3B: Deep quality |
| `steps/step-06-layer4.md` | Layer L4: Security |
| `steps/step-05-checkpoint.md` | Checkpoint generation |

### Analysis Modules
| Module | Purpose |
|--------|---------|
| `harness_quality_gate.adapters.python.solid_metrics` | SOLID Tier A (AST) |
| N/A | SOLID Tier B context (BMAD) — deferred |
| `harness_quality_gate.adapters.python.antipattern_tier_a` | 25 deterministic Tier A antipatterns (AST) |
| `harness_quality_gate.bmad.antipattern_judge` | 25 Tier B antipatterns — defined with context generator for BMAD review |
| `harness_quality_gate.adapters.python.principles` | DRY, KISS, YAGNI, LoD, CoI |
| `harness_quality_gate.adapters.python.weak_test` | Weak test detection (A1-A8) |
| `harness_quality_gate.bmad.mutation_analyzer` | Mutation kill-map analysis |
| N/A | Test diversity scoring — deferred |
| `harness_quality_gate.adapters.shared` | Security scanners (gitleaks, checkov, trivy, semgrep) |

### Configuration
| File | Purpose |
|------|---------|
| `config/quality-gate.yaml` | All threshold configurations |
| `harness_quality_gate/configurator.py` | Interactive configuration setup |

### References
| File | Purpose |
|------|---------|
| `references/security-tools-guide.md` | Security tools guide |
| `references/semgrep-python-rules.yaml` | Generic Python semgrep rules (15 security rules) |
| `references/home-assistant/semgrep-ha-rules.yaml` | Home Assistant specific rules (opt-in) |
| `references/semgrep-js-rules.yaml` | JavaScript/TypeScript semgrep rules |
| `references/verdict-schema.md` | Security verdict schema |
| `references/owasp-checklist.md` | OWASP Top 10 checklist |
| `references/pentest-remediation-index.md` | Remediation index |

---

## Configuration

All configuration is in `config/quality-gate.yaml`:

```yaml
# Layer 1: Test Execution
layer1:
  coverage_threshold: 85.0
  mutation_kill_threshold: 0.70

# Layer 2: Test Quality
layer2:
  weak_test:
    max_assertions_single: 1      # A1
    min_assertions: 3              # A2
    max_mock_ratio: 0.8           # A4
    # ...

# Layer 3: Code Quality (SOLID, Principles, Antipatterns)
layer3:
  solid:
    srp:
      max_public_methods: 7
      max_loc_per_class: 200
    # ...
  antipatterns:
    ap01_god_class:
      max_loc: 500
    # ...

# Layer 4: Security
layer4:
  severity_threshold: high
  confidence_threshold: 0.7
  tools:
    bandit:
      priority: required
      targets: ["src", "scripts"]
    # ...
```

### Mutation Policy: 100/100 Hard Gate

Both languages enforce the same hard gate — no per-module threshold ramps:

- **Python**: `mutmut` must report 0 survivors and 0 timeouts
  (`python3 -m harness_quality_gate.bmad.mutation_analyzer <repo> --gate`).
- **PHP**: Infection runs with `--min-msi=100 --min-covered-msi=100`;
  a config attempting to lower the thresholds is rejected with exit 4.

### Initial Configuration

No setup step is required — detection is automatic and defaults are sane:

```bash
python3 -m harness_quality_gate all {project-root} --json
```

Exit codes: `0` PASS · `1` FAIL · `2` UNSUPPORTED · `3` INFRA_INCOMPLETE
(PHP repo missing php/phpunit/phpstan/infection — payload lists
`missing_tools`) · `4` CONFIG_INVALID (v1 config schema is a hard error) ·
`5` INTERNAL_ERROR.

Optional tuning via a v2 config file (`.quality-gate.yaml`,
`config/quality-gate.yaml` or `quality-gate.yaml` with `schema_version: 2`).

---

## Checkpoint Output

The output is a JSON file in `_quality-gate/quality-gate-{timestamp}.json` designed for **agent consumption**:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "project_root": "/path/to/project",
  "overall_verdict": "PASS",
  "layers": {
    "l3a": {
      "verdict": "PASS",
      "duration_seconds": 45,
      "checks": {
        "ruff_check": {"verdict": "PASS", "details": "..."},
        "ruff_format": {"verdict": "PASS", "details": "..."},
        "pyright": {"verdict": "PASS", "details": "..."},
        "solid_tier_a": {"verdict": "PASS", "violations": []},
        "principles": {"verdict": "PASS", "violations": []},
        "antipatterns_tier_a": {"verdict": "PASS", "violations": []}
      }
    },
    "l1": {
      "verdict": "PASS",
      "duration_seconds": 900,
      "checks": {
        "pytest": {"verdict": "PASS", "tests_run": 150, "failures": 0},
        "coverage": {"verdict": "PASS", "percentage": 87.5},
        "mutation_testing": {"verdict": "PASS", "kill_rate": 0.72},
        "e2e": {"verdict": "PASS"}
      }
    },
    "l2": {...},
    "l3b": {...},
    "l4": {...}
  },
  "summary": {
    "total_checks": 45,
    "passed": 44,
    "warnings": 1,
    "failures": 0
  }
}
```

**For autonomous agents**, the checkpoint provides:
- **Per-layer verdicts** for targeted self-correction
- **Detailed failure information** with file locations and line numbers
- **Recovery guidance** via the Recovery Playbook (which layer to return to)
- **Actionable metrics** (coverage %, mutation kill rate, violation counts)

---

## Tool Dependencies

### Required Tools (L3A, L1, L2, L3B)

| Tool | Priority | Purpose |
|------|----------|---------|
| `pytest` | REQUIRED | Test execution |
| `ruff` | REQUIRED | Linting + formatting |
| `pyright` | REQUIRED | Type checking |
| `mutmut` | OPTIONAL | Mutation testing |

### Security Tools (L4)

| Tool | Priority | Purpose |
|------|----------|---------|
| `bandit` | REQUIRED | Python vulnerability scanning |
| `safety` / `pip-audit` | REQUIRED | Dependency CVE scanning |
| `gitleaks` | REQUIRED | Secret/API key detection |
| `semgrep` | RECOMMENDED | Semantic security rules |
| `checkov` | RECOMMENDED | YAML/JSON config validation |
| `deptry` | RECOMMENDED | Import consistency |
| `vulture` | RECOMMENDED | Dead code detection |
| `trivy` | OPTIONAL | Docker image scanning |

### PHP Tools

| Tool | Layer | Priority | Purpose |
|------|-------|----------|---------|
| `php` (≥8.2) | — | CRITICAL (exit 3 if missing) | Runtime |
| `phpunit` / `pest` | L1 | CRITICAL (exit 3 if missing) | Test execution |
| `infection` | L1 | CRITICAL (exit 3 if missing) | Mutation gate MSI 100/100 |
| `phpstan` | L3A | CRITICAL (exit 3 if missing) | Static analysis |
| PCOV extension | L1 | RECOMMENDED | Fast coverage for Infection |
| `phpmd` + nikic/php-parser visitors | L3A | RECOMMENDED | Antipatterns Tier A |
| `php-cs-fixer` | L3A | RECOMMENDED | Code style |
| `deptrac` | L3B | RECOMMENDED | Architecture validation |
| `psalm --taint-analysis` | L4 | RECOMMENDED | Taint flow analysis |
| `composer audit` | L4 | REQUIRED | Dependency CVE scanning |
| `local-php-security-checker` | L4 | RECOMMENDED | Security advisories |
| `shipmonk/dead-code-detector` | L4 | RECOMMENDED | Dead code (vulture equivalent) |
| `shipmonk/composer-dependency-analyser` | L4 | RECOMMENDED | Dependency analysis (deptry equivalent) |

---

## External Skill Dependencies

The quality gate skill has **soft dependencies** on other skills:

| Skill | Type | When Used | Effect if Missing |
|-------|------|-----------|------------------|
| `mutation-testing` | RECOMMENDED | On mutation testing failure | Gate fails but agent can work independently |
| `bmad-party-mode` | OPTIONAL | For Tier B (L3B) | Runs **Simulated Party Mode** (basic heuristics) with WARNING |
| `pentest-commands` | REFERENCE | Post-gate validation | Commands for verifying security fixes |
| `pentest-checklist` | REFERENCE | Post-gate verification | Structured pentesting checklists |

### How Dependencies Work

- **mutation-testing**: Recommended when mutation testing fails, but not required
- **bmad-party-mode**: If unavailable → executes Simulated Party Mode with basic heuristics, marks findings as LOW confidence. User is always notified with WARNING
- **pentest-commands/checklist**: Reference materials, not gate components

### User Notifications

When optional skills are unavailable, users are notified:

| Skill Missing | Notification | Action |
|--------------|--------------|--------|
| `bmad-party-mode` | `⚠️ WARNING: Running Simulated Party Mode...` | Run basic heuristics, mark findings as LOW confidence |
| `mutation-testing` | `⚠️ WARNING: mutation-testing skill not available...` | Continue without mutation guidance |
| `pentest-commands` | `ℹ️ INFO: pentest-commands not available...` | Use references/security-tools-guide.md |
| `pentest-checklist` | `ℹ️ INFO: pentest-checklist not available...` | Use references/owasp-checklist.md |

The gate continues with degraded functionality, but users are always informed.

### BMAD Party Mode Agents (when available)

| Agent | Role |
|-------|------|
| Winston | Architect — trust boundaries, data flows |
| Murat | Test Architect — exploitability, attack surface |
| Amelia | Developer — fix feasibility, implementation |

---

## Installation

### Prerequisites

- Python 3.10+
- pip

### Install Code Tools

```bash
# Linting and formatting
pip install ruff

# Type checking
pip install pyright

# Testing
pip install pytest pytest-cov pytest-timeout

# Mutation testing (optional)
pip install mutmut
```

### Install Security Tools

```bash
# Security scanning
pip install bandit safety
brew install gitleaks semgrep checkov trivy deptry vulture
# or
pip install semgrep checkov deptry vulture trivy
```

### Install as Skill

The skill is **agent-agnostic**. Drop the `SKILL.md` into whichever path
your agent scans for skills. The agent itself is the installer — see
`steps/step-00-install.md` for the LLM-driven tool install flow.

| Agent | Skill path (project) | Skill path (user-global) |
|-------|----------------------|--------------------------|
| opencode | `.opencode/skills/harness-quality-gate/` | `~/.config/opencode/skills/harness-quality-gate/` |
| Claude Code | `.claude/skills/harness-quality-gate/` | `~/.claude/skills/harness-quality-gate/` |
| Roo Code | `.roo/skills/harness-quality-gate/` | `~/.roo/skills/harness-quality-gate/` |
| Continue.dev | `.continue/skills/harness-quality-gate/` | `~/.continue/skills/harness-quality-gate/` |

Examples:

```bash
# opencode (project-local)
mkdir -p .opencode/skills
cp -r /path/to/harness-quality-gate .opencode/skills/

# Roo Code (user-global link)
mkdir -p ~/.roo/skills
ln -s /path/to/harness-quality-gate ~/.roo/skills/harness-quality-gate

# Claude Code (user-global copy)
mkdir -p ~/.claude/skills
cp -r /path/to/harness-quality-gate ~/.claude/skills/
```

After install, the agent reads `SKILL.md` and follows it. There is no
`install-tools` subcommand — the agent installs missing tools itself
following `steps/step-00-install.md`.

---

## Usage

### Basic Usage

```bash
# Run the full quality gate (deterministic 5-layer run)
cd /path/to/project
python3 -m harness_quality_gate all .

# Or follow the workflow manually (LLM-driven, layer by layer)
# 1. Read steps/step-00-install.md (if tools may be missing)
# 2. Read steps/step-01-init.md
# 3. Follow steps in sequence L3A → L1 → L2 → L3B → L4
```

### CLI Subcommands

The CLI exposes only **two** subcommands (per
`specs/php-support/decisions.md` §1, ratified 2026-06-11):

| Subcommand | Purpose |
|------------|---------|
| `all <repo>` | Run the full 5-layer quality gate against `<repo>` |
| `audit-ignores <repo>` | Scan for unjustified suppression annotations |

The historical subcommands from the original design (`detect`, `doctor`,
`install-tools`, `configure`, `layer3a`, `layer1`, `layer2`, `layer3b`,
`layer4`, `checkpoint`) were **deliberately not restored** after the
refactor — the skill is consumed by an LLM, not driven from a terminal.
The LLM reads the `steps/*.md` files and orchestrates the non-deterministic
parts (Tier B, fix validation) itself.

### Configure Thresholds

Edit `config/quality-gate.yaml` per project needs:

```yaml
layer1:
  coverage_threshold: 80.0  # Lower from 85 to 80

layer4:
  severity_threshold: critical  # Only block critical
```

---

## Contributing

Contributions are welcome! If this skill proves useful to you, please consider giving it a star ⭐ on GitHub — it helps the project gain visibility and encourages further development.

### How to Contribute

1. **Fork** the repository
2. **Create a branch** for your feature or fix (`git checkout -b feature/amazing-feature`)
3. **Ensure all checks pass** (run L3A smoke test first: `python3 -m harness_quality_gate all .`)
4. **Run the full quality gate before pushing**:
   - `ruff check harness_quality_gate/ tests/`
   - `pytest tests/unit/ -q --cov=harness_quality_gate --cov-fail-under=100 -p no:randomly`
   - `python -m harness_quality_gate audit-ignores harness_quality_gate` (must exit 0)
   - `make mutation` (CI checks `mutants/mutmut-cicd-stats.json`; must have 0 survived/no_tests/suspicious/timeout)
   - See [MUTATION_TESTING.md](MUTATION_TESTING.md) for the why behind each gate
5. **Commit your changes** (`git commit -m 'Add some amazing feature'`)
5. **Push to the branch** (`git push origin feature/amazing-feature`)
6. **Open a Pull Request**

### Development Guidelines

- Follow the existing code style and conventions
- Update documentation if you add new features
- Add tests if applicable (especially for new analysis scripts)
- Ensure the checkpoint JSON structure remains format-agnostic

---

## Support This Project

If `harness-quality-gate` helps you build better autonomous coding agents, consider:

- ⭐ **Starring** this repository on GitHub
- 🐛 **Reporting issues** with detailed reproduction steps
- 📝 **Contributing** improvements or new features
- 📢 **Sharing** with other developers working on Ralph Loop agents

---

## License

MIT License
