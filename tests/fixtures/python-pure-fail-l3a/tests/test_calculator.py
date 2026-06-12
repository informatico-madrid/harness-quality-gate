"""Basic tests."""
from calculator import add


def test_one() -> None:
    assert add(1, 2) == 3
