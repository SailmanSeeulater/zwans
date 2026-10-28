"""Turning amounts typed by people into cents, and back."""


def parse_amount(text: str) -> int:
    """Parse an amount like "12.50", "-3", "1,200.05" or "(4.10)" into cents.

    Parentheses mean a negative amount, the way accountants write it.
    """
    cleaned = text.strip().replace(",", "").replace("$", "")
    negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):
        negative = True
        cleaned = cleaned[1:-1]
    if cleaned.startswith("-"):
        negative = not negative
        cleaned = cleaned[1:]
    if not cleaned:
        raise ValueError(f"not an amount: {text!r}")
    whole, _, fraction = cleaned.partition(".")
    if not whole.isdigit() and whole != "":
        raise ValueError(f"not an amount: {text!r}")
    if len(fraction) > 2 or (fraction and not fraction.isdigit()):
        raise ValueError(f"not an amount: {text!r}")
    cents = int(whole or "0") * 100 + int(fraction.ljust(2, "0") or "0")
    return -cents if negative else cents


def format_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100:,}.{cents % 100:02d}"
