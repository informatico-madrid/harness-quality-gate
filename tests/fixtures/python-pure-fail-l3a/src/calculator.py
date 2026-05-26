"""Calculator with intentional lint issues (no return type hints)."""
import os


def add(a, b):  # missing type hints
    return a + b
