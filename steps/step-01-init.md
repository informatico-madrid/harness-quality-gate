# Step 01: Initialization

**Goal:** Setup environment, load config, cleanup orphans, prepare checkpoint state.

---

## 1.1 Load Configuration

Read config from `{skill-root}/config/quality-gate.yaml` if exists.

If no config found, use defaults:
- `output_folder = _bmad-output/quality-gate`
- `timestamp = current datetime ISO format`
- `checkpoint_file = {output_folder}/quality-gate-{timestamp}.json`

---

## 1.2 Create Output Directory

```bash
mkdir -p {project-root}/_bmad-output/quality-gate
```

---

## 1.3 Kill Pytest Orphans

Execute the orphan cleanup script to ensure clean test environment:

```bash
$PYTHON_RUNNER {project-root}/.ralph/kill_pytest_orphans.py
```

If script not found, skip this step.

---

## 1.4 Initialize Checkpoint State

Create in-memory state structure:

```json
{
  "checkpoint": "quality-gate",
  "timestamp": "<current ISO timestamp>",
  "PASS": null,
  "layers": {
    "layer3a_smoke_test": {
      "PASS": null,
      "ruff": {"status": null, "violations": 0},
      "pyright": {"status": null, "errors": 0},
      "check_headers": {"status": null},
      "SOLID_tier_a": {"S": null, "O": null, "L": null, "I": null, "D": null},
      "principles": {"DRY": null, "KISS": null, "YAGNI": null, "LoD": null, "CoI": null},
      "antipatterns_tier_a": {"status": null, "violations": 0}
    },
    "layer1_test_execution": {
      "PASS": null,
      "pytest": {"status": null, "duration_s": null, "tests_total": null, "tests_passed": null, "tests_failed": null},
      "coverage": {"status": null, "actual": null, "threshold": 85.0},
      "mutation_testing": {"status": null, "kill_rate": null, "threshold": 0.70, "installed": false}
    },
    "layer2_test_quality": {
      "PASS": null,
      "weak_tests": [],
      "mutation_kill_map": {},
      "diversity_score": null
    },
    "layer3b_deep_quality": {
      "PASS": null,
      "SOLID_tier_b": {"status": null, "violations": []},
      "antipatterns_tier_b": {"status": null, "violations": []}
    },
    "layer4_security_defense": {
      "PASS": null,
      "bandit": {"status": null, "findings_count": 0, "severity_counts": {}},
      "safety": {"status": null, "findings_count": 0, "severity_counts": {}},
      "gitleaks": {"status": null, "findings_count": 0, "severity_counts": {}},
      "semgrep": {"status": null, "findings_count": 0, "severity_counts": {}},
      "checkov": {"status": null, "findings_count": 0, "severity_counts": {}},
      "deptry": {"status": null, "findings_count": 0, "severity_counts": {}},
      "vulture": {"status": null, "findings_count": 0, "severity_counts": {}},
      "trivy": {"status": null, "findings_count": 0, "severity_counts": {}}
    },
    "layer3_code_quality": {
      "PASS": null,
      "ruff": {"status": null, "violations": 0},
      "pyright": {"status": null, "errors": 0},
      "check_headers": {"status": null},
      "SOLID": {"S": {"status": null, "violations": []}, "O": {"status": null, "violations": []}, "L": {"status": null, "violations": []}, "I": {"status": null, "violations": []}, "D": {"status": null, "violations": []}},
      "principles": {"DRY": {"status": null, "violations": 0}, "KISS": {"status": null, "violations": 0}, "YAGNI": {"status": null, "violations": 0}, "LoD": {"status": null, "violations": 0}, "CoI": {"status": null, "violations": 0}},
      "antipatterns": {}
    }
  },
  "summary": {
    "total_tests": null,
    "passed": null,
    "failed": null,
    "coverage_actual": null,
    "mutation_kill_rate": null,
    "weak_test_count": 0,
    "SOLID_violations_tier_a": 0,
    "SOLID_violations_tier_b": 0,
    "principle_violations": 0,
    "antipattern_violations_tier_a": 0,
    "antipattern_violations_tier_b": 0,
    "security_total_findings": 0,
    "security_findings_by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0},
    "security_tools_run": [],
    "security_tools_skipped": [],
    "security_tools_error": []
  }
}
```

---

## 1.5 Verify Tools Availability

Check which tools are installed **in the project venv, or on the system PATH**.

**If a venv is present, check venv first:**

```bash
if [ -d "{project-root}/.venv" ]; then
  PYTHON_RUNNER="{project-root}/.venv/bin/python"
else
  PYTHON_RUNNER="python3"
fi
export PYTHON_RUNNER
```

**Then run checks (use the candidate-aware API when more than one
candidate exists for a tool — see `steps/step-00-install.md` §0.8):**

```bash
# Core tools (L3A, L1, L2, L3B) — check venv first
$PYTHON_RUNNER -m pytest --version 2>/dev/null && echo "pytest=OK" || echo "pytest=MISSING"
$PYTHON_RUNNER -m ruff check --version 2>/dev/null && echo "ruff=OK" || echo "ruff=MISSING"
$PYTHON_RUNNER -m pyright --version 2>/dev/null && echo "pyright=OK" || echo "pyright=MISSING"
$PYTHON_RUNNER -c "import mutmut" 2>/dev/null && echo "mutmut=OK" || echo "mutmut=MISSING"

# Security tools (L4)
$PYTHON_RUNNER -c "import bandit" 2>/dev/null && echo "bandit=OK" || echo "bandit=MISSING"
$PYTHON_RUNNER -c "import safety" 2>/dev/null && echo "safety=OK" || echo "safety=MISSING"
which gitleaks 2>/dev/null && echo "gitleaks=OK" || echo "gitleaks=MISSING"
```

**Candidate-aware disambiguation (when something is MISSING or
multiple candidates exist):**

```bash
$PYTHON_RUNNER -c "
from harness_quality_gate.bootstrap import find_tool_candidates
from pathlib import Path
import json
repo = Path('{project-root}')
for name in ('ruff', 'pyright', 'pytest', 'mutmut', 'bandit', 'safety'):
    cs = find_tool_candidates(name, repo)
    print(name, json.dumps([(c.provenance, str(c.path)) for c in cs]))
"
```

The output lists every place the LLM should look. If the user has
multiple installations of the same tool, this is the structured data
the agent uses to present a clear choice (see §0.8 in
`steps/step-00-install.md`).

Store availability in state for conditional execution.

---

## 1.5.5 Detect and Enforce venv (Python projects only)

**CRITICAL**: Python quality-gate layers (L1-L4) require tools like pytest, ruff,
pyright, radon, bandit, etc. These are typically installed as dev-dependencies in
the project's virtualenv (`{project-root}/.venv/`).

When the CLI is invoked from the **system Python** (e.g., `python3 -m harness_quality_gate all .`),
all Python adapters use `sys.executable` which resolves to the **currently running interpreter**.
If running from system Python but the project uses a venv, tools like pytest **are not visible**
→ L1 fails with teardown errors, L3A fails with `reportMissingImports`.

**Fix — always invoke from the venv:**

```bash
# Check if project has a .venv
if [ -d "{project-root}/.venv" ]; then
  # Verify .venv Python has the required packages
  .venv/bin/python -c "import pytest; import ruff" 2>/dev/null && echo "VENV_CHECK=OK" || echo "VENV_CHECK=MISSING_DEPS"

  # If venv_check fails, recommend activation:
  echo "WARN: Use .venv/bin/python -m harness_quality_gate all ."
  PYTHON_RUNNER="{project-root}/.venv/bin/python"
else
  echo "VENV_CHECK=SKIPPED"
  PYTHON_RUNNER="python3"
fi
export PYTHON_RUNNER
# PYTHON_RUNNER is used by ALL subsequent step files — never use bare python3
```

**Decision:**
- `VENV_CHECK=OK` → proceed normally — all tools available in venv
- `VENV_CHECK=MISSING_DEPS` → warn: `pip install -e ".[dev]"` in the venv
- `VENV_CHECK=SKIPPED` (no .venv) → tools must be available on system PATH (CI/CD uses this path)

---

## 1.6 Detect Project Language

Run this check to determine whether the project is PHP or Python:

```bash
# Check for PHP project
if [ -f "{project-root}/composer.json" ]; then
  echo "LANGUAGE=php"
else
  echo "LANGUAGE=python"
fi
```

Store result as `{language}` in state (`php` or `python`).

**Decision tree for remaining steps:**
- `language=php` → use PHP-specific steps (PHPStan, Psalm, Deptrac, Infection, PHPUnit)
- `language=python` → use Python-specific steps (ruff, pyright, pytest, mutmut, bandit)

---

## 1.7 Next Step

**IMPORTANT: The execution order is L3A→L1→L2→L3B→L4→Checkpoint.**

After initialization, proceed to Layer 3A (smoke test), NOT Layer 1.

- **If `language=php`:** Load and follow `./steps/step-03a-layer3a-php.md`
- **If `language=python`:** Load and follow `./steps/step-03a-layer3a.md`

---

## 1.8 PYTHON_RUNNER Contract

The variable `PYTHON_RUNNER` resolved in §1.5.5 is **THE** canonical Python
interpreter path for the entire quality-gate workflow. Every subsequent step
file (step-03a, step-02, step-03, step-04, step-06, step-05) MUST use
`$PYTHON_RUNNER` instead of bare `python3`.

**Why:** When a project uses a virtualenv, bare `python3` resolves to the
system interpreter which lacks dev dependencies (pytest, ruff, bandit, etc.),
causing false FAILs across all layers.

**Contract:**
- `$PYTHON_RUNNER` is set and exported in this step (§1.5.5)
- All subsequent steps receive it in their shell environment
- No step may use bare `python3` — always `$PYTHON_RUNNER`
- The CLI (`harness_quality_gate`) is always invoked via `$PYTHON_RUNNER -m harness_quality_gate`
