"""Money is kept in whole cents (int) everywhere. These helpers turn text into cents and
back, and do the one kind of rounding the shop uses: half up, on the final amount."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from shopdesk.errors import InvalidInput

CENT = Decimal("1")


def parse_money(text: str | int | float) -> int:
    """"12.50" -> 1250, "12" -> 1200, "0.5" -> 50. More than two decimals is an error."""
    if isinstance(text, int):
        return text * 100
    raw = str(text).strip().replace(",", ".") if isinstance(text, str) else repr(text)
    if raw.startswith("£") or raw.startswith("$") or raw.startswith("€"):
        raw = raw[1:].strip()
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        raise InvalidInput(f"Not an amount of money: {text!r}") from None
    if not amount.is_finite():
        raise InvalidInput(f"Not an amount of money: {text!r}")
    cents = amount * 100
    if cents != cents.to_integral_value():
        raise InvalidInput(f"Too many decimals in {text!r}")
    return int(cents)


def format_money(cents: int, currency: str | None = None) -> str:
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(cents), 100)
    text = f"{sign}{whole}.{part:02d}"
    return f"{text} {currency}" if currency else text


def round_half_up(amount: Decimal) -> int:
    return int(amount.quantize(CENT, rounding=ROUND_HALF_UP))


def percent_of(cents: int, percent: int | Decimal) -> int:
    """`percent` percent of `cents`, rounded half up to a cent."""
    return round_half_up(Decimal(cents) * Decimal(percent) / Decimal(100))


def apply_rate(cents: int, rate: Decimal) -> int:
    """`cents` times a rate such as Decimal("0.20"), rounded half up."""
    return round_half_up(Decimal(cents) * rate)


def require_non_negative(cents: int, what: str) -> int:
    if cents < 0:
        raise InvalidInput(f"{what} can't be negative.")
    return cents
