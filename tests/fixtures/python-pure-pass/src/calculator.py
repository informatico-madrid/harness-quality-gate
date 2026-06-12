"""A simple calculator forking-free pure function module — all tests cover all branches."""


def add(a: int, b: int) -> int:
    if a == 0:
        return b
    if b == 0:
        return a
    return a + b
