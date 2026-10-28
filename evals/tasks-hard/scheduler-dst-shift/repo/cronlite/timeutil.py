"""Small date and time helpers."""

import re
from datetime import UTC, datetime, time, timedelta

from cronlite.zones import Zone

_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_DURATION = re.compile(r"^(\d+)\s*(m|min|h)$")


def parse_hhmm(text: str) -> time:
    match = _HHMM.match(text.strip())
    if not match:
        raise ValueError(f"not a time of day (HH:MM): {text!r}")
    return time(int(match.group(1)), int(match.group(2)))


def parse_duration(text: str) -> timedelta:
    match = _DURATION.match(text.strip().lower())
    if not match:
        raise ValueError(f"not a duration like 30m or 2h: {text!r}")
    amount = int(match.group(1))
    if amount < 1:
        raise ValueError("a duration must be at least 1")
    return timedelta(hours=amount) if match.group(2) == "h" else timedelta(minutes=amount)


def add_days(moment: datetime, days: int, zone: Zone) -> datetime:
    """The same wall-clock time in `zone`, `days` days later (or earlier)."""
    return moment + timedelta(days=days)


def floor_minute(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)  # type: ignore[misc]


def format_local(moment: datetime, zone: Zone) -> str:
    """'Sun 25 Oct 02:30 (+01:00)'"""
    aware = zone.aware(moment)
    offset = aware.utcoffset() or timedelta()
    sign = "-" if offset < timedelta() else "+"
    minutes = abs(int(offset.total_seconds())) // 60
    return f"{aware.strftime('%a %d %b %H:%M')} ({sign}{minutes // 60:02d}:{minutes % 60:02d})"
