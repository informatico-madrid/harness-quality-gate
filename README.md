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
13. [License](#license)

---

## Overview

This skill implements a **multi-layer quality gate harness** for autonomous coding agents. It validates Python code produced by AI agents through:

- **Static linting** (ruff, pyright)
- **Unit testing and coverage** (pytest)
- **Mutation testing** (mutmut)
- **Code quality analysis** (SOLID principles, design principles, antipatterns)
- **Security scanning** (bandit, safety, gitleaks, semgrep, checkov, deptry, vulture, trivy)

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

### Analysis Scripts
| File | Purpose |
|------|---------|
| `scripts/solid_metrics.py` | SOLID Tier A (AST) |
| `scripts/llm_solid_judge.py` | SOLID Tier B context (BMAD) |
| `scripts/antipattern_checker.py` | Antipatterns Tier A (50 AST patterns) |
| `scripts/antipattern_judge.py` | Antipatterns Tier B context (BMAD) |
| `scripts/principles_checker.py` | DRY, KISS, YAGNI, LoD, CoI |
| `scripts/weak_test_detector.py` | Weak test detection (A1-A8) |
| `scripts/mutation_analyzer.py` | Mutation kill-map analysis |
| `scripts/diversity_metric.py` | Test diversity scoring |
| `scripts/security_scanner.py` | Unified security scanner (Layer L4) |

### Configuration
| File | Purpose |
|------|---------|
| `config/quality-gate.yaml` | All threshold configurations |
| `scripts/configurator.py` | Interactive configuration setup |

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

### Per-Module Mutation Thresholds

The skill supports per-module mutation thresholds via `pyproject.toml`:

```toml
[tool.quality-gate.mutation]
# Per-module thresholds override global
[tool.quality-gate.mutation."src/core"]
kill_threshold = 0.80

[tool.quality-gate.mutation."src/utils"]
kill_threshold = 0.65
```

### Initial Configuration

For new projects, run the interactive configurator:

```bash
python3 scripts/configurator.py
```

This auto-detects project structure and asks for confirmation on each setting.

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

```bash
# Option 1: Local link
cd ~/.roo/skills
ln -s /path/to/quality-gate quality-gate

# Option 2: Copy
cp -r /path/to/quality-gate ~/.roo/skills/
```

---

## Usage

### Basic Usage

```bash
# Run the full quality gate
cd /path/to/project
python3 /path/to/quality-gate/scripts/security_scanner.py .

# Or follow the workflow manually
# 1. Read step-01-init.md
# 2. Follow steps in sequence L3A → L1 → L2 → L3B → L4
```

### Initial Configuration

```bash
# Auto-detect project structure and configure
python3 scripts/configurator.py
```

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
3. **Ensure all checks pass** (run L3A smoke test first: `python3 scripts/security_scanner.py .`)
4. **Commit your changes** (`git commit -m 'Add some amazing feature'`)
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
