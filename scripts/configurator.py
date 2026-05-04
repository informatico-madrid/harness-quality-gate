#!/usr/bin/env python3
"""
Quality Gate Configurator

Auto-discovers project structure and guides user through configuration
with inferred defaults + custom option for each parameter.

Usage:
    python3 scripts/configurator.py /path/to/project
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any


def find_source_dirs(project_root: Path) -> list[str]:
    """Auto-detect source directories."""
    candidates = ["src", "lib", "app", "packages", "source"]
    found = []
    for cand in candidates:
        if (project_root / cand).is_dir():
            found.append(cand)
    return found if found else ["src"]


def find_tests_dir(project_root: Path) -> list[str]:
    """Auto-detect tests directories."""
    candidates = ["tests", "test", "spec", "specs"]
    found = []
    for cand in candidates:
        if (project_root / cand).is_dir():
            found.append(cand)
    return found if found else ["tests"]


def find_pyproject_config(project_root: Path) -> dict[str, Any]:
    """Extract existing quality-gate config from pyproject.toml."""
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return {}

    content = pyproject.read_text()
    config: dict[str, Any] = {}

    # Extract [tool.quality-gate.mutation] section
    if "[tool.quality-gate.mutation]" in content:
        in_section = False
        for line in content.splitlines():
            if "[tool.quality-gate.mutation]" in line:
                in_section = True
                continue
            if in_section:
                if line.startswith("[") and "tool.quality-gate" not in line:
                    break
                if "global_kill_threshold" in line:
                    match = re.search(r"=\s*(\d+\.?\d*)", line)
                    if match:
                        config["mutation_global_threshold"] = float(match.group(1))

    return config


def detect_has_docker(project_root: Path) -> bool:
    """Check if project has Dockerfile."""
    return any(
        (project_root / f).exists()
        for f in ["Dockerfile", "Dockerfile.custom", "docker-compose.yml"]
    )


def detect_has_e2e(project_root: Path) -> bool:
    """Check if project has E2E test setup."""
    return any(
        (project_root / f).exists()
        for f in ["Makefile", "tox.ini", "e2e"]
    ) or (project_root / "tests").exists() and any(
        "e2e" in f.name for f in (project_root / "tests").iterdir()
    )


def infer_config(project_root: Path) -> dict[str, Any]:
    """Infer configuration from project structure."""
    source_dirs = find_source_dirs(project_root)
    tests_dirs = find_tests_dir(project_root)
    pyproject_config = find_pyproject_config(project_root)
    has_docker = detect_has_docker(project_root)
    has_e2e = detect_has_e2e(project_root)

    return {
        "project": {
            "name": project_root.name,
            "root": str(project_root),
        },
        "paths": {
            "source": source_dirs[0] if source_dirs else "src",
            "tests": tests_dirs[0] if tests_dirs else "tests",
            "inferred": {
                "source_dirs_found": source_dirs,
                "tests_dirs_found": tests_dirs,
            },
        },
        "layer1": {
            "coverage_threshold": 85.0,
            "mutation_threshold": pyproject_config.get("mutation_global_threshold", 0.70),
            "e2e_mandatory": has_e2e,
            "e2e_command": "make e2e" if (project_root / "Makefile").exists() else None,
        },
        "layer4": {
            "severity_threshold": "high",
            "has_docker": has_docker,
            "target_dirs": source_dirs + ["scripts"],
        },
        "features": {
            "e2e_available": has_e2e,
            "docker_available": has_docker,
            "has_pyproject": (project_root / "pyproject.toml").exists(),
        },
    }


def print_banner():
    print("\n" + "=" * 60)
    print("  QUALITY GATE CONFIGURATOR")
    print("  Auto-discovery + Confirmation")
    print("=" * 60 + "\n")


def print_section(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print("─" * 60)


def ask_choice(prompt: str, options: list[str], default: str | None = None) -> str:
    """Ask user to choose from options with custom option."""
    print(f"\n{prompt}")
    for i, opt in enumerate(options, 1):
        marker = " (default)" if opt == default else ""
        print(f"  {i}) {opt}{marker}")
    print(f"  {len(options) + 1}) Custom (enter manual value)")

    while True:
        try:
            choice = input(f"\nSelect option (1-{len(options) + 1}) or press Enter for default: ").strip()
            if not choice and default:
                return default
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return options[idx]
            elif idx == len(options):
                return input("Enter custom value: ").strip()
            else:
                print(f"Please enter 1-{len(options) + 1}")
        except ValueError:
            print("Please enter a number")


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    """Ask yes/no question."""
    default_str = "Y/n" if default else "y/N"
    while True:
        response = input(f"{prompt} ({default_str}): ").strip().lower()
        if not response:
            return default
        if response in ["y", "yes", "s", "si"]:
            return True
        if response in ["n", "no"]:
            return False
        print("Please enter y or n")


def ask_number(prompt: str, default: float, min_val: float = 0.0, max_val: float = 100.0) -> float:
    """Ask for a number with default."""
    while True:
        response = input(f"{prompt} (default: {default}): ").strip()
        if not response:
            return default
        try:
            val = float(response)
            if min_val <= val <= max_val:
                return val
            print(f"Please enter a number between {min_val} and {max_val}")
        except ValueError:
            print("Please enter a number")


def run_configurator(project_root: Path) -> dict[str, Any]:
    """Run the interactive configurator."""
    print_banner()

    # Auto-discover configuration
    inferred = infer_config(project_root)

    print(f"Project: {inferred['project']['name']}")
    print(f"Root: {inferred['project']['root']}")
    print(f"\nAuto-discovered structure:")
    print(f"  Source directories: {inferred['paths']['inferred']['source_dirs_found']}")
    print(f"  Tests directories: {inferred['paths']['inferred']['tests_dirs_found']}")
    print(f"  Has Dockerfile: {inferred['layer4']['has_docker']}")
    print(f"  Has E2E setup: {inferred['features']['e2e_available']}")

    config = inferred.copy()

    # PATH CONFIGURATION
    print_section("PATH CONFIGURATION")

    source = ask_choice(
        "Source directory (where your Python code lives):",
        inferred["paths"]["inferred"]["source_dirs_found"],
        inferred["paths"]["source"]
    )
    config["paths"]["source"] = source

    tests = ask_choice(
        "Tests directory:",
        inferred["paths"]["inferred"]["tests_dirs_found"],
        inferred["paths"]["tests"]
    )
    config["paths"]["tests"] = tests

    # OUTPUT FOLDER
    print_section("OUTPUT CONFIGURATION")

    output_folders = ["_quality-gate", "_bmad-output/quality-gate", ".quality-gate", "quality-gate-output"]
    output_default = output_folders[0]
    output_folder = ask_choice(
        "Output folder for checkpoint JSONs:",
        output_folders,
        output_default
    )
    config["output"] = {"folder": output_folder}

    # LAYER 1 CONFIGURATION
    print_section("LAYER 1: TEST EXECUTION")

    coverage = ask_number(
        "Coverage threshold (%)",
        inferred["layer1"]["coverage_threshold"],
        0.0,
        100.0
    )
    config["layer1"]["coverage_threshold"] = coverage

    mutation = ask_number(
        "Mutation testing kill threshold (0.0-1.0)",
        inferred["layer1"]["mutation_threshold"],
        0.0,
        1.0
    )
    config["layer1"]["mutation_threshold"] = mutation

    # E2E
    if inferred["features"]["e2e_available"]:
        print(f"\nE2E tests detected: {inferred['layer1']['e2e_command'] or 'make e2e'}")
        e2e_mandatory = ask_yes_no("Make E2E tests mandatory (fail gate if not run)?", False)
        config["layer1"]["e2e_mandatory"] = e2e_mandatory
    else:
        e2e_enabled = ask_yes_no("Enable E2E tests (will look for 'make e2e')?", False)
        config["layer1"]["e2e_mandatory"] = e2e_enabled
        if e2e_enabled:
            config["layer1"]["e2e_command"] = "make e2e"

    # LAYER 4 CONFIGURATION
    print_section("LAYER 4: SECURITY")

    severity_options = ["critical", "high", "medium"]
    severity = ask_choice(
        "Severity threshold (blocking level):",
        severity_options,
        inferred["layer4"]["severity_threshold"]
    )
    config["layer4"]["severity_threshold"] = severity

    if inferred["layer4"]["has_docker"]:
        trivy_enabled = ask_yes_no("Enable Trivy Docker scanning?", True)
        config["layer4"]["trivy_enabled"] = trivy_enabled
    else:
        config["layer4"]["trivy_enabled"] = False

    # SECURITY TOOLS CUSTOMIZATION
    print_section("SECURITY TOOLS")

    print("The following tools will be configured:")
    print("  REQUIRED (block gate if missing/failing):")
    print("    - bandit, safety/pip-audit, gitleaks")
    print("  RECOMMENDED (skip if not installed):")
    print("    - semgrep, checkov, deptry, vulture")
    print("  OPTIONAL (never blocks):")
    print("    - trivy")

    semgrep_ha = ask_yes_no(
        "Include Home Assistant-specific semgrep rules (for HA integrations)?",
        False
    )
    config["features"]["semgrep_ha_rules"] = semgrep_ha

    # SUMMARY
    print_section("CONFIGURATION SUMMARY")

    print(json.dumps(config, indent=2))

    confirm = ask_yes_no("\nSave this configuration?", True)

    if confirm:
        return config
    else:
        print("\nConfiguration cancelled. Run again to reconfigure.")
        sys.exit(0)


def write_config(project_root: Path, config: dict[str, Any]) -> Path:
    """Write configuration to quality-gate.yaml."""
    output_dir = project_root / config["output"]["folder"]
    output_dir.mkdir(parents=True, exist_ok=True)

    config_file = output_dir / "quality-gate.yaml"

    semgrep_configs = (
        '      - p/security-audit\n'
        '      - p/owasp-top-ten\n'
        '      - "{skill-root}/references/semgrep-python-rules.yaml"\n'
        '      - "{skill-root}/references/semgrep-js-rules.yaml"'
    )
    if config["features"]["semgrep_ha_rules"]:
        semgrep_configs += '\n      - "{skill-root}/references/home-assistant/semgrep-ha-rules.yaml"'

    yaml_content = f'''# Quality Gate Configuration
# Generated by configurator.py
# Project: {config["project"]["name"]}

# Layer 1: Test Execution
layer1:
  coverage_threshold: {config["layer1"]["coverage_threshold"]}
  mutation_kill_threshold: {config["layer1"]["mutation_threshold"]}
  mutation_targets_source: "pyproject.toml"
  pytest_timeout_seconds: 300
  e2e:
    command: "{config["layer1"].get("e2e_command", "make e2e")}"
    mandatory: {str(config["layer1"]["e2e_mandatory"]).lower()}

# Layer 2: Test Quality
layer2:
  weak_test:
    max_assertions_single: 1
    min_assertions: 3
    max_mock_ratio: 0.8
    max_nesting_for_stateless: 0
    allow_sleep: false
    allow_empty_raises: false
    allow_trivial_assertions: false
  min_edit_distance: 20
  diversity_similarity_threshold: 0.8

# Layer 3: Code Quality
layer3:
  solid:
    srp:
      max_public_methods: 7
      max_loc_per_class: 200
      max_arity: 5
    ocp:
      min_abc_usage: true
    lsp:
      type_hint_coverage: 0.90
    isp:
      max_unused_methods_ratio: 0.5
    dip:
      max_import_depth: 3
      zero_cycles: true
  principles:
    dry:
      duplicate_code_threshold: 6
    kiss:
      max_function_complexity: 10
      max_nesting_depth: 4
      max_parameters: 5
    yagni:
      unused_imports_ratio: 0
      dead_code_ratio: 0
    lod:
      max_chain_length: 3
      no_dot_chaining: true
    coi:
      inheritance_depth_max: 2
      composition_ratio: 0.5
  antipatterns:
    ap01_god_class:
      max_loc: 500
      max_public_methods: 20
    ap02_functional_decomposition:
      min_static_methods: 3
    ap03_poltergeist:
      max_class_loc: 60
    ap04_spaghetti_code:
      min_nesting: 6
      min_loc: 50
    ap05_magic_numbers:
      allow_hardcoded: false
    ap06_long_method:
      max_lines: 100
    ap07_large_class:
      max_instance_variables: 15
    ap08_long_parameter_list:
      max_parameters: 5
    ap09_feature_envy:
      min_foreign_calls: 3
    ap10_data_class:
      min_attributes: 3
    ap11_lazy_class:
      max_methods: 3
    ap12_speculative_generality:
      max_implementations: 1
    ap13_middle_man:
      delegation_ratio: 0.8
    ap17_refused_bequest:
      empty_method_ratio: 0.5
    ap18_switch_statements:
      max_cases: 5
    ap20_deep_nesting:
      max_nesting: 5
    ap21_message_chains:
      max_chain: 3
    ap22_dead_code: {{}}
    ap23_duplicate_code:
      duplicate_lines: 6
    ap24_primitive_obsession:
      max_primitive_args: 5
    ap25_data_clumps:
      min_repetitions: 3
      min_param_count: 3
    ap26_inconsistent_naming:
      allow_ruff_violations: false
    ap30_circular_dependency:
      max_cycles: 0
    ap31_hub_spoke:
      max_incoming_imports: 15
    ap39_yoyo_problem:
      max_inheritance_depth: 5

# Layer 4: Security & Defense
layer4:
  severity_threshold: "{config["layer4"]["severity_threshold"]}"
  confidence_threshold: 0.7
  phases:
    phase1_deterministic: true
    phase2_dedup_confidence: true
    phase3_llm_triage: true
    phase4_party_mode: true
    phase5_fix_validation: true
  llm_disabled_behavior: SKIP_TO_PARTY_MODE
  confidence_threshold: 0.7
  consensus_escalation_threshold: 0.5
  fix_validation:
    max_attempts_per_finding: 2
    max_total_attempts: 5
    re_run_phase1_only: true
  party_mode:
    agents:
    - Winston
    - Murat
    - Amelia
    max_consensus_rounds: 3
    require_adversarial_review: true
    fallback_verdict: WARNING
  dedup:
    enabled: true
    line_range_tolerance: 5
    cross_validation_bonus: 0.3
    known_pattern_bonus: 0.2
  tools:
    bandit:
      priority: required
      targets:
      - {config["paths"]["source"]}
      - scripts
      skip_rules:
      - B101
      - B311
      max_critical: 0
      max_high: 0
      max_medium: 10
    safety:
      priority: required
      fallback: pip-audit
      ignore_cvss_below: 0.0
    gitleaks:
      priority: required
    semgrep:
      priority: recommended
      configs:
{semgrep_configs}
    checkov:
      priority: recommended
      frameworks:
      - dockerfile
      - yaml
      - json
      skip_paths:
      - .git
      - __pycache__
      - node_modules
      - .venv
      - _bmad-output
      - tests
    deptry:
      priority: recommended
    vulture:
      priority: recommended
      min_confidence: 80
    trivy:
      priority: optional
      scan_type: config

# Output configuration
output:
  folder: "{config["output"]["folder"]}"
  checkpoint_filename: quality-gate-{{{{timestamp}}}}.json
  latest_alias: quality-gate-latest.json

# Tool availability
tools:
  pytest: required
  ruff: required
  pyright: required
  check_headers: required
  mutmut: optional
  bmad_party_mode: optional
  bandit: required
  safety: required
  gitleaks: required
  semgrep: optional
  checkov: optional
  deptry: optional
  vulture: optional
  trivy: optional
'''

    config_file.write_text(yaml_content)
    print(f"\nConfiguration saved to: {config_file}")
    return config_file


def main():
    if len(sys.argv) < 2:
        project_root = Path.cwd()
    else:
        project_root = Path(sys.argv[1]).resolve()

    if not project_root.exists():
        print(f"Error: Directory does not exist: {project_root}")
        sys.exit(1)

    config = run_configurator(project_root)
    write_config(project_root, config)

    print("\n" + "=" * 60)
    print("  CONFIGURATION COMPLETE")
    print("=" * 60)
    print("\nNext steps:")
    print(f"  1. Review {config['output']['folder']}/quality-gate.yaml")
    print(f"  2. Run quality gate: python3 <skill-root>/scripts/security_scanner.py {project_root}")
    print(f"  3. Or follow workflow: See SKILL.md → On Activation")


if __name__ == "__main__":
    main()