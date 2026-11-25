"""Repeat rules for series of appointments."""

from __future__ import annotations

import calendar
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from .errors import ValidationError
from .timeutil import format_date, parse_date

FREQUENCIES = ("daily", "weekdays", "weekly", "fortnightly", "monthly")
MAX_OCCURRENCES = 104


@dataclass(frozen=True)
class Recurrence:
    freq: str
    count: int | None = None
    until: date | None = None
    interval: int = 1

    def __post_init__(self) -> None:
        if self.freq not in FREQUENCIES:
            raise ValidationError(f"bad repeat {self.freq!r}: one of {', '.join(FREQUENCIES)}")
        if self.count is None and self.until is None:
            raise ValidationError("a series needs a count or an end date")
        if self.count is not None and not 1 <= self.count <= MAX_OCCURRENCES:
            raise ValidationError(f"a series has 1 to {MAX_OCCURRENCES} appointments")
        if self.interval < 1:
            raise ValidationError("the repeat interval is at least 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "freq": self.freq,
            "count": self.count,
            "until": format_date(self.until) if self.until else None,
            "interval": self.interval,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Recurrence:
        until = data.get("until")
        return cls(
            freq=data["freq"],
            count=data.get("count"),
            until=parse_date(until) if until else None,
            interval=data.get("interval", 1),
        )

    def occurrences(self, first: datetime) -> Iterator[datetime]:
        """The start of every appointment in the series, `first` included."""
        produced = 0
        for when in self._candidates(first):
            if self.until is not None and when.date() > self.until:
                return
            yield when
            produced += 1
            if produced >= (self.count or MAX_OCCURRENCES):
                return

    def _candidates(self, first: datetime) -> Iterator[datetime]:
        if self.freq == "monthly":
            yield from self._monthly(first)
            return
        if self.freq == "weekdays":
            step, when = timedelta(days=1), first
            while True:
                if when.weekday() < 5:
                    yield when
                when += step
        days = {"daily": 1, "weekly": 7, "fortnightly": 14}[self.freq] * self.interval
        k = 0
        while True:
            yield first + timedelta(days=days * k)
            k += 1

    def _monthly(self, first: datetime) -> Iterator[datetime]:
        """Same day of the month; months too short for it are left out."""
        year, month = first.year, first.month
        while True:
            if first.day <= calendar.monthrange(year, month)[1]:
                yield first.replace(year=year, month=month)
            month += self.interval
            while month > 12:
                month -= 12
                year += 1

    def describe(self) -> str:
        every = {"daily": "day", "weekdays": "weekday", "weekly": "week",
                 "fortnightly": "fortnight", "monthly": "month"}[self.freq]
        text = f"every {every}" if self.interval == 1 else f"every {self.interval} {every}s"
        if self.count:
            text += f", {self.count} times"
        if self.until:
            text += f", until {format_date(self.until)}"
        return text
