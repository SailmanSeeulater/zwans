"""Billing periods shown on invoices."""

from dataclasses import dataclass
from datetime import date, timedelta

from billing.schedule import Subscription, renewal_dates


@dataclass(frozen=True)
class Period:
    first_day: date
    last_day: date

    def __str__(self) -> str:
        return f"{self.first_day.isoformat()} to {self.last_day.isoformat()}"


def billing_periods(sub: Subscription, count: int) -> list[Period]:
    """The first `count` billing periods: each runs up to the day before the next renewal."""
    boundaries = [sub.start, *renewal_dates(sub, count)]
    return [
        Period(begin, end - timedelta(days=1))
        for begin, end in zip(boundaries, boundaries[1:], strict=False)
    ]
