"""Calendar arithmetic for billing."""

import calendar
from datetime import date

_DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def days_in_month(year: int, month: int) -> int:
    if month == 2 and calendar.isleap(year):
        return 29
    return _DAYS_IN_MONTH[month - 1]


def add_months(d: date, months: int, day: int | None = None) -> date:
    """The date `months` calendar months after `d` (months >= 0).

    The result falls on `day` (default: d.day), or on the last day of the target month if
    that month is shorter.
    """
    if months < 0:
        raise ValueError("months must not be negative")
    total = d.month - 1 + months  # months since January of d.year
    year = d.year + total // 12
    month = total % 12 + 1
    wanted = day if day is not None else d.day
    return date(year, month, min(wanted, days_in_month(year, month)))
