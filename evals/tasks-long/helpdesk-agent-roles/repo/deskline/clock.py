"""Time handling.

All timestamps are stored as ISO 8601 strings in UTC with a trailing ``Z`` and minute
precision is plenty for a helpdesk. Anything that needs "now" takes a clock, so tests
can control time.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

Clock = Callable[[], str]

FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def system_clock() -> str:
    """The real time, unless DESKLINE_NOW pins it (handy for scripts and demos)."""
    pinned = os.environ.get("DESKLINE_NOW")
    if pinned:
        return format_time(parse_time(pinned))
    return datetime.now(UTC).strftime(FORMAT)


def parse_time(text: str) -> datetime:
    text = text.strip()
    if len(text) == 10:
        text += "T00:00:00Z"
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"not a timestamp: {text!r}") from exc
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def format_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime(FORMAT)


def add_minutes(stamp: str, minutes: int) -> str:
    return format_time(parse_time(stamp) + timedelta(minutes=minutes))


def minutes_between(start: str, end: str) -> int:
    return int((parse_time(end) - parse_time(start)).total_seconds() // 60)


def days_between(start: str, end: str) -> float:
    return (parse_time(end) - parse_time(start)).total_seconds() / 86400


class SteppingClock:
    """A clock for scripts and tests: starts at ``start`` and moves ``step`` minutes per call."""

    def __init__(self, start: str = "2026-03-02T09:00:00Z", step: int = 1) -> None:
        self.current = parse_time(start)
        self.step = timedelta(minutes=step)

    def __call__(self) -> str:
        now = format_time(self.current)
        self.current += self.step
        return now

    def advance(self, minutes: int) -> None:
        self.current += timedelta(minutes=minutes)
