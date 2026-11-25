from datetime import date, datetime

import pytest
from clinicbook import ValidationError
from support import visit, wall


def test_the_agenda_lists_the_day_in_time_order(book):
    visit(book, datetime(2026, 1, 12, 11, 0), patient="P0002")
    visit(book, datetime(2026, 1, 12, 9, 0), clinician="dr-lind", room="C2", minutes=45)
    visit(book, datetime(2026, 1, 13, 9, 0))
    gone = visit(book, datetime(2026, 1, 12, 15, 0), patient="P0003")
    book.cancel(gone.id)

    agenda = book.agenda("camden", date(2026, 1, 12))

    assert [(wall(r.start)[11:], wall(r.end)[11:], r.room) for r in agenda.rows] == [
        ("09:00", "09:45", "C2"),
        ("11:00", "11:30", "C1"),
    ]
    assert agenda.render() == (
        "Camden Clinic, Monday 12 January 2026\n"
        "time         room  clinician     patient    kind     status\n"
        "-----------  ----  ------------  ---------  -------  ------\n"
        "09:00-09:45  C2    Dr Erik Lind  Jo Bloggs  consult  booked\n"
        "11:00-11:30  C1    Dr Ama Osei   Sam Patel  consult  booked\n"
        "2 appointments\n"
    )
    assert len(book.agenda("camden", date(2026, 1, 12), include_cancelled=True).rows) == 3


def test_an_empty_or_closed_day(book):
    book.close_day("camden", date(2026, 1, 16), "staff training")

    assert book.agenda("camden", date(2026, 1, 15)).render().endswith("No appointments.\n")
    assert "Closed: staff training" in book.agenda("camden", date(2026, 1, 16)).render()


def test_utilisation_counts_booked_minutes_per_room_and_day(book):
    visit(book, datetime(2026, 1, 12, 9, 0), minutes=60)
    visit(book, datetime(2026, 1, 12, 10, 0), minutes=90, patient="P0002")
    visit(book, datetime(2026, 1, 13, 9, 0), room="C2", minutes=120)
    cancelled = visit(book, datetime(2026, 1, 13, 14, 0), minutes=60)
    book.cancel(cancelled.id)

    report = book.utilisation("camden", date(2026, 1, 12), date(2026, 1, 14))

    assert report.booked["C1"] == {date(2026, 1, 12): 150}
    assert report.booked["C2"] == {date(2026, 1, 13): 120}
    assert report.open_minutes[date(2026, 1, 14)] == 9 * 60
    assert report.percent("C1", date(2026, 1, 12)) == 25.0
    assert "150 min" in report.render()

    with pytest.raises(ValidationError):
        book.utilisation("camden", date(2026, 1, 14), date(2026, 1, 12))


def test_no_show_summary(book, clock):
    a = visit(book, datetime(2026, 1, 12, 9, 0))
    b = visit(book, datetime(2026, 1, 12, 10, 0))
    c = visit(book, datetime(2026, 2, 2, 10, 0))
    book.complete(a.id)
    book.mark_no_show(b.id)
    book.complete(c.id)

    lines = book.no_shows("camden")

    assert [(ln.clinician, ln.month, ln.seen, ln.no_shows, ln.rate) for ln in lines] == [
        ("dr-osei", "2026-01", 1, 1, 50.0),
        ("dr-osei", "2026-02", 1, 0, 0.0),
    ]
