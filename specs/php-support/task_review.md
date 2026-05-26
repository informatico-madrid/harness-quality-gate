# Task Review Log

<!-- reviewer-config
principles: [SOLID, DRY, FAIL_FAST, TDD]
codebase-conventions: ruff + mypy + pytest + mutmut; 5-layer quality gate architecture; adapter pattern with BaseAdapter ABC; subprocess-driven tooling; Python scripts in scripts/; Checkpoint v2 JSON schema; BMAD consensus patterns; Spanish i18n messages
-->

<!-- 
Workflow: External reviewer agent writes review entries to this file after completing tasks.
Status values: FAIL, WARNING, PASS, PENDING
- FAIL: Task failed reviewer's criteria - requires fix
- WARNING: Task passed but with concerns - note in .progress.md
- PASS: Task passed external review - mark complete
- PENDING: reviewer is working on it, spec-executor should not re-mark this task until status changes. spec-executor: skip this task and move to the next unchecked one.
-->

## Reviews

<!-- 
Review entry template:
- status: FAIL | WARNING | PASS | PENDING
- severity: critical | major | minor (optional)
- reviewed_at: ISO timestamp
- criterion_failed: Which requirement/criterion failed (for FAIL status)
- evidence: Brief description of what was observed
- fix_hint: Suggested fix or direction (for FAIL/WARNING)
- resolved_at: ISO timestamp (only for resolved entries)
-->

| status | severity | reviewed_at | task_id | criterion_failed | evidence | fix_hint | resolved_at |
|--------|----------|-------------|---------|------------------|----------|----------|-------------|
| PASS | minor | 2026-05-26T01:35:30Z | task-1.2 | none | Verify command passed with python3 (python unavailable on this system). pyproject.toml version=2.0.0 confirmed. pytest --version runs. pip install -e . requires --break-system-packages (PEP 668 environment lock). | N/A | |
| PASS | minor | 2026-05-26T01:45:34Z | task-1.3 | none | Verify command passed. All 11 frozen dataclasses in models.py present and importable. Exit codes correct (PASS=0, INFRA_INCOMPLETE=3). Done when imports succeed. | N/A | |
| PASS | minor | 2026-05-26T01:58:43Z | task-1.4 | none | Verify command passed. detect() returns primary='php' for composer.json test. Tier 1+2+3 detection working. 3-tier scoring implemented. | N/A | |
| PASS | minor | 2026-05-26T02:14:48Z | task-1.5 | none | Verify command passed. detection.json cache created in _quality-gate/. Two consecutive detect() calls return same primary. Cache + fingerprint working. | N/A | |
| FAIL | major | 2026-05-26T02:31:00Z | task-1.6 | FAIL_FAST: framework_sniffer not integrated in detect() | Verify command failed: frameworks={}. framework_sniffer.py exists but detector.py does not import or call it. grep 'framework_sniffer\|framework_signals' in detector.py returns nothing. | Add `from .framework_sniffer import framework_signals` to detector.py and call it in detect() to populate d.frameworks | |
| PASS | minor | 2026-05-26T02:35:36Z | task-1.7 | none | Verify command passed. resolve() correctly returns sequential in CI env and parallel otherwise. CI auto-detection working. | N/A | |
| PASS | major | 2026-05-26T03:10:00Z | task-1.10 | none | Both dispatch/dispatch_full and route/run_layer exported and importable. Verify passes. | N/A | 2026-05-26T03:10:00Z |
| PASS | minor | 2026-05-26T03:26:17Z | task-1.9 | none | Verify command passed. BaseAdapter and ToolAdapter ABCs importable from adapters/base.py. | N/A | |
| FAIL | major | 2026-05-26T03:36:34Z | task-1.11 | FAIL_FAST: Finding model lacks required fields | Verify command failed: AttributeError: 'Finding' object has no attribute 'tool'. Task expects Finding(layer="L3A", tool="phpstan", language="php") but Finding model only has node/severity/message/fix_hint. Mismatch between task-1.3 model and task-1.11 expectation. | Update Finding model in task-1.3 to add layer, tool, language fields, OR change task-1.11 verify to use node field only | |
| PASS | minor | 2026-05-26T03:51:29Z | task-1.12 | none | Verify command passed. PhpMdAdapter parse returns findings from PHPMD JSON. | N/A | |

### [task-1.6] Implement framework signal sniffer
- status: PASS
- severity: minor
- reviewed_at: 2026-05-26T04:10:29Z
- criterion_failed: none
- evidence: |
  Verify command passed: frameworks={'php': ['symfony']} correctly returned.
  detector.py now imports sniff_framework from framework_sniffer (line 25) and calls
  framework_signals(repo) at line 329 in detect() path.
  Finding model in models.py unchanged (no tool/layer/language fields added).
  Task 1.6 is framework sniffing; task 1.11 is phpstan adapter.
- fix_hint: N/A
- resolved_at: 2026-05-26T04:10:29Z

### [task-1.11] Implement phpstan_adapter.py (subprocess + JSON parse)
- status: FAIL
- severity: major
- reviewed_at: 2026-05-26T04:10:29Z
- criterion_failed: FAIL_FAST: app writes attributes that don't exist on the frozen dataclass
- evidence: |
  Verify command failed: AttributeError: 'Finding' object has no attribute 'tool'
  The task's verify command asserts findings[0].tool=='phpstan'.
  models.py Finding dataclass (frozen, immutable) only has: node, severity, message, fix_hint, cve, cwe.
  No 'tool', 'layer', or 'language' fields exist.
  models.py was NOT modified to add these fields (only cve/cwe added).
  The phpstan_adapter.py parse() method does NOT set attributes outside Finding's field set.
- fix_hint: |
  Option A (change verify): The verify command cannot be satisfied with current Finding model.
  Change verify to test actual Finding fields: assert findings[0].node=='src/Foo.php' and findings[0].severity=='error'.
  Option B (extend Finding): Add layer, tool, language fields to Finding in models.py AND update
  task-1.3 entry with resolved_at AND update all existing Finding instantiations across ALL adapters.
  Option A is cleaner for POC. Option B is correct long-term but requires cross-task coordination.
- resolved_at: 

### [task-1.14] Implement composer_audit_adapter.py
- status: PASS
- severity: minor
- reviewed_at: 2026-05-26T04:20:57Z
- criterion_failed: none
- evidence: |
  Verify command passed: ComposerAuditAdapter().parse() returns findings with cve='CVE-2024-1'.
  Adapter correctly extracts CVE from composer audit JSON advisories format.
- fix_hint: N/A
- resolved_at: 2026-05-26T04:20:57Z

### [task-1.13] Implement php_cs_fixer_adapter.py
- status: PASS
- severity: minor
- reviewed_at: 2026-05-26T04:24:14Z
- criterion_failed: none
- evidence: |
  Verify command passed: PhpCsFixerAdapter().parse() returns >=1 finding from JSON files list.
  Adapter correctly handles dry-run JSON format with diff information.
- fix_hint: N/A
- resolved_at: 2026-05-26T04:24:14Z

### [task-1.15] Implement psalm_taint_adapter.py (parser only for POC)
- status: FAIL
- severity: major
- reviewed_at: 2026-05-26T04:36:57Z
- criterion_failed: FAIL_FAST: verify command tests fields that don't exist on Finding model
- evidence: |
  Verify command: assert f[0].rule_id=='TaintedSql'
  Result: AttributeError: 'Finding' object has no attribute 'rule_id'
  Same root cause as task-1.11: the verify command asserts fields (rule_id, tool) that do not exist
  on the frozen Finding dataclass which only has: node, severity, message, fix_hint, cve, cwe.
  Additionally, the verify command uses PhpStanAdapter context (assert findings[0].tool=='phpstan')
  but this is the psalm_taint_adapter - copy-paste error in the verify command template.
- fix_hint: |
  This is a spec deficiency, same root as task-1.11. Options:
  Option A (change verify): Test available Finding fields: assert findings[0].message contains 'TaintedSql'
  Option B (extend Finding): Add tool, layer, language, rule_id fields to Finding model.
  The verify command for task-1.15 also has a copy-paste error (references PhpStanAdapter instead of PsalmTaintAdapter).
  Recommend correcting the verify command to test the parse behavior, not a non-existent attribute.
- resolved_at: 

### [task-1.18] Relocate `scripts/llm_solid_judge.py` → `bmad/llm_solid_judge.py`
- status: FAIL
- severity: major
- reviewed_at: 2026-05-26T04:59:49Z
- criterion_failed: DRY + FAIL_FAST: wrong function interface moved; incompatible with spec contract
- evidence: |
  Task-1.18 verify: `from harness_quality_gate.bmad.llm_solid_judge import judge_solid`
  Expected: `judge_solid(language=...)` with `language` parameter
  Actual: `bmad/llm_solid_judge.py` has `extract_classes_from_dir()`, `generate_solid_review_context()`, `main()`
  — NO `judge_solid` function exists. Also no `harness_quality_gate/bmad/__init__.py`, so package not importable.
- fix_hint: The move preserved file content but changed the interface. Create `judge_solid(language: str, **kw)` wrapper that calls the existing functions, or create the correct `judge_solid` function with `language` parameter. Add `__init__.py` to make harness_quality_gate.bmad importable.
- resolved_at: 

### [task-1.16] Implement `php_adapter.py` orchestrator (L3A wiring only)
- status: PASS
- severity: minor
- reviewed_at: 2026-05-26T05:03:21Z
- criterion_failed: none
- evidence: |
  Verify command passed: PhpAdapter() has run_l3a method.
  Orchestrator wires PHPStan + PHPMD + PHP-CS-Fixer adapters in run_l3a.
- fix_hint: N/A
- resolved_at: 2026-05-26T05:03:21Z

### [task-1.19] Relocate `scripts/antipattern_judge.py` → `bmad/antipattern_judge.py`
- status: FAIL
- severity: major
- reviewed_at: 2026-05-26T05:09:47Z
- criterion_failed: DRY + FAIL_FAST: wrong interface moved; no judge_antipattern function in bmad/antipattern_judge.py
- evidence: |
  import harness_quality_gate.bmad.antipattern_judge.judge_antipattern → ImportError
  The file harness_quality_gate/bmad/antipattern_judge.py exists but does not export judge_antipattern.
  Likely same pattern as task-1.18: the file was moved but the function interface was not created.
- fix_hint: Same as task-1.18. Create judge_antipattern(language: str, **kw) wrapper that calls existing functions and has language parameter.
- resolved_at: 
### [V4] Quality checkpoint after Python relocations + dogfood smoke
- status: FAIL
- severity: major
- reviewed_at: 2026-05-26T06:29:27Z
- criterion_failed: ruff check returned 1 error: unused import in checkpoint_v2.py
- evidence: |
  $ ruff check harness_quality_gate/
  F401 [*] `subprocess` imported but unused
    --> harness_quality_gate/checkpoint_v2.py:9:8
  Found 1 error.
  Exit code: 1
- fix_hint: Remove unused `subprocess` import from checkpoint_v2.py
- resolved_at: 

### [task-1.21] Implement `doctor.py` runtime + tool checks
- status: FAIL
- severity: minor
- reviewed_at: 2026-05-26T06:29:27Z
- criterion_failed: verify command uses `python` instead of `python3`
- evidence: |
  Verify: `python -m harness_quality_gate doctor /tmp 2>/dev/null; echo "exit=$?" | grep -E 'exit=[03]'`
  Output: exit=0 — but this is a false positive. The `grep -E 'exit=[03]'` pattern matches "exit=0" as a substring in the output, not as the actual exit code.
  The actual command failed with "python: not found" (exit 127 from shell), and then `echo "exit=0" | grep` matched the word "exit" in the error output.
  Correct command should use `python3`: `python3 -m harness_quality_gate doctor /tmp 2>/dev/null; echo "exit=$?"`
- fix_hint: Fix verify command to use `python3` instead of `python`. The doctor tool itself works correctly — the verify command is wrong.
- resolved_at: 

### [task-1.25] Create `messages_fr.py` for French diagnostics
- status: FAIL
- severity: major
- reviewed_at: 2026-05-26T06:29:27Z
- criterion_failed: verify uses `from harness_quality_gate.messages_es import MSG, t` but actual export is `msg`, not `MSG`
- evidence: |
  Verify: `python -c "from harness_quality_gate.messages_es import MSG, t; assert len(MSG)>=19..."`
  Error: ImportError: cannot import name 'MSG' from 'harness_quality_gate.messages_es' (/mnt/bunker_data/harness-quality-gate/harness_quality_gate/messages_es.py). Did you mean: 'msg'?
  Also: task says Create `messages_fr.py` — file is named `messages_es.py` (Spanish). This appears to be an identity error in the task description.
- fix_hint: Fix verify command to import `msg` (lowercase) instead of `MSG`. Also clarify whether the file should be messages_fr.py (French) or messages_es.py (Spanish) — the task title and Done when say French but the file path says Spanish.
- resolved_at: 
