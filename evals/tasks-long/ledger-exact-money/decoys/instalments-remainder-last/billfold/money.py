"""Reading, writing, rounding and sharing out amounts of money.

Amounts are `Decimal`s with exactly their currency's number of places; negative means
money going out. Floats are refused everywhere: they can't hold 0.10 exactly.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

from .currencies import SYMBOLS, get_currency
from .errors import MoneyError

_NUMBER = re.compile(r"^(\d+(\.\d*)?|\.\d+)$")
_CODE = re.compile(r"^([A-Za-z]{3})\s*|\s*([A-Za-z]{3})$")


def _no_float(value: object) -> None:
    if isinstance(value, float):
        raise TypeError(f"floats can't hold money exactly; pass a str or Decimal, not {value!r}")


def parse_amount(value: object, *, decimal_comma: bool = False) -> Decimal:
    """Read an amount the way people write them, exactly as written.

    Accepts Decimal, int and strings such as "1234.50", "1,234.50", "-12", "+3.10",
    "(12.00)" (accountant's negative), "12.00-" (trailing minus, as some banks print),
    "€12.00", "12.00 EUR". With decimal_comma, "1.234,50" means 1234.50.
    """
    _no_float(value)
    if isinstance(value, bool):
        raise MoneyError(f"not an amount: {value!r}")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise MoneyError(f"not an amount: {value!r}")
        return value
    if isinstance(value, int):
        return Decimal(value)
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
    number = Decimal(text)
    return -number if negative else number


def decimal_number(value: object, what: str = "number") -> Decimal:
    """A plain decimal (a rate, a weight, a percentage): Decimal, int or str, no floats."""
    _no_float(value)
    if isinstance(value, bool):
        raise MoneyError(f"not a {what}: {value!r}")
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, str):
        try:
            number = Decimal(value.strip().replace(",", ""))
        except InvalidOperation:
            raise MoneyError(f"not a {what}: {value!r}") from None
    else:
        raise MoneyError(f"not a {what}: {value!r}")
    if not number.is_finite():
        raise MoneyError(f"not a {what}: {value!r}")
    return number


def places(currency: str) -> int:
    return get_currency(currency).exponent


def quantum(currency: str) -> Decimal:
    return Decimal(1).scaleb(-places(currency))


def _tidy(amount: Decimal) -> Decimal:
    """No negative zero: -0.00 reads badly in files and exports."""
    return amount.copy_abs() if amount == 0 else amount


def zero(currency: str) -> Decimal:
    return Decimal(0).quantize(quantum(currency))


def to_amount(value: object, currency: str) -> Decimal:
    """An amount in `currency`: exactly its places, refusing anything finer."""
    number = parse_amount(value)
    unit = quantum(currency)
    try:
        exact = number.quantize(unit)
    except InvalidOperation:
        raise MoneyError(f"amount out of range: {value!r}") from None
    if exact != number:
        raise MoneyError(
            f"{value!r} has more decimal places than {currency.upper()} allows "
            f"({places(currency)})"
        )
    return _tidy(exact)


def round_half_up(value: Decimal, currency: str) -> Decimal:
    """Round once to the currency's places, halves away from zero."""
    return _tidy(value.quantize(quantum(currency), rounding=ROUND_HALF_UP))


round_money = round_half_up


def amount_text(amount: Decimal, currency: str) -> str:
    """'1234.50', '-12.00', '1500': amounts in files, exports and alert payloads."""
    return format(_tidy(Decimal(amount).quantize(quantum(currency))), "f")


def to_minor(amount: Decimal, currency: str) -> int:
    return int(amount.scaleb(places(currency)).to_integral_value())


def from_minor(units: int, currency: str) -> Decimal:
    return _tidy(Decimal(units).scaleb(-places(currency)))


def share_evenly(total: Decimal, parts: int, currency: str) -> list[Decimal]:
    """Equal parts rounded toward zero; leftover minor units go to the first parts."""
    if parts < 1:
        raise MoneyError("share over at least one part")
    sign = -1 if total < 0 else 1
    base, extra = divmod(abs(to_minor(total, currency)), parts)
    return [from_minor(sign * (base + (1 if i < extra else 0)), currency) for i in range(parts)]


def share_by_weight(total: Decimal, weights: Sequence[Decimal], currency: str) -> list[Decimal]:
    """Exact shares rounded toward zero; leftover minor units go to the largest remainders
    (ties to the earlier part)."""
    if not weights:
        raise MoneyError("share over at least one part")
    sign = -1 if total < 0 else 1
    units = abs(to_minor(total, currency))
    weight_sum = sum(weights, Decimal(0))
    exact = [Decimal(units) * weight / weight_sum for weight in weights]
    floors = [int(value.to_integral_value(rounding=ROUND_DOWN)) for value in exact]
    left = units - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: (-(exact[i] - floors[i]), i))
    for index in order[:left]:
        floors[index] += 1
    return [from_minor(sign * units_each, currency) for units_each in floors]


def format_amount(
    amount: Decimal, currency: str = "EUR", *, code: bool = False, plus: bool = False
) -> str:
    """'1,234.50', '-12.00', '1,500' style text for people (the CLI and text reports)."""
    amount = Decimal(amount).quantize(quantum(currency))
    digits = f"{abs(amount):,f}"
    if amount < 0:
        sign = "-"
    elif plus and amount > 0:
        sign = "+"
    else:
        sign = ""
    text = sign + digits
    return f"{text} {currency}" if code else text


def is_zero(amount: Decimal, currency: str = "EUR") -> bool:
    return amount == 0


def same_amount(a: Decimal, b: Decimal, currency: str = "EUR") -> bool:
    return a == b


def describe(amount: Decimal, currency: str) -> str:
    """'paid 12.00 EUR' / 'received 12.00 EUR', for messages."""
    verb = "paid" if amount < 0 else "received"
    return f"{verb} {format_amount(abs(amount), currency, code=True)}"
