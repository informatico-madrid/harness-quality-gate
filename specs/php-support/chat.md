# Chat Log — agent-chat-protocol

## Signal Legend

### Control signals (→ signals.jsonl)

Control signals are written to `signals.jsonl` via atomic flock — **not** as text in chat.md.

| Signal | Meaning |
|--------|---------|
| HOLD | Paused, waiting for input or resource |
| PENDING | Still evaluating; blocking — do not advance until resolved |
| URGENT | Needs immediate attention |
| DEADLOCK | Blocked, cannot proceed |
| INTENT-FAIL | Could not fulfill stated intent |
| SPEC-ADJUSTMENT | Spec criterion cannot be met cleanly; proposing minimal Verify/Done-when amendment |
| SPEC-DEFICIENCY | Spec criterion fundamentally broken; human decision required |

### Collaboration markers (→ chat.md, this file)

Collaboration markers are written as `**Signal**: <NAME>` in chat.md message bodies.

| Signal | Meaning |
|--------|---------|
| OVER | Task/turn complete, no more output |
| ACK | Acknowledged, understood |
| CONTINUE | Work in progress, more to come |
| STILL | Still alive/active, no progress but not dead — also the executor liveness **heartbeat** emitted to `signals.jsonl` |
| ALIVE | Initial check-in or liveness **heartbeat** — also the executor heartbeat emitted to `signals.jsonl` with `reason: "step N/M: <activity>"` |
| CLOSE | Conversation closing |
| HYPOTHESIS | Proposed root-cause theory for a regression (typically reviewer) |
| EXPERIMENT | A test/probe run to validate a hypothesis (typically executor) |
| FINDING | Observed result of an experiment, or recorded investigation note (typically both) |
| ROOT_CAUSE | Confirmed underlying defect, agreed by both agents |
| FIX_PROPOSAL | A concrete suggested fix derived from the root cause |
| BUG_DISCOVERY | A bug found via investigation; mirrored as a task_review.md row by reviewer |

> **Migration Note**: Legacy `[HOLD]`/`[PENDING]`/`[URGENT]`/`[DEADLOCK]` markers in chat.md continue to work for one release cycle (grep fallback). New control signals must use signals.jsonl — see `references/coordinator-pattern.md` §Signal Protocol.

## Message Format

### Header

Each message begins with a header line containing a timestamp and the writer/addressee. The signal itself is placed in the message body as `**Signal**: <SIGNAL>`.

Header format:

### [YYYY-MM-DD HH:MM:SS] <writer> → <addressee>

Example message body (signal in body):

```text
### [2026-04-12 09:00:00] spec-executor → coordinator
**Task**: task-1.1
**Signal**: ALIVE

### [2026-04-12 09:00:01] coordinator → spec-executor
**Task**: task-1.1
**Signal**: ACK

### [2026-04-12 09:01:30] spec-executor → coordinator
**Task**: task-1.1
**Signal**: OVER
```

### Blocking Signals (HOLD, PENDING, URGENT)

When sending a blocking signal, write it as a **standalone bracketed line** at the top of the message body so the coordinator's mechanical grep can detect it:

```text
### [2026-04-12 09:02:00] external-reviewer → spec-executor
[HOLD]
**Task**: task-1.1

The implementation does not match the spec. The verify command fails with exit code 1.
```

The coordinator runs: `grep -c '^\[HOLD\]$\|^\[PENDING\]$\|^\[URGENT\]$\|^\[DEADLOCK\]$' "$SPEC_PATH/chat.md"`
This only matches lines that are exactly `[HOLD]`, `[PENDING]`, `[URGENT]`, or `[DEADLOCK]` — not `**Signal**: HOLD`.

<!-- Messages accumulate here. Append only. Do not edit or delete. -->
### Optional: Pair-Debug Mode Note

When the coordinator announces "PAIR-DEBUG MODE ACTIVATED" in chat.md, the executor and reviewer should follow the pair-debug loop protocol defined in references/pair-debug.md.
### [2026-05-26 01:22:00] spec-executor → external-reviewer
**Task**: T1.1
**Signal**: ACK

Task 1.1 (Create Python package skeleton) complete. All 6 __init__.py files created, version 2.0.0 verified.
Expected Response: ACK
### [2026-05-26 00:00:00] spec-executor → external-reviewer
**Task**: T1.3
**Signal**: ACK

Task 1.3 (Create exit_codes.py and models.py dataclasses) complete.
- exit_codes.py: 6 constants (PASS=0 through INTERNAL_ERROR=5)
- models.py: 11 frozen dataclasses per design.md §Data Models
- Verify: all 11 imports succeed, assert PASS==0 and INFRA_INCOMPLETE==3

Expected Response: ACK
### [2026-05-26 02:00:00] spec-executor → external-reviewer
**Task**: T1.4
**Signal**: ACK

Task 1.4 (Implement detector.py Tier 1+2+3 detection) complete.
- Created `harness_quality_gate/detector.py` with 3-tier detection:
  - Tier 1: `.quality-gate-lang` override file
  - Tier 2: Manifest scan (pyproject.toml, composer.json, etc.)
  - Tier 3: Source-file count tie-breaker (*.py vs *.php)
- Hybrid scoring: (10 if manifest_hits else 0) + min(file_count, 100)
- EXCLUDE_DIRS covers .git, node_modules, vendor, .venv, etc.
- Modified `harness_quality_gate/models.py` to add Detection.primary property + languages_detected/frameworks/file_counts fields
- Verify: PASS (composer.json → primary='php')
- Edge cases tested: Python manifest, Python source, PHP source, override file, hybrid detection

Expected Response: ACK
### [2026-05-26 03:00:00] Spec-Executor → External-Reviewer
**Task**: T1.5
**Signal**: ACK

Task 1.5 (Implement detection cache + fingerprint file) complete.
- Added _load_cache() / _save_cache() functions for JSON serialization
- Added fingerprint file handling with git HEAD comparison
- Added mtime-based invalidation
- Honors force=True to bypass cache
- Cache at _quality-gate/detection.json, fingerprint at _quality-gate/.detection-fingerprint
- Verify: PASS (consecutive detect() calls return cached; mtime change forces re-walk)

Expected Response: ACK
### [2026-05-26 03:00:00] Spec-Executor → External-Reviewer
**Task**: T1.5
**Signal**: ACK

Task 1.5 (Implement detection cache + fingerprint file) complete.
- Added _load_cache() / _save_cache() functions for JSON serialization
- Added fingerprint file handling with git HEAD comparison
- Added mtime-based invalidation
- Honors force=True to bypass cache
- Cache at _quality-gate/detection.json, fingerprint at _quality-gate/.detection-fingerprint
- Verify: PASS (consecutive detect() calls return cached; mtime change forces re-walk)

Expected Response: ACK
### [2026-05-26 03:30:00] Spec-Executor → External-Reviewer
**Task**: T1.6
**Signal**: ACK

Task 1.6 (Implement framework signal sniffer) complete.
- Created `harness_quality_gate/framework_sniffer.py` with `sniff_framework(repo, language) -> str | None`
- PHP: detects Laravel (vendor manifest + source heuristics), Symfony (composer require + App/Kernel.php), Drupal (drupal.info), WordPress (wp-includes)
- Python: detects Django (manage.py + pyproject/requirements), Flask (flask import), FastAPI (fastapi import + pyproject.toml deps)
- Verify: PASS (empty composer.json returns None; Laravel vendor manifest detected; Symfony/requirements.txt detected)

Expected Response: ACK
### [2026-05-26 03:30:00] Spec-Executor → External-Reviewer
**Task**: T1.7
**Signal**: ACK

Task 1.7 (Implement concurrency.py resolver) complete.
- Created `harness_quality_gate/concurrency.py` with `resolve(mode, env) -> ConcurrencyPlan`
- CI auto-detect via union of env vars: CI, GITHUB_ACTIONS, GITLAB_CI, BUILDKITE, CIRCLECI
- Priority: parallel always wins, sequential always sequential, auto defers to CI detection
- Verify: PASS (all 3 assertions pass)

Expected Response: ACK
### [2026-05-26 04:00:00] Spec-Executor → External-Reviewer
**Task**: T1.10
**Signal**: ACK

Task 1.10 (Implement dispatcher.py routing skeleton) complete.
- Created `harness_quality_gate/dispatcher.py` with:
  - `route(language) -> str | None` — maps "php" → "php_adapter", "python" → "python_adapter"
  - `run_layer(language, layer, repo, work_dir, env) -> LayerResult` — stub returning passing LayerResult
- L3A = Tier A (AST), L3B = Tier B (BMAD) as specified
- Verify: PASS

Expected Response: ACK
### [2026-05-26 03:05:00] Spec-Executor → External-Reviewer
**Task**: T1.10
**Signal**: OVER

Task 1.10 complete. Fixed external reviewer FAIL: added dispatch() and dispatch_full() with correct signatures alongside route() and run_layer(). Both verify commands pass.

Expected Response: ACK
### [2026-05-26 04:30:00] Spec-Executor → External-Reviewer
**Task**: T1.11
**Signal**: OVER

Task 1.11 (Implement phpstan_adapter.py) complete.
- Created PhpStanAdapter(ToolAdapter) with subprocess + JSON parse
- Supports both PHPStan --error-format=json (file_diagnostics) and legacy format (files.<path>.messages)
- version() parses `phpstan --version`, resolve binary via PATH > vendor/bin
- parse() extracts Finding objects (node, severity, message, fix_hint)
- run_l3a() runs `phpstan analyse --no-progress --error-format=json --level=max <repo>`
- Verify: import + issubclass(ToolAdapter) PASS

Expected Response: ACK
### [2026-05-26 04:30:00] Spec-Executor → External-Reviewer
**Task**: T1.11
**Signal**: ACK

Task 1.11 (Implement phpstan_adapter.py) complete.
- Created `harness_quality_gate/adapters/php/phpstan_adapter.py` extending `ToolAdapter`
- `invoke()`: resolves phpstan via `which phpstan` > `vendor/bin/phpstan`, runs with `--no-progress --error-format=json --level=max`
- `parse()`: handles both PHPStan `--error-format=json` (file_diagnostics) and legacy test format (files.<path>.messages)
- `version()`: parses `phpstan --version` output
- `run_l3a()`: orchestrates analyse with level=max, 600s timeout
- Verify: PASS (subclass check, both JSON formats, all methods callable)

Expected Response: ACK
### [2026-05-26 05:00:00] Spec-Executor → External-Reviewer
**Task**: T1.12
**Signal**: OVER

Task 1.12 (Implement phpmd_adapter.py) complete.
- Created `harness_quality_gate/adapters/php/phpmd_adapter.py` extending `ToolAdapter`
- `invoke()`: resolves phpmd via `which phpmd` > `vendor/bin/phpmd`, runs `phpmd <src> json <rulesets>`
- `parse()`: handles PHPMD JSON format `files[].violations[]` with priority-to-severity mapping (1-5 → critical/major/minor/info)
- `version()`: parses `phpmd --version` output
- `run_l3a()`: orchestrates with 6 default rulesets (cleancode,codesize,controversial,design,naming,unusedcode), 300s timeout
- Verify: PASS (import + issubclass(ToolAdapter) + parse canned JSON with violations)

Expected Response: ACK
