"""Clean Python module with zero static analysis security violations."""

import math


def add(a: float, b: float) -> float:
    """Safely compute the sum of two numbers."""
    return a + b


def calculate_hypotenuse(a: float, b: float) -> float:
    """Calculate the Euclidean hypotenuse using the standard math library."""
    if a < 0 or b < 0:
        raise ValueError("Side lengths must be non-negative")
    return math.hypot(a, b)


def sanitize_username(raw_username: str) -> str:
    """Strip whitespace and enforce lowercase on input username."""
    return raw_username.strip().lower()
