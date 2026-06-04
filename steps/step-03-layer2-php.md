# Step 03 (PHP): Layer 2 — Test Quality Analysis

**Goal:** Analyse the quality of the PHP test suite itself using the harness
weak-test detector (Tier A AST visitors A1–A8).

**Duration:** ~1–2 min

**Precondition:** Layer 1-PHP (PHPUnit + Infection) must have PASSED.

---

## 3-PHP.1 Weak-Test Detection (Tier A)

Run the PHP weak-test visitor against the test directory:

```bash
python3 -m harness_quality_gate all --repo {project-root} --json 2>&1 | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
  [print(json.dumps(l)) for l in d.get('layers',[]) if l.get('layer')=='L2']"
```

Or invoke the adapter directly (if the harness is available as a path/editable dep):
```bash
python3 -c "
from harness_quality_gate.adapters.php.php_adapter import PhpAdapter
from pathlib import Path
import json, os
r = PhpAdapter().run_l2(Path('{project-root}'), dict(os.environ))
print(json.dumps({'layer': r.layer, 'passed': r.passed, 'findings': len(r.findings)}))
"
```

**Capture:**
- Passed / Failed
- Weak-test findings (rule, file, line)
- Diversity violations

**Thresholds (from quality-gate.yaml):**
- `max_assertions_single`: ≤1 assert per test = ERROR
- `min_assertions`: <3 asserts = WARNING
- `max_mock_ratio`: >80% mocks = ERROR

---

## 3-PHP.2 Layer 2 Decision

**PASS:** No ERROR-level weak-test violations.
**FAIL:** Any ERROR-level violation (too-few asserts, mock saturation, empty tests).

WARNING-level findings are reported but do not block.

---

## 3-PHP.3 Next Step

Load and follow `./steps/step-04-layer3b-php.md`
