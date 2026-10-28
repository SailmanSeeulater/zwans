"""Holiday calendars. The file format is described in SPEC.md, section 6."""

import os
from collections.abc import Iterable
from datetime import date


class HolidayFileError(ValueError):
    """A holiday file that cannot be read. `line` is the 1-based number of the bad line."""

    def __init__(self, message: str, line: int):
        super().__init__(f"line {line}: {message}")
        self.line = line


class Holidays:
    """A set of holidays: `day in holidays` tells whether `day` is one."""

    def __init__(self, dates: Iterable[date] = ()):
        self.dates = set(dates)

    def __contains__(self, day: object) -> bool:
        return day in self.dates


def load_holidays(path: str | os.PathLike[str]) -> Holidays:
    """Read a holiday file."""
    raise NotImplementedError
