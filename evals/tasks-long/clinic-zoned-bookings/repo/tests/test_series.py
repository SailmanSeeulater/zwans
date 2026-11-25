from datetime import date, datetime

import pytest
from clinicbook import BookingError, Recurrence, ValidationError
from support import visit, wall


def series(book, start, rule, **overrides):  # noqa: ANN001, ANN201
    fields = dict(clinic="camden", clinician="dr-osei", room="C1", patient="P0001",
                  start=start, minutes=30, rule=rule)
    fields.update(overrides)
    return book.book_series(**fields)


def test_a_weekly_series_books_every_week(book):
    result = series(book, datetime(2026, 1, 12, 9, 0), Recurrence("weekly", count=4))

    assert [wall(a.start) for a in result.booked] == [
        "2026-01-12 09:00", "2026-01-19 09:00", "2026-01-26 09:00", "2026-02-02 09:00",
    ]
    assert result.skipped == []
    assert {a.series for a in result.booked} == {result.series.id}
    assert book.appointments(series=result.series.id) == result.booked


def test_occurrences_that_clash_are_skipped(book):
    visit(book, datetime(2026, 1, 19, 9, 0), clinician="dr-lind", patient="P0002")
    book.close_day("camden", date(2026, 1, 26), "boiler repair")

    result = series(book, datetime(2026, 1, 12, 9, 0), Recurrence("weekly", count=4))

    assert len(result.booked) == 2
    assert [wall(when) for when, _ in result.skipped] == ["2026-01-19 09:00", "2026-01-26 09:00"]
    assert "boiler repair" in result.skipped[1][1]


def test_a_series_nothing_of_which_fits_is_refused(book):
    with pytest.raises(BookingError):
        series(book, datetime(2026, 1, 11, 9, 0), Recurrence("weekly", count=3))  # Sundays
    assert book.store.series == {}


def test_until_and_daily_and_weekdays(book):
    daily = series(book, datetime(2026, 1, 12, 8, 0),
                   Recurrence("weekdays", until=date(2026, 1, 20)))
    assert [a.start.day for a in daily.booked] == [12, 13, 14, 15, 16, 19, 20]

    fortnightly = series(book, datetime(2026, 1, 12, 15, 0),
                         Recurrence("fortnightly", count=3), patient="P0002")
    assert [a.start.day for a in fortnightly.booked] == [12, 26, 9]


def test_monthly_leaves_out_short_months(book):
    book.set_hours("camden", {d: "08:00-18:00" for d in
                              ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})
    result = series(book, datetime(2026, 1, 31, 10, 0), Recurrence("monthly", count=3))

    assert [wall(a.start)[:10] for a in result.booked] == ["2026-01-31", "2026-03-31",
                                                            "2026-05-31"]


def test_rules_are_validated():
    with pytest.raises(ValidationError):
        Recurrence("hourly", count=3)
    with pytest.raises(ValidationError):
        Recurrence("weekly")
    with pytest.raises(ValidationError):
        Recurrence("weekly", count=500)
    assert Recurrence("weekly", count=6).describe() == "every week, 6 times"


def test_cancelling_a_series_cancels_what_is_still_to_come(book, clock):
    result = series(book, datetime(2026, 1, 12, 9, 0), Recurrence("weekly", count=4))
    clock.set(datetime(2026, 1, 20, 8, 0))

    cancelled = book.cancel_series(result.series.id)

    assert [a.start.day for a in cancelled] == [26, 2]
    assert [a.status for a in result.booked] == ["booked", "booked", "cancelled", "cancelled"]


def test_cancelling_a_series_from_a_day(book):
    result = series(book, datetime(2026, 1, 12, 9, 0), Recurrence("weekly", count=4))

    cancelled = book.cancel_series(result.series.id, from_day=date(2026, 1, 26))

    assert [a.start.day for a in cancelled] == [26, 2]
