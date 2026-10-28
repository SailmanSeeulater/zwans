"""Amounts of money and conversion to euros.

`data/rates.json` maps a currency code to a list of rates, each `{"from": DATE, "eur": X}`:
from DATE onwards (until the next entry), one unit of the currency is worth X euros.
Euros themselves need no entry.
"""

import json
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

CENT = Decimal("0.01")


class RateError(Exception):
    pass


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __str__(self) -> str:
        return f"{self.amount:,.2f} {self.currency}"


class Rates:
    def __init__(self, table: dict[str, list[tuple[date, Decimal]]]):
        self._table = {code: sorted(entries) for code, entries in table.items()}

    def rate(self, currency: str, on: date) -> Decimal:
        """Euros per unit of `currency`, as published for the date `on`."""
        if currency == "EUR":
            return Decimal(1)
        entries = self._table.get(currency)
        if not entries:
            raise RateError(f"no rates for {currency}")
        i = bisect_right([day for day, _ in entries], on) - 1
        if i < 0:
            raise RateError(f"no {currency} rate on or before {on}")
        return entries[i][1]

    def to_eur(self, money: Money, on: date) -> Decimal:
        return (money.amount * self.rate(money.currency, on)).quantize(CENT, ROUND_HALF_UP)


def load_rates(path: Path) -> Rates:
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    table = {
        code: [(date.fromisoformat(entry["from"]), Decimal(str(entry["eur"]))) for entry in entries]
        for code, entries in raw.items()
    }
    return Rates(table)
