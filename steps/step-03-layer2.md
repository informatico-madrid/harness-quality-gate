# Step 03: Layer 2 — Test Quality Analysis

**Goal:** Analyze test quality using AST-based weak test detection, mutation kill-map, and diversity metrics. Generate Layer 2 results.

---

## ⚠️ PRECONDITION: Layer 1 Must Pass First

**Layer 2 only executes if Layer 1 (test execution) passed.**

If L1 failed, the agent should have fixed the tests before proceeding to L2. The recovery playbook for L1 failure is:
1. Arreglar tests (pytest, coverage, mutation)
2. Volver a ejecutar Layer 1
3. Máximo 3 reintentos

---

## 2.1 Weak Test Detection (Rules A1-A8)

Run the weak test detector script:

```bash
python3 {skill-root}/scripts/weak_test_detector.py {project-root}/tests/ {project-root}/src/ 2>&1
```

### Weak Test Rules (A1-A8)

| Rule | Description | Threshold |
|------|-------------|-----------|
| **A1** | ≤1 assertion/test | Tests with only 1 assert are suspicious |
| **A2** | assertion count < 3 | Less than 3 asserts = insufficient coverage |
| **A3** | No parametrization and only 1 case | Hardcoded single-input tests |
| **A4** | mock count > 80% of test | Too much mocking = not testing real code |
| **A5** | No setup/teardown and no fixtures | Stateless tests don't test real state |
| **A6** | time.sleep > 0 in test | Tests with sleeps are flaky by design |
| **A7** | Empty exception (`assert raises Exception`) | `with pytest.raises(Exception): pass` |
| **A8** | Always-true assertion (`assert True`, `assert 1==1`) | Trivial assertions |

**Parse output** from weak_test_detector.py (expected JSON format):

```json
{
  "weak_tests": [
    {
      "file": "tests/test_foo.py",
      "test_name": "test_bar",
      "rule_violated": "A4",
      "description": "mock count 85% > 80% threshold",
      "severity": "ERROR"
    }
  ],
  "summary": {
    "total_tests_analyzed": 312,
    "weak_test_count": 5,
    "pass_rate": 0.84
  }
}
```

**Update state:**
```json
{
  "layer2_test_quality": {
    "weak_tests": <array>,
    "weak_test_count": <int>
  }
}
```

---

## 2.2 Mutation Kill-Map Analysis

Only run if mutation testing data exists from Layer 1.

Parse mutation results from `/.mutmut/index.html` or similar output:

```bash
python3 {skill-root}/scripts/mutation_analyzer.py {project-root}/ 2>&1
```

**Expected output:**
```json
{
  "mutation_kill_map": {
    "src/audit/judge.py": {"killed": 42, "total": 58, "rate": 0.724},
    "src/curation/curator_pipeline.py": {"killed": 15, "total": 30, "rate": 0.5}
  },
  "overall_kill_rate": 0.68
}
```

**Update state:**
```json
{
  "layer2_test_quality": {
    "mutation_kill_map": <object>,
    "mutation_kill_rate": <float>
  }
}
```

---

## 2.3 Test Diversity Metric

Run diversity analysis:

```bash
python3 {skill-root}/scripts/diversity_metric.py {project-root}/tests/ 2>&1
```

**Expected output:**
```json
{
  "diversity_score": 0.82,
  "min_edit_distance": 25,
  "max_edit_distance": 340
}
```

**Update state:**
```json
{
  "layer2_test_quality": {
    "diversity_score": <float>
  }
}
```

---

## 2.4 Determine Layer 2 PASS/FAIL

**Layer 2 PASS = true only if:**
- weak_test_count = 0
- OR all weak tests have severity = "WARNING" (not "ERROR")

**Layer 2 FAIL if:**
- weak_test_count > 0 AND any weak test has severity = "ERROR"

**Update state:**
```json
{
  "layer2_test_quality": {
    "PASS": true or false
  }
}
```

---

## 2.5 Next Step

Load and follow: `./steps/step-04-layer3b.md`
