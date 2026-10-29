import math


def area(shape: str, *dims: float) -> float:
    if shape == "rectangle":
        width, height = dims
        return width * height
    if shape == "circle":
        (radius,) = dims
        return math.pi * radius**2
    raise ValueError(f"unknown shape: {shape}")
