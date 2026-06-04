# Step 03A (PHP): Layer 3A — Tier A Smoke Test

**Goal:** Execute fast static analysis on a PHP/Symfony project as a smoke test.
Uses PHPStan (types), Psalm-taint (security), and Deptrac (architecture boundaries).

**Duration:** <1 min (PHPStan level max on a small slice) to ~3 min (full project)

**Precondition:** `composer install` must have run and vendor/ must exist.
If not, run `cd {project-root} && composer install --no-interaction --no-progress` first.

---

## IMPORTANT: Fail-Fast Rule

**If Layer 3A FAILS:**
- STOP immediately — do NOT run PHPUnit/Infection
- Fix the violations reported by PHPStan/Psalm/Deptrac
- Re-run Layer 3A (maximum 3 retries)

---

## 3A-PHP.1 PHPStan — Static Analysis (types, max level)

```bash
cd {project-root} && vendor/bin/phpstan analyse src/ --level max --error-format json 2>&1
```

**Capture:**
- Exit code (0=pass, 1=fail)
- JSON `{"totals": {"errors": N}, "files": {...}}`
- Error count

**If exit ≠ 0:** Store findings, mark L3A as FAIL.

---

## 3A-PHP.2 Psalm — Taint Analysis (security)

```bash
cd {project-root} && vendor/bin/psalm --taint-analysis --output-format=json 2>&1
```

**Capture:**
- Exit code
- JSON output with taint findings

If Psalm not installed (`vendor/bin/psalm` absent), skip with a warning.

---

## 3A-PHP.3 Deptrac — Architecture Boundaries

```bash
cd {project-root} && vendor/bin/deptrac analyse --formatter=json 2>&1
```

**Capture:**
- Exit code
- JSON `{"violations": N, ...}`
- Violation count

If `deptrac.yaml` not present in `{project-root}`, skip with a warning.
If Deptrac not installed, skip with a warning.

---

## 3A-PHP.4 ECS / PHP CS Fixer — Style Check

```bash
cd {project-root} && vendor/bin/ecs check src/ --no-progress 2>&1
```

If ECS not installed, try PHP CS Fixer:
```bash
cd {project-root} && vendor/bin/php-cs-fixer check src/ --diff 2>&1
```

If neither available, skip with a warning.

---

## 3A-PHP.5 Fail-Fast Decision

**If ANY of PHPStan / Psalm-taint / Deptrac returned non-zero:**
- Write partial checkpoint with L3A-PHP results
- STOP — do NOT run PHPUnit or Infection
- Report findings summary to user
- Recovery: fix violations → re-run L3A-PHP (max 3 retries)

**If Layer 3A-PHP PASS (or only optional tools were skipped):**
- Continue to `./steps/step-02-layer1-php.md`

---

## 3A-PHP.6 Next Step

- **Layer 3A PASS:** Load and follow `./steps/step-02-layer1-php.md`
- **Layer 3A FAIL:** Stop. Report findings. Wait for developer to fix.
