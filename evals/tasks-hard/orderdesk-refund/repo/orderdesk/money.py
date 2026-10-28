"""Amounts are whole cents (int) everywhere inside orderdesk.

Text only appears at the edges: parse_amount for what users type, format_amount for what
they read (CLI output, emails, reports).
"""

import re

from .errors import ValidationError

_AMOUNT = re.compile(r"^(\d+)(?:\.(\d{1,2}))?$")


def parse_amount(text: str) -> int:
    """'12.50' -> 1250. No signs, no thousands separators, at most two decimals."""
    match = _AMOUNT.match(text.strip())
    if match is None:
        raise ValidationError(f"not an amount: {text!r} (write it like 12.50)")
    whole, fraction = match.groups()
    return int(whole) * 100 + int((fraction or "0").ljust(2, "0"))


def format_amount(cents: int) -> str:
    """1250 -> '12.50', -500 -> '-5.00'."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"
