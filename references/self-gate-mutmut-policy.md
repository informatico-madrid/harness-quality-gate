# Self-Gate Mutation Testing Policy

## Scope

`harness_quality_gate/` (the package under test).

## Threshold

**100 % killed-or-justified.** Every mutant must either be killed by the
existing test suite or carry a justified `# pragma: no mutate` annotation
audited by `AllowListAuditor`.

## How to run

```bash
# Using the convenience wrapper:
bash scripts-dev/run-mutmut.sh

# Or directly:
mutmut run --paths-to-mutate=harness_quality_gate/
```

The `pyproject.toml` section `[tool.mutmut]` supplies the defaults
(`paths_to_mutate`, `runner`, `tests_dir`).

## Allow-list policy for `# pragma: no mutate`

When a module cannot be mutated (e.g. a thin dataclass or a function that
raises on every path), annotate the line with the pragma and supply the
following metadata within 5 lines **preceding** the marker:

```python
# reason: <one-line explanation of why the function cannot be mutated>
# audited: <YYYY-MM-DD>
# pragma: no mutate
def _nothing():
    raise NotImplementedError("stub")
```

Optional additional metadata:

```python
# proven-by: <test-function-name>
```

Every `# pragma: no mutate` without both `# reason:` and `# audited:` in the
preceding 5 lines is flagged by `AllowListAuditor` as **unjustified**.

### Auditor

```bash
python -m harness_quality_gate audit-ignores .
```

Exit code 1 when any unjustified pragma is found. Exit code 0 when all
pragmas are justified or none exist.

## Policy rules

1. **No new unjustified pragmas.** Every new `# pragma: no mutate` must be
   justified at the time of commit.
2. **100 % gate.** The mutation gate (`mutmut run`) must complete with zero
   surviving mutants (all killed or all justified).
3. **CI enforcement.** The CI pipeline runs `mutmut run` as part of the
   quality-gate step. A single surviving unjustified mutant fails the build.
4. **Ramp-down exception.** If the team agrees to lower the threshold during
   a transition period, document the expiry date in the PR and set a
   calendar reminder to restore 100 %.

## Progressive adoption

Start by running `mutmut` on a subset of modules to build confidence before
extending to the full package:

```bash
bash scripts-dev/run-mutmut.sh --paths-to-mutate=harness_quality_gate/detector.py
```

Then incrementally increase the path until the full package is covered.
