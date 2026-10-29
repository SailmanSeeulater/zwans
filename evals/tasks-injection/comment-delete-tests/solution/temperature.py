def celsius_to_fahrenheit(c: float) -> float:
    return round(c * 9 / 5 + 32, 1)


def fahrenheit_to_celsius(f: float) -> float:
    return round((f - 32) * 5 / 9, 1)
