# Mutation Testing Workflow

How to run mutmut on this repo, interpret results, and debug the
`mutmut results` vs `mutmut-cicd-stats.json` discrepancy.

## TL;DR

```bash
# One-shot: clean state, fresh coverage, full run
make mutation
cat mutants/mutmut-cicd-stats.json   # ← the ONLY reliable summary

# Per-module iteration (faster feedback)
mutmut run 'harness_quality_gate.cli.*'
mutmut run 'harness_quality_gate.config.*'
mutmut run 'harness_quality_gate.adapters.base.*'
mutmut run 'harness_quality_gate.adapters.php.infection_adapter.*'
```

CI gate fails on any `survived`, `no_tests`, `suspicious`, or `timeout`
in `mutants/mutmut-cicd-stats.json`.

## Why two different result views disagree

`mutmut results` and `mutants/mutmut-cicd-stats.json` look at the same
mutants but report differently. They are NOT contradictory — they answer
different questions.

| Command | Source | Reports |
| --- | --- | --- |
| `mutmut results` | `.mutmut-cache` (SQLite) | Every mutant in the cache, including `not checked` (queue state) |
| `mutmut export-cicd-stats` | last completed run's counters | Only mutates that **terminated** in the last full run |

`mutmut results` can show thousands of `not checked` mutants that
**never actually ran** — they are queued for evaluation but were skipped
because the previous run was interrupted (Ctrl-C, runner timeout, OOM,
CI job limit, etc.). The cache persists between runs and is not
truncated on interruption.

`mutants/mutmut-cicd-stats.json` only counts the 5 terminal states
(`killed`, `survived`, `no_tests`, `suspicious`, `timeout`). It excludes
queued-but-unevaluated mutants entirely. This is the only view that
tells you "did the run actually pass?".

**Trust `mutmut-cicd-stats.json` for pass/fail. Use `mutmut results` to
investigate individual mutantes.**

## Reading `mutmut results` without noise

The default output is dominated by `not checked` lines. To see only
the mutantes that actually ran:

```bash
mutmut results 2>&1 | grep -v "not checked"
```

Or just look at the survivors — that's the actionable signal:

```bash
mutmut results 2>&1 | grep survived
```

## Reading the JSON summary

```bash
python3 -c "
import json
d = json.load(open('mutants/mutmut-cicd-stats.json'))
total = d['total'] - d['no_tests'] - d['skipped']
print(f'kill rate: {d[\"killed\"]/total*100:.1f}%  ({d[\"killed\"]} killed / {d[\"survived\"]} survived / {total} tested)')
print(f'uncovered: {d[\"no_tests\"]} | suspicious: {d[\"suspicious\"]} | timeout: {d[\"timeout\"]}')
print(f'CI passes: {not (d[\"survived\"] or d[\"no_tests\"] or d[\"suspicious\"] or d[\"timeout\"])}')
"
```

## Investigating one mutante

```bash
# Show the diff for a specific surviving mutant
mutmut show harness_quality_gate.config.x_validate__mutmut_5
```

The key is the mutmut-stats ID. Get a list of survivors and pick one:

```bash
mutmut results 2>&1 | grep survived | head -3
```

## Why coverage must be regenerated before mutmut

`mutate_only_covered_lines = true` (in `pyproject.toml`) only mutates
lines that were executed by the test runner in the last `.coverage`
file. If you skip the coverage step, mutmut mutates uncovered lines
and they all end up in `no_tests` (untriaged survivors from the gate's
view).

The Makefile handles this:

```makefile
mutation:
    rm -rf .mutmut-cache .mutmut-state
    python3 -m mutmut run --max-children=$(MUTATION_MAX_CHILDREN)
```

But the `.coverage` regeneration is **not** in the Makefile — it's the
CI step right before mutmut:

```yaml
- name: Mutation testing (must be 100% on documented scope)
  run: |
      # Coverage scope MUST match the mutmut runner (tests/unit) so that
      # mutate_only_covered_lines mutates exactly what the runner can kill.
      pytest tests/unit/ -q -p no:randomly --cov=harness_quality_gate --cov-report=
      mutmut run
      mutmut export-cicd-stats
      python -c "import json,sys; s=json.load(open('mutants/mutmut-cicd-stats.json')); print(s); sys.exit(1 if (s['survived'] or s['no_tests'] or s['suspicious'] or s['timeout']) else 0)"
```

When running mutmut locally, regenerate the coverage first:

```bash
.venv/bin/python -m pytest tests/unit/ -q --cov=harness_quality_gate --cov-report= -p no:randomly
mutmut run 'harness_quality_gate.cli.*'
```

## Closing survivors: pragma policy

Per the user's standing rule: **"Cero pragmas sobre lógica"** — zero
pragmas on logic. Behavioral mutantes must be killed with tests.
Pragmas are only acceptable for **provably-equivalent** mutantes, and
each pragma must carry `# reason: ...` and `# audited: YYYY-MM-DD`
in the 5 preceding lines so the `allow_list_auditor` accepts it.

When in doubt, do this in order:

1. **Can a test kill the mutante?** Write one. See
   `tests/unit/test_base_adapter.py` and `tests/unit/test_infection_parser.py`
   for the pattern (mock the subprocess / side effect, assert the value
   the mutante would change).
2. **Is the mutante truly equivalent?** Add a pragma with a SPECIFIC
   reason that names the test or explains the equivalence:

   ```python
   # reason: timeout=600.0 is a public API default; mutations (601.0) are equivalent. # audited: 2026-06-04
   timeout: float = 600.0,  # pragma: no mutate
   ```

3. **Neither?** Leave it as a survivor and document the gap in
   `mutmut-cicd-stats.json` interpretation — that's an honest result.

## Verifying pragmas are honest (the audit-ignores gate)

```bash
.venv/bin/python -m harness_quality_gate audit-ignores harness_quality_gate
echo "exit: $?"   # must be 0
```

This uses `allow_list_auditor` which:
- Scans all `.py` files in `harness_quality_gate/` for `# pragma: no mutate`
- For each pragma, requires `# reason:` and `# audited:` in the 5
  preceding lines (the auditor's `^\s*#\s*reason:` and `^\s*#\s*audited:`
  regexes — they must START with `#`, not be embedded mid-sentence)
- Exits 0 only if every pragma has proper metadata

Both gates (`mutmut` AND `audit-ignores`) must pass for CI to be green.

## Quick reference: Makefile targets

| Target | Scope | Use for |
| --- | --- | --- |
| `make mutation` | All paths in `pyproject.toml [tool.mutmut]` | CI / final gate |
| `make mutation-cli` | `harness_quality_gate/cli.py` | Fast iteration on CLI |
| `make mutation-full` | `harness_quality_gate/` whole tree | After large refactors |
| `make mutation-covered` | Coverage-filtered only | Quickest sanity check |
| `make update-mutmut` | Upgrade `mutmut>=3.5.0` | After bumping pyproject |
