"""Parsing and formatting of dates and times, and small calendar helpers."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from .errors import InvalidTime

DATETIME_FORMAT = "%Y-%m-%dT%H:%M"
INSTANT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
UTC = timezone.utc
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


def parse_when(text: str) -> datetime:
    """Like parse_datetime, but also takes an offset or `Z` (giving an aware datetime)."""
    text = text.strip()
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return parse_datetime(text)


# -- zones and instants -----------------------------------------------------------------


@lru_cache(maxsize=None)
def zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def localize(naive: datetime, tz: ZoneInfo, *, lenient: bool = False) -> datetime:
    """A wall-clock time in `tz`. Times that happen twice mean the first one (fold=0).

    A time skipped by the clocks going forward raises InvalidTime, or with `lenient` is
    moved forward by the length of the gap.
    """
    aware = naive.replace(tzinfo=tz, fold=0)
    normal = aware.astimezone(UTC).astimezone(tz)
    if normal.replace(tzinfo=None) != naive:
        if not lenient:
            raise InvalidTime(
                f"{naive.strftime('%Y-%m-%d %H:%M')} does not exist in {tz.key} "
                "(the clocks go forward)"
            )
        return normal
    return aware


def in_zone(value: datetime, tz: ZoneInfo) -> datetime:
    """A naive wall-clock time in `tz`, or an aware datetime moved to `tz`."""
    if value.tzinfo is None:
        return localize(value, tz)
    return value.astimezone(tz)


def instant(value: datetime) -> datetime:
    """The same moment in UTC; a naive value is taken to be UTC already."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def format_instant(value: datetime) -> str:
    return instant(value).strftime(INSTANT_FORMAT)


def parse_instant(text: str) -> datetime:
    """`2026-03-02T14:00:00Z` (or a naive time, meaning UTC) as an aware UTC datetime."""
    return instant(parse_when(text))


def end_of(start: datetime, minutes: int) -> datetime:
    """`minutes` of real time after `start`, in start's zone."""
    if start.tzinfo is None:
        return start + timedelta(minutes=minutes)
    return (instant(start) + timedelta(minutes=minutes)).astimezone(start.tzinfo)


def local_midnight(day: date, tz: ZoneInfo) -> datetime:
    return localize(datetime.combine(day, time()), tz, lenient=True)


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
