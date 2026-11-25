"""Where billfold gets "today" and "now" from, so tests and scripts can pin them."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta


class SystemClock:
    def today(self) -> date:
        return date.today()

    def now(self) -> datetime:
        return datetime.now(UTC).replace(microsecond=0)


class FixedClock:
    """A clock that stands still until told to move. Each now() call ticks one second."""

    def __init__(self, today: date | str, hour: int = 9) -> None:
        if isinstance(today, str):
            today = date.fromisoformat(today)
        self._now = datetime(today.year, today.month, today.day, hour, tzinfo=UTC)

    def today(self) -> date:
        return self._now.date()

    def now(self) -> datetime:
        self._now += timedelta(seconds=1)
        return self._now

    def advance(self, days: int = 1) -> None:
        self._now += timedelta(days=days)


def from_environment() -> SystemClock | FixedClock:
    """BILLFOLD_TODAY=2026-03-01 pins the date for the CLI."""
    pinned = os.environ.get("BILLFOLD_TODAY")
    return FixedClock(pinned) if pinned else SystemClock()


def stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
