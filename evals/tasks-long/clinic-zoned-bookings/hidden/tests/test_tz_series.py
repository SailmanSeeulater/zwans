"""Rule 7: series keep their local wall-clock time across clock changes."""

from datetime import date, datetime

from clinicbook import ClinicBook, Recurrence
from support import wall
from zones import PEOPLE, utc


def series(book, clinic, start, rule, **overrides):  # noqa: ANN001, ANN201
    clinician, room = PEOPLE[clinic]
    fields = dict(clinic=clinic, clinician=clinician, room=room, patient="P0001",
                  start=start, minutes=30, rule=rule)
    fields.update(overrides)
    return book.book_series(**fields)


def test_a_weekly_series_stays_at_nine_when_new_york_changes_its_clocks(world):
    result = series(world, "brooklyn", datetime(2026, 3, 2, 9, 0), Recurrence("weekly", count=3))

    assert [wall(a.start) for a in result.booked] == [
        "2026-03-02 09:00", "2026-03-09 09:00", "2026-03-16 09:00",
    ]
    assert [a.start for a in result.booked] == [
        utc(2026, 3, 2, 14, 0), utc(2026, 3, 9, 13, 0), utc(2026, 3, 16, 13, 0),
    ]


def test_a_weekday_series_stays_at_ten_when_sydney_changes_its_clocks(world):
    result = series(world, "bondi", datetime(2026, 4, 3, 10, 0), Recurrence("weekdays", count=3))

    assert [a.start for a in result.booked] == [
        utc(2026, 4, 2, 23, 0), utc(2026, 4, 6, 0, 0), utc(2026, 4, 7, 0, 0),
    ]
    assert {wall(a.start)[11:] for a in result.booked} == {"10:00"}


def test_a_london_series_over_the_spring_change(world):
    result = series(world, "camden", datetime(2026, 3, 23, 10, 0),
                    Recurrence("weekly", until=date(2026, 4, 6)))

    assert [a.start for a in result.booked] == [
        utc(2026, 3, 23, 10, 0), utc(2026, 3, 30, 9, 0), utc(2026, 4, 6, 9, 0),
    ]


def test_an_occurrence_in_the_lost_hour_is_skipped(world):
    result = series(world, "nightcare", datetime(2026, 3, 6, 2, 30), Recurrence("daily", count=4))

    assert [wall(a.start) for a in result.booked] == [
        "2026-03-06 02:30", "2026-03-07 02:30", "2026-03-09 02:30",
    ]
    assert [when.date() for when, _ in result.skipped] == [date(2026, 3, 8)]
    assert result.booked[2].start == utc(2026, 3, 9, 6, 30)


def test_a_series_given_an_aware_start_repeats_its_local_time(world):
    result = series(world, "brooklyn", utc(2026, 3, 2, 14, 0), Recurrence("weekly", count=2))

    assert [wall(a.start) for a in result.booked] == ["2026-03-02 09:00", "2026-03-09 09:00"]


def test_series_times_survive_a_reopen(world, clock, tmp_path):
    result = series(world, "brooklyn", datetime(2026, 3, 2, 9, 0), Recurrence("weekly", count=3))
    world.save(tmp_path / "book.json")

    again = ClinicBook.open(tmp_path / "book.json", clock=clock)

    assert [a.start for a in again.appointments(series=result.series.id)] == [
        a.start for a in result.booked
    ]
    assert [wall(a.start) for a in again.appointments(series=result.series.id)] == [
        wall(a.start) for a in result.booked
    ]
