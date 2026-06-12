"""Assertion-counting fixes in the weak-test visitor — self-eval F13.

mock assertion methods (``m.assert_called_once_with``), unittest-style
``self.assertEqual`` and non-empty ``pytest.raises``/``warns`` blocks are
assertions; not counting them flagged 1369 false-positive A1 errors on
this repo's own suite.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from harness_quality_gate.adapters.python.weak_test import analyze_test_file


def _analyze(tmp_path: Path, body: str) -> list[dict]:
    f = tmp_path / "test_sample.py"
    f.write_text(textwrap.dedent(body), encoding="utf-8")
    return analyze_test_file(f)


def _violation_rules(tests: list[dict], name: str) -> set[str]:
    for t in tests:
        if t["name"] == name:
            return {v["rule"] for v in t.get("violations", [])}
    return set()


class TestMockAssertionsCounted:
    def test_mock_assert_methods_count_as_assertions(self, tmp_path: Path) -> None:
        tests = _analyze(tmp_path, """\
            def test_spy_wiring():
                m = object()
                m.assert_called_once_with(1)
                m.assert_not_called()
                m.assert_any_call(2)
        """)
        assert _violation_rules(tests, "test_spy_wiring").isdisjoint({"A1", "A2"})

    def test_unittest_assert_methods_count(self, tmp_path: Path) -> None:
        tests = _analyze(tmp_path, """\
            def test_unittest_style(self):
                self.assertEqual(1, 1)
                self.assertTrue(True)
                self.assertIn(1, [1])
        """)
        assert _violation_rules(tests, "test_unittest_style").isdisjoint({"A1", "A2"})

    def test_zero_assertions_still_flagged_a1(self, tmp_path: Path) -> None:
        tests = _analyze(tmp_path, """\
            def test_nothing():
                x = 1 + 1
                print(x)
        """)
        assert "A1" in _violation_rules(tests, "test_nothing")


class TestRaisesBlocksCounted:
    def test_nonempty_pytest_raises_counts_as_assertion(self, tmp_path: Path) -> None:
        tests = _analyze(tmp_path, """\
            import pytest

            def test_boom():
                with pytest.raises(ValueError):
                    int("x")
                with pytest.raises(KeyError):
                    {}["k"]
                assert True is True
        """)
        assert _violation_rules(tests, "test_boom").isdisjoint({"A1", "A2"})

    def test_empty_raises_does_not_count(self, tmp_path: Path) -> None:
        tests = _analyze(tmp_path, """\
            import pytest

            def test_empty():
                with pytest.raises(ValueError):
                    pass
        """)
        rules = _violation_rules(tests, "test_empty")
        assert "A7" in rules  # empty raises stays flagged
        assert "A1" in rules  # and contributes no assertion
