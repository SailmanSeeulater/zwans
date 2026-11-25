"""Small helpers shared by the tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def visit(book: Any, start: datetime, **overrides: Any) -> Any:
    """Book a 30-minute consult at Camden with the usual people, unless told otherwise."""
    fields = dict(clinic="camden", clinician="dr-osei", room="C1", patient="P0001",
                  start=start, minutes=30)
    fields.update(overrides)
    return book.book(**fields)


def wall(value: datetime) -> str:
    """A time as the front desk sees it: `2026-01-12 09:00`."""
    return value.strftime("%Y-%m-%d %H:%M")


def lines_of(ical: str) -> list[str]:
    """iCalendar content lines, unfolded."""
    unfolded: list[str] = []
    for raw in ical.split("\r\n"):
        if raw.startswith(" ") and unfolded:
            unfolded[-1] += raw[1:]
        elif raw:
            unfolded.append(raw)
    return unfolded
