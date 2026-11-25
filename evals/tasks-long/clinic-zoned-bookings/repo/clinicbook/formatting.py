"""How times and tables look to people: the CLI, reports and messages."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime


def when(value: datetime) -> str:
    """`Mon 02 Mar 2026 09:00`."""
    return value.strftime("%a %d %b %Y %H:%M")


def short_when(value: datetime) -> str:
    """`Mon 2 Mar at 09:00`, for messages."""
    return f"{value.strftime('%a')} {value.day} {value.strftime('%b')} at {value.strftime('%H:%M')}"


def hm(value: datetime) -> str:
    return value.strftime("%H:%M")


def span(start: datetime, end: datetime) -> str:
    return f"{hm(start)}-{hm(end)}"


def day_title(day: date) -> str:
    """`Monday 2 March 2026`."""
    return f"{day.strftime('%A')} {day.day} {day.strftime('%B %Y')}"


def table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    cells = [[str(h) for h in headers]] + [[str(c) for c in row] for row in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip() for row in cells]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"
