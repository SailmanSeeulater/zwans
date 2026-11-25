from datetime import date, datetime

import pytest
from clinicbook import ValidationError
from support import visit, wall


def test_day_slots_skip_busy_times(book):
    book.configure(slot_minutes=30)
    visit(book, datetime(2026, 1, 10, 9, 0))
    visit(book, datetime(2026, 1, 10, 9, 0), clinician="dr-lind", room="C2", patient="P0002")
    visit(book, datetime(2026, 1, 10, 10, 0), patient="P0003")

    slots = book.slots("camden", date(2026, 1, 10), 60)

    assert [(wall(s.start)[11:], s.clinician, s.room) for s in slots] == [
        ("09:30", "dr-lind", "C2"),  # dr-osei is busy again at 10, and so is C1
        ("10:00", "dr-lind", "C2"),
        ("10:30", "dr-lind", "C1"),
        ("11:00", "dr-lind", "C1"),
        ("11:30", "dr-lind", "C1"),
        ("12:00", "dr-lind", "C1"),
    ]


def test_next_free_slot_moves_on_to_later_days(book):
    book.close_day("camden", date(2026, 1, 6), "closed")

    slot = book.next_free_slot("camden", 30, clinician="dr-osei",
                               after=datetime(2026, 1, 5, 17, 40))

    assert wall(slot.start) == "2026-01-07 08:00"
    assert wall(slot.end) == "2026-01-07 08:30"


def test_next_free_slot_respects_before(book):
    slot = book.next_free_slot("camden", 30, after=datetime(2026, 1, 5, 17, 40),
                               before=datetime(2026, 1, 6, 0, 0))
    assert slot is None


def test_next_free_slot_starts_from_now(book, clock):
    clock.set(datetime(2026, 1, 5, 10, 7))

    slot = book.next_free_slot("camden", 30)

    assert wall(slot.start) == "2026-01-05 10:15"


def test_the_waitlist_books_the_first_free_slot(book, clock):
    for i, hour in enumerate(range(8, 18)):
        visit(book, datetime(2026, 1, 6, hour, 0), minutes=60, patient=f"P000{1 + i % 3}",
              room="C1" if i % 2 else "C2")
    entry = book.waitlist_add(patient="P0003", clinic="camden", minutes=30,
                              clinician="dr-osei", earliest=datetime(2026, 1, 6, 8, 0))

    booked = book.offer_waitlist()

    assert [wall(a.start) for a in booked] == ["2026-01-07 08:00"]
    assert entry.status == "offered" and entry.appointment == booked[0].id
    offer = book.outbox[-1]
    assert offer.template == "waitlist_offer"
    assert "Wed 7 Jan at 08:00" in offer.text
    assert book.waitlist() == []


def test_waitlist_windows_are_kept(book):
    book.waitlist_add(patient="P0001", clinic="camden", minutes=30,
                      earliest=datetime(2026, 1, 9, 16, 30), latest=datetime(2026, 1, 9, 17, 0))
    visit(book, datetime(2026, 1, 9, 16, 30), patient="P0002")
    visit(book, datetime(2026, 1, 9, 16, 30), patient="P0003", clinician="dr-lind", room="C2")

    assert book.offer_waitlist() == []
    assert len(book.waitlist()) == 1

    with pytest.raises(ValidationError):
        book.waitlist_add(patient="P0001", clinic="camden", minutes=30,
                          earliest=datetime(2026, 1, 9, 17, 0), latest=datetime(2026, 1, 9, 9, 0))


def test_old_waitlist_entries_expire(book, clock):
    entry = book.waitlist_add(patient="P0001", clinic="camden", minutes=30,
                              earliest=datetime(2026, 6, 1, 9, 0))
    clock.set(datetime(2026, 3, 7, 8, 0))

    report = book.run_jobs()

    assert report.waitlist_expired == [entry.id]
