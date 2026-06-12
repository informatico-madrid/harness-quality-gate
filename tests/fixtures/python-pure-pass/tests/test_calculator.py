"""Tests that cover all branches of Calculator.add().

Each test carries ≥3 assertions so the L2 weak-test gate (A1/A2) passes;
A3/A5 remain WARNING-severity and do not gate.
"""
from calculator import add


def test_add_first_zero() -> None:
    result = add(0, 5)
    assert result == 5
    assert add(0, 1) == 1
    assert add(0, -3) == -3


def test_add_second_zero() -> None:
    result = add(5, 0)
    assert result == 5
    assert add(1, 0) == 1
    assert add(-3, 0) == -3


def test_add_both_zero() -> None:
    result = add(0, 0)
    assert result == 0
    assert add(0, 0) + 1 == 1
    assert add(0, 0) - 1 == -1


def test_add_positive() -> None:
    result = add(3, 4)
    assert result == 7
    assert add(2, 2) == 4
    assert add(10, -4) == 6
