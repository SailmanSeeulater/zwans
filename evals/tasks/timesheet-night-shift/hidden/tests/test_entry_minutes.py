import pytest

from timesheet.entries import Entry, parse_line, parse_sheet
from timesheet.summary import minutes_by_week


@pytest.mark.parametrize(
    ("line", "minutes"),
    [
        ("2024-03-06 22:00-06:00 support", 480),
        ("2024-03-06 23:30-00:15 support", 45),
        ("2024-03-06 12:00-00:00 support", 720),
        ("2024-03-06 00:00-23:59 support", 1439),
        ("2024-03-06 23:59-00:00 support", 1),
        ("2024-03-06 00:01-00:00 support", 1439),
        ("2024-03-06 08:15-16:45 support", 510),
    ],
)
def test_entry_minutes(line: str, minutes: int) -> None:
    assert parse_line(line).minutes == minutes


def test_entry_built_directly() -> None:
    assert (
        Entry(
            day=parse_line("2024-01-01 01:00-02:00 x").day, start=1380, end=60, project="x"
        ).minutes
        == 120
    )


def test_night_shift_on_sunday_counts_for_the_week_it_started() -> None:
    entries = parse_sheet("2024-03-10 21:00-05:00 support\n2024-03-11 09:00-10:00 support\n")

    totals = minutes_by_week(entries)

    assert list(totals.values()) == [480, 60]
