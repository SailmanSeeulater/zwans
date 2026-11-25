"""The currencies billfold knows about, and how many decimal places each one has."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import UnknownCurrency


@dataclass(frozen=True)
class Currency:
    code: str
    exponent: int
    symbol: str
    name: str

    @property
    def minor_units(self) -> int:
        """How many minor units make one major unit (100 cents to the euro)."""
        return 10**self.exponent


_TABLE = (
    Currency("EUR", 2, "€", "Euro"),
    Currency("USD", 2, "$", "US dollar"),
    Currency("GBP", 2, "£", "Pound sterling"),
    Currency("CHF", 2, "Fr.", "Swiss franc"),
    Currency("SEK", 2, "kr", "Swedish krona"),
    Currency("CAD", 2, "C$", "Canadian dollar"),
    Currency("JPY", 0, "¥", "Japanese yen"),
)

CURRENCIES: dict[str, Currency] = {currency.code: currency for currency in _TABLE}
SYMBOLS: dict[str, str] = {currency.symbol: currency.code for currency in _TABLE}


def get_currency(code: str) -> Currency:
    try:
        return CURRENCIES[code.upper()]
    except (KeyError, AttributeError):
        raise UnknownCurrency(str(code)) from None


def exponent(code: str) -> int:
    return get_currency(code).exponent


def is_known(code: str) -> bool:
    return isinstance(code, str) and code.upper() in CURRENCIES


def normalise_code(code: str) -> str:
    """'eur' -> 'EUR', raising UnknownCurrency for anything we don't know."""
    return get_currency(code).code
