"""Pay dates for each pay group, worked out from the group's cadence rule."""

from datetime import date
from pathlib import Path

import cadence

HOLIDAYS_FILE = Path(__file__).resolve().parents[1] / "data" / "holidays.txt"

GROUPS = {
    "staff": "monthly on business day -1",
    "contractors": "every 2 weeks on fri; from 2025-01-03; closed: previous",
    "board": "every 3 months on day 15; from 2025-01-15; closed: next",
}


def pay_dates(group: str, year: int) -> list[date]:
    """Every pay date of `group` in `year`."""
    holidays = cadence.load_holidays(HOLIDAYS_FILE)
    return cadence.expand(GROUPS[group], date(year, 1, 1), date(year, 12, 31), holidays)


def next_pay_date(group: str, today: date) -> date | None:
    """The first pay date of `group` on or after `today`, looking a year ahead."""
    holidays = cadence.load_holidays(HOLIDAYS_FILE)
    upcoming = cadence.expand(GROUPS[group], today, date(today.year + 1, today.month, 28), holidays)
    return upcoming[0] if upcoming else None
