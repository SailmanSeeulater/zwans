"""Money amounts.

The books keep a single currency, to the cent. Make amounts with parse_amount(); never
from user input directly. Wherever an amount has to be rounded (tax, discounts, splits) it
is rounded to the nearest cent with halves rounded up, away from zero, the way the finance
team's spreadsheet rounds.

Amounts are Decimals: binary floats can't hold most cent values exactly, so sums drift and
"half a cent" is often a hair under half.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

Money = Decimal
ZERO: Money = Decimal("0.00")
CENT = Decimal("0.01")


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
    try:
        amount = Decimal(cleaned).quantize(CENT)
    except InvalidOperation:
        raise AmountError(f"not an amount: {text!r}") from None
    return -amount if negative else amount


def round_cents(amount: Money) -> Money:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def percent_of(amount: Money, percent: str) -> Money:
    """`percent` per cent of `amount`, rounded to the cent. `percent` is text, like "8.25"."""
    return round_cents(amount * Decimal(percent) / 100)


def format_amount(amount: Money) -> str:
    return f"{amount:,.2f}"
