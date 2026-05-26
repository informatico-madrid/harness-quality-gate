"""Configuration-file generator for harness-quality-gate.

Generates stub configuration files for quality-gate (v2), Infection,
PHPUnit, PHPStan, and Deptrac (PHP) or Pytest (Python) based on the
result of the language detector.

Design: configurator component, TD-10, E10
Requirements: FR-12, FR-13, FR-15, FR-20, FR-22, US-6, US-8, US-14
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[misc,assignment]

from .models import Detection


class ConfigInvalid(Exception):
    """Raised when a generated configuration would lower thresholds."""


@dataclass
class ConfigReport:
    """Report from configuration generation."""

    quality_gate_yaml: Path
    infection_json5: Path | None = None
    phpunit_xml: Path | None = None
    phpstan_neon: Path | None = None
    deptrac_yaml: Path | None = None
    errors: list[str] = field(default_factory=list)


def configure(
    repo: Path,
    detection: Detection,
    opts: dict[str, Any] | None = None,
) -> ConfigReport:
    """Configure quality-gate for the given repository.

    Args:
        repo: Path to repository root.
        detection: Result from the language detector.
        opts: Optional overrides (allow_ramp, frameworks, etc.).

    Returns:
        ConfigReport with paths to generated files.

    Raises:
        ConfigInvalid: If threshold lowering detected without --allow-ramp.
    """
    opts = opts or {}
    quality_gate_dir = repo / "_quality-gate"
    quality_gate_dir.mkdir(parents=True, exist_ok=True)

    quality_gate_yaml = quality_gate_dir / "quality-gate.yaml"
    report = ConfigReport(quality_gate_yaml=quality_gate_yaml)

    lang = detection.language.lower()

    _generate_quality_gate_yaml(quality_gate_yaml, detection)

    # Check threshold lowering
    if not opts.get("allow_ramp", False):
        _check_thresholds_raise(quality_gate_yaml)

    if lang == "php":
        report = _generate_php_configs(quality_gate_yaml, repo, detection, report)
    elif lang == "python":
        _generate_python_section(quality_gate_yaml, detection)
    else:
        report.errors.append(f"Unsupported language for configuration: {lang}")

    return report


def _generate_quality_gate_yaml(path: Path, detection: Detection) -> None:
    """Generate quality-gate.yaml v2."""
    if yaml is None:
        return

    lang = detection.language.lower()

    if lang == "php":
        l3a_tool = "phpstan"
        l1_tool = "phpunit"
        l2_tool = "phpmd"
        l4_tool = "php-security"
    elif lang == "python":
        l3a_tool = "ruff+pyright"
        l1_tool = "pytest"
        l2_tool = "ruff"
        l4_tool = "bandit+gitleaks"
    else:
        l3a_tool = l1_tool = l2_tool = l4_tool = "unknown"

    config = {
        "version": "2",
        "language": lang,
        "detection": {
            "framework": detection.framework,
            "confidence": detection.confidence,
        },
        "layers": {
            "l3a": {"enabled": True, "tool": l3a_tool},
            "l1": {"enabled": True, "tool": l1_tool},
            "l2": {"enabled": True, "tool": l2_tool},
            "l3b": {"enabled": True, "tool": "weak_test"},
            "l4": {"enabled": True, "tool": l4_tool},
        },
        "thresholds": {
            "min_msi": 100,
            "min_covered_msi": 100,
            "min_coverage": 100,
        },
    }

    path.write_text(yaml.dump(config, default_flow_style=False), encoding="utf-8")


def _check_thresholds_raise(path: Path) -> None:
    """Check if existing config has lowered Infection thresholds."""
    if yaml is None:
        return
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return

    if not isinstance(data, dict):
        return

    thresholds = data.get("thresholds", {})
    if not isinstance(thresholds, dict):
        return

    min_msi = thresholds.get("min_msi", 100)
    min_covered_msi = thresholds.get("min_covered_msi", 100)

    if isinstance(min_msi, (int, float)) and min_msi < 100:
        raise ConfigInvalid(
            "Infection MSI threshold lowered to {} — pass --allow-ramp to permit"
        )
    if isinstance(min_covered_msi, (int, float)) and min_covered_msi < 100:
        raise ConfigInvalid(
            "Infection covered MSI threshold lowered to {} — pass --allow-ramp to permit"
        )


def _generate_php_configs(
    quality_gate_yaml: Path,
    repo: Path,
    detection: Detection,
    report: ConfigReport,
) -> ConfigReport:
    """Generate PHP-specific config files."""
    qg_dir = quality_gate_yaml.parent

    infection_json5 = qg_dir / "infection.json5"
    _generate_infection(infection_json5)
    report.infection_json5 = infection_json5.relative_to(repo)

    phpunit_xml = qg_dir / "phpunit.xml"
    _generate_phpunit(phpunit_xml)
    report.phpunit_xml = phpunit_xml.relative_to(repo)

    phpstan_neon = qg_dir / "phpstan.neon"
    _generate_phpstan(phpstan_neon, detection)
    report.phpstan_neon = phpstan_neon.relative_to(repo)

    deptrac_yaml = qg_dir / "deptrac.yaml"
    _generate_deptrac(deptrac_yaml)
    report.deptrac_yaml = deptrac_yaml.relative_to(repo)

    return report


def _generate_infection(path: Path) -> None:
    """Generate infection.json5 stub."""
    config = {
        "minMsi": 100,
        "minCoveredMsi": 100,
        "timeoutsAsEscaped": True,
        "maxTimeouts": 0,
        "tmpDir": "var/infection",
    }
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def _generate_phpunit(path: Path) -> None:
    """Generate phpunit.xml with 11 strict-mode flags."""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<phpunit'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' xsi:noNamespaceSchemaLocation="vendor/phpunit/phpunit/phpunit.xsd"'
        ' strictMode="true"'
        ' stopOnFailure="true"'
        ' beStrictAboutCoverageMetrics="true"'
        ' beStrictAboutTodoAnnotatedTests="true"'
        ' bootstrap="vendor/autoload.php"'
        ' verbose="true"'
        ' testdox="true"'
        ' stopOnRisky="true"'
        ' stopOnSkipped="true"'
        ' beStrictAboutResourceUsageDuringSmallTests="true"'
        ' colors="true"'
        '>'
        "  <coverage pathCoverage=\"false\"/>"
        "</phpunit>"
    )
    path.write_text(xml, encoding="utf-8")


def _generate_phpstan(path: Path, detection: Detection) -> None:
    """Generate phpstan.neon with framework-conditional includes."""
    config: dict[str, Any] = {
        "includes": [
            "phpstan-baseline.neon",
            "phpstan.neon.dist",
        ],
    }

    frameworks = detection.frameworks.get("php", [])
    framework_includes = {
        "symfony": "phpstan-symfony",
        "laravel": "larastan",
        "drupal": "phpstan-drupal",
        "wordpress": "phpstan-wordpress",
    }
    for fw in frameworks:
        if fw in framework_includes:
            config["includes"].append(framework_includes[fw])

    path.write_text(yaml.dump(config, default_flow_style=False), encoding="utf-8")


def _generate_deptrac(path: Path) -> None:
    """Generate deptrac.yaml with Domain/Application/Infrastructure/UI starter layers."""
    config = {
        "paths": ["./src"],
        "layers": [
            {
                "name": "Domain",
                "path": ["./src/Domain"],
                "exclude": ["./src/Domain/Entity"],
            },
            {
                "name": "Application",
                "path": ["./src/Application"],
                "exclude": [],
            },
            {
                "name": "Infrastructure",
                "path": ["./src/Infrastructure"],
                "exclude": [],
            },
            {
                "name": "UI",
                "path": ["./src/UI"],
                "exclude": [],
            },
        ],
        "rules": [
            {"from": "Domain", "to": ["Domain", "Application", "Infrastructure", "UI"]},
            {"from": "Application", "to": ["Domain", "Application"]},
            {
                "from": "Infrastructure",
                "to": ["Domain", "Application", "Infrastructure"],
            },
            {"from": "UI", "to": ["Domain", "Application", "UI"]},
        ],
    }
    path.write_text(yaml.dump(config, default_flow_style=False), encoding="utf-8")


def _generate_python_section(quality_gate_yaml: Path, _detection: Detection) -> None:
    """Append Python-specific pytest section to quality-gate.yaml."""
    data = yaml.safe_load(quality_gate_yaml.read_text(encoding="utf-8")) or {}

    data.setdefault("language_profiles", {})
    data["language_profiles"]["python"]["pytest"] = {
        "testpaths": ["tests"],
        "python_files": ["test_*.py", "*_test.py"],
        "python_functions": ["test_*"],
        "python_classes": ["Test*"],
        "addopts": [
            "--strict-markers",
            "--strict-config",
            "--cov=harness_quality_gate",
            "--cov-report=term-missing",
            "--cov-report=xml",
        ],
        "min_cov": 100,
    }

    quality_gate_yaml.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
