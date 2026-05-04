# Step 04: Layer 3B — Tier B Deep Quality (BMAD Party Mode)

**Goal:** Execute deep code quality checks via BMAD Party Mode for SOLID Tier B and Antipatterns Tier B. Generate Layer 3B results.

**Duration:** ~15 min (BMAD multi-agent consensus)

---

## ⚠️ PRECONDITION: Layers 1 and 2 Must Pass First

**Layer 3B only executes if Layer 1 (test execution) and Layer 2 (test quality) both passed.**

If L1 or L2 failed, the agent should have fixed those issues before proceeding to L3B.

---

## IMPORTANT: Recovery Playbook for L3B Failure

**If Layer 3B FAILS:**
- Refactorizar código para resolver violaciones
- **Go back to Layer 3A** (NOT to Layer 1)
- Re-ejecutar Layer 3A to verify code quality is restored
- Then proceed to Layer 1 to verify tests still pass
- Maximum 3 retries

**Rationale:** When L3B fails after L1+L2 passed, the refactorización may have broken code quality (detectable by L3A's fast AST checks) without breaking tests. Going back to L3A instead of L1 saves ~15 min of mutation testing per recovery cycle.

---

## 3B.1 SOLID Tier B (BMAD Multi-Agent Consensus)

### Step B.1: Generate SOLID Review Context

First, extract class inventory for the agents to review:

```bash
python3 {skill-root}/scripts/llm_solid_judge.py {project-root}/src/ 2>&1
```

This outputs a JSON with a `review_context` field containing structured class context.
It does NOT call external APIs.

### Step B.2: Invoke BMAD Party Mode for SOLID Review

Activate the `bmad-party-mode` skill with the following configuration:

**Agents to spawn (2-3 in parallel):**
- **Winston** (Architect) - Evaluates architectural SOLID compliance
- **Murat** (Test Architect) - Evaluates testability implications of SOLID violations
- Optionally **Sally** (UX Designer) if the class has user-facing interfaces

**Prompt for each agent:**
```
You are reviewing Python classes for SOLID principle violations.

{review_context from llm_solid_judge.py goes here}

For each class, evaluate:
- S (Single Responsibility): Does this class have ONE reason to change?
- O (Open/Closed): Can behavior be extended without modifying source?
- L (Liskov Substitution): Can subclasses replace parents transparently?
- I (Interface Segregation): Are interfaces small and focused?
- D (Dependency Inversion): Do high-level modules depend on abstractions?

Respond with a JSON list of violations found:
{"violations": [{"letter": "S", "class": "Foo", "reason": "...", "severity": "HIGH"}]}
If no violations: {"violations": [], "PASS": true}
```

### Step B.3: Invoke BMAD Adversarial Review

After Party Mode produces findings, activate `bmad-review-adversarial-general`:

**Content to review:** The combined SOLID findings from all Party Mode agents.

The adversarial reviewer will:
- Challenge false positives (flagged violations that aren't real)
- Find missed violations that agents overlooked
- Ensure findings are actionable, not theoretical

### Step B.4: Build Consensus

Combine results from both mechanisms:

| Source | Role | Weight |
|--------|------|--------|
| Party Mode agents | Independent SOLID evaluation | Primary findings |
| Adversarial Review | Challenge and refine findings | Removes false positives |

**Consensus rule:** A violation is confirmed if:
- At least 2 of 3 Party Mode agents agree, OR
- Adversarial review does NOT reject the finding

**Output format:**
```json
{
  "tier_b_solid": {
    "method": "BMAD Party Mode + Adversarial Consensus",
    "agents_consulted": ["Winston", "Murat"],
    "adversarial_review": true,
    "violations": [
      {
        "letter": "S",
        "class": "UserManager",
        "file": "src/auth.py",
        "reason": "Handles persistence AND business logic AND email",
        "severity": "HIGH",
        "consensus": "3/3 agents agree, adversarial confirmed"
      }
    ],
    "PASS": false
  }
}
```

### Tier B Override (G9)

If Tier B consensus explicitly identifies a Tier A violation as a **false positive**, the verdict can be **downgraded to WARNING** (not FAIL). This requires 3/3 agents agreeing it is a false positive AND adversarial reviewer concurring.

**Fallback:** If BMAD Party Mode is not available, skip Tier B and mark as `SKIPPED`.

**Update state:**
```json
{
  "layer3b_deep_quality": {
    "SOLID_tier_b": {
      "status": "PASS" or "FAIL" or "SKIPPED",
      "violations": <array>
    }
  }
}
```

---

## 3B.2 Antipatterns Tier B (BMAD Multi-Agent Consensus)

### Step B.1: Generate Antipattern Review Context

```bash
python3 {skill-root}/scripts/antipattern_judge.py {project-root}/src/ {project-root}/tests/ 2>&1
```

This outputs a JSON with a `review_context` field containing structured code context
and definitions for all 25 Tier B patterns. It does NOT call external APIs.

### Step B.2: Invoke BMAD Party Mode for Antipattern Review

Activate the `bmad-party-mode` skill with the following configuration:

**Agents to spawn (2 in parallel):**
- **Winston** (Architect) - Evaluates architectural antipatterns
- **Murat** (Test Architect) - Evaluates testing antipatterns

**Prompt for each agent:**
```
You are reviewing Python code for antipattern violations.

{review_context from antipattern_judge.py goes here}

For each Tier B pattern (AP14-AP16, AP19, AP27-AP29, AP32-AP38, AP40-AP50),
evaluate whether the codebase exhibits it.

Respond with a JSON list of confirmed violations:
{"violations": [{"id": "AP14", "name": "Divergent Change", "file": "src/foo.py",
  "class": "Foo", "reason": "...", "severity": "HIGH"}]}
If no violations: {"violations": [], "PASS": true}
```

### Step B.3: Invoke BMAD Adversarial Review

After Party Mode produces findings, activate `bmad-review-adversarial-general`
to challenge false positives and find missed violations.

### Step B.4: Build Consensus

Same consensus rule as SOLID Tier B:
- Violation confirmed if 2/3 agents agree AND adversarial doesn't reject

### Tier B Antipatterns (25 patterns)

| # | Antipattern | Category | Red Flags |
|---|-------------|-----------|-----------|
| AP14 | Divergent Change | Code | Methods from different functional domains |
| AP15 | Shotgun Surgery | Code | A change touches >3 files |
| AP16 | Parallel Inheritance | Code | Hierarchies that mirror each other |
| AP19 | Temporary Field | Code | Attributes None most of the time |
| AP27 | Incomplete Library Class | Code | Inherits from external class and adds helpers |
| AP28 | Comments as Deodorant | Code | Comments explaining bad code |
| AP29 | Inappropriate Intimacy | Code | Access to private members of other class |
| AP32 | Stovepipe System | Architecture | Hardcoded connections |
| AP33 | Vendor Lock-In | Architecture | Coupling to specific API |
| AP34 | Lava Flow | Architecture | Dead code from experiments |
| AP35 | Ambiguous Viewpoint | Architecture | Mixed abstraction levels |
| AP36 | Golden Hammer | Architecture | Same solution for everything |
| AP37 | Reinvent the Wheel | Architecture | Re-implement stdlib |
| AP38 | Boat Anchor | Architecture | Unused code "just in case" |
| AP40 | Base Bean | Architecture | Inherits from utility class |
| AP41 | Hard-Coded Test Data | Testing | Literals in tests |
| AP42 | Sensitive Equality | Testing | Compare toString/dict completely |
| AP43 | Test Code Duplication | Testing | Duplicated setup in tests |
| AP44 | Test Per Method | Testing | One test per method, no edge cases |
| AP45 | Mock Object Abuse | Testing | >80% mocks |
| AP46 | Assertion Roulette | Testing | Assertions without message |
| AP47 | Eager Test | Testing | One test verifies multiple things |
| AP48 | Dependency Hell | Process | Conflicting dependencies |
| AP49 | Magic Pushbutton | Process | Auto-generated code without understanding |
| AP50 | Continuous Obsolescence | Process | Obsolete dependencies |

**Fallback:** If BMAD Party Mode is not available, Tier B patterns are marked as `SKIPPED`
and do not affect the global PASS/FAIL.

**Update state:**
```json
{
  "layer3b_deep_quality": {
    "antipatterns_tier_b": {
      "status": "PASS" or "FAIL" or "SKIPPED",
      "violations": <array>
    }
  }
}
```

---

## 3B.3 Determine Layer 3B PASS/FAIL

**Layer 3B PASS = true only if:**
- SOLID Tier B status = PASS or SKIPPED
- Antipatterns Tier B status = PASS or SKIPPED

**Important distinction:**
- **SKIPPED** = BMAD Party Mode not available, Tier B not executed (not a failure)
- **FAIL** = BMAD Party Mode ran and found violations

**Update state:**
```json
{
  "layer3b_deep_quality": {
    "PASS": true or false
  }
}
```

---

## 3B.4 Recovery Decision

**If Layer 3B FAIL:**
- Follow Recovery Playbook: refactorizar código → volver a L3A (NOT to L1)
- Maximum 3 retries
- If still failing after 3 retries, block iteration

**If Layer 3B PASS (or SKIPPED):**
- Continue to Layer 4 (Security & Defense)

---

## 3B.5 Next Step

Load and follow: `./steps/step-06-layer4.md`