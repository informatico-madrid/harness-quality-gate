# Step 03A: Layer 3A — Tier A Smoke Test

**Goal:** Execute fast AST-based code quality checks as a smoke test. If these fail, don't waste time on mutation testing (~15 min) or BMAD Party Mode (~15 min).

**Duration:** <1 min

**Precondition:** This layer runs FIRST, before Layer 1. No preconditions required — it's the entry point after initialization.

---

## IMPORTANT: Fail-Fast Rule

**If Layer 3A FAILS:**
- STOP immediately
- Do NOT execute Layer 1, Layer 2, or Layer 3B
- Refactorizar código para resolver violaciones
- Volver a ejecutar Layer 3A
- Máximo 3 reintentos
- Si después de 3 reintentos sigue fallando, bloquear iteración

**Rationale:** L3A detects code quality issues in <1 min. Running mutation testing (~15 min) when code quality is already bad is wasted effort.

---

## 3A.1 Ruff Lint Check

```bash
cd {project-root} && python3 -m ruff check src/ tests/ 2>&1
```

**Capture:**
- Exit code
- Violation count
- List of violations

**Update state:**
```json
{
  "layer3a_smoke_test": {
    "ruff": {
      "status": "PASS" or "FAIL",
      "violations": <int>,
      "details": <array of violations>
    }
  }
}
```

---

## 3A.2 Ruff Format Check

```bash
cd {project-root} && python3 -m ruff format --check src/ tests/ 2>&1
```

**If FAIL (formatting issues):**
- Run `ruff format` to auto-fix before proceeding

---

## 3A.3 Pyright Type Check

```bash
cd {project-root} && python3 -m pyright src/ 2>&1
```

**Capture:**
- Exit code
- Error count

**Update state:**
```json
{
  "layer3a_smoke_test": {
    "pyright": {
      "status": "PASS" or "FAIL",
      "errors": <int>
    }
  }
}
```

---

## 3A.4 Check Headers (Constitution)

```bash
cd {project-root} && python3 scripts/check_headers.py --check 2>&1
```

**Update state:**
```json
{
  "layer3a_smoke_test": {
    "check_headers": {
      "status": "PASS" or "FAIL"
    }
  }
}
```

---

## 3A.5 SOLID Tier A (Fast AST)

Run SOLID metrics script:

```bash
python3 {skill-root}/scripts/solid_metrics.py {project-root}/src/ 2>&1
```

### SOLID Rules (Tier A)

| Letter | Principle | Metrics |
|--------|-----------|---------|
| **S** | Single Responsibility | max_public_methods: 7, max_arity: 5 |
| **O** | Open/Closed | abstractness >= 10% (ABC/Protocol ratio) |
| **L** | Liskov Substitution | type_hint_coverage: 90% |
| **I** | Interface Segregation | max_unused_methods_ratio: 0.5 |
| **D** | Dependency Inversion | max_import_depth: 3, zero_cycles: true |

**Update state:**
```json
{
  "layer3a_smoke_test": {
    "SOLID_tier_a": {
      "S": {"status": "PASS" or "FAIL", "violations": []},
      "O": {"status": "PASS" or "FAIL", "violations": []},
      "L": {"status": "PASS" or "FAIL", "violations": []},
      "I": {"status": "PASS" or "FAIL", "violations": []},
      "D": {"status": "PASS" or "FAIL", "violations": []}
    }
  }
}
```

---

## 3A.6 Principles (DRY, KISS, YAGNI, LoD, CoI)

Run principles checker:

```bash
python3 {skill-root}/scripts/principles_checker.py {project-root}/src/ 2>&1
```

### Principles Rules

| Principle | Description | Metrics |
|-----------|-------------|---------|
| **DRY** | Don't Repeat Yourself | duplicate_code_threshold: 6 lines |
| **KISS** | Keep It Simple | max_function_complexity: 10, max_nesting_depth: 4, max_parameters: 5 |
| **YAGNI** | You Aren't Gonna Need It | unused_imports_ratio: 0, dead_code_ratio: 0 |
| **LoD** | Law of Demeter | max_chain_length: 3, no dot-chaining |
| **CoI** | Composition Over Inheritance | inheritance_depth_max: 2, composition_ratio: 0.5 |

**Update state:**
```json
{
  "layer3a_smoke_test": {
    "principles": {
      "DRY": {"status": "PASS" or "FAIL", "violations": 0},
      "KISS": {"status": "PASS" or "FAIL", "violations": 0},
      "YAGNI": {"status": "PASS" or "FAIL", "violations": 0},
      "LoD": {"status": "PASS" or "FAIL", "violations": 0},
      "CoI": {"status": "PASS" or "FAIL", "violations": 0}
    }
  }
}
```

---

## 3A.7 Antipatterns Tier A (25 patterns, AST-based)

Run AST-based antipattern checker:

```bash
python3 {skill-root}/scripts/antipattern_checker.py {project-root}/src/ {project-root}/tests/ --tier-a-only 2>&1
```

### Tier A Antipatterns (25 patterns)

| # | Antipattern | AST Detection |
|---|-------------|---------------|
| AP01 | God Class | >500 LOC or >20 public methods |
| AP02 | Functional Decomposition | Only static methods, no state |
| AP03 | Poltergeist | Short class, no state or behavior |
| AP04 | Spaghetti Code | Nesting >= 6 + LOC > 50 |
| AP05 | Magic Numbers | Numeric literals without constant |
| AP06 | Long Method | Function > 100 lines |
| AP07 | Large Class | >15 instance variables |
| AP08 | Long Parameter List | >5 parameters |
| AP09 | Feature Envy | Method uses more foreign than own attributes |
| AP10 | Data Class | Only fields, no behavior |
| AP11 | Lazy Class | Few methods, no behavior |
| AP12 | Speculative Generality | Abstract with only one implementation |
| AP13 | Middle Man | >80% delegation |
| AP17 | Refused Bequest | Subclass with empty methods (pass/...) |
| AP18 | Switch Statements | >5 match/if-elif branches |
| AP20 | Deep Nesting | Nesting depth > 5 |
| AP21 | Message Chains | Chain a.b.c.d > 3 |
| AP22 | Dead Code | Unreachable code, commented code |
| AP23 | Duplicate Code | Identical blocks of 6+ lines |
| AP24 | Primitive Obsession | >5 primitive parameters |
| AP25 | Data Clumps | Same group of parameters in multiple functions |
| AP26 | Inconsistent Naming | ruff N802, N803, N804, N805, N806 |
| AP30 | Circular Dependency | Cycles in import graph |
| AP31 | Hub/Spoke | Module imported by >15 others |
| AP39 | Yo-Yo Problem | Inheritance depth > 5 |

**Update state:**
```json
{
  "layer3a_smoke_test": {
    "antipatterns_tier_a": {
      "status": "PASS" or "FAIL",
      "violations": <int>,
      "details": [
        {"id": "AP05", "name": "Magic Numbers", "files": ["src/foo.py:42"]}
      ]
    }
  }
}
```

---

## 3A.8 Determine Layer 3A PASS/FAIL

**Layer 3A PASS = true only if:**
- ruff status = PASS
- pyright status = PASS
- check_headers status = PASS
- ALL SOLID Tier A letters = PASS
- ALL principles = PASS
- ALL Tier A antipatterns = PASS

**Update state:**
```json
{
  "layer3a_smoke_test": {
    "PASS": true or false
  }
}
```

---

## 3A.9 Fail-Fast Decision

**If Layer 3A FAIL:**
- Write partial checkpoint with L3A results
- STOP execution here
- Output final checkpoint with all other layers as `null`
- Report to user: "L3A smoke test failed. Fix code quality issues before proceeding to mutation testing."
- Follow Recovery Playbook: refactorizar código → volver a L3A (máximo 3 reintentos)

**If Layer 3A PASS:**
- Continue to `./steps/step-02-layer1.md`

---

## 3A.10 Next Step

Load and follow: `./steps/step-02-layer1.md`