"""Money amounts.

The books keep a single currency, to the cent. Make amounts with parse_amount(); never
from user input directly. Wherever an amount has to be rounded (tax, discounts, splits) it
is rounded to the nearest cent with halves rounded up, away from zero, the way the finance
team's spreadsheet rounds.
"""

Money = float
ZERO: Money = 0.0


class AmountError(ValueError):
    pass


def parse_amount(text: str) -> Money:
    """Parse "1,234.50", "-3", or "(12.00)" (accounting style for -12.00)."""
    cleaned = text.strip().replace(",", "")
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]
    whole, _, cents = cleaned.lstrip("-").partition(".")
    if not whole.isdigit() or (cents and not cents.isdigit()) or len(cents) > 2:
        raise AmountError(f"not an amount: {text!r}")
    amount = float(cleaned)
    return -amount if negative else amount


def round_cents(amount: Money) -> Money:
    return round(amount, 2)


def percent_of(amount: Money, percent: str) -> Money:
    """`percent` per cent of `amount`, rounded to the cent. `percent` is text, like "8.25"."""
    return round_cents(amount * float(percent) / 100)


def format_amount(amount: Money) -> str:
    return f"{amount:,.2f}"
