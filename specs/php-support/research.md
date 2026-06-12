---
spec: php-support
phase: research
created: 2026-05-25
updated: 2026-05-25 (round 2)
---

# Research: php-support — Polyglot Quality Gate (Python + PHP)

## Executive Summary

The `harness-quality-gate` skill must work **from a single installation** against both Python and PHP projects, auto-detecting at invocation time. This is **highly feasible** with three structural changes and one hard policy decision:

1. **Single Python orchestrator + per-language adapters** (no separate skills). One `runner.py` calls a deterministic detector, then dispatches to either `adapters/python/*` or `adapters/php/*`. All PHP tools (PHPStan, Psalm, PHPUnit, Infection, Deptrac, composer audit) expose JSON CLIs — Python drives them via subprocess; the only `.php` files in the skill are `nikic/PHP-Parser` visitors for the 8–10 antipatterns PHPMD doesn't cover.
2. **Detection seam lives in `configurator.py` + a new `legacy scripts/ (migrated to harness_quality_gate/)detector.py`**, persisted to `_quality-gate/detection.json` and the v2 `quality-gate.yaml`. Heuristics: composer.json/composer.lock/phpunit.xml → PHP; pyproject.toml/setup.py/requirements*.txt → Python; tie-break by source-file count; `.quality-gate-lang` is the user override.
3. **Config schema v2** with `gates:` (shared thresholds), `language_profiles.{python,php}:` (tool-specific), `shared_tools:` (gitleaks/checkov/trivy/semgrep). Backward-compat via dual-read: legacy flat v1 configs auto-wrap into `language_profiles.python`.
4. **Infection 100/100 hard gate** (the user's non-negotiable). Achievable but bounded — empirical prior art shows 100/100 only at <~3–5k LoC of mutable code. Ship 100/100 as default, paired with a **Justified-Ignore Allow-List policy**: every `@infection-ignore-all`, `mutators.*.ignore`, and `source.excludes` entry must carry `reason:`/`proven-by:`/`audited:` metadata; the reviewer-agent diff-gates un-justified additions.

**Reuse:** ~55% of current files reusable as-is or with thin dispatcher; ~45% needs a per-language fork (entirely the AST-bound files: `antipattern_checker`, `solid_metrics`, `principles_checker`, `weak_test_detector`, plus tool runners). All orchestration, BMAD Party Mode, checkpoint emission, references, and YAML config stay shared.

**Feasibility: HIGH | Risk: MEDIUM (Infection 100/100 on >5k LoC) | Effort: L (~5–7 weeks)**

Three critical corrections required *regardless of PHP*:
- The skill uses `{skill-root}` which is **not** a Claude Code primitive. Canonical is `${CLAUDE_SKILL_DIR}` per [code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills). Broken portability today.
- Detection must live in an executable Python script invoked by `workflow.md`; inline `!` injection in `SKILL.md` runs **once** and is not re-scanned.
- Checkpoint JSON must add `language` (and `languages_detected[]` for hybrid repos) so downstream agents can branch without re-detecting.

---

## 1. Source-Code Coupling Audit (Per-File Matrix)

Read of every `legacy scripts/ (migrated to harness_quality_gate/)*.py`, `steps/*.md`, `references/*`, `config/quality-gate.yaml`, `SKILL.md`, `workflow.md`. Classification: **LANG_AGNOSTIC** | **LIGHT_COUPLING** (parameterizable dispatcher) | **MODERATE_COUPLING** (split + dispatcher) | **HEAVY_COUPLING** (full per-language fork).

| File | Lines | Coupling | Python-only constructs | Required change |
|------|------:|----------|------------------------|-----------------|
| `SKILL.md` | 416 | LANG_AGNOSTIC | none | Update to mention both langs; replace `{skill-root}` → `${CLAUDE_SKILL_DIR}` |
| `workflow.md` | 297 | LANG_AGNOSTIC | none | None — sequence is generic; commands come from dispatcher |
| `config/quality-gate.yaml` | 258 | LIGHT_COUPLING | tool names + `paths.src=src/` | Migrate to v2 dual-profile schema (§3) |
| `legacy scripts/ (migrated to harness_quality_gate/)configurator.py` | 569 | LIGHT_COUPLING | L20-28, L74-82 hardcode Python signals; L98-100 only infers pyproject.toml | Add `detect_language()` (40 lines), `--language` flag, branch `write_config()` |
| `legacy scripts/ (migrated to harness_quality_gate/)antipattern_checker.py` | 1195 | **HEAVY** | `import ast`; L215-453 AST visitors for all 25 Tier A patterns | Fork: `adapters/python/antipattern_tier_a.py` + `adapters/php/antipattern_tier_a.py` (nikic/PHP-Parser) |
| `legacy scripts/ (migrated to harness_quality_gate/)antipattern_judge.py` | 380 | HEAVY (data) | L21,186,193-194 AST parsing for Tier B context | Fork; BMAD prompt parameterized by `language` |
| `legacy scripts/ (migrated to harness_quality_gate/)solid_metrics.py` | 341 | **HEAVY** | `import ast`; ClassMetricsCollector visitor | Fork; PHP twin with PHP-Parser + PHPMD `codesize` |
| `legacy scripts/ (migrated to harness_quality_gate/)principles_checker.py` | 366 | **HEAVY** | L18,26-145 AST for DRY/KISS/YAGNI/LoD/CoI | Fork; PHP twin with PHPCPD + PHPMD + custom visitor |
| `legacy scripts/ (migrated to harness_quality_gate/)weak_test_detector.py` | 313 | **HEAVY** | L22,29-144 AST + `test_*.py` convention + pytest.raises | Refactor to strategy pattern: shared rule engine + per-lang AST visitor adapter |
| `legacy scripts/ (migrated to harness_quality_gate/)diversity_metric.py` | 152 | LIGHT_COUPLING | L15,22,54 AST + `test_*.py` glob | Parameterize file glob; algorithm (Levenshtein) is generic |
| `legacy scripts/ (migrated to harness_quality_gate/)llm_solid_judge.py` | 179 | LIGHT_COUPLING (prompt) | L22,36-37 AST class extraction | Strategy pattern; BMAD prompt template per lang |
| `legacy scripts/ (migrated to harness_quality_gate/)mutation_analyzer.py` | 372 | MODERATE | L31-44 shells out to `mutmut`; pyproject.toml parser | Refactor to parser strategy: mutmut JSON | Infection JSON; same kill-map output schema |
| `legacy scripts/ (migrated to harness_quality_gate/)security_scanner.py` | 1317 | MODERATE | L30-42 dataclass; L111-150 bandit CWE map; L150-191 tool runners (bandit/safety/deptry/vulture) | Refactor as orchestrator → `adapters/python/security.py` + `adapters/php/security.py` |
| `references/semgrep-python-rules.yaml` | 220 | MODERATE | Python-only rules | Keep; add `semgrep-php-rules.yaml` (~180 lines) |
| `references/semgrep-js-rules.yaml` | 286 | LANG_AGNOSTIC | JS/TS rules | Keep as-is |
| `references/security-tools-guide.md` | 11KB | LIGHT_COUPLING | Documents bandit/safety/vulture/deptry | Split into `…-python.md` + `…-php.md` |
| `references/owasp-checklist.md` | 13KB | LANG_AGNOSTIC | OWASP Top 10 | Keep as-is |
| `references/pentest-remediation-index.md` | 15KB | LANG_AGNOSTIC | CWE→remediation | Keep; add PHP examples in appendix |
| `references/verdict-schema.md` | 7.6KB | LANG_AGNOSTIC | JSON schema | Add `language` field (§4) |
| `steps/step-01-init.md` | ~100 | LIGHT | kills pytest orphans | Detect language; conditional cleanup |
| `steps/step-02-layer1.md` | ~150 | LIGHT | pytest/mutmut/make e2e | Dispatcher: pytest+mutmut OR phpunit+infection |
| `steps/step-03a-layer3a.md` | ~150 | LIGHT | `ruff check src/ tests/` | Dispatcher per lang |
| `steps/step-03-layer2.md` | ~100 | LIGHT | weak_test/diversity/mutation analyzers | Dispatcher per lang |
| `steps/step-04-layer3b.md` | ~200 | LIGHT | llm_solid_judge / antipattern_judge | Dispatcher per lang (prompts) |
| `steps/step-05-checkpoint.md` | ~150 | LANG_AGNOSTIC | JSON emit | Add `language` field |
| `steps/step-06-layer4.md` | ~300 | LIGHT | security_scanner CLI | Pass `--language` |

### Reuse percentages

| Bucket | Files | LoC | Action |
|--------|------:|----:|--------|
| LANG_AGNOSTIC | 13 | 1,480 | Keep |
| LIGHT_COUPLING | 6 | 950 | Thin dispatcher |
| MODERATE_COUPLING | 2 | 1,506 | Refactor (strategy pattern) |
| HEAVY_COUPLING | 6 | 3,225 | Per-language fork |

**Net:** orchestration + checkpoint + BMAD + references (~55%) reusable as-is or with parameterization; AST-bound analysis engines (~45%) need PHP twins. **Architecture is 100% reusable** — only implementation details differ (Python `ast` ↔ `nikic/PHP-Parser`).

### Hot files needing PHP twin

| Target file (new) | Est. LoC | Source library |
|-------------------|---------:|----------------|
| `adapters/php/antipattern_tier_a.py` + `visitors/*.php` | 950 + visitors | `nikic/PHP-Parser` 5.0 |
| `adapters/php/solid_metrics.py` + `visitors/*.php` | 280 | PHPMD + nikic |
| `adapters/php/principles.py` + `visitors/*.php` | 300 | PHPCPD + PHPMD + nikic |
| `adapters/php/test.py` (PHPUnit) | 270 | PHPUnit JSON output |
| `adapters/php/mutation.py` (Infection) | 280 | Infection JSON log |
| `adapters/php/security.py` | 400 | Psalm + composer audit + Semgrep |
| `adapters/php/architecture.py` | 150 | Deptrac JSON output |
| `references/semgrep-php-rules.yaml` | 180 | new |

**Total new PHP-adapter code: ~2,900 LoC** (Python orchestration drives PHP tools via subprocess; pure-PHP code limited to nikic visitors).

---

## 2. Installation & Bootstrap Flow

### 2.1 Current flow (Python-only, hardcoded)

```
INSTALL skill → CLAUDE_SKILL_DIR populated
       ▼
FIRST INVOCATION in target repo
  python3 ${CLAUDE_SKILL_DIR}/legacy scripts/ (migrated to harness_quality_gate/)configurator.py {project-root}
       ▼
AUTO-DISCOVERY (configurator.py:85-122)
  find_source_dirs() → [src, lib, app, packages]   (Python-flavored)
  find_tests_dir()   → [tests, test, spec]
  detect_has_docker(), detect_has_e2e()
  find_pyproject_config() → [tool.quality-gate.*]
       ▼
INTERACTIVE CONFIRMATION (L191-312) → user picks paths, thresholds
       ▼
WRITE CONFIG (L315-544)
  {project-root}/_quality-gate/quality-gate.yaml
  (Python-hardcoded: ruff, pytest, pyright, bandit, safety…)
       ▼
WORKFLOW (workflow.md → step-01-init.md → L3A → L1 → L2 → L3B → L4 → checkpoint)
  Hardcoded: `ruff check src/ tests/`, `pytest`, `bandit -r src/`…
       ▼
CHECKPOINT (_quality-gate/quality-gate-{ts}.json)
  Language-agnostic JSON shape (but no `language` field today)
```

### 2.2 Proposed dual-target flow

```
INSTALL skill (one-time, marketplace)
       ▼
FIRST INVOCATION
  python3 ${CLAUDE_SKILL_DIR}/legacy scripts/ (migrated to harness_quality_gate/)runner.py {project-root}
       ▼
DETECT (legacy scripts/ (migrated to harness_quality_gate/)detector.py — deterministic, no network, no LLM)
  Tier 1: .quality-gate-lang override file
  Tier 2: manifest presence (composer.json/composer.lock vs pyproject.toml/setup.py)
  Tier 3: source-file count tie-breaker (5+ files threshold)
  → {primary: "python"|"php"|"hybrid"|None, confidence, signals[]}
  → writes _quality-gate/detection.json
       ▼
CONFIGURE (configurator.py with --language flag, auto-detected)
  Generates v2 dual-profile quality-gate.yaml
  Optionally generates infection.json5, phpstan.neon, deptrac.yaml stubs
       ▼
DISPATCH (dispatcher.py routes by language to adapters/{python,php}/*)
       ▼
WORKFLOW (workflow.md unchanged; step files call dispatcher with layer name)
       ▼
CHECKPOINT (with `language`, `languages_detected[]`, `tool_versions`)
```

### 2.3 Detection algorithm

Adopted from GitHub Linguist precedence; only Tier 1–3 needed for quality-gate scope.

```python
def detect_language(project_root: Path) -> DetectionResult:
    """Returns: {primary, all, confidence, signals[]}. Deterministic."""

    # TIER 1 — explicit user override (precedence 1.0)
    if (project_root / ".quality-gate-lang").exists():
        lang = (project_root / ".quality-gate-lang").read_text().strip()
        return {"primary": lang, "confidence": 1.0,
                "signals": [".quality-gate-lang override"]}

    # TIER 2 — manifest files
    PY_MANIFESTS  = ["pyproject.toml", "setup.py", "setup.cfg",
                     "requirements.txt", "Pipfile", "poetry.lock", "uv.lock"]
    PHP_MANIFESTS = ["composer.json", "composer.lock"]
    py_hits  = [m for m in PY_MANIFESTS  if (project_root / m).exists()]
    php_hits = [m for m in PHP_MANIFESTS if (project_root / m).exists()]

    # TIER 3 — source file count (excludes vendor/, node_modules/, .venv/, etc.)
    py_count  = count_files(project_root, "*.py",  exclude=EXCLUDE_DIRS)
    php_count = count_files(project_root, "*.php", exclude=EXCLUDE_DIRS)

    has_py  = bool(py_hits)  or py_count  >= 5
    has_php = bool(php_hits) or php_count >= 5

    detected = {l for l, h in [("python", has_py), ("php", has_php)] if h}

    if not detected:
        return {"primary": None, "confidence": 0.0,
                "signals": ["no Python or PHP signals"]}
    if len(detected) == 1:
        primary = next(iter(detected))
        return {"primary": primary, "confidence": 0.95 if py_hits or php_hits else 0.7,
                "signals": [...]}

    # HYBRID — score-based tie-breaker
    py_score  = (10 if py_hits  else 0) + min(py_count, 100)
    php_score = (10 if php_hits else 0) + min(php_count, 100)
    if py_score  >= 2 * php_score:  return {"primary": "python", "confidence": 0.75, ...}
    if php_score >= 2 * py_score:   return {"primary": "php",    "confidence": 0.75, ...}
    return {"primary": "hybrid",    "confidence": 0.6, ...}

EXCLUDE_DIRS = {".git", "node_modules", "vendor", ".venv", "venv",
                "__pycache__", "dist", "build", ".tox",
                "_quality-gate", "_bmad-output"}
```

| Edge case | Behavior |
|-----------|----------|
| Empty repo | `primary=None` → workflow prompts user |
| Only tests, no src | Tier 3 source-count handles via test files |
| Vendored `vendor/` tree (large, no composer.json) | EXCLUDE_DIRS strips it |
| Monorepo with `apps/api-php/composer.json` + `apps/web-py/pyproject.toml` | If both equal → `hybrid`; workflow iterates per subdir |
| User override | `.quality-gate-lang` always wins |

### 2.4 Recommended seam: **Option A — in `configurator.py` + new `detector.py`**

Three alternatives evaluated (configurator.py, workflow.md, new runner.py); configurator wins because:
- runs once per project (persistent)
- user confirms language during interactive setup
- minimal disruption to workflow orchestration
- straightforward to extend to `--generate-stubs` for `infection.json5`/`phpstan.neon`/`deptrac.yaml`

Detection logic itself lives in `legacy scripts/ (migrated to harness_quality_gate/)detector.py` (importable + invocable standalone) so other components (doctor, dispatcher) reuse it.

---

## 3. Config Schema v2 (Dual-Profile)

```yaml
# config/quality-gate.yaml — v2 polyglot schema
schema_version: 2

# Optional override; if absent, detector decides
detection:
  override: null            # null | python | php | hybrid
  exclude_dirs: [vendor, node_modules]

# Cross-language gates — apply regardless of language
gates:
  coverage_threshold: 100.0          # ← UPDATED for 100% requirement
  mutation_kill_threshold: 1.00      # ← UPDATED for 100% MSI
  mutation_covered_threshold: 1.00   # ← UPDATED
  diversity_min_edit_distance: 20
  diversity_similarity_threshold: 0.8
  layer4_severity_threshold: high
  layer4_confidence_threshold: 0.7
  output:
    folder: _quality-gate
    checkpoint_filename: "quality-gate-{timestamp}.json"
    latest_alias: quality-gate-latest.json

language_profiles:

  python:
    enabled: auto
    runtime: { min_version: "3.10" }
    tools:
      lint:     { primary: ruff,    command: "ruff check" }
      format:   { primary: ruff,    command: "ruff format --check" }
      typecheck: { primary: pyright, command: "pyright" }
      test:     { primary: pytest,  command: "pytest", timeout_seconds: 300 }
      coverage: { primary: coverage, threshold: 100.0 }
      mutation:
        primary: mutmut
        min_msi: 1.00
        min_covered_msi: 1.00
        per_module_targets_source: "pyproject.toml"
      antipattern_tier_a:
        primary: ast_visitor
        thresholds: { ... }   # existing AP01–AP31 thresholds
      security:
        bandit: { priority: required, skip_rules: [B101, B311] }
        safety: { priority: required, fallback: pip-audit }
        semgrep:
          configs:
            - p/security-audit
            - p/owasp-top-ten
            - "${CLAUDE_SKILL_DIR}/references/semgrep-python-rules.yaml"
        deptry:  { priority: recommended }
        vulture: { priority: recommended, min_confidence: 80 }

  php:
    enabled: auto
    runtime:
      min_version: "8.2"
      composer_min_version: "2.5"
      coverage_engine: pcov  # pcov | xdebug (auto-fallback)
    tools:
      lint:
        primary: php-cs-fixer
        command: "php-cs-fixer fix --dry-run --diff"
        preset: "@PER-CS2.0"
      typecheck:
        primary: phpstan
        command: "phpstan analyse --memory-limit=2G"
        level: max
        rule_packs:
          - phpstan/phpstan-strict-rules
          - phpstan/phpstan-deprecation-rules
          - shipmonk/phpstan-rules
          - ergebnis/phpstan-rules
          - spaze/phpstan-disallowed-calls
      test:
        primary: phpunit         # phpunit | pest (detector sniffs)
        command: "phpunit"
        timeout_seconds: 300
        coverage: { driver: pcov, format: clover }
      mutation:
        primary: infection
        command: "infection --threads=max"
        min_msi: 100             # ← non-negotiable 100/100
        min_covered_msi: 100
        timeouts_as_escaped: true
        max_timeouts: 0
        git_diff_lines: true     # for incremental Ralph iterations
      antipattern_tier_a:
        primary: phpmd_plus_visitors
        phpmd:
          rulesets: [cleancode, codesize, controversial, design, naming, unusedcode]
        visitors:
          path: "${CLAUDE_SKILL_DIR}/legacy scripts/ (migrated to harness_quality_gate/)adapters/php/visitors"
        thresholds: { ... }      # mirror Python AP01–AP31 numeric thresholds
      architecture:              # NEW for PHP — hexagonal validation
        primary: deptrac
        config: "deptrac.yaml"
        fail_on_uncovered: true
        secondary: phpat         # optional add-on
      security:
        psalm:
          priority: required
          mode: taint_analysis
          command: "psalm --taint-analysis"
        composer_audit:
          priority: required
          command: "composer audit --format=json --no-dev"
        local_php_security_checker: { priority: optional }
        roave_security_advisories: { priority: recommended }
        semgrep:
          configs:
            - p/php
            - p/phpcs-security-audit
            - p/owasp-top-ten
            - "${CLAUDE_SKILL_DIR}/references/semgrep-php-rules.yaml"
        deptry_equivalent:  { primary: shipmonk/composer-dependency-analyser }
        vulture_equivalent: { primary: shipmonk/dead-code-detector }

shared_tools:
  gitleaks: { priority: required }
  checkov:  { priority: recommended }
  trivy:    { priority: optional }

layer4:
  phases:
    phase1_deterministic: true
    phase2_dedup_confidence: true
    phase3_llm_triage: true
    phase4_party_mode: true
    phase5_fix_validation: true
  party_mode:
    agents: [Winston, Murat, Amelia]
    max_consensus_rounds: 3
```

### Backward compatibility (v1 → v2)

- v1 flat config (no `schema_version` or `=1`) → loader wraps it into `language_profiles.python`, prints one-time `migrating config schema 1 → 2` and writes back.
- Existing `{skill-root}` aliased to `${CLAUDE_SKILL_DIR}` until v3; both forms work.
- `python3 ${CLAUDE_SKILL_DIR}/legacy scripts/ (migrated to harness_quality_gate/)security_scanner.py /repo` (legacy CLI) routed via shim to `runner.py security /repo`.
- Pure-Python projects: detector → python, no PHP runtime required, ever.

---

## 4. Layer-by-Layer PHP Tooling Matrix

| Layer | Python tool today | PHP equivalent | Recommendation | Notes |
|-------|-------------------|----------------|----------------|-------|
| **L3A.1** ruff check | `ruff` | PHP-CS-Fixer (dry-run) + PHPStan @ daily lint | `php-cs-fixer fix --dry-run --diff` + `phpstan analyse --memory-limit=2G --level=max` | PHPStan absorbs ruff's lint semantics |
| **L3A.2** ruff format | `ruff format` | PHP-CS-Fixer (preset `@PER-CS2.0`) | same | Pint acceptable for Laravel-only; default PHP-CS-Fixer |
| **L3A.3** type check | `pyright` | **PHPStan** (primary) | level `max` + `phpstan-strict-rules` + deprecation-rules + spaze/disallowed-calls + ergebnis/rules + shipmonk/rules | Start at L6, ramp via baseline, target max |
| **L3A.4** check_headers | custom | port-as-is, parameterize `.php` ext | same | Header convention is project-defined |
| **L3A.5** SOLID Tier A | `solid_metrics.py` (AST) | nikic/PHP-Parser visitors + ergebnis/phpstan-rules + Phauthentic + PHPMD `codesize` | Hybrid: PHPStan rule packs + custom visitor for arity/LoC/method-count | |
| **L3A.6** Principles (DRY/KISS/YAGNI/LoD/CoI) | `principles_checker.py` | PHPCPD (DRY) + PHPMD (KISS/CoI) + shipmonk/composer-dependency-analyser (YAGNI) + custom visitor (LoD) | bundle | PHPCPD detects duplicates; PHPMD `cleancode`/`design` |
| **L3A.7** Antipatterns Tier A (25) | `antipattern_checker.py` | **PHPMD rulesets + custom nikic visitors** | port AST visitors to `PhpParser\NodeVisitorAbstract`; PHPMD covers ~13/25, ~12 need custom | |
| **L1.1** test runner | `pytest` | **PHPUnit 11+** (or Pest if detected) | strict mode: `requireCoverageMetadata`, `beStrictAboutCoverageMetadata`, `failOnRisky`, `failOnWarning`, `failOnIncomplete`, `failOnEmptyTestSuite` | |
| **L1.2** coverage | `coverage` | **PCOV** (fallback Xdebug) | ~2.8–5× faster than Xdebug; PHPUnit `pathCoverage="false"` to stay with PCOV | PCOV last release 2021 but works on PHP 8.4 |
| **L1.3** mutation testing | `mutmut` | **Infection** | `minMsi: 100`, `minCoveredMsi: 100`, `--threads=max`, `--git-diff-lines` for incremental | See §5 |
| **L1.5** E2E | `make e2e` | unchanged | `make e2e` (project-defined) | |
| **L2.1** weak test detection | `weak_test_detector.py` | strategy-pattern shared engine + PHP-Parser visitor | port A1–A8; PHPUnit `beStrictAboutTestsThatDoNotTestAnything` partially covers A1 | |
| **L2.2** mutation kill-map | parse `mutmut` | parse `infection-log.json` | shared analyzer with parser strategy | Infection emits per-mutator + per-file metrics natively |
| **L2.3** diversity metric | `diversity_metric.py` | parameterized glob | same algorithm | Levenshtein is language-agnostic |
| **L3B.1** SOLID Tier B (BMAD) | `llm_solid_judge.py` | shared; PHP prompt template | reuse engine; swap prompt for PHP idioms (traits, interfaces, attributes, readonly) | |
| **L3B.2** Antipatterns Tier B (BMAD) | `antipattern_judge.py` | same | shared with PHP-aware prompt | |
| **L3B.3** Architecture (NEW for PHP) | — | **Deptrac** (primary), PHPat optional | declarative YAML layer rules + JSON/GitHub/JUnit reporters + cycle detection | See §4.1 |
| **L4.1** bandit | `bandit` | **Psalm taint analysis** (primary) + Semgrep `p/phpcs-security-audit` (secondary) | Psalm uniquely offers built-in taint; PHPStan does not | |
| **L4.2** safety/pip-audit | `safety` / `pip-audit` | **composer audit** (primary) + **local-php-security-checker** (binary fast) + **roave/security-advisories** (preventive constraint) | run all three; roave blocks install of vulnerable versions | |
| **L4.3** gitleaks | unchanged | gitleaks | reuse | polyglot |
| **L4.4** semgrep | `semgrep` | semgrep + `p/php` + `p/phpcs-security-audit` + `p/owasp-top-ten` | reuse | PHP rules marked "experimental but useful" — pair with Psalm taint |
| **L4.5** checkov | unchanged | checkov | reuse | Dockerfile/YAML/JSON |
| **L4.6** deptry | `deptry` | **shipmonk/composer-dependency-analyser** | single tool replaces composer-unused + composer-require-checker | |
| **L4.7** vulture | `vulture` | **shipmonk/dead-code-detector** (PHPStan extension) | framework-aware (Symfony/Laravel/Doctrine reflection) | |
| **L4.8** trivy | unchanged | trivy | reuse | scans Dockerfile + composer.lock |

### 4.1 Hexagonal architecture — Deptrac vs PHPat vs ArchUnitPHP

| Criterion | **Deptrac** (recommended) | PHPat | ArchUnitPHP |
|-----------|---------------------------|-------|-------------|
| Config style | Declarative YAML | Fluent DSL (PHP) | Fluent DSL (PHP) |
| Coupling | Standalone binary | Requires PHPStan | Standalone |
| Layer model | Layer→layer ruleset | Class-set assertions | Class-set assertions |
| Reporters | JSON, GitHub, JUnit, GraphViz | PHPStan output | text |
| Cycle detection | **Built-in** | manual | manual |
| Agent-friendliness | High (YAML diffable) | Medium (PHP DSL) | Medium |
| Maturity (2026) | qossmic/deptrac active | active | less active |

**Pick Deptrac primary.** PHPat optional secondary if user prefers in-PHPStan assertions. Sample `deptrac.yaml`:

```yaml
paths: ["./src"]
layers:
  - { name: Domain,          collectors: [{ type: directory, regex: src/Domain/.* }] }
  - { name: Application,     collectors: [{ type: directory, regex: src/Application/.* }] }
  - { name: Infrastructure,  collectors: [{ type: directory, regex: src/Infrastructure/.* }] }
  - { name: UI,              collectors: [{ type: directory, regex: src/UI/.* }] }
ruleset:
  Domain:         []
  Application:    [Domain]
  Infrastructure: [Domain, Application]
  UI:             [Application]
```

---

## 5. Infection 100% MSI + 100% Coverage Strategy

**User requirement: 100% line coverage AND 100% mutation kill rate (MSI = 100, Covered MSI = 100). Non-negotiable.**

### 5.1 Verdict

| Codebase size | Verdict | Path |
|---------------|---------|------|
| Library, <1k LoC of mutable code | **YES** — proven by `sebastianbergmann/lines-of-code`, `complexity`, `cli-parser` | one or two iterations |
| Application, 1–10k LoC | **YES with effort** | requires disciplined `@infection-ignore-all` with justification on framework-required equivalent-mutant sites |
| Monolith, >10k LoC | **PRACTICALLY NO** without escape valves | compounding equivalent-mutant pressure → loop diverges |

**Strongest empirical signal:** Infection's own ~25k-LoC codebase does **not** enforce 100/100; it ships with per-mutator carve-outs (Assert::.*, ProtectedVisibility on BaseReportLocator, etc.). Maks Rafalko, the author, does not eat his own dog food on this metric.

### 5.2 Recommended policy: 100/100 + Justified-Ignore Allow-List

Ship 100/100 as the default hard gate, paired with:

1. `minMsi: 100`, `minCoveredMsi: 100` non-negotiable in `infection.json5`.
2. Every `@infection-ignore-all` annotation MUST carry an adjacent doc-comment with `reason:`, optional `proven-by:` (pointing to the test covering the conceptual contract), and `audited:` (date + reviewer).
3. Every entry in `mutators.*.ignore`, `global-ignore`, `global-ignoreSourceCodeByRegex`, `source.excludes` MUST have a JSON5 comment above it with same fields.
4. The Ralph **reviewer-agent** runs `legacy scripts/ (migrated to harness_quality_gate/)audit-ignores.php` (NEW) that fails the gate if any ignore lacks justification metadata.
5. The Ralph **checkpoint** metric tracks `ignored_count` and `ignored_delta` separately from MSI — human reviewer sees "100/100, +3 ignores this PR" and can challenge each.
6. Per-project override: `infection.json5.local` may relax to `minMsi: 95` for legacy modules during a ramp; spec template generates this opt-in with a TODO.

### 5.3 Drop-in `infection.json5` for 100/100 mode

```json5
{
  "$schema": "vendor/infection/infection/resources/schema.json",
  "timeout": 25,
  "threads": "max",

  "source": {
    "directories": ["src"],
    "excludes": [
      // reason: generated code, equivalent-mutant farm
      "Generated/**",
      // reason: framework bootstrap, wiring not behavior
      "Kernel.php",
      // reason: DI compile passes, schema-time only
      "DependencyInjection/Compiler/**",
      // reason: Doctrine migrations, run-once, schema not unit-testable
      "Migrations/**"
    ]
  },

  "logs": {
    "json":       "var/infection/infection-log.json",
    "text":       "var/infection/infection.log",
    "html":       "var/infection/infection.html",
    "summary":    "var/infection/summary.log",
    "perMutator": "var/infection/per-mutator.md",
    "github":     true
  },

  "phpUnit": { "configDir": ".", "customPath": "vendor/bin/phpunit" },

  "mutators": {
    "global-ignoreSourceCodeByRegex": [
      // reason: Webmozart\Assert is fail-fast precondition; equivalent mutants
      "Assert::.*",
      // reason: Logger calls side-effect-only; mutating args is noise
      "\\$this->logger->.*",
      // reason: pragma markers, not behavior
      "@psalm-.*",
      "@phpstan-.*"
    ],
    "global-ignore": [
      // reason: VOs are pure data carriers, accessor mutations equivalent
      "App\\Domain\\*\\ValueObject\\*"
    ],
    "@default": true,
    // reason: framework containers call public methods; visibility downgrade
    //         produces equivalent mutants on Symfony/Laravel
    "@function_signature": false,
    "PublicVisibility": false,
    "ProtectedVisibility": false,
    "ArrayItemRemoval": {
      "settings": { "remove": "first", "limit": 1 }
    }
  },

  "minMsi": 100,
  "minCoveredMsi": 100,
  // reason: interfaces/abstracts have zero mutants → would otherwise NaN
  "ignoreMsiWithNoMutations": true,
  // reason: timeouts must count as escapes — no silent kill-by-timeout
  "timeoutsAsEscaped": true,
  "maxTimeouts": 0,

  "testFramework": "phpunit",
  "testFrameworkOptions": "--testsuite=unit",
  "initialTestsPhpOptions": "-d memory_limit=512M",
  "bootstrap": "tests/bootstrap.php",
  "tmpDir": "var/infection"
}
```

### 5.4 Companion `phpunit.xml` (PHPUnit 11+, strict mode)

```xml
<phpunit
    requireCoverageMetadata="true"
    beStrictAboutCoverageMetadata="true"
    beStrictAboutOutputDuringTests="true"
    beStrictAboutChangesToGlobalState="true"
    beStrictAboutTestsThatDoNotTestAnything="true"
    failOnDeprecation="true"
    failOnPhpunitDeprecation="true"
    failOnEmptyTestSuite="true"
    failOnIncomplete="true"
    failOnNotice="true"
    failOnRisky="true"
    failOnWarning="true"
    cacheDirectory=".phpunit.cache">

  <source ignoreIndirectDeprecations="true" restrictNotices="true" restrictWarnings="true">
    <include><directory>src</directory></include>
    <exclude>
      <!-- MUST mirror infection.json5 source.excludes exactly -->
      <directory>src/Generated</directory>
      <file>src/Kernel.php</file>
      <directory>src/Migrations</directory>
    </exclude>
  </source>

  <coverage
      includeUncoveredFiles="true"
      pathCoverage="false"
      ignoreDeprecatedCodeUnits="true"
      disableCodeCoverageIgnoreAnnotations="false">
    <report>
      <clover outputFile="var/coverage/clover.xml"/>
      <html outputDirectory="var/coverage/html" lowUpperBound="100" highLowerBound="100"/>
    </report>
  </coverage>
</phpunit>
```

**Critical:** PHPUnit `<source><exclude>` MUST mirror `infection.json5` `source.excludes` exactly. Drift causes PHPUnit to demand coverage on code Infection cannot see → guaranteed failure.

PHPUnit 10 renamed `forceCoversAnnotation` → `requireCoverageMetadata`; old name removed in v11. Pin a major version in `composer.json`.

### 5.5 Mutator decisions

| Profile | Enabled? | Reason |
|---------|----------|--------|
| `@default` | YES | baseline (arithmetic, boolean, cast, conditional_boundary, equal, identical, removal, return_value, sort, unwrap, extensions) |
| `@arithmetic` | YES | watch `*1`/`/1`/`+0` equivalent patterns |
| `@boolean` | YES | `TrueValue.array_search=false` to suppress noisy strict-flag |
| `@cast` | YES | highly killable |
| `@conditional_boundary` | YES | boundary tests are THE point of mutation testing |
| `@removal` | YES | forces side-effect assertions |
| `@return_value` | YES | use `ignore` on factory methods without observable contract |
| `@sort` (Spaceship `<=>`) | YES | highly killable |
| `@unwrap` (array_filter/map removal) | YES | forces tests to use post-transform values |
| `@function_signature` | **NO** for framework apps | Symfony/Laravel call public via DI → equivalent mutants |
| `PublicVisibility` / `ProtectedVisibility` | **NO** for apps; YES for libraries with reflection tests | same reason |
| `@equal` / `@identical` | CAUTIOUS YES | equivalent when operand types match; justify per call-site |
| `@number` (off-by-one detector) | YES (opt-in) | critical for boundary code |
| `@regex` | YES if regex-heavy | forces anchor/flag coverage |
| `NullSafeMethodCall` / `NullSafePropertyCall` | YES | force null + non-null receiver tests |
| `MatchArmRemoval` | YES | each arm needs explicit case |

### 5.6 Coverage backend

| Backend | Line | Branch | Path | Speed vs Xdebug | Verdict |
|---------|:---:|:---:|:---:|:---:|---------|
| **PCOV** | ✓ | ✗ | ✗ | **~2.8–5× faster** | **Use for 100/100** |
| Xdebug 3 (mode=coverage) | ✓ | ✓ | ✓ | baseline (slow) | only if branch/path required |
| phpdbg | ✓ | ✗ | ✗ | ~2× faster | deprecated; do not adopt |

PCOV install: `pecl install pcov` then `phpunit -d pcov.enabled=1 -d xdebug.mode=off`. PHPUnit `pathCoverage="false"` is required to stay with PCOV.

### 5.7 Performance budget (PCOV + threads=max on 8-core CI)

| LoC range | Mutants | Full run | Incremental (`--git-diff-lines`) |
|-----------|---------|----------|----------------------------------|
| <1k | 50–200 | <1 min | <30s |
| 1–5k | 500–2k | 3–10 min | 30–90s |
| 5–15k | 2k–8k | 10–30 min | 1–5 min |
| 15–50k | 8k–30k | 30–120 min | 2–10 min |
| >50k | 30k+ | CI-prohibitive | 5–20 min |

**Levers for autonomous loops (use all):**
- `--threads=max` (linear speedup)
- `--git-diff-lines --git-diff-base=origin/main` (essential for tight Ralph iteration)
- `--only-covering-test-cases` (replaces deprecated `--only-covered`)
- `--coverage=var/coverage --skip-initial-tests` (reuse pre-collected PCOV)
- `--filter=src/Path/To/Module` (per-module loops)
- `tmpDir` on tmpfs (RAM-backed)

Tight-loop recipe:

```bash
vendor/bin/phpunit --coverage-php var/coverage/cov.php          # ~30s with PCOV
vendor/bin/infection \
    --coverage=var/coverage \
    --skip-initial-tests \
    --git-diff-lines --git-diff-base=origin/main \
    --threads=max \
    --only-covering-test-cases \
    --logger-github --no-progress
```

### 5.8 Agent cheats and L2 countermeasures

| Cheat | Detection | Mitigation |
|-------|-----------|------------|
| Tests with zero assertions | `beStrictAboutTestsThatDoNotTestAnything` + `failOnRisky` | PHPUnit marks risky; L2 also rejects PRs whose new tests have no `assert*\\(` |
| Tests that only call `__construct` + `assertInstanceOf` | AST scan for "only `new X` + `assertInstanceOf`" | custom nikic visitor in L2 |
| Tests that mock the SUT (mock the class under test) | grep `createMock(SameClassAsCovers)` | static rule in L2 |
| `expectException(Throwable::class)` (any-throw passes) | PHPStan rule bans base classes in `expectException` | L2 rule |
| `markTestSkipped` / `markTestIncomplete` | `failOnIncomplete="true"` mandatory | |
| `@codeCoverageIgnore` spam | for 100/100 set `disableCodeCoverageIgnoreAnnotations="true"` OR audit every annotation | reviewer-agent diff |
| `@infection-ignore-all` spam | track count + diff in reviewer-agent | reject un-justified additions |

### 5.9 Iteration recipe (Ralph Loop)

```
ITERATION N:
  1. phpunit --coverage-php (~30s with PCOV)
  2. infection (informational, no hard gate)
  3. parse var/infection/infection-log.json:
       if stats.msi == 100 && stats.coveredMsi == 100 → DONE
       else: collect escaped[] + notCovered[]
  4. For each surviving mutant, classify:
       A) Killable    → write new test asserting broken behavior
       B) Equivalent  → @infection-ignore-all + reason + audited
       C) Out of scope → source.excludes + reason + audited
  5. Reviewer-agent gate (BEFORE next iteration):
       - count delta of @infection-ignore-all annotations
       - reject if added without justification metadata
       - verify new tests have assertion count > 0
       - verify no test mocks its own SUT class
  6. Re-run from step 1 with --git-diff-lines for fast feedback;
     full run only on iteration close.
  7. Final iteration: infection --min-msi=100 --min-covered-msi=100 → exit 0
```

### 5.10 Equivalent-mutant escape hatches (surgical → blunt)

(a) **Per-mutator `ignoreSourceCodeByRegex`** — surgical, justified inline:
```json5
"Plus": {
  "ignoreSourceCodeByRegex": [
    // reason: byte-position arithmetic clamped by substr(); Plus→Minus equivalent
    ".*\\$offset\\s*\\+\\s*\\$length.*"
  ]
}
```

(b) **Per-mutator `ignore` on FQCN::method** — class-scoped, justified inline.

(c) **`@infection-ignore-all` annotation** — inline last resort. Note: `@infection-ignore-for <Mutator>` does **NOT** exist as a stable feature (Issue #2291 open). Use per-mutator config-file `ignore` instead.

---

## 6. Polyglot Skill Architecture (Decision Record)

### 6.1 Dispatcher options compared

| Criterion | A: Python runner + subprocess to PHP scripts | B: Shell runner.sh | C: Three skills (-python, -php, -common) | **D: Python orchestrator + per-language adapters** |
|-----------|----:|----:|----:|:----:|
| Install simplicity | one skill | one skill | **three skills** | **one skill** |
| Code reuse (judges, metrics) | high | low | medium | **highest** |
| Debuggability | unified | two cultures | 3× surface | **unified** |
| Maintenance | medium | high (duplicate runners) | high (version skew) | **low** |
| Bash composer.json parsing | n/a | **fragile** | n/a | n/a |
| Cross-skill deps | n/a | n/a | **not supported** (issue #9444) | n/a |
| **Verdict** | OK | reject | reject | **PICK** |

**Pick D.** All PHP tools (PHPStan, Psalm, PHPUnit, Infection, PHPMD, Deptrac, composer audit) ship as CLI tools with JSON output. Python orchestrator drives them via subprocess; the only `.php` files in the skill are `nikic/PHP-Parser` visitors for the 8–10 antipatterns PHPMD can't cover.

### 6.2 Recommended layout

```
harness-quality-gate/
├── .claude-plugin/plugin.json
└── skills/harness-quality-gate/
    ├── SKILL.md                                # uses ${CLAUDE_SKILL_DIR}; mentions both langs
    ├── workflow.md                             # language-agnostic; dispatcher fills commands
    ├── config/
    │   ├── quality-gate.yaml                   # v2 dual-profile
    │   ├── quality-gate.v1.example.yaml        # legacy reference
    │   └── php-tool-versions.json              # pinned PHAR versions
    ├── references/
    │   ├── verdict-schema.md                   # adds `language` field
    │   ├── owasp-checklist.md                  # shared
    │   ├── pentest-remediation-index.md        # shared
    │   ├── security-tools-guide-python.md      # split from current
    │   ├── security-tools-guide-php.md         # NEW
    │   ├── semgrep-python-rules.yaml           # unchanged
    │   ├── semgrep-php-rules.yaml              # NEW (~180 lines)
    │   └── semgrep-js-rules.yaml               # unchanged
    ├── legacy scripts/ (migrated to harness_quality_gate/)
    │   ├── runner.py                           # NEW entrypoint
    │   ├── detector.py                         # NEW language detection
    │   ├── dispatcher.py                       # NEW routing
    │   ├── doctor.py                           # NEW doctor subcommand
    │   ├── configurator.py                     # modified (PHP-aware)
    │   ├── install_php_tools.sh                # NEW (PHAR helper)
    │   ├── audit_ignores.php                   # NEW (justified-ignore gate)
    │   ├── shared/
    │   │   ├── diversity_metric.py
    │   │   ├── llm_solid_judge.py              # BMAD, prompt-parameterized
    │   │   ├── antipattern_judge.py            # BMAD, prompt-parameterized
    │   │   ├── weak_test_detector.py           # strategy pattern + per-lang visitor
    │   │   ├── mutation_analyzer.py            # parser strategy (mutmut|infection)
    │   │   ├── checkpoint.py
    │   │   └── validate_config.py
    │   ├── adapters/
    │   │   ├── base.py                         # LanguageAdapter ABC
    │   │   ├── python/{lint,typecheck,test,mutation,antipattern_tier_a,solid_metrics,principles,security}.py
    │   │   └── php/
    │   │       ├── {lint,typecheck,test,mutation,antipattern_tier_a,solid_metrics,principles,architecture,security}.py
    │   │       └── visitors/                   # nikic/PHP-Parser visitors
    │   │           ├── god_class.php
    │   │           ├── feature_envy.php
    │   │           ├── data_clumps.php
    │   │           └── …
    │   └── legacy_shims/                       # backward compat re-exports
    │       ├── security_scanner.py             # → runner.py security
    │       └── antipattern_checker.py          # → runner.py antipattern
    └── steps/
        ├── step-01-init.md                     # modified — calls detector first
        ├── step-02-layer1.md                   # dispatcher
        ├── step-03-layer2.md
        ├── step-03a-layer3a.md
        ├── step-04-layer3b.md
        ├── step-05-checkpoint.md
        └── step-06-layer4.md
```

### 6.3 Doctor workflow (PHP runtime missing)

```
$ python3 ${CLAUDE_SKILL_DIR}/legacy scripts/ (migrated to harness_quality_gate/)runner.py doctor /path/to/repo

harness-quality-gate doctor — PHP toolchain check
Language detected: php (confidence 0.95)

Required runtimes:
  ✓ php       8.3.10       /usr/bin/php
  ✓ composer  2.7.2        /usr/local/bin/composer

Required tools:
  ✓ phpunit   11.0.6       vendor/bin/phpunit
  ✓ phpstan   2.1.34       vendor/bin/phpstan
  ✗ infection NOT FOUND    install: composer require --dev infection/infection
                                  OR PHAR: curl -L https://github.com/infection/infection/releases/latest/download/infection.phar
                                          -o ~/.local/bin/infection && chmod +x ~/.local/bin/infection
  ✗ deptrac   NOT FOUND    install: PHAR from https://github.com/qossmic/deptrac/releases
  ✓ pcov      1.0.11       enabled in php.ini
  ⚠ xdebug    3.3.2        conflicts with pcov — recommend disabling for Infection runs

Verdict: INFRA_INCOMPLETE — 2 required tools missing
Run: bash ${CLAUDE_SKILL_DIR}/legacy scripts/ (migrated to harness_quality_gate/)install_php_tools.sh
```

**PHAR policy:** do NOT bundle PHARs inside the skill (5–30 MB each, version drift, marketplace updates lag tool releases). DO ship `install_php_tools.sh` that downloads pinned versions from `config/php-tool-versions.json` to `~/.local/bin/`. Discovery order: `vendor/bin/<tool>` → `${COMPOSER_HOME:-~/.composer}/vendor/bin/<tool>` → `which <tool>` → `~/.local/bin/<tool>.phar` → NOT FOUND.

### 6.4 Checkpoint JSON v2 (stable additive contract)

```jsonc
{
  "schema_version": "2.0.0",
  "spec": "...",
  "timestamp": "2026-05-25T10:00:00Z",

  "language": "php",                             // NEW
  "languages_detected": ["php"],                 // NEW (list for hybrid)
  "detection_signals": [
    "php manifests: ['composer.json', 'composer.lock']",
    "source files: py=0 php=187"
  ],

  "runtime": {                                   // NEW environment fingerprint
    "harness_skill_version": "2.0.0",
    "python_version": "3.12.4",
    "php_version": "8.3.10",
    "composer_version": "2.7.2",
    "tool_versions": {
      "phpunit": "11.0.6", "phpstan": "2.1.34",
      "infection": "0.29.6", "psalm": "5.26.1", "deptrac": "2.0.3"
    }
  },

  "layer1_test_execution": {
    "PASS": true,
    "language": "php",                           // denormalized per layer
    "tool_used": "phpunit",
    "coverage_pct": 100.0,
    "mutation_msi": 100.0,
    "mutation_covered_msi": 100.0,
    "tool_specific": {
      "infection": {
        "killed": 412, "escaped": 0, "errored": 0,
        "timed_out": 0, "not_covered": 0,
        "ignored_count": 5,                      // NEW — for justified-ignore tracking
        "ignored_delta": 0                       // NEW — vs previous run
      }
    }
  },

  "layer3_code_quality": {
    "tier_a": {
      "lint":          { "tool": "php-cs-fixer", "PASS": true },
      "typecheck":     { "tool": "phpstan", "level": "max", "PASS": true },
      "antipatterns":  { "tool": "phpmd+ast_visitors", "tier_a_findings": [] },
      "solid":         { "violations": [] },
      "principles":    { },
      "architecture":  { "tool": "deptrac", "violations": 0, "uncovered_classes": 0 }
    },
    "tier_b": { "antipatterns": [], "solid": [] }
  },

  "layer4_security_defense": {
    "language": "php",
    "tools_run": ["psalm", "composer_audit", "semgrep", "gitleaks"],
    "tools_skipped": ["bandit", "safety"],       // NEW explicit skip list
    "findings": [ /* ... */ ]
  },

  "overall_pass": true
}
```

**Stability:** existing keys never removed or renamed. New keys are additive. For hybrid repos, each layer carries a `per_language: { python: {...}, php: {...} }` sub-block.

### 6.5 Backward-compat guarantees (existing Python users)

1. No config changes required — v1 flat configs auto-wrap into `language_profiles.python`.
2. Same checkpoint output for pure-Python repos (only `language: "python"` added).
3. Same step files invoked; dispatcher merely substitutes tool commands.
4. `.quality-gate-lang` → `python` is a one-line opt-out for users who want zero PHP-detection overhead.
5. No new required runtimes; Python users never need PHP/Composer installed.
6. `{skill-root}` aliased to `${CLAUDE_SKILL_DIR}` until v3.
7. No removed scripts; legacy paths shimmed to re-export with deprecation warning until v3.
8. Same CLI surface — `python3 ${CLAUDE_SKILL_DIR}/legacy scripts/ (migrated to harness_quality_gate/)security_scanner.py /repo` keeps working via shim.

### 6.6 Test strategy

Fixture repos under `tests/fixtures/`:
- `python-pure-pass/`, `python-pure-fail-layer3a/`, `python-pure-fail-layer4/`
- `php-pure-pass/`, `php-pure-fail-mutation/`, `php-pure-fail-deptrac/`, `php-pure-fail-psalm-taint/`
- `hybrid-py-php/`, `empty-repo/`, `monorepo/`
- `php-no-runtime/` (PATH stripped of `php` — verifies INFRA_INCOMPLETE)
- `legacy-config-v1/` (schema_version=1 → auto-migrate)

CI matrix: `{ubuntu, macos, windows} × {py 3.10/3.12} × {php 8.2/8.3/8.4} × {composer, no-composer (PHAR-only)} × {with-runtime, no-runtime}`. 7 jobs total.

Test categories: detector unit tests, dispatcher routing tests (with mocked tools), adapter unit tests (canned JSON), E2E fixture tests, schema validation tests, backward-compat tests.

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|:----------:|:------:|------------|
| 100/100 unreachable on >5k LoC mutable code | HIGH | loop diverges | per-module gating via `--filter`; ramp 80→90→100 for legacy modules; document escape valve |
| Agent abuses `@infection-ignore-all` to fake green | HIGH | false PASS | reviewer-agent diff-gate + `audit_ignores.php` script + checkpoint `ignored_delta` metric |
| Equivalent mutants from `@equal`/`@identical` consume budget | MEDIUM | slow convergence | start with `@equal: false, @identical: false`; re-enable case-by-case |
| PHPUnit 10/11/12 attribute renames break strict mode | MEDIUM | invalid config | pin PHPUnit major in `composer.json`; use new names (`requireCoverageMetadata`) |
| PCOV missing locally | MEDIUM | works-in-CI-not-local | document install; offer Xdebug fallback with warning in checkpoint |
| `--git-diff-lines` misses cross-file impact | LOW | survivor slips PR | full run on `main` push (post-merge); diff-lines only for PR feedback |
| Symfony/Laravel public visibility → equivalent mutants | HIGH for framework apps | constant survivor pressure | disable `@function_signature` / `PublicVisibility` / `ProtectedVisibility` in template |
| Doctrine entities → equivalent-mutant farms | HIGH | inflated `escaped[]` | `global-ignore` entity namespaces; test invariants via aggregate-level behavior tests |
| `{skill-root}` portability bug on plugin installs | HIGH (already broken) | skill mis-resolves paths | migrate to `${CLAUDE_SKILL_DIR}` with legacy alias |
| Hybrid repo detection ambiguity | MEDIUM | wrong gate runs | `.quality-gate-lang` override + audit log in `detection.json` |
| PHP runtime absent | MEDIUM | gate cannot start | `doctor` subcommand + INFRA_INCOMPLETE verdict (not FAIL) |

---

## 8. Related Specs

| Spec | Relationship | Status |
|------|--------------|--------|
| (none yet) | first spec | — |

---

## 9. Open Questions for Requirements Phase

1. **Hybrid repo policy.** When detection returns `hybrid` (truly mixed Py+PHP), run both gates in parallel (a), require `.quality-gate-lang` (b), or prompt agent (c)? **Recommend (a)** — autonomous Ralph Loop needs zero-prompt operation.
2. **Infection 100/100 escape valve.** Strict 100/100 with justified-ignore allow-list, or allow `minMsi: 95` ramp for opt-in legacy modules via `infection.json5.local`? **Recommend the second** with documented TODO.
3. **PHPUnit vs Pest primary.** PHPUnit is more universal; Pest is more idiomatic in modern Laravel. Detector sniffs `tests/Pest.php` / `pest.config.php` and switches. OK?
4. **Framework-conditional rule packs.** Auto-enable Larastan when `composer.json` requires `laravel/framework`? Same for `phpstan-symfony` with Symfony? **Recommend yes.**
5. **BMAD prompt strategy.** Maintain (a) two prompt templates (PHP + Python), (b) one bilingual template, or (c) auto-translate via LLM at runtime? **Recommend (a)** — deterministic.
6. **Coverage engine fallback.** If PCOV unavailable on PHP 8.5+ in future, silent fallback to Xdebug or fail loudly? **Recommend silent fallback** with warning in checkpoint.
7. **Composer global vs project-local.** When `vendor/bin/phpunit` and `~/.composer/vendor/bin/phpunit` differ, which wins? **Recommend project-local** (matches `composer.lock`).
8. **Plugin marketplace versioning.** Ship v2 as new plugin (`harness-quality-gate-v2`) or in-place upgrade? **Recommend in-place** with auto-migration; bump major; document breaking changes only relevant to schema authors.
9. **Roo / .roomodes integration.** The repo has `.roomodes` referencing the current skill. Does the polyglot port need to update Roo mode definitions too, or out of scope? **Needs user confirmation.**
10. **Cross-language deduplication.** For hybrid repos, if the same CWE appears in both Python and PHP code, share a finding ID or separate? **Recommend separate** — remediation differs per language.
11. **Tool auto-installation.** Should configurator auto-run `composer require --dev` or `pip install` for missing tools, or warn only? **Recommend warn-only** Phase 1; optional `--auto-install` flag Phase 2.
12. **Antipattern parity in PHP.** Can custom nikic visitors achieve **feature parity** with Python's 25 Tier A patterns? Research shows ~12 patterns need custom code; the rest map to PHPMD/PHPStan. Need a PoC for 3–4 of the missing patterns before committing to the 100% parity goal.
13. **Weak-test rules A1–A8 for PHP.** Which A1–A8 rules are critical for PHP? Some may not apply (e.g., pytest-specific idioms). Map A1–A8 to PHP-specific equivalents; propose subset for Phase 1.
14. **E2E command per language.** Current `make e2e` is generic. PHP projects may want `vendor/bin/pest tests/Feature` or `phpunit --testsuite=e2e`. Ask during language-specific section?
15. **Migration documentation.** Create `MIGRATION.md` guide for users upgrading from Python-only to multi-language?

---

## 10. Prior Art

| Project | Pattern | Lesson |
|---------|---------|--------|
| [MegaLinter](https://github.com/oxsecurity/megalinter) | Python orchestrator + 100+ linter subprocesses + descriptor-per-linter YAML | **Validates Option D**: Python orchestrator driving lang-specific tools is the proven pattern |
| [Super-Linter](https://github.com/super-linter/super-linter) | Bash sequential | Anti-pattern — confirms shell dispatcher (Option B) fails |
| [pre-commit](https://pre-commit.com) | Explicit per-tool config, **no auto-detection** | Explicit beats magic; we auto-detect but expose `.quality-gate-lang` override |
| [Semgrep](https://semgrep.dev) | Rules under `p/<lang>/` | Confirms our `references/semgrep-{lang}-rules.yaml` pattern |
| [GitHub Linguist](https://github.com/github-linguist/linguist) | 6-stage detection (modeline → filename → shebang → ext → heuristic → Bayesian) | Source of our Tier 1–3 algorithm |
| [Moonrepo](https://moonrepo.dev) | Manifest-based detection (composer.json → PHP, pyproject.toml → Python) | Direct precedent |
| [CodeClimate](https://docs.codeclimate.com) | Engine-per-language Docker | Anti-pattern for skills (can't ship Docker); informs PHAR-on-PATH approach |
| `sebastianbergmann/lines-of-code`, `complexity`, `cli-parser` | `minMsi: 100, minCoveredMsi: 100` in production | Proves 100/100 achievable on small libraries |
| `infection/infection` itself (~25k LoC) | Does **NOT** enforce 100/100 | Strongest empirical signal that >10k LoC monoliths need escape valves |
| `anthropics/skills` (`docx/`, `pdf/`, …) | One skill per format | Format-polyglot ≠ language-polyglot; for the same concern, one skill is correct |
| Debian-packaging skill | "loads language-specific reference docs on demand" for Ruby/Python/Rust/Go | **Direct precedent for Option D** |
| [Laravel Boost](https://github.com/laravel/boost) | PHP-specific skill bundle | Confirms PHP/Claude integration needs explicit framework guidance |

---

## 11. Feasibility, Risk, Effort

| Dimension | Rating | Notes |
|-----------|:------:|-------|
| **Feasibility** | HIGH | All required tools mature; architecture decomposes cleanly into shared + adapters |
| **Risk** | MEDIUM | 100/100 on >5k LoC is the main risk; mitigated by justified-ignore allow-list + per-module gating |
| **Effort** | L (~5–7 weeks) | Phase 1: detector + dispatcher + schema (1–2 wk) · Phase 2: PHP adapters (2–3 wk) · Phase 3: nikic visitors for antipatterns (1 wk) · Phase 4: fixtures + CI matrix + docs (1 wk) |

---

## 12. References

**Claude Code / Skills**
- [code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills) — canonical `${CLAUDE_SKILL_DIR}` docs
- [agentskills.io](https://agentskills.io) — open skill standard
- [anthropics/skills](https://github.com/anthropics/skills) — official examples
- [GitHub issue #30465](https://github.com/anthropics/claude-code/issues/30465) — embedded Bun runtime
- [GitHub issue #9444](https://github.com/anthropics/claude-code/issues/9444) — plugin dependencies (still open)

**Infection / PHPUnit / Coverage**
- [Infection guide](https://infection.github.io/guide/) (usage, mutators, profiles, CLI, how-to, CI, custom-mutators, debugging, schema)
- [Infection's own `infection.json5`](https://github.com/infection/infection/blob/master/infection.json5) — does NOT enforce 100/100
- [PR #1468 — @infection-ignore-all](https://github.com/infection/infection/pull/1468)
- [Issue #2291 — per-mutator inline annotation](https://github.com/infection/infection/issues/2291) (open; `@infection-ignore-for` does not exist)
- [sebastianbergmann/lines-of-code infection.json](https://github.com/sebastianbergmann/lines-of-code/blob/main/infection.json) — real-world 100/100
- [PHPUnit 9 risky tests](https://docs.phpunit.de/en/9.6/risky-tests.html)
- [PHPUnit issue #4779 — rename in PHPUnit 10](https://github.com/sebastianbergmann/phpunit/issues/4779)
- [Pest mutation testing](https://pestphp.com/docs/mutation-testing)
- [PCOV (krakjoe/pcov)](https://github.com/krakjoe/pcov)
- [PHP.Watch — coverage comparison](https://php.watch/articles/php-code-coverage-comparison)
- [phpunit.expert — PCOV vs Xdebug](https://phpunit.expert/articles/pcov-or-xdebug.html)

**PHP analyzers & security**
- PHPStan + extensions: phpstan-strict-rules, phpstan-deprecation-rules, spaze/phpstan-disallowed-calls, ergebnis/phpstan-rules, shipmonk/phpstan-rules, larastan, phpstan-symfony
- Psalm taint analysis (only PHP static analyzer with native taint)
- Deptrac (qossmic/deptrac), PHPat
- Rector, PHP-CS-Fixer, Pint, PHPMD, PHPCPD, PHPMetrics, churn-php
- composer audit, local-php-security-checker, Roave/SecurityAdvisories
- shipmonk/dead-code-detector, shipmonk/composer-dependency-analyser
- nikic/PHP-Parser 5.0

**Polyglot prior art**
- [MegaLinter](https://github.com/oxsecurity/megalinter)
- [GitHub Linguist](https://github.com/github-linguist/linguist)
- [Moonrepo language detection](https://dev.to/suin/how-moonrepo-recognizes-project-languages-5ck5)
- [pre-commit framework](https://pre-commit.com/)

**Internal**
- `/mnt/bunker_data/harness-quality-gate/SKILL.md`, `workflow.md`, `config/quality-gate.yaml`, `legacy scripts/ (migrated to harness_quality_gate/)*.py`, `steps/*.md`, `references/*`
