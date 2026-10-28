"""Timesheet entries, one per line:

    2024-03-04 09:00-17:30 billing
    2024-03-05 22:00-06:00 support     (a night shift: ends the next morning)

Times are 24-hour HH:MM. An entry whose end is earlier than its start runs past midnight,
and belongs to the day it started on. Blank lines and lines starting with # are skipped.
"""

from dataclasses import dataclass
from datetime import date


class EntryError(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    day: date
    start: int  # minutes after midnight
    end: int  # minutes after midnight
    project: str

    @property
    def minutes(self) -> int:
        return self.end - self.start


def parse_clock(text: str) -> int:
    hours, sep, minutes = text.partition(":")
    if not sep or not hours.isdigit() or not minutes.isdigit() or len(minutes) != 2:
        raise EntryError(f"bad time {text!r}, expected HH:MM")
    h, m = int(hours), int(minutes)
    if h > 23 or m > 59:
        raise EntryError(f"bad time {text!r}")
    return h * 60 + m


def parse_line(line: str) -> Entry:
    parts = line.split()
    if len(parts) != 3:
        raise EntryError(f"expected 'DATE START-END PROJECT', got {line!r}")
    day_text, span, project = parts
    try:
        day = date.fromisoformat(day_text)
    except ValueError:
        raise EntryError(f"bad date {day_text!r}") from None
    start_text, sep, end_text = span.partition("-")
    if not sep:
        raise EntryError(f"bad time span {span!r}")
    start, end = parse_clock(start_text), parse_clock(end_text)
    if start == end:
        raise EntryError(f"empty time span {span!r}")
    return Entry(day, start, end, project.lower())


def parse_sheet(text: str) -> list[Entry]:
    entries = []
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            entries.append(parse_line(line))
        except EntryError as exc:
            raise EntryError(f"line {number}: {exc}") from None
    return entries
