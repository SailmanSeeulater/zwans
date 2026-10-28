"""Reading people and their busy time from .cal files.

A .cal file describes one person:

    # Lines starting with '#' are comments. Header lines are 'key: value'.
    name: Ana Lima
    email: ana@example.com
    offset: +02:00          local time minus UTC
    hours: 09:00-17:00      local working hours; 22:00-06:00 is a night shift
    days: mon-fri           or a list such as mon,tue,thu, or a mix: mon-wed,fri;
                            a range may wrap past Sunday: sun-thu

    # Busy time, one interval per line, in UTC: start, a dash, end, then an optional title.
    2025-03-03 09:00 - 2025-03-03 09:30  Standup
    2025-03-03 13:00 - 14:00             Lunch (the end may leave out the date)

`name` and `email` are required; the other headers have the defaults shown in
meetslot.people.Person.
"""

import re
from datetime import datetime, time, timedelta
from pathlib import Path

from meetslot.people import Person

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
HEADER_RE = re.compile(r"([a-z]+)\s*:\s*(.*)")
OFFSET_RE = re.compile(r"([+-])(\d{2}):(\d{2})")
HOURS_RE = re.compile(r"(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2})")
BUSY_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})\s*-\s*(?:(\d{4}-\d{2}-\d{2}) )?(\d{2}:\d{2})(?:\s+(.*))?"
)


class CalFileError(ValueError):
    def __init__(self, path: Path, line: int, message: str):
        super().__init__(f"{path}:{line}: {message}")
        self.path = path
        self.line = line


def _offset(text: str) -> timedelta:
    match = OFFSET_RE.fullmatch(text)
    if not match:
        raise ValueError(f"bad offset {text!r}, expected something like +02:00")
    sign = 1 if match[1] == "+" else -1
    hours, minutes = int(match[2]), int(match[3])
    if hours > 14 or minutes >= 60:
        raise ValueError(f"offset out of range: {text!r}")
    return sign * timedelta(hours=hours, minutes=minutes)


def _hours(text: str) -> tuple[time, time]:
    match = HOURS_RE.fullmatch(text)
    if not match:
        raise ValueError(f"bad hours {text!r}, expected something like 09:00-17:00")
    return time(int(match[1]), int(match[2])), time(int(match[3]), int(match[4]))


def _days(text: str) -> frozenset[int]:
    days: set[int] = set()
    for part in text.replace(" ", "").lower().split(","):
        first, _, last = part.partition("-")
        if first not in DAY_NAMES or (last and last not in DAY_NAMES):
            raise ValueError(f"bad days {text!r}")
        a = DAY_NAMES.index(first)
        b = DAY_NAMES.index(last) if last else a
        if b < a:
            b += 7  # the range wraps past Sunday, like sun-thu
        days.update(day % 7 for day in range(a, b + 1))
    return frozenset(days)


def _busy(text: str) -> tuple[datetime, datetime, str]:
    match = BUSY_RE.fullmatch(text)
    if not match:
        raise ValueError(f"cannot read busy time {text!r}")
    start = datetime.fromisoformat(f"{match[1]} {match[2]}")
    end = datetime.fromisoformat(f"{match[3] or match[1]} {match[4]}")
    if end <= start:
        raise ValueError("busy time must end after it starts")
    return start, end, (match[5] or "").strip()


def read_person(path: Path) -> Person:
    headers: dict[str, str] = {}
    busy: list[tuple[datetime, datetime]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            if line[0].isdigit():
                start, end, _title = _busy(line)
                busy.append((start, end))
                continue
            match = HEADER_RE.fullmatch(line)
            if not match:
                raise ValueError(f"cannot read line {line!r}")
            key, value = match[1], match[2].split("  ")[0].strip()
            if key in headers:
                raise ValueError(f"{key} given twice")
            if key not in ("name", "email", "offset", "hours", "days"):
                raise ValueError(f"unknown header {key!r}")
            headers[key] = value
        except ValueError as exc:
            raise CalFileError(path, number, str(exc)) from None
    for key in ("name", "email"):
        if key not in headers:
            raise CalFileError(path, 0, f"missing {key}")
    person = Person(name=headers["name"], email=headers["email"], busy=busy)
    try:
        if "offset" in headers:
            person.utc_offset = _offset(headers["offset"])
        if "hours" in headers:
            person.work_start, person.work_end = _hours(headers["hours"])
        if "days" in headers:
            person.workdays = _days(headers["days"])
    except ValueError as exc:
        raise CalFileError(path, 0, str(exc)) from None
    return person


def read_people(folder: Path) -> list[Person]:
    """Every person in the .cal files of `folder`, sorted by name."""
    people = [read_person(path) for path in sorted(folder.glob("*.cal"))]
    return sorted(people, key=lambda person: person.name)
