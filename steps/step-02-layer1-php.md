# Step 02 (PHP): Layer 1 — Test Execution + Mutation

**Goal:** Run PHPUnit test suite with coverage, then Infection mutation testing.
For Rompehielos-generated code: Tier-B tests (unit/integration/functional) only.

**Duration:** PHPUnit ~30s–5 min; Infection ~10–30 min depending on scope.

**Precondition:** Layer 3A-PHP must have PASSED.

---

## 2-PHP.1 PHPUnit — Test Execution

```bash
cd {project-root} && vendor/bin/phpunit --coverage-text --coverage-clover coverage.xml \
  --log-junit junit.xml 2>&1
```

**Capture:**
- Exit code (0=all pass, 1=failures/errors)
- Pass/fail/error/skipped counts
- Coverage percentage
- Duration

**If PHPUnit fails:** Mark Layer 1 as FAIL. Do NOT run Infection.

---

## 2-PHP.2 Coverage Check

From PHPUnit coverage output:
- Target threshold: **85%** (configurable in `quality-gate.yaml`)
- If coverage < threshold: mark as WARNING (not hard FAIL at this stage — Infection will reveal the real picture)

---

## 2-PHP.3 Infection — Mutation Testing (Tier-B only)

**CRITICAL SCOPE RULE:** Infection MUST target ONLY the generated `src/` directory.
It must NEVER include `features/` (Behat oracle) or `tests/` themselves.

Verify `infection.json5` has correct `source.directories`:
```json
{
  "source": { "directories": ["src"] },
  "minMsi": 100,
  "minCoveredMsi": 100
}
```

If `minMsi` < 100 or `minCoveredMsi` < 100 in the config: **ABORT** — the gate is weakened.

```bash
cd {project-root} && vendor/bin/infection --min-msi=100 --min-covered-msi=100 \
  --coverage=coverage.xml --logger-json=infection-log.json 2>&1
```

**Capture:**
- MSI (Mutation Score Index)
- Covered MSI
- Killed / Survived / Escaped counts
- Duration

**If MSI < 100:** Mark Layer 1 as FAIL. Surviving mutants listed in findings.

---

## 2-PHP.4 Self-Test: Infection Path-Scope Guard

Before accepting Infection results, verify the scope was correct:

```bash
# Infection config must NOT include features/ or oracle directories
grep -r "features\|oracle" infection.json5 2>/dev/null && echo "SCOPE_VIOLATION" || echo "SCOPE_OK"
```

If `SCOPE_VIOLATION`: Abort — Infection was run with an incorrect scope that could
corrupt the oracle. This is a hard gate failure regardless of MSI score.

---

## 2-PHP.5 Layer 1 Decision

**PASS criteria:**
- PHPUnit exit 0 (all tests pass)
- Infection MSI = 100 AND Covered MSI = 100
- No scope violation

**FAIL criteria (any of):**
- PHPUnit failures/errors
- MSI < 100 (surviving mutants with unjustified `@infection-ignore-all`)
- Scope violation (Infection touched oracle/features/)

---

## 2-PHP.6 Next Step

- **Layer 1 PASS:** Load and follow `./steps/step-03-layer2-php.md`
- **Layer 1 FAIL:** Stop. Report surviving mutants. Developer must either kill them
  with tests or add `@infection-ignore-all` with `// reason:` + `// audited:` metadata.
