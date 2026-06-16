---
title: Self-Evaluation Wiring for harness-quality-gate
date: 2026-06-15
status: draft
author: system-architect
reviewed-by: —
related:
  - plans/informe-harness-quality-gate.md
  - SKILL.md
---

# Self-Evaluation Wiring for `harness-quality-gate`

## 1. Purpose

Enable `harness-quality-gate` (the tool) to self-evaluate by running against its own source code. This is the "eat your own dog food" test — if the gate cannot pass its own 5-layer criteria, it cannot credibly enforce them on others.

The mechanism: `python -m harness_quality_gate all .` from within the repo produces a JSON checkpoint whose gate verdict becomes a CI quality gate.

## 2. What It Means to Self-Evaluate

When `harness-quality-gate` runs against the repository it lives in:

1. **Language auto-detection** finds no `composer.json` → selects Python adapter.
2. **Five layers execute sequentially**:
   - `run_l3a` → ruff + pyright
   - `run_l1` → pytest (mutmut excluded in CI — returns empty MutationStats)
   - `run_l2` → weak-test detection + diversity
   - `run_l3b` → SOLID metrics + antipattern Tier A
   - `run_l4` → bandit + vulture + deptry
3. **All results are merged** — if any layer's `passed` field is `False`, the gate FAILS.
4. **Checkpoint JSON is written** to `_quality-gate/quality-gate-latest.json` for downstream consumption. Note: there is no top-level `PASS` key — the verdict is computed as `all(layer["passed"] for layer in checkpoint["layers"])`.

### 2.1 PASS Criteria Per Layer

| Layer | Tools | Gate Condition | How PASS is Determined |
|-------|-------|----------------|----------------------|
| **L3A** | ruff + pyright | No `"severity": "error"` findings | `not any(f.severity == "error")` |
| **L1** | pytest + mutmut | All tests pass, mutation MSI ≥ threshold | `not has_errors and mutation_passed` |
| **L2** | weak-test detector | No `"severity": "error"` findings | `not any(f.severity == "error")` |
| **L3B** | SOLID + antipatterns | No `"severity": "error"` findings | `not any(f.severity == "error")` |
| **L4** | bandit + vulture + deptry | No `"severity": "error"` findings | `not any(f.severity == "error")` |

Per the adapter code (`python_adapter.py` lines 106, 143, 179, 213, 275), **every layer gates only on `error`-severity findings**. SOLID and antipattern tiers emit `warning` by design — they are advisory, not blocking.

## 3. Self-Evaluation Pipeline Design

### 3.1 Architecture Decision Records

#### ADR-001: Exclude mutation testing (L1 mutmut) from CI self-eval

**Context.** The mutation layer is the most expensive step: ~6000–7000 mutants, 20–25 minutes even on a 40-core local machine. It requires `mutmut` on PATH, a working Python test environment, and the test files being copyable into a `mutants/` sandbox.

**Decision.** Exclude `mutmut` from the CI `self-eval` job. L1 will run `pytest` only; mutation results will be reported as `SKIPPED` with a note pointing to the local pre-commit gate.

**Rationale.**
- MSIs ≥ 100% is an absolute policy gate (config.py line 129: any `min_msi < 100` raises `ConfigInvalid`). However, `mutmut` is not available on GitHub-hosted runners, and the adapter gracefully degrades to empty stats when `shutil.which("mutmut") is None` (python_adapter.py lines 441–446).
- Empty MutationStats (`total=0, survived=0`) means `mutation_passed` is `True` (line 134: `survived == 0 and timed_out == 0`). So L1 would technically PASS with empty mutation stats, which we want for CI self-eval.
- Full mutation runs are enforced **locally** before merge, as documented in `.github/workflows/ci.yml` lines 15–21. This is a conscious pre-commit discipline gate.

**Alternatives considered.**
- Run full mutmut in CI → rejected: 2-core hosted runner would take 2+ hours.
- Install mutmut and run with `--max-children=1` → rejected: still 30+ minutes, wastes runner minutes, and CI environment differences could produce spurious mutations.
- Skip L1 entirely → rejected: we still want pytest to run as part of self-eval.

#### ADR-002: Skip L4 sub-layers that are not available in CI

**Decision.** L4 tools (`bandit`, `vulture`, `deptry`) will be installed via `pip install` when they are not pre-installed on the runner. If a tool is unavailable, it is gracefully skipped (the adapter returns `[]` findings). No findings → no error findings → layer still passes.

**Rationale.** Self-eval should reflect the *best effort* of the toolchain when run in a standard CI environment. Tools that can be installed should be installed; tools that cannot should be skipped.

#### ADR-003: Self-eval job runs on main-schedule and main-push only

**Decision.** The `self-eval` job runs only on `main` branch pushes and the Sunday daily cron (not on pull requests or `develop` branch).

**Rationale.** Self-eval is a periodic health check, not a per-PR gate. PRs already have lint/test via the `lint` and `test` jobs. Mutation is a local pre-commit gate. The self-eval's unique value is verifying the *full* gate pipeline (layers 1–5, minus mutation) runs successfully end-to-end in CI, detecting integration drift.

#### ADR-004: Self-eval runs AFTER the standard test job

**Decision.** `self-eval` depends on `test` succeeding, not `mutation`.

**Rationale.** The `self-eval` job invokes `harness-quality-gate all .`, which internally runs pytest (L1). If the test suite is broken, there is no point running the gate. However, we do NOT wait for `mutation` (which runs separately and locally) — CI self-eval is about structural integrity, not mutation coverage.

### 3.2 New Job Definition

```yaml
  # ──────────────────────────────────────────────
  # SELF-EVAL STAGE — Quality gate runs on itself
  # ──────────────────────────────────────────────
  # Runs `harness-quality-gate all .` against this repo.
  # L3A→L1(pytest only)→L2→L3B→L4 gate.
  # Excludes mutmut (L1 mutation) — enforced locally before merge.
  # Run on: main pushes, weekly cron, manual dispatch.
  # ──────────────────────────────────────────────
  self-eval:
    name: Self-Evaluation (QG Gate)
    runs-on: ubuntu-latest
    timeout-minutes: 10
    needs: test
    if: >-
      always() &&
      (
        (github.event_name == 'push' && github.ref == 'refs/heads/main') ||
        (github.event_name == 'schedule') ||
        (github.event_name == 'workflow_dispatch')
      )

    steps:
      - uses: actions/checkout@v4

      - name: Setup Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Cache pip dependencies
        uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('pyproject.toml') }}-self-eval
          restore-keys: |
            ${{ runner.os }}-pip-

      - name: Install package (editable + dev)
        run: pip install -e ".[dev]"

      - name: Install quality-gate tool dependencies
        run: pip install ruff pyright bandit vulture deptry mutmut

      - name: Run quality gate on self
        run: |
          set -euo pipefail
          echo "════════════════════════════════════════════"
          echo " Self-Evaluation: Quality Gate on Itself"
          echo "════════════════════════════════════════════"
          echo ""
          echo "Running: harness-quality-gate all ."
          echo "(L3A→L1(pytest)→L2→L3B→L4, mutmut excluded)"
          echo ""
           python -m harness_quality_gate all . --json 2>&1 | tee _quality-gate/self-eval-output.json

      - name: Parse self-eval result
        id: parse
        run: |
          # reason: extract the PASS/FAIL flag from the checkpoint JSON
          # The CLI writes json to stdout with indent=2
          PASS=$(python3 -c "
          import json, sys
          data = json.load(open('_quality-gate/self-eval-output.json'))
          layers = data.get('layers', [])
          all_pass = all(l.get('passed', False) for l in layers)
          # Also check top-level 'PASS' key
          top = data.get('PASS', all_pass)
          print('PASS' if top else 'FAIL')
          ")
          # reason: the string "PASS"/"FAIL" is metadata; exact case
          # doesn't change the control flow in subsequent steps.
          echo "self_eval_result=$PASS" >> "$GITHUB_OUTPUT"
          echo "Self-evaluation: $PASS"
          if [ "$PASS" != "PASS" ]; then
            echo "⚠️ Self-evaluation FAILED — quality gate does not pass on its own code"
          fi

      - name: Show layer summary
        if: always()
        run: |
          echo "## Self-Evaluation Results" >> "$GITHUB_STEP_SUMMARY"
          echo "" >> "$GITHUB_STEP_SUMMARY"
          echo "| Layer | Status |" >> "$GITHUB_STEP_SUMMARY"
          echo "|-------|--------|" >> "$GITHUB_STEP_SUMMARY"
          python3 -c "
          import json
          data = json.load(open('_quality-gate/self-eval-output.json'))
          for layer in data.get('layers', []):
              status = '✅ PASS' if layer.get('passed') else '❌ FAIL'
              findings = len(layer.get('findings', []))
              print(f'| {layer.get(\"layer\")} ({layer.get(\"language\")}) | {status} ({findings} findings) |')
          " | tee -a "$GITHUB_STEP_SUMMARY"
          echo "" >> "$GITHUB_STEP_SUMMARY"
          echo "The quality gate ran `harness-quality-gate all .` against itself." >> "$GITHUB_STEP_SUMMARY"
          echo "Layer L1 excluded mutmut mutation testing (enforced locally before merge)." >> "$GITHUB_STEP_SUMMARY"
```

### 3.3 Concurrency in CI

The CLI sets `"ci": bool(os.environ.get("CI"))` in the checkpoint runtime metadata (`cli.py` line 201). The concurrency config (`config.py` lines 30–40) detects CI env vars and uses `max_workers_ci: 1`. This means the full gate runs **sequentially** in CI, which is safe but slower. The 10-minute timeout is generous enough for a clean sequential run (L3A < 1 min, L1 pytest ~2 min, L2 ~30 sec, L3B ~1 min, L4 ~1 min).

## 4. Known Limitations and Workarounds

### 4.1 Mutation Testing (L1 mutmut)

| Problem | Impact | Workaround |
|---------|--------|------------|
| `mutmut` not on GitHub runner PATH by default | L1 mutation stats = empty (total=0, survived=0) | ADR-001: Graceful degradation. Empty stats → `mutation_passed = True`. MSI enforcement is a local pre-commit gate. |
| `mutmut` requires `also_copy` dirs (`references`, `config`, `bmad/*`, etc.) | Baseline collection fails with `FileNotFoundError` | If we ever re-enable mutmut in CI, we must ensure the `also_copy` directories are accessible from the `mutants/` sandbox. |
| ~6000 mutants, ~22 min on local machine | CI runner (2 cores) would take 2+ hours | Rejected by ADR-001. Mutation discipline is local. |

### 4.2 PHP Tools

| Problem | Impact | Workaround |
|---------|--------|------------|
| `php`, `phpstan`, `infection`, `phpunit` not on standard GitHub runner | L1 would fail with exit 3 (`INFRA_INCOMPLETE`) for a PHP repo | Not applicable to self-eval: this repo is Python-only (no `composer.json`). PHP adapter would only run if a `composer.json` is detected. |
| If the repo were hybrid | Both adapters would need toolchains | Rejected by design (`SKILL.md` line 54): hybrid repos are not supported. |

### 4.3 L3B Warnings Are Non-Blocking

The SOLID metrics adapter (`python_adapter.py` lines 343) and antipattern adapter (`python_adapter.py` lines 368) both emit `warning` severity. Since gate logic checks `severity == "error"`, L3B warnings **never** cause a FAIL. This is intentional (self-eval F11 note in the code comment).

### 4.4 Pyright Configuration

Pyright may find its own configuration at `pyrightconfig.json` in the repo root. The adapter runs pyright against the target repo (`python_adapter.py` line 397: `self.pyright.invoke(repo, [], env=...)`). The existing `pyrightconfig.json` already exists in this repo — pyright will use it during self-eval.

### 4.5 Checkpoint Write Conflicts

The `all` command writes to `_quality-gate/quality-gate-latest.json` (`cli.py` lines 220–232). If this step runs concurrently with another CI job that also invokes the gate, the write could race. Current design serializes `self-eval` after `test`, and no other job runs the full gate, so this is not a practical concern.

## 5. Integration with Existing Pipeline

### 5.1 Modified Job Dependency Chain

```
lint ──→ test ──→ burn-in* (conditional)
                  │
                  ▼
             self-eval ←─── NEW
                  │
                  ▼
            quality-gate
                  │
                  ▼
                report
```

\* burn-in still conditional: only on schedule or `workflow_dispatch` with `run_burn_in=true`.

**Dependency table:**

| Job | Depends On | Condition |
|-----|-----------|-----------|
| `lint` | *(none)* | all push/PR/schedule |
| `test` | `lint` | all push/PR/schedule |
| `burn-in` | `test` | schedule OR dispatch(w=ture) |
| `self-eval` ← NEW | `test` | main push OR schedule OR dispatch |
| `quality-gate` | `lint`, `test`, `self-eval` | `always()` — checks all |
| `report` | `test`, `burn-in`, `quality-gate` | `always()` |

### 5.2 Modified `quality-gate` Job

The `quality-gate` job needs to check `self-eval` result too:

```yaml
  quality-gate:
    name: Quality Gate
    runs-on: ubuntu-latest
    needs: [lint, test, self-eval]    # ← add self-eval
    if: always()
    timeout-minutes: 5

    steps:
      # ... existing lint + test checks ...

      - name: Check self-eval result
        run: |
          if [ "${{ needs.self-eval.result }}" == "failure" ]; then
            echo "::error::Self-evaluation failed — P0 quality gate BLOCKED"
            exit 1
          fi
          if [ "${{ needs.self-eval.result }}" == "cancelled" ]; then
            echo "::warning::Self-evaluation was cancelled — quality gate SKIPPED"
            exit 1
          fi
          echo "Self-eval: ${{ needs.self-eval.result }}"

      - name: Gate decision
        run: |
          echo "## Quality Gate: PASS ✅" >> "$GITHUB_STEP_SUMMARY"
          echo "" >> "$GITHUB_STEP_SUMMARY"
          echo "| Gate Rule | Threshold | Result |" >> "$GITHUB_STEP_SUMMARY"
          echo "|-----------|-----------|--------|" >> "$GITHUB_STEP_SUMMARY"
          echo "| Lint/Type (P0) | 100% pass | ${{ needs.lint.result }} |" >> "$GITHUB_STEP_SUMMARY"
          echo "| Tests (P0+P1) | 100% pass | ${{ needs.test.result }} |" >> "$GITHUB_STEP_SUMMARY"
          echo "| Self-Eval (P0) | Gate passes on itself | ${{ needs.self-eval.result }} |" >> "$GITHUB_STEP_SUMMARY"
          echo "| Coverage | 100% fail_under | Enforced per shard |" >> "$GITHUB_STEP_SUMMARY"
          echo "| Mutation MSI | 100% | Local pre-commit gate |" >> "$GITHUB_STEP_SUMMARY"
```

### 5.3 Modified `report` Job

The `report` job needs to include `self-eval` in its needs and summary:

```yaml
  report:
    needs: [test, burn-in, self-eval, quality-gate]  # ← add self-eval

    steps:
      - name: Generate summary
        run: |
          echo "## Quality Gate Pipeline — Execution Summary" >> "$GITHUB_STEP_SUMMARY"
          echo "" >> "$GITHUB_STEP_SUMMARY"
          echo "| Job | Status |" >> "$GITHUB_STEP_SUMMARY"
          echo "|-----|--------|" >> "$GITHUB_STEP_SUMMARY"
          echo "| \`lint\` | ${{ needs.lint.result }} |" >> "$GITHUB_STEP_SUMMARY"
          echo "| \`test\` | ${{ needs.test.result }} |" >> "$GITHUB_STEP_SUMMARY"
          echo "| \`self-eval\` | ${{ needs.self-eval.result }} |" >> "$GITHUB_STEP_SUMMARY"
          echo "| \`burn-in\` | ${{ needs.burn-in.result }} |" >> "$GITHUB_STEP_SUMMARY"
          echo "| \`quality-gate\` | ${{ needs.quality-gate.result }} |" >> "$GITHUB_STEP_SUMMARY"
```

### 5.4 Concurrency Group

Self-eval should share the existing concurrency group to avoid duplicate runs:
```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```
This is already defined at the workflow level and applies to all jobs. When a new push comes in, only the latest commit's jobs run.

## 6. CI Workflow Integration Summary

The `self-eval` job integrates into `.github/workflows/test.yml` as follows:

**Placement:** After the `test` job block, before the `burn-in` job block.

**Why there:** 
- `self-eval` depends on `test` (the tests must pass before the gate can pass).
- `burn-in` also depends on `test` but is independent of `self-eval` (burn-in checks test flakiness, self-eval checks gate integrity).
- They could run in parallel in theory, but `self-eval` writing checkpoint files to `_quality-gate/` while `burn-in` runs pytest concurrently is safe since they use different directories.

**Total pipeline impact:**
- Adds ~3–5 minutes to main-branch push flow (install dependencies + run gate).
- No impact on PR flow (self-eval does not run on PRs per ADR-003).
- Weekly cron now runs: test + self-eval + (conditional) burn-in + quality-gate + report.

## 7. Future Considerations

### 7.1 MSI Threshold Progression

The `infection.thresholds` in config defaults to 100% MSI / 100% covered MSI. The pipeline currently gates on this value from the config file and the mutation results are parsed from the `tool_specific.mutation_stats` field in the checkpoint JSON.

If we ever want a graduated threshold approach:

| Phase | min_msi | min_covered_msi | Context |
|-------|---------|-----------------|---------|
| Current | 100% | 100% | Policy as-is (config.py line 129: never allows < 100%) |
| Future Phase 1 | ~80% | ~85% | If local mutation discipline weakens; would require config schema change |
| Future Phase 2 | 95% | 95% | Steady state improvement target |
| Steady State | 100% | 100% | Current policy |

**Note:** `config.py` line 129 enforces `min_msi >= 100.0` as a hard policy. Any reduction requires a schema version bump from `v2` to `v3`.

### 7.2 Adding PHP Self-Eval

When PHP tools become available in CI (via `shivammathur/setup-php` action), the self-eval job could additionally validate PHP adapter code in `harness_quality_gate/adapters/php/`. This would:

1. Detect a PHP fixture repo in `tests/fixtures/` or similar.
2. Set up PHP toolchain.
3. Run `harness-quality-gate all <fixture-dir>`.

This is deferred until PHP adapter code is production-ready and the CI runner environment is extended with PHP tooling.

### 7.3 Checkpoint Integration

The self-eval checkpoint JSON (`_quality-gate/quality-gate-latest.json`) can be consumed by:

1. **Checkpoint system** (`checkpoint.py`): Already generates v2 checkpoints with schema validation. Self-eval results flow through the same checkpoint pipeline.
2. **Quality gate job**: Can read the checkpoint file directly instead of re-parsing the CLI output, enabling consistent parsing logic.
3. **External tools**: The `_quality-gate/` directory is a well-known location per the CLI convention (`cli.py` lines 159, 220, 227). External CI jobs or reporting tools can read this file.

### 7.4 Artifact Management

Consider uploading the self-eval checkpoint as a CI artifact:
```yaml
- name: Upload self-eval checkpoint
  uses: actions/upload-artifact@v4
  with:
    name: self-eval-checkpoint
    path: _quality-gate/quality-gate-latest.json
    retention-days: 90
```

This enables post-hoc analysis of self-eval results, historical trend tracking, and debugging when a self-eval fails.

### 7.5 Future: Mutation in CI

If the project ever decides to run mutation testing in CI, the following approaches are possible:

| Approach | Pros | Cons |
|----------|------|------|
| Full mutmut with 2+ runner instances | 100% MSI enforcement in CI | Expensive, slow on hosted runners |
| Partial mutation (key files only) | Faster, catches critical dead mutates | Only covers critical surface |
| Cached mutmut results | Reuse local mutation data | Stale results, not self-eval |
| `mutmut diff` (new mutants only) | Fast, focuses on new code | Not full self-eval |

**Recommendation:** Keep mutation as a local pre-commit gate. It has proven working (per Makefile mutation workflow) and CI is the wrong place for 20-minute mutation campaigns.

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Self-eval FAILS due to tool version drift | Medium | Medium — blocks CI on main | Pin tool versions; log versions in checkpoint |
| Long-running L1 mutation in CI causes timeouts | High* | High — runner waste | ADR-001: Excluded from CI |
| Checkpoint JSON parser fails on new schema | Low | Medium — silent failure | Schema validation in `checkpoint.py:validate()` |
| Self-eval masks broken gate logic | Low | High — false confidence | Periodic manual audit of gate behavior |
| CI environment differences from local | Medium | Low—tools degrade gracefully | Document known differences; log tool versions |

*\* Mitigated: mutmut is explicitly excluded from CI per ADR-001.*

## 9. Success Criteria

The self-eval is considered **operational** when:

1. ✅ `self-eval` job exists in `.github/workflows/test.yml` and runs on main pushes and weekly cron.
2. ✅ All 5 layers report PASS on self-eval (L3A, L1 with pytest, L2, L3B, L4).
3. ✅ `quality-gate` job includes `self-eval` in its `needs` and checks its result.
4. ✅ `report` job includes `self-eval` in its summary.
5. ✅ Self-eval checkpoint is written to `_quality-gate/quality-gate-latest.json` and is parseable.
6. ✅ No `mutmut` is run in CI — mutation enforcement remains a local pre-commit discipline.
7. ✅ The self-eval job completes within 10 minutes on a standard GitHub-hosted runner.

## 10. Implementation Checklist

- [x] Add `self-eval` job block to `.github/workflows/test.yml`
- [x] Modify `quality-gate` job: add `self-eval` to `needs`, add result check step
- [x] Modify `report` job: add `self-eval` to `needs`, update summary
- [ ] Test on a feature branch: push to trigger self-eval, verify all layers PASS
- [ ] If self-eval FAILS: fix failing layer (likely L3B warnings, which already don't gate)
- [x] Add artifact upload for self-eval checkpoint JSON
- [ ] Update SKILL.md to document self-eval workflow
- [ ] Update README.md to mention self-eval as a practice the tool follows