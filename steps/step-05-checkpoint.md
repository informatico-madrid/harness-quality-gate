# Step 05: Generate Checkpoint

**Goal:** Finalize checkpoint JSON with all 5 layers (L3A, L1, L2, L3B, L4), write to file, determine global PASS/FAIL.

---

## 5.1 Calculate Summary

Calculate aggregate metrics from all layers:

```json
{
  "summary": {
    "total_tests": <from layer1.pytest.tests_total>,
    "passed": <from layer1.pytest.tests_passed>,
    "failed": <from layer1.pytest.tests_failed>,
    "coverage_actual": <from layer1.coverage.actual>,
    "mutation_kill_rate": <from layer1.mutation_testing.kill_rate or null>,
    "e2e_total": <from layer1.e2e.tests_total or 0>,
    "e2e_passed": <from layer1.e2e.tests_passed or 0>,
    "e2e_failed": <from layer1.e2e.tests_failed or 0>,
    "weak_test_count": <from layer2.weak_tests.length>,
    "SOLID_violations_tier_a": <count of SOLID Tier A letters with FAIL>,
    "SOLID_violations_tier_b": <count of SOLID Tier B violations>,
    "principle_violations": <count of principles with FAIL>,
    "antipattern_violations_tier_a": <count of Tier A antipatterns with FAIL>,
    "antipattern_violations_tier_b": <count of Tier B antipatterns violations>
  }
}
```

---

## 5.2 Determine Global PASS/FAIL

**Global PASS = true ONLY if:**
- layer3a_smoke_test.PASS = true
- layer1_test_execution.PASS = true
- layer2_test_quality.PASS = true
- layer3b_deep_quality.PASS = true
- layer4_security_defense.PASS = true

**If ANY layer FAIL → global PASS = false**

**Key distinction:**
- **WARNING** = issue is logged, visible, but does NOT block the gate
- **FAIL** = issue blocks the gate, must be fixed before COMMIT
- **SKIPPED** = Tier B not executed (not a failure, but not a pass either)

---

## 5.3 Write Checkpoint JSON

Write to `{project-root}/_bmad-output/quality-gate/quality-gate-{timestamp}.json`:

```json
{
  "checkpoint": "quality-gate",
  "timestamp": "<ISO timestamp>",
  "PASS": true or false,
  "layers": {
    "layer3a_smoke_test": {
      "PASS": true or false,
      "ruff": {"status": "PASS", "violations": 0},
      "pyright": {"status": "PASS", "errors": 0},
      "check_headers": {"status": "PASS"},
      "SOLID_tier_a": {"S": "PASS", "O": "PASS", "L": "PASS", "I": "PASS", "D": "PASS"},
      "principles": {"DRY": "PASS", "KISS": "PASS", "YAGNI": "PASS", "LoD": "PASS", "CoI": "PASS"},
      "antipatterns_tier_a": {"status": "PASS", "violations": 0}
    },
    "layer1_test_execution": { ... },
    "layer2_test_quality": { ... },
    "layer3b_deep_quality": {
      "PASS": true or false,
      "SOLID_tier_b": {"status": "PASS" or "SKIPPED", "violations": []},
      "antipatterns_tier_b": {"status": "PASS" or "SKIPPED", "violations": []}
    },
    "layer4_security_defense": {
      "PASS": true or false,
      "bandit": {"status": "PASS", "findings_count": 0, "severity_counts": {}},
      "safety": {"status": "PASS", "findings_count": 0, "severity_counts": {}},
      "gitleaks": {"status": "PASS", "findings_count": 0, "severity_counts": {}},
      "semgrep": {"status": "PASS" or "SKIPPED", "findings_count": 0},
      "checkov": {"status": "PASS" or "SKIPPED", "findings_count": 0},
      "deptry": {"status": "PASS" or "SKIPPED", "findings_count": 0},
      "vulture": {"status": "PASS" or "SKIPPED", "findings_count": 0},
      "trivy": {"status": "PASS" or "SKIPPED", "findings_count": 0}
    }
  },
  "summary": { ... }
}
```

Also write to `{project-root}/_bmad-output/quality-gate/quality-gate-latest.json` as alias.

**G1 Temporal Tracking — Quality Gate History:**

After writing the checkpoint, also update the history file at `{project-root}/_bmad-output/quality-gate/.quality-gate-history.json` (create if not exists).

```json
{
  "runs": [
    {
      "timestamp": "<ISO timestamp>",
      "PASS": true or false,
      "summary": { ... },
      "violations_by_id": {
        "AP05": ["file1.py:42"],
        "SOLID.O": ["file2.py:10"],
        "SOLID_TIER_B.S": ["file3.py:20"]
      },
      "layer3a_pass": true,
      "layer1_pass": true,
      "layer2_pass": true,
      "layer3b_pass": true,
      "layer4_pass": true
    }
  ],
  "temporal_alerts": []
}
```

**Temporal Alert Logic:** When a new run detects a violation for an ID that was PASS in the previous run but is FAIL now, add to `temporal_alerts`:
```json
{
  "type": "regression",
  "id": "AP05",
  "prev_timestamp": "<old timestamp>",
  "now_timestamp": "<new timestamp>",
  "files": ["file.py:42"]
}
```

When a specific violation (same file:lineno) appears in 3+ consecutive runs without being fixed, add:
```json
{
  "type": "persistent_violation",
  "id": "SOLID.S",
  "count": 3,
  "files": ["file.py:42"]
}
```

---

## 5.4 Report to User

Present a summary table:

```
╔═══════════════════════════════════════════════════════════════════╗
║                    QUALITY GATE RESULTS                           ║
╠═══════════════════════════════════════════════════════════════════╣
║  Layer 3A: Smoke Test (Tier A AST, <1 min)                      ║
║    ruff:                 ✓ PASS                                  ║
║    pyright:              ✓ PASS                                  ║
║    check_headers:        ✓ PASS                                  ║
║    SOLID Tier A:         ✓ PASS                                  ║
║    principles:           ✓ PASS                                  ║
║    antipatterns Tier A:  ✓ PASS                                  ║
║                          → Layer 3A: PASS                         ║
╠═══════════════════════════════════════════════════════════════════╣
║  Layer 1: Test Execution                                          ║
║    pytest:              ✓ PASS (312 tests, 0 failed)            ║
║    coverage:            ✓ PASS (87.3% >= 85%)                   ║
║    mutation testing:    ✓ PASS (gate OK)                        ║
║    e2e:                 ✓ PASS (23 tests, 0 failed)             ║
║                          → Layer 1: PASS                         ║
╠═══════════════════════════════════════════════════════════════════╣
║  Layer 2: Test Quality                                           ║
║    weak tests:           ✓ PASS (0 errors)                       ║
║    diversity score:      0.82                                    ║
║                          → Layer 2: PASS                         ║
╠═══════════════════════════════════════════════════════════════════╣
║  Layer 3B: Deep Quality (Tier B BMAD, ~15 min)                   ║
║    SOLID Tier B:         ✓ PASS (or SKIPPED)                    ║
║    antipatterns Tier B:  ✓ PASS (or SKIPPED)                    ║
║                          → Layer 3B: PASS                         ║
╠═══════════════════════════════════════════════════════════════════╣
║  Layer 4: Security & Defense (~2-5 min)                           ║
║    bandit:              ✓ PASS (0 findings)                      ║
║    safety:              ✓ PASS (0 CVEs)                          ║
║    gitleaks:            ✓ PASS (0 secrets)                       ║
║    semgrep:             ✓ PASS (0 findings)                      ║
║    checkov:             ⊘ SKIPPED (not installed)                ║
║    deptry:              ✓ PASS (0 issues)                        ║
║    vulture:             ✓ PASS (0 dead code)                     ║
║    trivy:               ⊘ SKIPPED (no Dockerfile)                ║
║                          → Layer 4: PASS                         ║
╠═══════════════════════════════════════════════════════════════════╣
║  GLOBAL PASS: PASS                                               ║
╚═══════════════════════════════════════════════════════════════════╝
```

---

## 5.5 Smart-Ralph Integration

The checkpoint file is ready for smart-ralph VERIFY step:

```bash
cat _bmad-output/quality-gate/quality-gate-latest.json | jq '.PASS'
```

**If PASS = true:** smart-ralph can proceed to COMMIT
**If PASS = false:** agent MUST fix issues before COMMIT

---

## 5.6 Next Step

Workflow complete. The skill has generated the checkpoint JSON.
