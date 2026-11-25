"""Exchange rates and converting between currencies.

A rate base->quote on a date says how many units of `quote` one unit of `base` buys. The
rate used for a day is the latest one on or before it. When only quote->base is known,
the conversion goes through that one backwards.
"""

from __future__ import annotations

import bisect
import csv
from datetime import date
from pathlib import Path

from .currencies import get_currency, normalise_code
from .dates import parse_date
from .errors import ImportProblem, RateMissing, ValidationError
from .models import Rate


class RateTable:
    def __init__(self) -> None:
        self._rates: dict[tuple[str, str], list[tuple[date, float]]] = {}

    def set(self, base: str, quote: str, rate: float | str, on: date) -> Rate:
        base, quote = normalise_code(base), normalise_code(quote)
        if base == quote:
            raise ValidationError("a rate needs two different currencies")
        value = float(rate)
        if value <= 0:
            raise ValidationError(f"a rate must be positive, not {rate}")
        series = self._rates.setdefault((base, quote), [])
        days = [day for day, _ in series]
        index = bisect.bisect_left(days, on)
        if index < len(series) and series[index][0] == on:
            series[index] = (on, value)
        else:
            series.insert(index, (on, value))
        return Rate(base, quote, on, value)

    def _latest(self, base: str, quote: str, on: date) -> float | None:
        series = self._rates.get((base, quote))
        if not series:
            return None
        days = [day for day, _ in series]
        index = bisect.bisect_right(days, on)
        if index == 0:
            return None
        return series[index - 1][1]

    def find(self, base: str, quote: str, on: date) -> float:
        """The rate base->quote for a day, using quote->base backwards if needed."""
        base, quote = normalise_code(base), normalise_code(quote)
        if base == quote:
            return 1.0
        direct = self._latest(base, quote, on)
        if direct is not None:
            return direct
        backwards = self._latest(quote, base, on)
        if backwards is not None:
            return 1 / backwards
        raise RateMissing(f"no {base}->{quote} rate on or before {on.isoformat()}")

    def convert(self, amount: float, base: str, quote: str, on: date) -> float:
        """`amount` of base in quote, rounded to quote's minor unit."""
        rate = self.find(base, quote, on)
        return round(amount * rate, get_currency(quote).exponent)

    def all(self) -> list[Rate]:
        rates = []
        for (base, quote), series in sorted(self._rates.items()):
            rates.extend(Rate(base, quote, day, value) for day, value in series)
        return rates

    def pairs(self) -> list[tuple[str, str]]:
        return sorted(self._rates)

    def __len__(self) -> int:
        return sum(len(series) for series in self._rates.values())


def read_rates_csv(path: Path | str) -> list[tuple[date, str, str, float]]:
    """Rows of a rates file with the columns date, base, quote, rate."""
    rows = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = {"date", "base", "quote", "rate"} - set(reader.fieldnames or ())
        if missing:
            raise ImportProblem(f"rates file is missing columns: {', '.join(sorted(missing))}")
        for number, row in enumerate(reader, start=2):
            try:
                day = parse_date(row["date"])
                rate = float(row["rate"])
            except (ValueError, ValidationError) as error:
                raise ImportProblem(str(error), number) from None
            rows.append((day, row["base"].strip(), row["quote"].strip(), rate))
    return rows
