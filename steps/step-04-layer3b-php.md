# Step 04 (PHP): Layer 3B — Deep Quality (Tier B BMAD)

**Goal:** Evaluate the generated PHP/Symfony code for SOLID principles,
antipatterns Tier B, and architectural intent using the BMAD LLM judge.

**Duration:** ~10–15 min (LLM Party Mode)

**Precondition:** Layer 2-PHP must have PASSED.

---

## 4-PHP.1 SOLID Tier B (LLM Judge)

Analyse `src/` for SOLID adherence beyond what Deptrac/PHPStan can check:
- **SRP:** classes with clear single responsibility
- **OCP:** extension points via interfaces (not `if`/`switch` over types)
- **LSP:** subtypes honour the parent contract
- **ISP:** narrow interfaces (no fat interfaces)
- **DIP:** Domain depends on abstractions (Ports), not Infrastructure

Invoke the SOLID judge context generator:
```python
from harness_quality_gate.bmad.llm_solid_judge import generate_solid_judge_context
context = generate_solid_judge_context("{project-root}/src")
# Present context to BMAD Party Mode agents
```

Record verdict: PASS / FAIL / NEEDS_REVIEW per principle.

---

## 4-PHP.2 Antipattern Tier B (LLM Judge)

Evaluate for patterns that require semantic understanding (AP14–AP16, AP19,
AP27–AP29, AP32–AP38) — these cannot be detected by AST alone.

Key antipatterns for Symfony/Hexagonal code:
- **AP14** Anemic Domain Model (entities with no behaviour, only getters/setters)
- **AP15** Big Ball of Mud (no clear layer boundaries)
- **AP19** Smart UI (business logic leaking into controllers)
- **AP27** Primitive Obsession in Domain (using `string` instead of Value Objects)
- **AP28** Inappropriate Intimacy (Infrastructure layer importing from Domain internals)

Record findings per antipattern.

---

## 4-PHP.3 Layer 3B Decision

**PASS:** No FAIL or NEEDS_REVIEW findings from the LLM judge on Tier B patterns.
**FAIL:** Any confirmed Tier B violation.
**NEEDS_CONSENSUS:** LLM judge not confident → escalate to BMAD Party Mode.

---

## 4-PHP.4 Next Step

Load and follow `./steps/step-06-layer4.md`

> Note: Layer 4 (Security & Defense) is shared between Python and PHP.
> The security tools (bandit/semgrep for Python; semgrep/checkov for PHP) are
> invoked the same way via the existing `step-06-layer4.md`.
