# Step 02: Layer 1 — Test Execution

**Goal:** Execute test suite with coverage, mutation analysis, and E2E tests. Generate Layer 1 results.

---

## ⚠️ PRECONDITION: Layer 3A Must Pass First

**Layer 1 only executes if Layer 3A (Tier A smoke test) passed.**

If L3A failed, the agent should have already refactorized before reaching this step. The recovery playbook for L3A failure is:
1. Refactorizar código para resolver violaciones
2. Volver a ejecutar Layer 3A (no Layer 1)
3. Máximo 3 reintentos

**Rationale:** If code quality smoke test fails, running mutation testing (~15 min) is wasted effort. Fix the code quality issues first.

---

## 1.1 Kill Pytest Orphans (Re-confirm)

```bash
python3 {project-root}/.ralph/kill_pytest_orphans.py 2>/dev/null || true
```

---

## 1.2 Run pytest

```bash
cd {project-root} && python3 -m pytest tests/ -q -p no:randomly -p no:warnings --tb=short 2>&1
```

**Capture:**
- Exit code
- Duration in seconds
- Tests total / passed / failed counts
- Output summary

**Update state:**
```json
{
  "layer1_test_execution": {
    "pytest": {
      "status": "PASS" or "FAIL",
      "duration_s": <float>,
      "tests_total": <int>,
      "tests_passed": <int>,
      "tests_failed": <int>
    }
  }
}
```

---

## 1.3 Run Coverage Check

```bash
cd {project-root} && python3 -m pytest tests/ \
  --cov=src \
  --cov-report=term-missing \
  --cov-report=xml:coverage.xml \
  --cov-fail-under=85 \
  -p no:randomly -p no:warnings 2>&1
```

If the project defines its own coverage configuration (`[tool.coverage]`
in `pyproject.toml` or `.coveragerc`), prefer the project's settings and
only enforce the threshold.

**Capture:**
- Coverage percentage (parse from output)
- Exit code

**Update state:**
```json
{
  "layer1_test_execution": {
    "coverage": {
      "status": "PASS" or "FAIL",
      "actual": <float>,
      "threshold": 85.0
    }
  }
}
```

---

## 1.4 Run Mutation Testing

**This step is BLOCKING, not optional.** Mutation testing is the primary defense against test-triviality evasion (writing shallow tests that pass coverage but don't actually verify behavior). If mutmut is not installed, Layer 1 FAILS.

**⚠️ CRITICAL: Always activate the virtual environment first.** All Python/mutmut commands below MUST be prefixed with `. .venv/bin/activate &&`. If `.venv/bin/activate` does not exist, STOP and inform the user to create the venv first.

**Data source**: mutmut 3.x stores results in an internal cache (NOT `.mutmut/index.html`). The gate script uses `mutmut results --all true` to get per-mutant status and aggregates by module name.

### 1.4.1 Ensure mutmut results exist

```bash
cd {project-root} && . .venv/bin/activate && mutmut run 2>&1 || true
```

### 1.4.2 Run mutation gate (100/100 hard gate)

```bash
. .venv/bin/activate && python3 -m harness_quality_gate.bmad.mutation_analyzer {project-root} --gate 2>&1
```

**This command:**
- Runs `mutmut results --all true` to get per-mutant status (killed/survived/timeout/no_tests)
- Extracts module name from mutant identifiers (e.g., `src/my_module/my_func.py::my_func__mutmut_42: killed` → module `my_module`)
- Gates on the 100/100 policy: every module must have 0 survivors and 0 timeouts
  (per-module threshold ramps are deliberately not supported — same hard gate as
  Infection `--min-msi=100` on the PHP side)
- Outputs JSON with the per-module kill-map and OK/NOK gate result
- Exit code: 0 = OK, 1 = NOK

**Capture:**
- Gate result (OK/NOK) from exit code
- Per-module kill rates from `mutation_kill_map` in the JSON output
- Overall kill rate from `overall_kill_rate`

**Update state:**
```json
{
  "layer1_test_execution": {
    "mutation_testing": {
      "status": "PASS" or "FAIL",
      "gate": "OK" or "NOK",
      "overall_kill_rate": <float>,
      "modules_checked": <int>,
      "modules_passed": <int>,
      "modules_failed": <int>,
      "details": [
        {
          "module": "calculations",
          "kill_rate": 0.55,
          "threshold": 0.48,
          "killed": 1100,
          "total": 2000,
          "passed": true
        }
      ],
      "installed": true
    }
  }
}
```

**If mutmut is NOT installed:**
```json
{
  "layer1_test_execution": {
    "mutation_testing": {
      "status": "FAIL",
      "installed": false,
      "reason": "mutmut not installed — mutation testing is BLOCKING. Install mutmut to proceed."
    }
  }
}
```

**If `[tool.quality-gate.mutation]` not found in pyproject.toml:**
- Use global default threshold (0.48)
- Warn user to add `[tool.quality-gate.mutation]` section to `pyproject.toml`

**If mutation testing FAILS (NOK):**
Report to user:
- Which modules failed and their scores vs thresholds
- List of surviving mutants per failed module
- **RECOMMEND:** "Activate the 'mutation-testing' skill for guidance on improving weak tests that fail to kill surviving mutants."

---

## 1.5 Run E2E Tests (OPTIONAL)

**E2E tests are OPTIONAL.** If `make e2e` is not available, skip this step with status `SKIPPED`.

```bash
cd {project-root} && make e2e 2>&1 || true
```

**Capture:**
- Exit code
- E2E tests total / passed / failed counts
- Duration in seconds

**If make e2e fails:**
- E2E is OPTIONAL, so this is a WARNING, not a FAIL
- Continue to Layer 1 PASS/FAIL determination

**Update state:**
```json
{
  "layer1_test_execution": {
    "e2e": {
      "status": "PASS" or "FAIL",
      "duration_s": <float>,
      "tests_total": <int>,
      "tests_passed": <int>,
      "tests_failed": <int>
    }
  }
}
```

**If make e2e is not available or fails:**
```json
{
  "layer1_test_execution": {
    "e2e": {
      "status": "SKIPPED",
      "reason": "E2E tests are OPTIONAL in Layer 1: 'make e2e' unavailable or failing does not block L1 PASS."
    }
  }
}
```

---

## 1.6 Determine Layer 1 PASS/FAIL

**Layer 1 PASS = true only if:**
- pytest status = PASS
- coverage status = PASS
- mutation_testing status = PASS (FAIL if not installed OR kill_rate < threshold)
- e2e status = PASS or SKIPPED (E2E is OPTIONAL)

**Update state:**
```json
{
  "layer1_test_execution": {
    "PASS": true or false
  }
}
```

---

## 1.7 Fast-Fail Decision

**If Layer 1 FAIL:**
- Write partial checkpoint with Layer 1 results
- STOP execution here
- Output final checkpoint with all `null` for Layers 2 and 3
- Report to user that Layer 1 must pass before proceeding

**If Layer 1 PASS:**
- Continue to `./steps/step-03-layer2.md`

---

## 1.8 Next Step

Load and follow: `./steps/step-03-layer2.md`
