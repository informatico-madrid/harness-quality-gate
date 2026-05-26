---
spec: php-support
basePath: specs/php-support
phase: requirements
schema_version: 2
updated: 2026-05-25
---

# Requirements: php-support

## Goal

Deliver a single `harness-quality-gate` skill installation that, with zero
manual configuration, drives the same five-layer quality gate
(L3A → L1 → L2 → L3B → L4) against Python projects, PHP projects, and hybrid
Python+PHP repositories. The skill auto-detects the project language at
invocation time, dispatches to per-language tool adapters (Python keeps its
current toolchain; PHP gets PHPStan + Psalm-taint + PHPUnit + PCOV + Infection
+ Deptrac + shipmonk + composer-audit + nikic/PHP-Parser visitors), enforces
Infection `minMsi: 100` AND `minCoveredMsi: 100` as a HARD gate paired with a
**Justified-Ignore Allow-List** governance policy, and emits a single
checkpoint JSON v2 contract with a `language` field (plus `per_language`
sub-blocks for hybrid repos) so autonomous Claude agents inside Ralph spec
loops can self-verify identically regardless of language. Backward
compatibility is explicitly NOT a requirement (zero existing users): the port
ships as a clean v2.0.0 with restructured config schema, `${CLAUDE_SKILL_DIR}`
placeholder, and `runner.py` subcommand surface.

## Personas

| Persona | Description | Primary need |
|---------|-------------|--------------|
| **Autonomous Claude agent** (spec-executor, reviewer, qa-engineer in Ralph loops) | LLM agent running inside `/ralphharness:implement` that invokes the skill to self-verify code changes before claiming PASS. | Deterministic checkpoint JSON it can `json.loads` and branch on without re-detecting language. |
| **Human developer (local)** | Engineer running the skill locally before pushing — Python, PHP, or polyglot codebases. | Fast incremental feedback (`--git-diff-lines`), clear remediation messages, Spanish-language doctor output. |
| **CI pipeline** | GitHub Actions / GitLab CI matrix job invoking the skill as a quality gate before merge. | Exit codes, stable JSON contract, no hidden network calls, reproducible runs. |
| **Skill maintainer** | Future contributor adding a third language (TS, Go, Rust) or upgrading a pinned tool version. | Clean adapter ABC seam, dual-profile config schema, isolated per-language adapter packages. |
| **Spec-reviewer agent** | LLM agent that diff-audits Infection ignores between iterations to detect cheating. | `ignored_count` / `ignored_delta` tracked in checkpoint; deterministic `audit_ignores` subcommand. |

---

## User Stories

### US-1: Auto-detect language from manifest signals

**As an** autonomous Claude agent invoking the skill on an unknown repo
**I want** the skill to determine whether the repo is Python, PHP, hybrid, or
unsupported using deterministic manifest + source-count heuristics
**So that** I do not need to read `composer.json` / `pyproject.toml` myself or
re-derive language on every invocation.

**Acceptance Criteria (Gherkin):**
- **Given** a repo containing `pyproject.toml` and `*.py` source files only,
  **When** `runner.py detect <repo>` runs,
  **Then** the output JSON MUST contain `{"primary": "python", "confidence": >= 0.9}`
  AND `signals[]` MUST include `"python manifests: ['pyproject.toml']"`.
- **Given** a repo containing `composer.json`, `composer.lock`, `phpunit.xml`
  and only `*.php` source files,
  **When** detection runs,
  **Then** the output JSON MUST contain `{"primary": "php", "confidence": >= 0.9}`.
- **Given** a repo containing BOTH manifests with comparable source-file
  counts (within 2× of each other after excluding `vendor/`, `node_modules/`,
  `.venv/`, `__pycache__/`, `dist/`, `build/`, `_quality-gate/`),
  **When** detection runs,
  **Then** `primary` MUST equal `"hybrid"` AND `confidence` MUST be `>= 0.6`.
- **Given** a repo with a `.quality-gate-lang` file containing `php`,
  **When** detection runs,
  **Then** `primary` MUST equal `"php"` AND `confidence` MUST equal `1.0`
  AND `signals[]` MUST include the override token, regardless of any other
  manifest evidence.
- **Given** an empty repo with no Python or PHP signals,
  **When** detection runs,
  **Then** `primary` MUST be `null` AND the runner MUST exit with code `2`
  (UNSUPPORTED), NOT code `1` (FAIL).

---

### US-2: Persist detection result to disk for re-use

**As a** developer running the skill repeatedly in the same repo
**I want** detection to run once and cache the result
**So that** subsequent invocations skip the file-walk and complete L3A in
under 60 seconds on a 5k-LoC repo.

**Acceptance Criteria:**
- **Given** detection has run once and written `_quality-gate/detection.json`,
  **When** `runner.py <layer> <repo>` is invoked again within the same git
  HEAD,
  **Then** the runner MUST read the cached `detection.json` and MUST NOT
  re-walk the source tree (verified by absence of `os.walk` calls in a
  traced run).
- **Given** the cached `detection.json` exists but `composer.json` was added
  or removed since the cache was written (mtime newer than `detection.json`),
  **When** the runner is invoked,
  **Then** detection MUST be re-run automatically and `detection.json`
  rewritten.
- **Given** the user wants to force re-detection,
  **When** `runner.py detect <repo> --force` is invoked,
  **Then** the cache MUST be discarded and detection MUST run from scratch.

---

### US-3: Dispatch L3A (smoke layer) to the right language adapter

**As an** autonomous agent running L3A on a PHP project
**I want** the skill to invoke `php-cs-fixer --dry-run`, `phpstan analyse
--level=max`, PHP custom-header check, PHP SOLID Tier A visitors, PHP
principles checker (PHPCPD + PHPMD + custom visitor), and PHP antipattern
Tier A (PHPMD rulesets + nikic visitors)
**So that** I get equivalent feedback to a Python project running ruff +
pyright + AST checks.

**Acceptance Criteria:**
- **Given** a PHP repo,
  **When** `runner.py layer3a <repo>` is invoked,
  **Then** the following commands MUST be executed in order (each with its
  own subprocess timeout): PHPStan, PHP-CS-Fixer (dry-run), PHPMD,
  custom-visitor batch.
- **Given** a Python repo,
  **When** `runner.py layer3a <repo>` is invoked,
  **Then** ruff + pyright + existing Python AST visitors MUST run AND zero
  PHP tools MUST be invoked (verified by traced subprocess inventory).
- **Given** a layer3a run on a PHP repo with at least one PHPStan error,
  **When** the layer completes,
  **Then** the checkpoint JSON `layer3_code_quality.tier_a.typecheck.PASS`
  MUST equal `false` AND `tool` MUST equal `"phpstan"` AND `level` MUST
  equal `"max"`.

---

### US-4: Enforce Infection 100/100 as a HARD gate

**As a** product owner of the quality gate
**I want** Infection to fail the build whenever MSI < 100 OR Covered MSI < 100
**So that** there is no tolerated mutation gap — every surviving mutant is
either killed by a new test or formally justified.

**Acceptance Criteria:**
- **Given** an `infection.json5` generated by the configurator,
  **When** the file is parsed,
  **Then** it MUST contain `"minMsi": 100`, `"minCoveredMsi": 100`,
  `"timeoutsAsEscaped": true`, AND `"maxTimeouts": 0`.
- **Given** an Infection run produces `stats.msi = 99.8`,
  **When** the L1 layer evaluates the JSON log,
  **Then** `layer1_test_execution.PASS` MUST equal `false` AND the runner
  process MUST exit with non-zero status.
- **Given** an Infection run produces `stats.msi = 100 AND stats.coveredMsi = 100`
  AND zero escaped mutants AND zero timeouts AND zero errored mutants,
  **When** the L1 layer evaluates the JSON log,
  **Then** `layer1_test_execution.PASS` MUST equal `true`.
- **Given** the user attempts to override the threshold via a project-local
  config file,
  **When** the runner parses the merged config,
  **Then** any local override that LOWERS `minMsi` or `minCoveredMsi` below
  `100` MUST be rejected with a clear error message in the doctor output
  (Spanish: "Umbral de MSI no puede bajar de 100 — revise política") unless
  the user passes `--allow-ramp` explicitly AND the override is scoped to a
  module path (`infection.json5.local` per-module is the only allowed escape
  valve, per research §5.2).

---

### US-5: Govern Infection ignores via Justified-Ignore Allow-List

**As a** spec-reviewer agent auditing iteration N+1 against iteration N
**I want** every newly-added `@infection-ignore-all` annotation, every
`mutators.*.ignore` entry, every `global-ignore` entry, and every
`source.excludes` entry to carry adjacent `reason:` / `proven-by:` /
`audited:` metadata
**So that** agents cannot silently game 100/100 by burying ignores in code
or config.

**Acceptance Criteria:**
- **Given** a PHP source file containing `@infection-ignore-all` without an
  adjacent doc-comment carrying `reason:` AND `audited:` (date in ISO 8601
  + reviewer handle) within the 5 lines preceding the annotation,
  **When** `runner.py audit-ignores <repo>` runs,
  **Then** the runner MUST exit non-zero AND list the offending file + line
  in `findings[]`.
- **Given** an `infection.json5` containing a `global-ignore` entry without
  a JSON5 comment line directly above it carrying `reason:` AND `audited:`,
  **When** `audit-ignores` runs,
  **Then** the runner MUST exit non-zero.
- **Given** iteration N had 5 justified ignores and iteration N+1 has 7
  ignores where the 2 new ones lack `proven-by:`,
  **When** the reviewer-agent invokes `audit-ignores --diff-from <ref>`,
  **Then** `ignored_delta` MUST equal `+2` AND `unjustified_new[]` MUST list
  the 2 file:line pairs AND exit code MUST be non-zero.
- **Given** the checkpoint JSON is written after L1,
  **When** the JSON is parsed,
  **Then** `layer1_test_execution.tool_specific.infection.ignored_count` AND
  `.ignored_delta` MUST be integers (NOT strings, NOT null).

---

### US-6: Run PHPUnit with mandatory strict mode

**As an** agent expecting test results to be trustworthy
**I want** PHPUnit to be configured with every strict-mode + fail-on-* flag
enabled
**So that** "PASS" actually means "every test asserted something, no
deprecations, no warnings, no risky behavior, no incomplete tests".

**Acceptance Criteria:**
- **Given** the configurator generates a `phpunit.xml` stub,
  **When** the file is parsed,
  **Then** the root `<phpunit>` element MUST set: `requireCoverageMetadata="true"`,
  `beStrictAboutCoverageMetadata="true"`, `beStrictAboutTestsThatDoNotTestAnything="true"`,
  `failOnRisky="true"`, `failOnWarning="true"`, `failOnIncomplete="true"`,
  `failOnDeprecation="true"`, `failOnPhpunitDeprecation="true"`,
  `beStrictAboutOutputDuringTests="true"`, `beStrictAboutChangesToGlobalState="true"`,
  `disableCodeCoverageIgnoreAnnotations="true"`.
- **Given** the `<coverage>` element exists in the generated `phpunit.xml`,
  **When** parsed,
  **Then** it MUST contain `pathCoverage="false"` (because L1 uses PCOV which
  does not support path coverage).
- **Given** a project has a hand-written `phpunit.xml` that omits any of the
  required strict-mode flags,
  **When** `runner.py doctor <repo>` runs,
  **Then** the doctor output MUST flag each missing attribute as a WARNING
  with a one-line remediation (Spanish copy).

---

### US-7: Switch test runner to Pest when project opts in

**As a** Laravel developer who prefers Pest over PHPUnit
**I want** the skill to auto-switch to Pest when my `composer.json` requires
both `pestphp/pest` AND `pestphp/pest-plugin-mutate`
**So that** I do not have to maintain a parallel PHPUnit configuration just
to satisfy the gate.

**Acceptance Criteria:**
- **Given** a PHP repo whose `composer.json` `require-dev` keys include both
  `pestphp/pest` AND `pestphp/pest-plugin-mutate`,
  **When** detection runs,
  **Then** `language_profiles.php.tools.test.primary` MUST be set to
  `"pest"` AND L1 dispatcher MUST invoke `vendor/bin/pest --coverage`.
- **Given** a PHP repo with `pestphp/pest` but WITHOUT
  `pestphp/pest-plugin-mutate`,
  **When** detection runs,
  **Then** the doctor MUST emit a WARNING explaining that Pest is detected
  but mutation-testing integration is missing, AND the runner MUST fall back
  to PHPUnit (because Infection 100/100 enforcement requires the mutate
  plugin for Pest).
- **Given** a PHP repo without any Pest dependency,
  **When** detection runs,
  **Then** PHPUnit MUST be selected as the primary test runner.

---

### US-8: Validate hexagonal architecture with Deptrac

**As a** developer practicing hexagonal / clean architecture in PHP
**I want** the skill's L3B layer to fail when Domain layer imports from
Infrastructure (or any other declared boundary violation)
**So that** architectural drift is caught at quality-gate time, not at
human-review time.

**Acceptance Criteria:**
- **Given** the configurator detects PHP AND finds a `deptrac.yaml` in the
  repo root,
  **When** `runner.py layer3b <repo>` is invoked,
  **Then** `deptrac analyse --formatter=json --output=...` MUST be executed
  AND its JSON output MUST be parsed into the checkpoint
  `layer3_code_quality.tier_a.architecture` block.
- **Given** the repo has no `deptrac.yaml`,
  **When** the configurator runs with `--generate-stubs`,
  **Then** a starter `deptrac.yaml` with `Domain / Application / Infrastructure
  / UI` layers MUST be written AND the user MUST be prompted (or, in agent
  mode, auto-accepted) before overwriting.
- **Given** Deptrac reports 3 layer violations + 2 uncovered classes,
  **When** L3B completes,
  **Then** `checkpoint.layer3_code_quality.tier_a.architecture.violations`
  MUST equal `3` AND `.uncovered_classes` MUST equal `2` AND
  `architecture.PASS` MUST equal `false`.

---

### US-9: Run PHP security scanning with Psalm taint + composer audit

**As a** security-conscious developer
**I want** the L4 layer for PHP to run Psalm in taint-analysis mode,
`composer audit`, `local-php-security-checker`, `roave/security-advisories`
checks, Semgrep with PHP/OWASP rulesets, plus shared tools (gitleaks,
checkov, trivy)
**So that** I get equivalent OR stronger coverage than the Python bandit +
safety + semgrep + deptry + vulture stack.

**Acceptance Criteria:**
- **Given** a PHP repo with at least one tainted-input → sink path
  (e.g., `$_GET['x']` flowing unsanitized into a `mysqli::query` call),
  **When** L4 runs,
  **Then** Psalm taint analysis MUST report at least one `TaintedSql`
  finding in the checkpoint `layer4_security_defense.findings[]`.
- **Given** the repo's `composer.lock` references a package with a published
  CVE in the FriendsOfPHP advisories database,
  **When** L4 runs,
  **Then** `composer audit --format=json` MUST report it AND the finding
  MUST appear in the checkpoint with CWE/CVE identifier preserved.
- **Given** the PHP runtime exposes `roave/security-advisories` as a dev
  dependency,
  **When** the configurator runs,
  **Then** the doctor MUST verify presence AND warn if missing (preventive
  constraint blocks install of vulnerable versions).
- **Given** Psalm is unavailable (not in `vendor/bin/`, no PHAR found),
  **When** L4 runs,
  **Then** the runner MUST exit `INFRA_INCOMPLETE` (NOT FAIL) AND the
  checkpoint `tools_skipped[]` MUST include `"psalm"`.

---

### US-10: Emit a single checkpoint JSON v2 contract for both languages

**As an** autonomous agent verifying its own work
**I want** one JSON schema with a top-level `language` field and per-layer
`language` denormalization
**So that** I can `json.loads(open("…/quality-gate-latest.json").read())`
and branch on `data["language"]` without parsing tool-specific output.

**Acceptance Criteria:**
- **Given** a successful run on a Python repo,
  **When** the checkpoint is written,
  **Then** the JSON MUST contain `"schema_version": "2.0.0"`,
  `"language": "python"`, `"languages_detected": ["python"]`,
  `"runtime.python_version"`, AND `"runtime.tool_versions"`.
- **Given** a successful run on a PHP repo,
  **When** the checkpoint is written,
  **Then** the JSON MUST contain `"language": "php"`,
  `"languages_detected": ["php"]`, `"runtime.php_version"`,
  `"runtime.composer_version"` (if composer present), AND
  `runtime.tool_versions` MUST include `phpunit`, `phpstan`, `infection`,
  `psalm`, `deptrac` keys (each a SemVer string).
- **Given** a successful run on a hybrid repo,
  **When** the checkpoint is written,
  **Then** `"language": "hybrid"` MUST be set AND each layer block MUST
  contain a `per_language: {"python": {...}, "php": {...}}` sub-block with
  identical schema to the single-language layer block.
- **Given** the v2 schema document `references/verdict-schema.md`,
  **When** the checkpoint is validated against it,
  **Then** validation MUST pass (every field present + correctly typed) AND
  any consumer relying on schema_version 2.x MUST never see a removed or
  renamed field within the 2.x line.

---

### US-11: Provide a doctor subcommand for runtime + tool diagnosis

**As a** developer hitting an "unknown error" on first invocation in a PHP
repo
**I want** `runner.py doctor <repo>` to tell me exactly which runtimes and
tools are missing and how to install them
**So that** I am not left guessing whether PHP, Composer, Infection, or PCOV
is the bottleneck.

**Acceptance Criteria:**
- **Given** a repo detected as PHP,
  **When** `runner.py doctor <repo>` runs,
  **Then** the output MUST list each required runtime (`php`, `composer`)
  and each required tool (`phpunit`, `phpstan`, `infection`, `psalm`,
  `deptrac`, `pcov`) with version + path or "NOT FOUND" + install
  instruction (Spanish copy).
- **Given** `php` is present on PATH but `composer` is absent,
  **When** doctor runs,
  **Then** the verdict MUST be `INFRA_INCOMPLETE` (NOT FAIL) AND the
  recommended remediation MUST be to install Composer OR to use the PHAR
  fallback via `install_php_tools.sh`.
- **Given** PCOV and Xdebug are both enabled in php.ini,
  **When** doctor runs,
  **Then** a WARNING MUST be emitted recommending Xdebug be disabled for
  Infection runs (per research §6.3).
- **Given** an autonomous agent calls doctor with `--json`,
  **When** doctor runs,
  **Then** the output MUST be valid JSON parseable by `json.loads` with
  keys `verdict`, `runtimes[]`, `tools[]`, `warnings[]`, `remediation[]`.

---

### US-12: Install PHP tools deterministically with pinned versions

**As a** skill operator on a fresh CI runner with no global PHP tools
**I want** a bootstrap script that installs each required PHP tool to a
known location at a pinned version
**So that** the gate result is reproducible across machines and the skill
does not silently regress when an upstream tool changes behavior.

**Acceptance Criteria:**
- **Given** the file `config/php-tool-versions.json` exists,
  **When** parsed,
  **Then** it MUST be a JSON object whose keys include `phpunit`, `phpstan`,
  `infection`, `psalm`, `deptrac`, `php-cs-fixer`, `phpmd` AND whose values
  MUST be pinned SemVer strings (no `latest`, no `^`, no `~` ranges).
- **Given** a repo with `composer` available on PATH,
  **When** `runner.py install-tools <repo>` runs,
  **Then** `composer require --dev` MUST be invoked with each pinned version
  AND tools MUST land in `<repo>/vendor/bin/`.
- **Given** a repo with `php` on PATH but `composer` absent,
  **When** `install-tools` runs,
  **Then** PHARs MUST be downloaded from official upstream URLs to
  `${CLAUDE_SKILL_DIR}/bin/` AND each download MUST be checksum-verified
  against a SHA-256 declared in `config/php-tool-versions.json` AND the
  runner MUST exit non-zero if any checksum mismatches.
- **Given** an offline environment with no network access,
  **When** `install-tools` runs,
  **Then** the runner MUST fail with a clear error message identifying the
  first tool whose download failed (NOT silently fall through to NOT
  FOUND).

---

### US-13: Support hybrid Python+PHP repos in parallel

**As an** owner of a polyglot monorepo (Symfony backend + Python data
pipeline)
**I want** the skill to run both Python and PHP gates against my repo and
aggregate results into one checkpoint
**So that** my single CI step covers the whole codebase without me wiring
two skills.

**Acceptance Criteria:**
- **Given** a hybrid repo detected as `primary: hybrid`,
  **When** `runner.py all <repo>` is invoked,
  **Then** Python and PHP adapters MUST be executed in parallel (process
  pool, not sequentially) AND wall-clock for the run MUST equal
  `max(python_runtime, php_runtime) + overhead < 10s`.
- **Given** a hybrid run completes,
  **When** the checkpoint is written,
  **Then** every layer block MUST contain `per_language.python` AND
  `per_language.php` sub-blocks AND the top-level `overall_pass` MUST equal
  `python.PASS && php.PASS` (logical AND).
- **Given** one language gate fails and the other passes,
  **When** the checkpoint is written,
  **Then** `overall_pass` MUST equal `false` AND `per_language[failing].PASS`
  MUST equal `false` AND `per_language[passing].PASS` MUST equal `true`
  (no cross-contamination).
- **Given** the user wants to limit a hybrid run to one language,
  **When** `runner.py all <repo> --only python` is invoked,
  **Then** PHP adapters MUST NOT execute AND the checkpoint MUST contain
  only `per_language.python`.

---

### US-14: Auto-load framework-conditional rule packs

**As a** Symfony developer
**I want** PHPStan to load `phpstan/phpstan-symfony` automatically when my
`composer.json` requires `symfony/framework-bundle`
**So that** the skill understands Symfony container types, service IDs, and
controller signatures without me editing config.

**Acceptance Criteria:**
- **Given** a repo whose `composer.json` `require` contains
  `symfony/framework-bundle`,
  **When** the configurator generates the PHPStan config,
  **Then** the generated config MUST include `phpstan/phpstan-symfony` in
  the `includes` list AND the doctor MUST verify it is installed.
- **Given** a repo whose `composer.json` `require` contains
  `laravel/framework`,
  **When** the configurator runs,
  **Then** `larastan/larastan` MUST be added to the PHPStan includes AND
  Deptrac rule generation MUST include a `Console / Http / Domain` starter
  layer template.
- **Given** a repo whose `composer.json` requires `drupal/core` OR
  `roots/wordpress`,
  **When** the configurator runs,
  **Then** the corresponding framework-aware PHPStan extension MUST be
  included AND `shipmonk/dead-code-detector` MUST be configured with the
  matching framework reflector.
- **Given** a repo with none of the supported framework dependencies
  (framework-agnostic vanilla PHP),
  **When** the configurator runs,
  **Then** only baseline PHPStan rule packs MUST be included (no framework
  extension) AND the gate MUST still operate.

---

### US-15: Surface BMAD (Tier B) judges to PHP via shared prompts

**As an** owner of the BMAD Party-Mode multi-judge consensus engine
**I want** the existing `llm_solid_judge.md` and `antipattern_judge.md`
prompts to remain a single source of truth, augmented with explicit
`## Python examples` and `## PHP examples` sections inside each
**So that** review criteria stay consistent cross-language and there is no
prompt-drift between language forks.

**Acceptance Criteria:**
- **Given** the BMAD prompt file `references/llm_solid_judge.md`,
  **When** read,
  **Then** the file MUST contain an `## Python examples` section AND a
  `## PHP examples` section, each with at least 3 worked examples
  illustrating the same SOLID violation in idiomatic language form
  (traits / interfaces / attributes / readonly for PHP).
- **Given** the dispatcher invokes the SOLID judge on a PHP file,
  **When** the prompt is rendered,
  **Then** the rendered prompt MUST include the language token `"language": "php"`
  in the system message AND the `## PHP examples` section MUST be
  highlighted (e.g., placed before Python in the final prompt) while keeping
  the rubric identical.
- **Given** the same BMAD invocation across two iterations on the same code,
  **When** results are compared,
  **Then** the reviewer rubric (criterion list + severity scale) MUST be
  byte-identical regardless of language.

---

### US-16: Refactor without backward-compat shims

**As a** skill maintainer
**I want** to rename `{skill-root}` → `${CLAUDE_SKILL_DIR}` everywhere with
NO alias, restructure `scripts/*.py` into `runner.py` subcommands, replace
the v1 flat YAML config with v2 dual-profile schema with NO migration
shim, and drop legacy CLI re-exports
**So that** the skill ships as a clean v2.0.0 first release without
inherited tech debt.

**Acceptance Criteria:**
- **Given** the v2 codebase,
  **When** `grep -r "{skill-root}" .` is run across the skill directory,
  **Then** ZERO matches MUST be returned (no aliases, no shims).
- **Given** the v2 codebase,
  **When** the `scripts/` directory is listed,
  **Then** `runner.py`, `detector.py`, `dispatcher.py`, `doctor.py`,
  `configurator.py`, `install_php_tools.sh`, `audit_ignores.py`, and
  the `shared/`, `adapters/python/`, `adapters/php/` subdirs MUST exist AND
  `legacy_shims/` MUST NOT exist.
- **Given** a v1-style flat config (no `schema_version` key),
  **When** the runner loads it,
  **Then** the runner MUST exit with a clear error message
  (Spanish: "Esquema v1 ya no soportado. v2.0.0 es la primera versión
  pública") AND MUST NOT attempt auto-migration.
- **Given** the repo,
  **When** `find . -name "MIGRATION.md"` is run,
  **Then** no file MUST be returned (no migration documentation required
  per interview decision).

---

### US-17: Provide PHP-aware weak-test detection (L2)

**As a** reviewer enforcing test quality
**I want** the L2 weak-test detector to flag PHP-specific anti-patterns:
zero-assertion tests, tests that only `assertInstanceOf` after `new`, tests
that mock their own SUT class, `expectException(Throwable::class)` /
`expectException(Exception::class)`, and `markTestSkipped` / `markTestIncomplete`
**So that** "100% coverage + 100% MSI" cannot be faked via hollow tests.

**Acceptance Criteria:**
- **Given** a PHP test file containing a `function testFoo()` body with zero
  `$this->assert*()` or `expect*()` calls,
  **When** L2 runs,
  **Then** the test MUST be flagged in `layer2_test_quality.weak_tests[]`
  with rule code `A1`.
- **Given** a PHP test where the test class uses `createMock(FooService::class)`
  AND the production code under test is `FooService`,
  **When** L2 runs,
  **Then** the test MUST be flagged with rule code `A3` (SUT mocked).
- **Given** a PHP test calling `$this->expectException(\Throwable::class)`
  OR `\Exception::class`,
  **When** L2 runs,
  **Then** the test MUST be flagged with rule code `A4` (overly-broad
  exception assertion).
- **Given** a Python repo,
  **When** L2 runs,
  **Then** the existing Python weak-test rules MUST execute unchanged
  (no regression).

---

### US-18: Spanish-language end-user messages

**As a** Spanish-speaking developer (primary user persona)
**I want** all doctor output, configurator prompts, and runner error
messages to be in Spanish
**So that** I can act on them without translation overhead.

**Acceptance Criteria:**
- **Given** any error message emitted by `runner.py`, `doctor.py`, or
  `configurator.py`,
  **When** the message is rendered to stdout/stderr,
  **Then** the message MUST be in Spanish (canonical examples: "Umbral
  de MSI no puede bajar de 100", "Esquema v1 ya no soportado",
  "Herramienta PHP no encontrada — ejecute install-tools").
- **Given** the requirements / design / config schema files in
  `${CLAUDE_SKILL_DIR}/`,
  **When** inspected,
  **Then** they MUST remain in English (tooling consistency — JSON keys,
  YAML keys, code identifiers all English).
- **Given** the BMAD Party-Mode judges produce a verdict,
  **When** the verdict is surfaced in the checkpoint,
  **Then** the human-readable `summary` field MAY be in Spanish but the
  structured fields (`severity`, `rule_code`, `file`, `line`, `confidence`)
  MUST remain English / canonical identifiers.

---

## Functional Requirements

| ID | Requirement | Priority | Maps to US |
|----|-------------|----------|-----------|
| FR-1 | The system MUST auto-detect project language via `scripts/detector.py` using Tier 1 (`.quality-gate-lang` override) → Tier 2 (manifest presence) → Tier 3 (source-file count tie-breaker), per research §2.3. | MUST | US-1 |
| FR-2 | Detection MUST exclude `.git`, `node_modules`, `vendor`, `.venv`, `venv`, `__pycache__`, `dist`, `build`, `.tox`, `_quality-gate`, `_bmad-output` when counting source files. | MUST | US-1 |
| FR-3 | Detection result MUST be cached to `_quality-gate/detection.json` AND auto-invalidated when any manifest file mtime exceeds the cache mtime. | MUST | US-2 |
| FR-4 | A `runner.py detect <repo> [--force] [--json]` CLI subcommand MUST exist returning the detection result. | MUST | US-1, US-2 |
| FR-5 | The dispatcher MUST route each layer invocation to `adapters/python/*` OR `adapters/php/*` based on the detected language, with zero cross-invocation. | MUST | US-3 |
| FR-6 | All five layers (L3A, L1, L2, L3B, L4) MUST have a PHP adapter implementation that emits the same JSON shape as the Python adapter (modulo per-tool `tool_specific` sub-block). | MUST | US-3, US-8, US-9, US-10 |
| FR-7 | The PHP L3A adapter MUST invoke PHPStan at `level=max` with rule packs `phpstan-strict-rules`, `phpstan-deprecation-rules`, `shipmonk/phpstan-rules`, `ergebnis/phpstan-rules`, `spaze/phpstan-disallowed-calls` (baseline) + framework pack per FR-22. | MUST | US-3 |
| FR-8 | The PHP L3A adapter MUST invoke PHP-CS-Fixer with preset `@PER-CS2.0` in `--dry-run --diff` mode. | MUST | US-3 |
| FR-9 | The PHP L3A adapter MUST invoke PHPMD with rulesets `cleancode, codesize, controversial, design, naming, unusedcode`. | MUST | US-3 |
| FR-10 | The PHP L3A adapter MUST ship and invoke nikic/PHP-Parser custom visitors covering the ~12 Tier A antipatterns PHPMD does not cover (see research §1, "Hot files needing PHP twin"). | MUST | US-3 |
| FR-11 | The PHP L1 adapter MUST select PHPUnit by default AND switch to Pest only when BOTH `pestphp/pest` AND `pestphp/pest-plugin-mutate` are present in `composer.json`. | MUST | US-7 |
| FR-12 | The configurator MUST generate a `phpunit.xml` stub containing all strict-mode flags listed in US-6 AC-1 + `<coverage pathCoverage="false">`. | MUST | US-6 |
| FR-13 | The configurator MUST generate an `infection.json5` containing `minMsi: 100`, `minCoveredMsi: 100`, `timeoutsAsEscaped: true`, `maxTimeouts: 0`, `testFramework` matching FR-11, AND `tmpDir: var/infection`. | MUST | US-4 |
| FR-14 | The L1 adapter MUST hard-fail when Infection `stats.msi < 100` OR `stats.coveredMsi < 100` OR `stats.escaped > 0` OR `stats.errored > 0` OR `stats.timedOut > 0`. | MUST | US-4 |
| FR-15 | The skill MUST forbid lowering `minMsi` or `minCoveredMsi` below 100 in any config file UNLESS the override is per-module via `infection.json5.local` AND the user passes `--allow-ramp`. | MUST | US-4 |
| FR-16 | A `runner.py audit-ignores <repo> [--diff-from <git-ref>]` subcommand MUST exist that validates Justified-Ignore Allow-List metadata on every `@infection-ignore-all` annotation AND every `mutators.*.ignore` / `global-ignore` / `source.excludes` entry. | MUST | US-5 |
| FR-17 | The Justified-Ignore metadata schema MUST require: `reason:` (free-text, non-empty), `proven-by:` (optional, test path), `audited:` (ISO 8601 date + reviewer handle, both non-empty). | MUST | US-5 |
| FR-18 | The checkpoint JSON `layer1_test_execution.tool_specific.infection` block MUST include integer fields `killed`, `escaped`, `errored`, `timed_out`, `not_covered`, `ignored_count`, `ignored_delta`. | MUST | US-5, US-10 |
| FR-19 | The L3B adapter MUST invoke Deptrac with `--formatter=json` AND parse violations + uncovered classes into `layer3_code_quality.tier_a.architecture`. | MUST | US-8 |
| FR-20 | The configurator's `--generate-stubs` mode MUST produce a starter `deptrac.yaml` with layers `Domain / Application / Infrastructure / UI` matching research §4.1. | MUST | US-8 |
| FR-21 | The L4 PHP adapter MUST invoke Psalm with `--taint-analysis`, `composer audit --format=json --no-dev`, `local-php-security-checker`, Semgrep with rulesets `p/php + p/phpcs-security-audit + p/owasp-top-ten + ${CLAUDE_SKILL_DIR}/references/semgrep-php-rules.yaml`, shared tools (gitleaks, checkov, trivy), `shipmonk/dead-code-detector`, AND `shipmonk/composer-dependency-analyser`. | MUST | US-9 |
| FR-22 | The configurator MUST detect Symfony / Laravel / Drupal / WordPress / framework-agnostic via `composer.json` require keys AND conditionally add the corresponding PHPStan extension (`phpstan-symfony`, `larastan`, drupal extension, WordPress extension) to the generated PHPStan config. | MUST | US-14 |
| FR-23 | The configurator MUST verify presence of `roave/security-advisories` in `composer.json` dev dependencies AND emit a doctor WARNING if absent. | SHOULD | US-9 |
| FR-24 | The checkpoint JSON MUST include top-level `language`, `languages_detected[]`, `detection_signals[]`, `runtime` (with `harness_skill_version`, `python_version` if Python adapter ran, `php_version` if PHP adapter ran, `composer_version` if composer present, `tool_versions{}`), AND `schema_version: "2.0.0"`. | MUST | US-10 |
| FR-25 | For hybrid runs, every layer block MUST contain a `per_language: {"python": {...}, "php": {...}}` sub-block carrying the identical schema to the single-language layer block. | MUST | US-13 |
| FR-26 | A `runner.py doctor <repo> [--json]` subcommand MUST exist that verifies runtime (php / composer / python) presence + version + path AND each required tool's presence + version + install instruction. | MUST | US-11 |
| FR-27 | The doctor MUST emit verdict `INFRA_INCOMPLETE` (distinct from `FAIL`) when required runtimes or tools are missing, AND the runner MUST exit with code 3 for INFRA_INCOMPLETE (distinct from 1=FAIL, 2=UNSUPPORTED, 0=PASS). | MUST | US-11 |
| FR-28 | The doctor MUST detect PCOV + Xdebug both enabled AND emit a WARNING recommending Xdebug be disabled during Infection runs. | SHOULD | US-11 |
| FR-29 | A `config/php-tool-versions.json` file MUST exist with pinned SemVer versions for `phpunit`, `phpstan`, `infection`, `psalm`, `deptrac`, `php-cs-fixer`, `phpmd` AND a SHA-256 checksum per PHAR. | MUST | US-12 |
| FR-30 | An `install_php_tools.sh` (or `runner.py install-tools` subcommand) MUST install via `composer require --dev` when composer is on PATH, OR download PHARs to `${CLAUDE_SKILL_DIR}/bin/` with checksum verification when only `php` is on PATH. | MUST | US-12 |
| FR-31 | Tool discovery order MUST be: `<repo>/vendor/bin/<tool>` → `${COMPOSER_HOME:-~/.composer}/vendor/bin/<tool>` → `which <tool>` → `${CLAUDE_SKILL_DIR}/bin/<tool>.phar` → NOT FOUND. | MUST | US-11, US-12 |
| FR-32 | The skill MUST use `${CLAUDE_SKILL_DIR}` everywhere AND MUST NOT contain any `{skill-root}` placeholder (no alias, no shim). | MUST | US-16 |
| FR-33 | The skill MUST NOT include any `MIGRATION.md`, `legacy_shims/`, or v1-config auto-migration code path. | MUST | US-16 |
| FR-34 | Loading a v1-style flat config MUST emit a clear Spanish-language error message AND exit non-zero. | MUST | US-16 |
| FR-35 | The L2 weak-test detector MUST implement PHP rules A1 (zero-assertion), A3 (SUT-mocked), A4 (overly-broad exception), A5 (`markTestSkipped`/`markTestIncomplete`), A6 (`@codeCoverageIgnore` spam), A7 (only-constructor-+-instanceof), A8 (assertion on tautology) via shared rule engine + PHP-Parser visitor strategy. | MUST | US-17 |
| FR-36 | The BMAD prompts `references/llm_solid_judge.md` AND `references/antipattern_judge.md` MUST contain explicit `## Python examples` AND `## PHP examples` sections each with ≥3 worked examples. | MUST | US-15 |
| FR-37 | The BMAD dispatcher MUST inject the detected `language` into the prompt system message AND must keep the rubric byte-identical across languages. | MUST | US-15 |
| FR-38 | All end-user-facing messages (doctor output, configurator prompts, runner error messages) MUST be in Spanish; all code identifiers, JSON keys, YAML keys, file paths, and rule codes MUST remain in English. | MUST | US-18 |
| FR-39 | The skill MUST cache the language-detection result to `.quality-gate-lang.cache` (separate from `_quality-gate/detection.json`) for runtime-fast re-reads, scoped to git HEAD. | SHOULD | US-2 |
| FR-40 | Config schema v2 MUST follow the dual-profile structure: top-level `gates`, `language_profiles.python`, `language_profiles.php`, `shared_tools`, `layer4` (per research §3). | MUST | US-3, US-10 |
| FR-41 | For Python projects, ZERO PHP tool MUST be invoked AND zero PHP runtime check MUST fire. | MUST | US-1, US-13 |
| FR-42 | For PHP projects, ZERO Python tool (other than the orchestrator itself) MUST be invoked. | MUST | US-1, US-13 |
| FR-43 | The runner MUST expose subcommands: `detect`, `doctor`, `install-tools`, `audit-ignores`, `configure`, `layer3a`, `layer1`, `layer2`, `layer3b`, `layer4`, `all`, `checkpoint`. | MUST | US-1..US-13 |
| FR-44 | The PHP adapters MUST use `subprocess.run` with explicit per-tool timeouts (default 300s; configurable per layer in `gates.timeouts`). | SHOULD | US-3, US-9 |
| FR-45 | All PHAR downloads MUST verify against SHA-256 declared in `config/php-tool-versions.json` AND MUST exit non-zero on mismatch (security baseline). | MUST | US-12 |

---

## Non-Functional Requirements

| ID | Requirement | Target / Metric |
|----|-------------|------------------|
| NFR-1 | L3A smoke layer (Python OR PHP) MUST complete within 60 seconds on a 5,000-LoC repo with cached detection. | Wall-clock measured by `runner.py`, logged in checkpoint `layer3_code_quality.tier_a.duration_seconds`. |
| NFR-2 | Detection (cold cache) MUST complete within 2 seconds on a 50,000-file repo (excluding `EXCLUDE_DIRS`). | Wall-clock measured in `detector.py`. |
| NFR-3 | Detection cache hit rate MUST exceed 95% after the first invocation in the same repo, given no manifest mtime changes. | Log analysis over rolling 100 invocations in fixture-test CI. |
| NFR-4 | Skill installation footprint MUST be under 100 MB (excluding tools installed into the target project's `vendor/`). | `du -sh ${CLAUDE_SKILL_DIR}` in CI. |
| NFR-5 | Checkpoint JSON v2 schema MUST be additively backward-stable across all patch + minor versions (no field removed, no field renamed within the 2.x line). | Schema-diff linter in CI; v2.x → v2.y must add-only. |
| NFR-6 | For a hybrid run, total wall-clock MUST equal `max(python_runtime, php_runtime) + parallelism_overhead < 10s`. | Wall-clock measured by `runner.py all`. |
| NFR-7 | Infection 100/100 enforcement MUST be deterministic — same input + same tool versions MUST produce identical `killed/escaped/errored/timed_out/not_covered` counts across two consecutive runs. | Fixture-test in CI with `php-pure-pass` fixture; assert byte-identical `infection-log.json` after `jq`-normalize. |
| NFR-8 | PHAR download fallback MUST verify SHA-256 checksums declared in `config/php-tool-versions.json`; mismatched downloads MUST exit non-zero AND MUST NOT leave a partial PHAR on disk. | Security test: corrupt a downloaded PHAR + re-run; assert non-zero exit + no orphaned `.phar` file. |
| NFR-9 | The doctor subcommand MUST complete within 5 seconds on a fresh CI runner (no caches). | Wall-clock measured in CI. |
| NFR-10 | The skill MUST function on a Claude Code runtime where only embedded Bun is guaranteed; the doctor MUST report INFRA_INCOMPLETE for missing `python`, `php`, OR `composer` rather than crashing. | Fixture test `python-no-runtime/` + `php-no-runtime/` in CI matrix. |
| NFR-11 | All log output MUST be UTF-8 encoded; all Spanish messages MUST render correctly without `mojibake` on `en_US.UTF-8` and `es_ES.UTF-8` locales. | CI locale matrix. |
| NFR-12 | The runner MUST emit zero network calls during `detect`, `layer3a`, `layer1`, `layer2`, `layer3b`, `audit-ignores`, OR `checkpoint`. Network calls are permitted ONLY during `install-tools` (PHAR downloads + composer require) AND L4 security tools that require CVE database queries. | Strace/network-mock test in CI. |
| NFR-13 | All subprocess invocations MUST have explicit timeouts (no unbounded `subprocess.run`). Default per-tool timeout is 300 seconds; layer-level rollup timeout is 1800 seconds. | Code-review checklist + lint rule. |
| NFR-14 | The skill MUST run on Python 3.10+ AND PHP 8.2+; older runtime versions MUST be detected by the doctor with a clear Spanish error message. | Doctor unit test. |
| NFR-15 | The runner exit-code contract: 0 = PASS, 1 = FAIL, 2 = UNSUPPORTED (no detectable language), 3 = INFRA_INCOMPLETE (missing runtime / tool), 4 = CONFIG_INVALID, 5 = INTERNAL_ERROR. | Documented in `references/verdict-schema.md`; verified by exit-code tests in CI. |
| NFR-16 | Checkpoint JSON output MUST validate against a JSON Schema document shipped at `references/verdict-schema.json` (machine-readable, in addition to the markdown reference). | CI validation step. |
| NFR-17 | The PHP custom-visitor batch (nikic/PHP-Parser) MUST handle files up to 5,000 lines without exceeding 512 MB of memory. | Memory-profile fixture test. |
| NFR-18 | Tool-version pin in `config/php-tool-versions.json` MUST be a strict SemVer (no `latest`, no `^`, no `~`, no `>=`). | JSON-schema validator on `php-tool-versions.json`. |
| NFR-19 | The Infection-100/100 mode MUST tolerate runs up to 10,000 mutants within 30 minutes wall-clock on an 8-core runner with PCOV + `--threads=max` + `--git-diff-lines` enabled. | Performance benchmark in CI on `php-medium-fixture/`. |
| NFR-20 | The `audit_ignores` subcommand MUST complete in under 5 seconds on a repo with up to 1,000 `@infection-ignore-all` annotations + 500 `mutators.*.ignore` entries. | Wall-clock test. |

---

## Glossary

- **Tier A** — Deterministic AST-based antipattern detection (no LLM). Python uses `ast` stdlib; PHP uses PHPMD + nikic/PHP-Parser visitors.
- **Tier B** — BMAD Party-Mode multi-judge LLM consensus (Winston, Murat, Amelia agents per research §3, `layer4.party_mode`).
- **BMAD** — "Best Multi-Agent Debate" — the consensus engine running ≥3 LLM judges per finding with N rounds of debate.
- **Justified-Ignore Allow-List** — Governance policy requiring `reason:` / `proven-by:` (optional) / `audited:` (ISO date + reviewer) metadata adjacent to every Infection ignore (annotation OR config entry). Enforced by `audit_ignores` subcommand.
- **MSI** — Mutation Score Indicator. `(killed + timed_out_treated_as_killed) / (killed + escaped + errored + timed_out_treated_as_escaped)` × 100. Infection metric.
- **Covered MSI** — MSI computed only over mutants generated on lines covered by at least one test. Infection metric.
- **PCOV** — `krakjoe/pcov` PHP extension providing fast line-coverage (~2.8–5× faster than Xdebug). No branch or path coverage. Last release 2021; works on PHP 8.4.
- **PHAR** — PHP Archive — single-file distribution format used by PHPUnit, PHPStan, Infection, Psalm, Deptrac, PHP-CS-Fixer, PHPMD as a fallback when Composer is unavailable.
- **Doctor** — Bootstrap subcommand (`runner.py doctor <repo>`) that diagnoses runtime + tool presence and emits INFRA_INCOMPLETE verdict if anything required is missing.
- **Checkpoint JSON v2** — Output contract (schema v2.0.0) consumed by autonomous Claude agents for self-verification. Top-level `language` field + per-layer `language` denormalization + `per_language` sub-blocks for hybrid.
- **L3A / L1 / L2 / L3B / L4** — Five quality-gate layers per `workflow.md`: L3A (smoke: lint + typecheck + AST), L1 (test execution: PHPUnit/pytest + coverage + Infection/mutmut), L2 (test quality: weak-test detection + diversity + mutation kill-map), L3B (deep: SOLID + antipattern Tier B BMAD + architecture/Deptrac), L4 (security defense: taint + CVE + secrets + dep-analysis).
- **Deptrac** — `qossmic/deptrac` standalone PHP binary for declarative YAML-based hexagonal architecture validation. Selected over PHPat per research §4.1.
- **Psalm taint analysis** — Built-in Psalm mode (`--taint-analysis`) that traces tainted input (`$_GET`, `$_POST`, request) through to sinks (SQL, HTML, shell, SSRF). Only mainstream PHP static analyzer with native taint per research §4 + §10.
- **`@PER-CS2.0`** — PHP Evolving Recommendation Coding Standard 2.0 preset for PHP-CS-Fixer.
- **`@infection-ignore-all`** — Inline annotation (PHPDoc comment) above a class / method / property telling Infection to skip mutating it. Must carry Justified-Ignore metadata per FR-17.
- **Hybrid repo** — Repository where the detector returns `primary: hybrid` because both Python and PHP signals are present with comparable strength. Runs both gates in parallel per US-13.
- **`shipmonk/dead-code-detector`** — PHPStan extension; framework-aware (Symfony/Laravel/Doctrine reflection) dead-code finder. Vulture equivalent for PHP per research §1, §4.
- **`shipmonk/composer-dependency-analyser`** — Single-tool replacement for `composer-unused` + `composer-require-checker`; finds unused + shadow + misplaced deps in one pass. Deptry equivalent for PHP per research §4.
- **`roave/security-advisories`** — Composer constraint package that blocks installing versions of dependencies with known CVEs. Preventive, complementary to reactive `composer audit`.
- **`${CLAUDE_SKILL_DIR}`** — Canonical Claude Code skills environment variable per [code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills). Replaces the (non-canonical, broken-on-plugin-install) `{skill-root}` placeholder.
- **Pest** — Modern PHP testing framework built on PHPUnit. Opt-in via `pestphp/pest` + `pestphp/pest-plugin-mutate` per US-7.

---

## Out of Scope (v1)

- TypeScript / JavaScript / Go / Rust / Ruby / Java / .NET language support (future polyglot expansion; only Python + PHP in v2.0.0).
- IDE-extension integration (VSCode, PhpStorm, etc.) — skill-only, no editor protocols.
- Coverage UI / HTML reports beyond what PHPUnit's `<html>` reporter or `pytest-cov` emit natively. No custom dashboard.
- Auto-fixing of violations (PHPMD / PHPCS / Rector auto-fix mode disabled by skill); detection + reporting only. Users may run `--fix` manually outside the skill.
- Cross-language finding deduplication for hybrid repos. Each language reports independently in `per_language` blocks; the same CWE in both Python and PHP files emits TWO separate findings.
- Migration tooling for legacy installs. Zero existing users → no migration code, no `MIGRATION.md`, no v1-config auto-wrap, no `{skill-root}` alias, no `legacy_shims/`.
- Backward compatibility shims of any kind. v2.0.0 is the first public release.
- Auto-installation of Composer or PHP itself. The doctor reports INFRA_INCOMPLETE; the user installs the runtime via their OS package manager.
- Bundling PHARs inside the skill artifact (size + version drift + marketplace update lag). PHARs are downloaded on-demand by `install_php_tools.sh` per research §6.3.
- Cross-skill dependencies (Claude Code does not support them per issue #9444). Single-skill orchestrator only.
- Plugin / marketplace versioning helpers — out of scope for the quality-gate skill itself.
- Roo / `.roomodes` integration updates (research §9 question 9, awaiting user confirmation; not in v2.0.0 unless explicitly added in a follow-up spec).
- Per-mutator `@infection-ignore-for <Mutator>` inline annotation (Infection issue #2291 still open; feature does not exist as a stable API). Use config-file `mutators.*.ignore` instead.
- Per-directory MSI threshold inside a single Infection run (Infection has no native support; emulated via multiple `--filter` runs, but a built-in feature is not in scope).
- Distributed mutation testing (multiple machines). Single-machine `--threads=max` only.
- Web UI / TUI for browsing checkpoint history. JSON files in `_quality-gate/` only.
- Notifications (Slack, email, GitHub PR comments). Exit code + checkpoint JSON only; integrations belong to CI config, not the skill.
- Auto-generation of PHP test scaffolding from production code.
- Refactoring suggestions beyond surfacing findings (no "fix-it" code suggestions in checkpoint).

---

## Dependencies

### Claude Code primitives
- `${CLAUDE_SKILL_DIR}` — canonical skills environment variable.
- Skill tool (invocation surface).
- Bash tool (for runtime subprocess invocations from agent loops if used).
- Embedded Bun runtime (guaranteed; nothing else).

### Required external runtimes
- **Python ≥ 3.10** — orchestrator (`runner.py`, `dispatcher.py`, all `adapters/python/*`, all `shared/*`).
- **PHP ≥ 8.2** — required only for PHP-detected repos; doctor reports INFRA_INCOMPLETE if absent.
- **Composer ≥ 2.5** — optional but recommended; PHAR fallback if absent.

### External Python tools (unchanged from current skill)
- `ruff`, `pytest`, `pyright`, `mutmut`, `bandit`, `safety` / `pip-audit`, `semgrep`, `vulture`, `deptry`, `coverage`.

### External PHP tools (new in v2.0.0)
- **L3A**: `phpstan/phpstan ^2.1` + extensions (`phpstan-strict-rules`, `phpstan-deprecation-rules`, `shipmonk/phpstan-rules`, `ergebnis/phpstan-rules`, `spaze/phpstan-disallowed-calls`); `friendsofphp/php-cs-fixer ^3`; `phpmd/phpmd ^2.15`; `nikic/php-parser ^5`.
- **L1**: `phpunit/phpunit ^11`; `pestphp/pest ^3` (opt-in); `infection/infection ^0.30`; PCOV PHP extension (with Xdebug fallback).
- **L2**: shared analyzer reuses `nikic/php-parser` for AST.
- **L3B**: `qossmic/deptrac ^2` (architecture); `phpstan/phpdoc-parser` (transitively).
- **L4**: `vimeo/psalm ^5` (taint mode); `composer audit` (built into Composer ≥ 2.4); `local-php-security-checker` (standalone binary); `roave/security-advisories` (Composer constraint); `shipmonk/dead-code-detector`; `shipmonk/composer-dependency-analyser`.
- **Framework packs (conditional)**: `phpstan/phpstan-symfony`, `larastan/larastan`, `mglaman/phpstan-drupal`, `szepeviktor/phpstan-wordpress`.

### Cross-cutting shared tools (unchanged)
- `gitleaks`, `checkov`, `trivy`, `semgrep` (language-agnostic; reused across both adapters).

### Build / CI dependencies
- GitHub Actions matrix (or equivalent) supporting Ubuntu + macOS + Windows × Python {3.10, 3.12} × PHP {8.2, 8.3, 8.4} × {with-composer, no-composer}.

---

## Success Metrics

1. **Greenfield PHP smoke**: A fresh `symfony/skeleton` project + tests achieves green-on-all-five-layers checkpoint within 5 wall-clock minutes after running `runner.py install-tools && runner.py all <repo>`.
2. **Infection 100/100 reference**: The skill enforces 100/100 on a known-passing benchmark (`sebastianbergmann/lines-of-code` or equivalent ≤ 1k-LoC library) AND the checkpoint reports `msi: 100, coveredMsi: 100, ignored_count: <small N>`.
3. **Hybrid repo aggregation**: A repo with `apps/api-php/` (Symfony) + `apps/scripts-py/` (Python) produces a valid v2 checkpoint where `per_language.python.PASS` AND `per_language.php.PASS` are both set AND `overall_pass = python.PASS && php.PASS`.
4. **Justified-Ignore zero-false-positive**: `audit_ignores` on a clean repo with all annotations correctly metadata-tagged returns ZERO findings AND exit 0.
5. **Detection determinism**: Running `runner.py detect` 100 times on the same repo with no mtime changes returns byte-identical `detection.json` AND uses the cache after the first invocation.
6. **Doctor accuracy**: On a runner where `php` exists but `composer` and `infection` are absent, doctor MUST report exactly those two as missing AND emit verdict INFRA_INCOMPLETE (exit 3).
7. **Schema stability**: v2.0.1, v2.1.0, … checkpoints validate against the same JSON Schema as v2.0.0 (additive-only changes verified in CI).
8. **Spanish-localization completeness**: A locale audit across `runner.py`, `doctor.py`, `configurator.py`, `install_php_tools.sh` shows 100% of user-facing strings are Spanish (excluding code identifiers / JSON keys / rule codes).
9. **PHAR security**: Corrupting any downloaded PHAR forces non-zero exit AND leaves no orphaned `.phar` on disk.
10. **Performance budget**: L3A < 60s on a 5k-LoC PHP project; full L1+L2+L3B+L4 < 10 minutes on a 5k-LoC PHP project with `--threads=max` AND PCOV.

---

## Open Questions Inherited from Research (Status After Interview)

Research §9 enumerated 15 open questions. Interview resolutions below; remaining unresolved items carry into design.

| # | Question | Status | Resolution / Carry-forward |
|---|----------|:------:|----------------------------|
| 1 | Hybrid repo policy — parallel, require override, or prompt? | RESOLVED | **Parallel** per US-13 / FR-25. Hybrid runs both adapters in parallel; wall-clock = max(python, php). |
| 2 | Infection escape valve — strict 100/100 OR ramp? | RESOLVED | **Strict 100/100 hard gate** + Justified-Ignore Allow-List + per-module `infection.json5.local` ramp ONLY via `--allow-ramp` flag (FR-15). |
| 3 | PHPUnit vs Pest primary? | RESOLVED | **PHPUnit primary**; Pest auto-switch when both `pestphp/pest` AND `pestphp/pest-plugin-mutate` are present (FR-11 / US-7). |
| 4 | Framework-conditional rule packs auto-enabled? | RESOLVED | **Yes** — Symfony, Laravel, Drupal, WordPress, framework-agnostic; conditional PHPStan extension load via composer.json sniff (FR-22 / US-14). |
| 5 | BMAD prompt strategy — two templates, one bilingual, or auto-translate? | RESOLVED | **One shared prompt per judge with `## Python examples` + `## PHP examples` sections inside** (FR-36 / US-15). Variant of (b) "bilingual template". |
| 6 | Coverage engine fallback — silent or loud? | RESOLVED | **Silent fallback to Xdebug** with WARNING in checkpoint (FR-28 / US-11). |
| 7 | Composer global vs project-local precedence? | RESOLVED | **Project-local wins** per FR-31. |
| 8 | Plugin marketplace versioning — new plugin or in-place? | DEFERRED to design | Interview said "ship as v2 first release, no users". Carry decision to design: marketplace plugin name (`harness-quality-gate` vs `harness-quality-gate-v2`) is a release-engineering question, not a requirements question. |
| 9 | Roo / `.roomodes` integration update? | OPEN | Marked "Needs user confirmation" in research. Interview did not address; **OUT OF SCOPE for v2.0.0** (see Out of Scope). Reopen in a follow-up spec if needed. |
| 10 | Cross-language finding dedup in hybrid? | RESOLVED | **No dedup** — per language sub-block emits independent findings (Out of Scope item; FR-25). |
| 11 | Tool auto-install via configurator? | RESOLVED | **Warn-only in Phase 1**; `--auto-install` flag deferred to Phase 2 (out of scope for v2.0.0). Doctor + `install-tools` subcommand are the affordances. |
| 12 | Antipattern parity 25/25 in PHP? | OPEN | Carry to design: need PoC for 3–4 of the ~12 antipatterns PHPMD does not cover (research §1). Acceptable to ship partial parity in v2.0.0 with documented gap, but the gap MUST be enumerated in design. |
| 13 | Weak-test rules A1–A8 PHP mapping? | RESOLVED (partial) | FR-35 enumerates A1, A3, A4, A5, A6, A7, A8. A2 ("only mocks, no real interaction") deferred to design — Python rule semantics may not map cleanly. |
| 14 | E2E command per language? | OPEN | Carry to design: should `gates.e2e_command` be language-specific in the config schema, or is `make e2e` sufficient? Recommend per-language slot in `language_profiles.{lang}.tools.e2e.command`. |
| 15 | Migration documentation? | RESOLVED | **No** — no users, no migration doc (FR-33). |

**Net unresolved → design phase**: Q8 (marketplace versioning), Q9 (`.roomodes` — already deferred to follow-up), Q12 (antipattern parity gap PoC), Q13 partial (rule A2 mapping), Q14 (per-language E2E command schema).

---

<!-- Changed: initial v2.0.0 requirements draft from research.md REVIEW_PASS + interview answers. No prior requirements.md to supersede. -->
