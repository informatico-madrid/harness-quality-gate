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
python3 {project-root}/.ralph/kill_pytest_orphans.py
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

Check which tools are installed:

```bash
# Core tools (L3A, L1, L2, L3B)
python3 -m pytest --version 2>/dev/null && echo "pytest=OK" || echo "pytest=MISSING"
python3 -m ruff --version 2>/dev/null && echo "ruff=OK" || echo "ruff=MISSING"
python3 -m pyright --version 2>/dev/null && echo "pyright=OK" || echo "pyright=MISSING"
python3 -c "import mutmut" 2>/dev/null && echo "mutmut=OK" || echo "mutmut=MISSING"

# Security tools (L4)
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

Store availability in state for conditional execution.

---

## 1.6 Next Step

**IMPORTANT: The execution order is L3A→L1→L2→L3B→L4→Checkpoint.**

After initialization, proceed to Layer 3A (smoke test), NOT Layer 1.

Load and follow: `./steps/step-03a-layer3a.md`
