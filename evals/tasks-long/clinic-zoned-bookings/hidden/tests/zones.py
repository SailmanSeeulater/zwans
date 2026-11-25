"""Helpers for the time zone tests."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

UTC = timezone.utc
LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")
SYDNEY = ZoneInfo("Australia/Sydney")

INSTANT = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

PEOPLE = {
    "camden": ("dr-osei", "C1"),
    "brooklyn": ("dr-park", "B1"),
    "bondi": ("dr-hale", "S1"),
    "nightcare": ("dr-park", "N1"),
}


def utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


def visit_at(book: Any, clinic: str, start: datetime, **overrides: Any) -> Any:
    """Book a 30-minute consult at `clinic` with its usual clinician and room."""
    clinician, room = PEOPLE[clinic]
    fields = dict(clinic=clinic, clinician=clinician, room=room, patient="P0001",
                  start=start, minutes=30)
    fields.update(overrides)
    return book.book(**fields)


def u(value: datetime) -> datetime:
    """The instant in UTC. (An aware time in a repeated hour never compares equal to a
    time in another zone, so instants are compared in UTC.)"""
    assert value.tzinfo is not None, f"{value!r} is naive"
    return value.astimezone(UTC)


def offset_hours(value: datetime) -> float:
    offset = value.utcoffset()
    assert offset is not None, f"{value!r} is naive"
    return offset / timedelta(hours=1)
