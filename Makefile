# Makefile for harness-quality-gate mutation testing
# Mutmut 3.6.0 | 18-core parallel execution | Config: pyproject.toml [tool.mutmut]
#
# ═══════════════════════════════════════════════════════════
# COMPLETE MUTATION WORKFLOW — ANY AGENT CAN FOLLOW THIS
# ═══════════════════════════════════════════════════════════
#
# STEP BY STEP (ALL STEPS ARE MANDATORY — MUST follow this exact order):
#
#   1. make check-tests
#      ── Verify ALL 1139 tests pass BEFORE mutation (MANDATORY)
#
#   2. make coverage
#      ── Verify test coverage is 100% (MANDATORY — fails if < 100%)
#
#   3. make clean-mutmut
#      ── Clear mutmut cache (MANDATORY before each run)
#
#   4. make mutation
#      ── Run full mutmut on all 19 files (~20 min for 6851 mutants)
#
#   5. Parse results (automatic — shown at end of step 4):
#      ── Last line of log shows: 🎉 killed 🙁 survived ⏰ timeout
#      ── MSI = killed / total × 100 → Target: 100%
#
# FAIL STATE: If steps 1-3 fail, DO NOT proceed to step 4.
#
# ═══════════════════════════════════════════════════════════
# PARTIAL MUTATION (for parallel subagents working on different files)
# ═══════════════════════════════════════════════════════════
#
#   make mutation-path FILE_PATH=harness_quality_gate/adapters/php/php_adapter.py
#
#   - Each FILE_PATH gets its own isolated directory: mutant_<path>/
#   - Multiple agents can run mutation-path in parallel safely
#   - If FILE_PATH is missing, the command FAILS
#   - Mutants from different files don't conflict in .mutmut-cache/
#
# ═══════════════════════════════════════════════════════════
# HOW TO READ MUTMUT OUTPUT (last 5 lines of log):
# ═══════════════════════════════════════════════════════════
#
#   Example output line:
#     ⠇ 6851/6851  🎉 3804 🫥 0  ⏰ 1  🤔 0  🙁 3046  🔇 0  🧙 0
#
#   Emoji legend:
#     🎉   = killed/mutants eliminated (GOOD - tests caught them)
#     🙁   = survived/mutants passed tests (BAD - need more/better tests)
#     ⏰   = timeout (mutant ran too long, counted as survived)
#     🔇   = suppressed (test suite failed for this mutant, ignored)
#     🧙   = left alone (mutmut could not create mutation)
#     🫥   = not tested (no test covers this line of code)
#     ⠇   = spinner (shows total/surviving count being updated)
#
#   MSI formula:
#     MSI = killed / (killed + survived + timeout) × 100
#     Example: 3804 / (3804 + 3046 + 1) × 100 = 55.53%
#
# ═══════════════════════════════════════════════════════════
# KNOWN BUG — frozen importlib bootstrap error
# ═══════════════════════════════════════════════════════════
#
# Symptom:
#   FileNotFoundError: [Errno 2] No such file or directory:
#   '/.../mutants/<frozen importlib._bootstrap>'
#
# Cause:
#   Mutmut trampoline record_trampoline_hit() cannot handle frozen stdlib
#   module paths. When __main__.py is mutated, the trampoline tries to
#   resolve <frozen importlib._bootstrap> which raises FileNotFoundError.
#
# Prevention (ALREADY applied):
#   - __main__.py is EXCLUDED from paths_to_mutate in pyproject.toml
#   - pyproject.toml runner uses: pytest tests/unit/ -q --tb=no
#   - NEVER add mutmut_immune markers or -k filters to runner config
#
# If bug recurs: Verify pyproject.toml[tool.mutmut] does NOT list
#   __main__.py in paths_to_mutate array. Recheck runner= line does
#   not select tests that import mutated __main__.py.
#
# ═══════════════════════════════════════════════════════════

.PHONY: mutation mutation-path check-tests coverage clean-mutmut test-e2e help

# Load .env file if it exists
ifneq (,$(wildcard ./.env))
include .env
export
endif

MUTATION_MAX_CHILDREN ?= $(shell nproc)
VENV = .venv

help:
	@echo ""
	@echo "Available targets:"
	@echo "  make check-tests                          - Run all 1139 tests (step 1)"
	@echo "  make coverage                              - Run coverage (step 2)"
	@echo "  make clean-mutmut                          - Clear mutmut cache (step 3)"
	@echo "  make mutation                              - Full mutation on all files (step 4)"
	@echo "  make mutation-path FILE_PATH=<file.py>     - Partial mutation on single file"
	@echo "  make test-e2e                              - Run e2e suite (PHP tests skip without php/composer)"
	@echo "  make help                                  - Show this help"
	@echo ""

# ─────────────────────────────────────────────────────────
# 1. PRE-FLIGHT: Verify all tests pass (MANDATORY before mutation)
# ─────────────────────────────────────────────────────────
check-tests:
	@echo "Running all unit tests (pre-flight check for mutation testing)..."
	$(VENV)/bin/python -m pytest tests/unit/ -q --tb=no --ignore=tests/e2e
	@echo "All tests pass — ready for mutation testing"
	@echo "(e2e suite is separate: run 'make test-e2e' — needs PHP/composer for the PHP smoke)"

# ─────────────────────────────────────────────────────────
# 1b. E2E: Full-pipeline smoke tests (python + php fixtures)
# ─────────────────────────────────────────────────────────
test-e2e:
	@echo "Running e2e suite (PHP tests skip cleanly when php/composer are unavailable)..."
	$(VENV)/bin/python -m pytest tests/e2e/ -q -m e2e --tb=short

# ─────────────────────────────────────────────────────────
# 2. COVERAGE: Verify 100% test coverage (MANDATORY — fails if < 100%)
# ─────────────────────────────────────────────────────────
coverage:
	@echo "Running test coverage report (required: 100%)..."
	$(VENV)/bin/python -m pytest tests/unit/ --cov=harness_quality_gate --cov-report=term-missing -q --tb=no

# ─────────────────────────────────────────────────────────
# 3. CLEAN: Clear mutmut cache (MANDATORY before each run)
# ─────────────────────────────────────────────────────────
clean-mutmut:
	rm -rf .mutmut/ .mutmut-cache .mutmut-state mutants/
	mkdir -p mutants/harness_quality_gate
	@echo "Cache cleared — ready for fresh mutation run"

# ─────────────────────────────────────────────────────────
# 4. PRIMARY: Run full mutation testing (all cores, all files)
# ─────────────────────────────────────────────────────────
# Config: pyproject.toml [tool.mutmut] — paths_to_mutate, runner, timeout, etc.
# Source files: 19 Python files from paths_to_mutate config
# Expected: ~7047 mutants, ~25 min on 18 cores
mutation:
	@echo "╔══════════════════════════════════════════╗"
	@echo "║   Mutation Testing — Full Parallel Run  ║"
	@echo "╚══════════════════════════════════════════╝"
	@echo ""
	@echo "Cores:       $(MUTATION_MAX_CHILDREN)"
	@echo "Config:      pyproject.toml [tool.mutmut]"
	@echo "Source:      19 Python files"
	@echo "Expected:    ~6851 mutants / ~20 minutes"
	@echo ""
	@echo "──────── Step 1/4: Pre-flight test check ────────"
	$(VENV)/bin/python -m pytest tests/unit/ -q --tb=no --ignore=tests/e2e
	@echo ""
	@echo "──────── Step 2/4: Clean mutmut cache ────────"
	rm -rf .mutmut/ .mutmut-cache .mutmut-state
	mkdir -p mutants/harness_quality_gate
	@echo "Cache cleaned"
	@echo ""
	@echo "──────── Step 3/4: Running mutmut ────────"
	$(VENV)/bin/mutmut run --max-children=$(MUTATION_MAX_CHILDREN) 2>&1 | tee mutmut_run.log
	@echo ""
	@echo "╔══════════════════════════════════════════╗"
	@echo "║         MUTATION TEST COMPLETE           ║"
	@echo "╚══════════════════════════════════════════╝"
	@echo ""
	@echo "Full log:   mutmut_run.log"
	@echo "Saved:      results.txt"
	@echo ""
	@echo "Parsing emojis from last 5 lines of log:"
	@echo "  🎉 = killed   🙁 = survived   ⏰ = timeout"
	@echo ""
	@echo "── MUTATION SUMMARY ────────"
	@if [ -f mutmut_run.log ]; then \
		$(VENV)/bin/python scripts/parse_mutmut_results.py mutmut_run.log; \
	fi
	@echo ""
	@echo "── To re-parse anytime: ────────"
	@echo "  $(VENV)/bin/python scripts/parse_mutmut_results.py mutmut_run.log"

# ─────────────────────────────────────────────────────────
# 5. PARTIAL: Run mutation testing on a single file (for parallel subagents)
# ─────────────────────────────────────────────────────────
# USAGE (FILE_PATH parameter REQUIRED):
#   make mutation-path FILE_PATH=harness_quality_gate/adapters/php/php_adapter.py
#
# If FILE_PATH is not provided, the command FAILS.
#
# Creates: mutant_<path>/  — isolated directory with:
#   - mutation.log  — mutmut run output
#   - results.json  — parsed emoji counts
#   - results.txt   — human-readable summary
#
# EXAMPLES:
#   make mutation-path FILE_PATH=harness_quality_gate/adapters/php/php_adapter.py
#   make mutation-path FILE_PATH=harness_quality_gate/adapters/python/python_adapter.py
#
# Parallel safe: multiple agents can run different FILE_PATHs simultaneously.
# Each gets its own directory: mutant_<path>/ — no conflicts.
# Mutants from different files coexist in .mutmut-cache without issues.
#
# NOTE: FILE_PATH is used instead of PATH because PATH is a reserved
# Makefile variable containing the system $PATH environment variable.
mutation-path:
	@if [ -z "$(FILE_PATH)" ]; then \
		echo ""; \
		echo "ERROR: FILE_PATH parameter is required"; \
		echo "Usage: make mutation-path FILE_PATH=harness_quality_gate/adapters/php/php_adapter.py"; \
		echo "Or run full mutation: make mutation"; \
		echo ""; \
		exit 1; \
	fi
	@echo "════════════════════════════════════════════"
	@echo " Partial Mutation Testing: $(FILE_PATH)"
	@echo "════════════════════════════════════════════"
	@DIR_NAME=`echo "$(FILE_PATH)" | tr '/' '_' | tr '.' '_'`; \
	DIR="mutant_$$DIR_NAME"; \
	mkdir -p $$DIR; \
	MODULE_PATH=`echo "$(FILE_PATH)" | sed 's|/|.|g; s|\.py$$||'`; \
	echo "Output directory:  $$DIR/"; \
	echo "File:              $(FILE_PATH)"; \
	echo "Mutmut filter:     $$MODULE_PATH*"; \
	echo ""; \
	echo "──────── Step 1/4: Pre-flight test check ────────"; \
	$(VENV)/bin/python -m pytest tests/unit/ -q --tb=no --ignore=tests/e2e; \
	echo ""; \
	echo "──────── Step 2/4: Clean mutmut state ────────"; \
	rm -rf .mutmut/ .mutmut-cache .mutmut-state; \
	mkdir -p mutants/harness_quality_gate; \
	echo "Cache cleaned"; \
	echo ""; \
	echo "──────── Step 3/4: Running mutmut on $(FILE_PATH) ────────"; \
	$(VENV)/bin/mutmut run "$$MODULE_PATH*" --max-children=$(MUTATION_MAX_CHILDREN) 2>&1 | tee $$DIR/mutation.log; \
	echo ""; \
	echo "──────── Step 4/4: Parsing results ────────"; \
	echo ""; \
	echo "╔══════════════════════════════════════════╗"; \
	echo "║      MUTATION TEST COMPLETE              ║"; \
	echo "╚══════════════════════════════════════════╝"; \
	echo ""; \
	if [ -f $$DIR/mutation.log ]; then \
		$(VENV)/bin/python scripts/parse_mutmut_results.py $$DIR/mutation.log $$MODULE_PATH; \
	fi; \
	echo ""; \
	echo "Artifacts saved to: $$DIR/"; \
	echo "  mutation.log    — full mutmut output"; \
	echo "  results.json    — structured JSON"; \
	echo "  results.txt     — human-readable summary"
