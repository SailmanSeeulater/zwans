"""Holiday calendars. The file format is described in SPEC.md, section 6."""

import calendar
import os
import re
from collections.abc import Iterable
from datetime import date, timedelta

DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


class HolidayFileError(ValueError):
    """A holiday file that cannot be read. `line` is the 1-based number of the bad line."""

    def __init__(self, message: str, line: int):
        super().__init__(f"line {line}: {message}")
        self.line = line


class Holidays:
    """A set of holidays: `day in holidays` tells whether `day` is one."""

    def __init__(self, dates: Iterable[date] = (), yearly: Iterable[tuple[int, int]] = ()):
        self.dates = set(dates)
        self.yearly = set(yearly)

    def _yearly_on(self, day: date) -> bool:
        return (day.month, day.day) in self.yearly

    def __contains__(self, day: object) -> bool:
        if not isinstance(day, date):
            return False
        if day in self.dates or self._yearly_on(day):
            return True
        # Every-year holidays on a weekend are also observed on the nearest weekday.
        if day.weekday() == 4 and self._yearly_on(day + timedelta(days=1)):
            return True
        if day.weekday() == 0 and self._yearly_on(day - timedelta(days=1)):
            return True
        return False


def _parse_date(text: str, line: int) -> date:
    match = DATE_RE.fullmatch(text)
    if not match:
        raise HolidayFileError(f"bad date {text!r}", line)
    try:
        return date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        raise HolidayFileError(f"no such date {text!r}", line) from None


def load_holidays(path: str | os.PathLike[str]) -> Holidays:
    """Read a holiday file."""
    dates: set[date] = set()
    yearly: set[tuple[int, int]] = set()
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        first = line.split(None, 1)[0]
        if first.startswith("*-"):
            match = re.fullmatch(r"\*-(\d{2})-(\d{2})", first)
            if not match:
                raise HolidayFileError(f"bad every-year date {first!r}", number)
            month, day = int(match[1]), int(match[2])
            if not 1 <= month <= 12 or not 1 <= day <= calendar.monthrange(2024, month)[1]:
                raise HolidayFileError(f"no such day {first!r}", number)
            yearly.add((month, day))
        elif ".." in first:
            left, right = first.split("..", 1)
            begin, finish = _parse_date(left, number), _parse_date(right, number)
            if finish < begin:
                raise HolidayFileError("range ends before it starts", number)
            day = begin
            while day <= finish:
                dates.add(day)
                day += timedelta(days=1)
        else:
            dates.add(_parse_date(first, number))
    return Holidays(dates, yearly)
