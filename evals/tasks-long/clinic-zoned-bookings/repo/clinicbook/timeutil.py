"""Parsing and formatting of dates and times, and small calendar helpers."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta

DATETIME_FORMAT = "%Y-%m-%dT%H:%M"
DATE_FORMAT = "%Y-%m-%d"
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

_DATETIME_INPUTS = (
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
)
_DATE_INPUTS = ("%Y-%m-%d", "%d/%m/%Y")


def parse_datetime(text: str) -> datetime:
    """`2026-03-02T09:00`, `2026-03-02 09:00` (seconds allowed)."""
    text = text.strip()
    for fmt in _DATETIME_INPUTS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"not a date and time: {text!r} (expected YYYY-MM-DD HH:MM)")


def format_datetime(value: datetime) -> str:
    return value.strftime(DATETIME_FORMAT)


def parse_date(text: str) -> date:
    """`2026-03-02` or the old system's `02/03/2026`."""
    text = text.strip()
    for fmt in _DATE_INPUTS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"not a date: {text!r} (expected YYYY-MM-DD)")


def format_date(value: date) -> str:
    return value.strftime(DATE_FORMAT)


def parse_clock(text: str) -> int:
    """`08:30` -> 510 minutes after midnight. `24:00` is allowed, as a closing time."""
    hours, sep, minutes = text.strip().partition(":")
    if not sep or not hours.isdigit() or not minutes.isdigit() or len(minutes) != 2:
        raise ValueError(f"not a time of day: {text!r} (expected HH:MM)")
    total = int(hours) * 60 + int(minutes)
    if int(minutes) >= 60 or total > 24 * 60:
        raise ValueError(f"not a time of day: {text!r}")
    return total


def format_clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def minutes_of_day(value: datetime) -> int:
    return value.hour * 60 + value.minute


def weekday_key(day: date) -> str:
    return WEEKDAYS[day.weekday()]


def at(day: date, minutes: int) -> datetime:
    """The time `minutes` after midnight on `day` (1440 is the next midnight)."""
    return datetime.combine(day, time()) + timedelta(minutes=minutes)


def on_grid(value: datetime, step: int) -> bool:
    return value.second == 0 and value.microsecond == 0 and minutes_of_day(value) % step == 0


def ceil_to_grid(value: datetime, step: int) -> datetime:
    """The first time at or after `value` that is a whole multiple of `step` minutes."""
    base = value.replace(second=0, microsecond=0)
    if base < value:
        base += timedelta(minutes=1)
    remainder = minutes_of_day(base) % step
    if remainder:
        base += timedelta(minutes=step - remainder)
    return base


def date_range(first: date, last: date) -> Iterator[date]:
    """Every day from `first` to `last`, both included."""
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)
