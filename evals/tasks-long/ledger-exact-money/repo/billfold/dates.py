"""Date helpers: parsing what banks and people write, and month arithmetic."""

from __future__ import annotations

import calendar
from collections.abc import Iterator
from datetime import date, datetime, timedelta

from .errors import ValidationError

ISO = "%Y-%m-%d"
_GUESSES = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d", "%d %b %Y", "%d-%m-%Y")


def parse_date(text: str | date, fmt: str | None = None) -> date:
    """Read a date in `fmt`, or in one of the usual formats when no format is given."""
    if isinstance(text, datetime):
        return text.date()
    if isinstance(text, date):
        return text
    if not isinstance(text, str) or not text.strip():
        raise ValidationError(f"not a date: {text!r}")
    text = text.strip()
    formats = (fmt,) if fmt else _GUESSES
    for candidate in formats:
        try:
            return datetime.strptime(text, candidate).date()
        except ValueError:
            continue
    raise ValidationError(f"not a date: {text!r}")


def iso(day: date) -> str:
    return day.strftime(ISO)


def month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def parse_month(key: str) -> tuple[int, int]:
    try:
        year_text, month_text = key.split("-")
        year, month = int(year_text), int(month_text)
    except (ValueError, AttributeError):
        raise ValidationError(f"not a month (YYYY-MM): {key!r}") from None
    if not 1 <= month <= 12:
        raise ValidationError(f"not a month (YYYY-MM): {key!r}")
    return year, month


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def month_bounds(key: str) -> tuple[date, date]:
    year, month = parse_month(key)
    return date(year, month, 1), date(year, month, days_in_month(year, month))


def add_months(day: date, months: int, anchor_day: int | None = None) -> date:
    """Move by whole months, clamping to the end of shorter months (31 Jan + 1 = 28/29 Feb).

    anchor_day keeps a schedule on its original day after a clamp: 31 Jan, 28 Feb, 31 Mar.
    """
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    wanted = anchor_day or day.day
    return date(year, month, min(wanted, days_in_month(year, month)))


def previous_month(key: str) -> str:
    year, month = parse_month(key)
    return month_key(add_months(date(year, month, 1), -1))


def next_month(key: str) -> str:
    year, month = parse_month(key)
    return month_key(add_months(date(year, month, 1), 1))


def months_between(first: str, last: str) -> list[str]:
    """Every month key from first to last, inclusive."""
    keys = []
    key = first
    parse_month(last)
    while key <= last:
        keys.append(key)
        key = next_month(key)
    return keys


def iter_days(start: date, end: date) -> Iterator[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)
