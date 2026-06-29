# PERSISTENT_PROMPT_CONSTRAINTS — Anti-Lazy Test Generation Rules

These constraints must be included in ANY system prompt where an LLM generates unit tests.
Without these constraints, LLMs consistently produce weak tests that pass normally but
fail to kill mutants in mutation testing (mutmut/Infection).

## Academic Evidence

| Paper | Finding | Impact |
|---|---|---|
| arXiv:2408.01760 | LLMs use `assertContains`, partial matching, `assertEquals(true, true)` | Structural coverage ≠ semantic validity |
| arXiv:2501.12862 | Equivalent mutants bypass standard LLM detection entirely | Requires explicit negative constraints |
| arXiv:2406.09843 | Assertion errors dominate LLM test failures; overlap with human tests | Training data leakage, not genuine reasoning |
| arXiv:2410.10628 | LLMs default to "Assertion Roulette" (magic number asserts) | `assertEquals(true, true)` is the dominant smell |
| arXiv:2506.14297 | Weak assertions survive mutation at 60%+ rate | Only explicit anti-weakness prompts reduce rate |
| arXiv:2602.03181 | Self-debugging CoT improves repair but requires negative constraints | Must specify what NOT to do |

## MANDATORY CONSTRAINTS (include in system prompt)

### ASSERTION DENSITY

```
RULE A1: Every assertion must verify COMPLETE structural equality, NEVER partial matches.
  - GOOD: assert result == {"key": "exact_value", "num": 42}
  - BAD:  assert "exact_value" in str(result)
  - BAD:  assertContains(result, "partial")
  - BAD:  assertTrue(result is not None)

RULE A2: Use exact type matchers, never lenient matchers.
  - Python: assert a == b (always), NEVER assert a in b for non-strings
  - PHP:    assertSame($a, $b) ALWAYS, never assertEquals() or toEqual()

RULE A3: Assert full call signatures on mock spies.
  - GOOD: mock.assert_called_once_with(arg1, arg2, kwarg1=5)
  - BAD:  mock.assert_called()
  - BAD:  mock.assert_called_once()
```

### MOCK STRICTNESS

```
RULE M1: Mock spies must verify COMPLETE argument lists, including kwargs and defaults.
  - If a function passes `timeout=600`, the mock MUST assert `timeout=600` exactly.
  - Partial kwargs = equivalent mutants survive.

RULE M2: PHP mock expectations must use strict identity.
  - GOOD: $mock->expects(...)->with($this->identicalTo(['a', 'b']))
  - BAD:  $mock->expects(...)->with(['a', 'b'])

RULE M3: NEVER mock the entire implementation away.
  - Mock only EXTERNAL dependencies (filesystem, network, subprocesses).
  - Internal methods that contain mutation hotspots must run with real logic.
```

### BOUNDARY COVERAGE

```
RULE B1: Every comparison operator in production code needs 3 test inputs.
  - If code uses `x > 0`, tests must cover: x=-1, x=0, x=1.
  - The boundary value (x=0) is what distinguishes `>` from `>=`.

RULE B2: Boolean combinations need truth tables.
  - If code uses `a and b`, test all 4 combinations: TT, TF, FT, FF.
  - This is what kills `and`↔`or` mutations.

RULE B3: Default parameters need "absent" tests.
  - If `def f(timeout=600)`, one test must call `f()` WITHOUT the kwarg,
    then observe the 600 value downstream.
```

### NEGATIVE CONSTRAINTS (what LLMs must NOT do)

```
FORBIDDEN P1: No assertion roulette — `assertEqual(True, True)`, `assertTrue(result)`
  when result is a boolean from a comparison-heavy function.

FORBIDDEN P2: No partial string matching — `assertIn`, `assertContains`, `str_contains`
  when the production code constructs a specific string. Use exact equality.

FORBIDDEN P3: No magic number assertions without derivation — if you assert `42`,
  the test must include a comment or variable name explaining WHY 42.

FORBIDDEN P4: No `@SuppressWarnings`, `# pragma: no mutmut`, `@infection-ignore-all`
  without a written justification in the same commit referencing a specific equivalent type.

FORBIDDEN P5: No generic exception assertions — `pytest.raises(Exception)` is insufficient.
  Must use specific exception types: `pytest.raises(ValueError, match=re.escape("exact msg"))`.

FORBIDDEN P6: No boolean assertions on computed comparisons — do NOT write
  `assertTrue(len(items) > 0)` when the code has `len(items) > 0`.
  Write `assert len(items) == 3` (exact expected count).
```

### PROPERTY-BASED FALLBACK

```
RULE P0: When specific examples cannot distinguish a mutation, use randomized inputs.
  - Hypothesis/pytest: @given(st.integers(min_value=-1000, max_value=1000))
  - PHP/phpspec: use \PhpSpec\Matcher\ThrowsExceptionMatcher with ranges

  Randomized inputs are the only reliable way to kill arithmetic mutations
  where specific values might accidentally be symmetric (e.g., 2+2 == 2*2).
```

### DENSE ASSERTION TEMPLATE

```python
# This is the assertion pattern that kills the most mutant types:

def test_function_complete_output():
    result = target_function(input_with_specific_values)

    # Full structural equality — kills string, number, key mutations
    assert result == ExpectedType(
        field1="exact_string_value",   # kills "XXstringXX" mutations
        field2=42,                      # kills 42→43 mutations
        field3=True,                    # kills True→False mutations
    )

    # Complete spy verification — kills kwarg passthrough mutations (H1)
    mock_dependency.assert_called_once_with(
        arg1=input_with_specific_values,
        arg2="exact",
        timeout=600,       # kills timeout passthrough
        check=False,       # kills boolean passthrough
    )

    # Boundary case — kills comparison mutations
    assert target_function(boundary_value) == expected_at_boundary
```

## INTEGRATION

Add these constraints to the system prompt section labeled "TEST GENERATION RULES":

```
You are generating unit tests for code that will be evaluated with mutation
testing. Your tests MUST kill mutants — not just make the test suite pass.
Follow these rules (failure to follow any rule will cause mutants to survive):
[PASTE RULES A1-A3, M1-M3, B1-B3, P0, FORBIDDEN P1-P6]
```

## MEASUREMENT

Verify effectiveness by running mutation testing after test generation:
- **Target**: MSI = 100% (0 survived, 0 no-tests, 0 suspicious, 0 timeout)
- **Acceptable**: MSI ≥ 98% with written justification for each survival
- **Fail**: MSI < 90% indicates systematic test weakness — regenerate with stricter prompts

## References

- `MUTANT_KILLING_GUIDE.md` — reactive: how to kill survivors after detection
- `SUBAGENT_MUTATION_INSTRUCTIONS.md` — operational: mutation workflow commands
- This document — proactive: prevent weak tests from being generated in the first place
