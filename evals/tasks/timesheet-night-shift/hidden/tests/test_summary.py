from datetime import date

from timesheet.entries import parse_sheet
from timesheet.report import weekly_report
from timesheet.summary import minutes_by_project, minutes_by_week, overtime_by_week

SHEET = """
# week of 4 March
2024-03-04 09:00-17:00 billing
2024-03-05 09:00-17:00 billing
2024-03-06 22:00-06:00 support
2024-03-07 22:00-06:00 support
2024-03-08 08:00-18:00 billing
2024-03-11 09:00-12:00 billing
"""


def test_minutes_by_project() -> None:
    assert minutes_by_project(parse_sheet(SHEET)) == {"billing": 29 * 60, "support": 16 * 60}


def test_overtime() -> None:
    entries = parse_sheet(SHEET)

    assert minutes_by_week(entries) == {date(2024, 3, 4): 42 * 60, date(2024, 3, 11): 180}
    assert overtime_by_week(entries) == {date(2024, 3, 4): 2 * 60, date(2024, 3, 11): 0}


def test_report() -> None:
    assert weekly_report(parse_sheet(SHEET)).splitlines() == [
        "Projects",
        "  billing       29:00",
        "  support       16:00",
        "Weeks",
        "  2024-03-04    42:00  (overtime 2:00)",
        "  2024-03-11     3:00",
    ]
