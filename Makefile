# Makefile for harness-quality-gate
# Uses mutmut 3.5.0 with --max-children for parallel execution
# Note: paths_to_mutate is configured in pyproject.toml, NOT as CLI flag

.PHONY: mutation mutation-cli mutation-full clean

MUTATION_MAX_CHILDREN ?= $(shell nproc)

# Update mutmut to 3.5.0 (same as ha-ev-trip-planner) to get --max-children support
update-mutmut:
	@echo "Upgrading mutmut to >=3.5.0 (same as ha-ev-trip-planner)..."
	pip3 install --upgrade "mutmut>=3.5.0"
	@echo "Verified version:"
	python3 -m mutmut --version

# Run mutmut on ALL files in paths_to_mutate (from pyproject.toml) with --max-children for parallel execution
mutation:
	@echo "Running mutmut with --max-children=$(MUTATION_MAX_CHILDREN) (parallel execution)"
	@echo "Configuration from pyproject.toml:"
	@echo "  - paths_to_mutate: $(MUTATION_PATHS)"
	@echo "  - mutate_only_covered_lines = true"
	@echo "  - backup = false"
	rm -rf .mutmut-cache .mutmut-state
	python3 -m mutmut run --max-children=$(MUTATION_MAX_CHILDREN) 2>&1 | tee mutation_results.out
	@echo ""
	@echo "Results saved to mutation_results.out"

# Run mutmut on cli.py only (for quick testing)
# Uses positional argument (path after 'run') instead of --paths-to-mutate flag
mutation-cli:
	@echo "Running mutmut on harness_quality_gate/cli.py with --max-children=$(MUTATION_MAX_CHILDREN)"
	rm -rf .mutmut-cache .mutmut-state
	python3 -m mutmut run harness_quality_gate/cli.py --max-children=$(MUTATION_MAX_CHILDREN) 2>&1 | tee mutation_cli_results.out
	@echo ""
	@echo "Results saved to mutation_cli_results.out"

# Run mutmut on ALL harness_quality_gate directory with --max-children
mutation-full:
	@echo "Running FULL mutation testing with --max-children=$(MUTATION_MAX_CHILDREN)"
	rm -rf .mutmut-cache .mutmut-state
	python3 -m mutmut run harness_quality_gate --max-children=$(MUTATION_MAX_CHILDREN) 2>&1 | tee mutation_full_results.out
	@echo ""
	@echo "Full results saved to mutation_full_results.out"

# Run mutmut with coverage-based filtering only (fastest, only tests covered lines)
mutation-covered:
	@echo "Running mutmut with mutate_only_covered_lines=true (fastest mode)"
	rm -rf .mutmut-cache .mutmut-state
	python3 -m mutmut run --max-children=$(MUTATION_MAX_CHILDREN) --test-time-multiplier=1.5 --test-time-out=30 2>&1 | tee mutation_covered_results.out
	@echo ""
	@echo "Results saved to mutation_covered_results.out"

# Clean mutmut cache
clean:
	rm -rf .mutmut-cache .mutmut-state
