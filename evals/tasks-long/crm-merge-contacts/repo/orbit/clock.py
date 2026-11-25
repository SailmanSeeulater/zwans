"""Time, as ISO 8601 strings in UTC ("2026-03-01T09:00:00Z").

Everything that records a time takes a clock: a callable returning the current time. The
CLI uses the system clock unless ORBIT_NOW is set, in which case time starts there and
moves on by one second per reading, so scripts and tests get stable output.
"""

import os
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

type Clock = Callable[[], str]

FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def parse(stamp: str) -> datetime:
    return datetime.strptime(stamp, FORMAT).replace(tzinfo=UTC)


def format_time(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(FORMAT)


def parse_date(text: str) -> date:
    return date.fromisoformat(text)


def system_clock() -> str:
    return format_time(datetime.now(UTC))


class TickingClock:
    """Starts at `start` and moves on by `step` seconds every time it is read."""

    def __init__(self, start: str, step: int = 1) -> None:
        self._next = parse(start)
        self._step = timedelta(seconds=step)

    def __call__(self) -> str:
        now = self._next
        self._next += self._step
        return format_time(now)


def clock_from_env(variable: str = "ORBIT_NOW") -> Clock:
    start = os.environ.get(variable)
    return TickingClock(start) if start else system_clock


def later(first: str | None, second: str | None) -> str | None:
    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)


def add_seconds(stamp: str, seconds: int) -> str:
    return format_time(parse(stamp) + timedelta(seconds=seconds))


def days_between(earlier: str, later_stamp: str) -> float:
    return (parse(later_stamp) - parse(earlier)).total_seconds() / 86400
