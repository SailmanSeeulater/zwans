"""Money is whole cents (int). Divisions round half up, explicitly, in one place."""


def round_half_up(numerator: int, denominator: int) -> int:
    """numerator / denominator rounded to the nearest int, halves going up. Both >= 0."""
    if numerator < 0 or denominator <= 0:
        raise ValueError("round_half_up works on non-negative amounts only")
    return (2 * numerator + denominator) // (2 * denominator)


def format_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}"
