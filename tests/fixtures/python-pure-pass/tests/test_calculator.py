"""Tests that cover all branches of Calculator.add()."""
from calculator import add


def test_add_first_zero() -> None:
    assert add(0, 5) == 5


def test_add_second_zero() -> None:
    assert add(5, 0) == 5


def test_add_both_zero() -> None:
    assert add(0, 0) == 0


def test_add_positive() -> None:
    assert add(3, 4) == 7
