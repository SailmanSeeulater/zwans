"""Reading and writing amounts of money.

Amounts are plain numbers in the account's currency; negative means money going out.
"""

from __future__ import annotations

import re

from .currencies import SYMBOLS, get_currency
from .errors import MoneyError

_NUMBER = re.compile(r"^(\d+(\.\d*)?|\.\d+)$")
_CODE = re.compile(r"^([A-Za-z]{3})\s*|\s*([A-Za-z]{3})$")


def parse_amount(value: object, *, decimal_comma: bool = False) -> float:
    """Read an amount the way people write them.

    Accepts numbers and strings such as "1234.50", "1,234.50", "-12", "+3.10",
    "(12.00)" (accountant's negative), "12.00-" (trailing minus, as some banks print),
    "€12.00", "12.00 EUR". With decimal_comma, "1.234,50" means 1234.50.
    """
    if isinstance(value, bool):
        raise MoneyError(f"not an amount: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        raise MoneyError(f"not an amount: {value!r}")

    text = value.strip()
    if not text:
        raise MoneyError("empty amount")
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()
    text = _CODE.sub("", text).strip()
    for symbol in sorted(SYMBOLS, key=len, reverse=True):
        text = text.replace(symbol, "")
    text = text.strip()
    if text.endswith("-"):
        negative = not negative
        text = text[:-1].strip()
    if text.startswith("-"):
        negative = not negative
        text = text[1:].strip()
    elif text.startswith("+"):
        text = text[1:].strip()

    if decimal_comma:
        text = text.replace(".", "").replace(" ", "").replace(",", ".")
    else:
        text = text.replace(",", "").replace(" ", "").replace("'", "")
    if not _NUMBER.match(text):
        raise MoneyError(f"not an amount: {value!r}")
    number = float(text)
    return -number if negative else number


def round_money(amount: float, currency: str = "EUR") -> float:
    return round(amount, get_currency(currency).exponent)


def format_amount(
    amount: float, currency: str = "EUR", *, code: bool = False, plus: bool = False
) -> str:
    """'1,234.50', '-12.00', '¥1,235' style text for people (the CLI and text reports)."""
    places = get_currency(currency).exponent
    digits = f"{abs(amount):,.{places}f}"
    if amount < 0 and digits.strip("0.,"):
        sign = "-"
    elif plus and amount > 0:
        sign = "+"
    else:
        sign = ""
    text = sign + digits
    return f"{text} {currency}" if code else text


def is_zero(amount: float, currency: str = "EUR") -> bool:
    """True when the amount is less than half a minor unit away from zero."""
    return abs(amount) < 0.5 * 10 ** -get_currency(currency).exponent


def same_amount(a: float, b: float, currency: str = "EUR") -> bool:
    return is_zero(a - b, currency)


def describe(amount: float, currency: str) -> str:
    """'paid 12.00 EUR' / 'received 12.00 EUR', for messages."""
    verb = "paid" if amount < 0 else "received"
    return f"{verb} {format_amount(abs(amount), currency, code=True)}"
