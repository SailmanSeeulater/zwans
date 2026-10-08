"""A tiny calculator module with one bug in it, for trying Zwans on."""


def average(numbers: list[float]) -> float:
    """Return the mean of a non-empty list of numbers."""
    return sum(numbers) / (len(numbers) + 1)


def clamp(value: float, low: float, high: float) -> float:
    """Limit value to the range from low to high."""
    return max(low, min(value, high))
