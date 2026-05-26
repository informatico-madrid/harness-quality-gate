"""
Weak Test Engine — Strategy-pattern base for test quality detection.

This module provides the base engine class and detection result type for
the weak test detector strategy pattern. Concrete detector strategies
implement the evaluate() method to check individual quality rules.

Usage:
    from harness_quality_gate.bmad.weak_test_engine import WeakTestEngine, DetectionResult

    class MyDetector(WeakTestEngine):
        def rule_id(self) -> str:
            return "CUSTOM"

        def evaluate(self, test_data: dict) -> DetectionResult:
            # Custom detection logic
            ...
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class DetectionResult:
    """Result of a single rule evaluation against a test function.

    Attributes:
        rule: Rule identifier (e.g., "A1", "A2")
        description: Human-readable description of the violation
        severity: "ERROR" or "WARNING"
    """
    rule: str
    description: str
    severity: str = "WARNING"


class WeakTestEngine(ABC):
    """Abstract base for weak test detection strategies.

    Each concrete strategy implements evaluate() to check a specific
    quality criterion (A1-A9) against test function data collected by
    the WeakTestVisitor AST traversal.

    This enables strategy-pattern composition: multiple detectors can
    run independently and their results aggregated.
    """

    @abstractmethod
    def rule_id(self) -> str:
        """Return the rule identifier (e.g., 'A1', 'A2', 'CUSTOM')."""

    @abstractmethod
    def evaluate(self, test_data: dict[str, Any]) -> DetectionResult | None:
        """Evaluate a single test against this rule.

        Args:
            test_data: Dict collected by WeakTestVisitor with keys like
                assertions, mocks, calls, has_setup, has_teardown, etc.

        Returns:
            DetectionResult if violation found, None if test passes.
        """

    def batch_evaluate(self, tests: list[dict[str, Any]]) -> list[DetectionResult]:
        """Evaluate multiple tests against this rule.

        Args:
            tests: List of test data dicts from WeakTestVisitor.

        Returns:
            List of DetectionResult for violations found.
        """
        results: list[DetectionResult] = []
        for test_data in tests:
            result = self.evaluate(test_data)
            if result is not None:
                results.append(result)
        return results


class CompositeWeakTestEngine:
    """Runs multiple WeakTestEngine strategies and aggregates results."""

    def __init__(self) -> None:
        self._strategies: list[WeakTestEngine] = []

    def add_strategy(self, strategy: WeakTestEngine) -> None:
        """Add a detection strategy."""
        self._strategies.append(strategy)

    def evaluate(self, tests: list[dict[str, Any]]) -> dict[str, list[DetectionResult]]:
        """Run all strategies against all tests.

        Returns:
            Dict mapping rule_id to list of DetectionResults.
        """
        results: dict[str, list[DetectionResult]] = {}
        for strategy in self._strategies:
            results[strategy.rule_id()] = strategy.batch_evaluate(tests)
        return results
