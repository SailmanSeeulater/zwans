"""Rules 9 and 10: no-shows and the waitlist compare instants; slot searches walk the
clinic's local days and hours."""

from datetime import date, datetime

from support import wall
from zones import u, utc, visit_at


def test_no_shows_are_marked_by_instant(world, clock):
    appt = visit_at(world, "brooklyn", datetime(2026, 1, 12, 9, 0))  # ends 14:30 UTC

    clock.set(utc(2026, 1, 12, 14, 40))
    assert world.run_jobs().no_shows == []
    clock.set(utc(2026, 1, 12, 14, 45))
    assert world.run_jobs().no_shows == [appt.id]


def test_next_free_slot_knows_the_clinicians_day_in_another_zone(world):
    # Dr Park is in Camden 14:00-17:00 London time: 09:00-12:00 in New York.
    visit_at(world, "camden", datetime(2026, 1, 12, 14, 0), clinician="dr-park", minutes=180)

    slot = world.next_free_slot("brooklyn", 30, clinician="dr-park",
                                after=datetime(2026, 1, 12, 9, 0))

    assert u(slot.start) == utc(2026, 1, 12, 17, 0)
    assert wall(slot.start) == "2026-01-12 12:00" and wall(slot.end) == "2026-01-12 12:30"


def test_next_free_slot_starts_from_now_in_the_clinics_zone(world, clock):
    clock.set(utc(2026, 1, 12, 23, 10))  # 10:10 on Tuesday in Sydney

    slot = world.next_free_slot("bondi", 30)

    assert wall(slot.start) == "2026-01-13 10:15"
    assert u(slot.start) == utc(2026, 1, 12, 23, 15)


def test_next_free_slot_walks_local_days(world, clock):
    clock.set(utc(2026, 1, 10, 6, 0))  # 17:00 on Saturday in Sydney, closing time

    slot = world.next_free_slot("bondi", 30)

    assert wall(slot.start) == "2026-01-12 08:00"  # Sunday closed, Monday opening


def test_next_free_slot_before_is_local_time(world):
    slot = world.next_free_slot("bondi", 30, after=datetime(2026, 1, 13, 16, 0),
                                before=datetime(2026, 1, 13, 16, 30))
    assert wall(slot.start) == "2026-01-13 16:00"
    assert world.next_free_slot("bondi", 30, after=datetime(2026, 1, 13, 16, 40),
                                before=datetime(2026, 1, 14, 8, 0)) is None


def test_slots_on_the_night_the_clocks_go_forward(world):
    slots = world.slots("nightcare", date(2026, 3, 8), 60)

    starts = [wall(s.start)[11:] for s in slots]
    assert starts[:9] == ["00:00", "00:15", "00:30", "00:45", "01:00", "01:15", "01:30",
                          "01:45", "03:00"]
    assert "02:00" not in starts and "02:30" not in starts
    assert starts[starts.index("05:00") + 1] == "20:00"
    assert slots[8].start == utc(2026, 3, 8, 7, 0)


def test_the_waitlist_books_in_its_local_window(world, clock):
    entry = world.waitlist_add(patient="P0002", clinic="brooklyn", minutes=30,
                               clinician="dr-park", earliest=datetime(2026, 1, 13, 8, 0),
                               latest=datetime(2026, 1, 13, 12, 0))
    assert u(entry.earliest) == utc(2026, 1, 13, 13, 0)
    assert wall(entry.latest) == "2026-01-13 12:00"

    clock.set(utc(2026, 1, 13, 12, 50))  # 07:50 in New York
    (appt,) = world.offer_waitlist()

    assert u(appt.start) == utc(2026, 1, 13, 13, 0)
    offer = world.outbox[-1]
    assert offer.template == "waitlist_offer" and "Tue 13 Jan at 08:00" in offer.text


def test_the_waitlist_respects_the_end_of_its_window_in_local_time(world, clock):
    world.waitlist_add(patient="P0002", clinic="bondi", minutes=30,
                       latest=datetime(2026, 1, 13, 9, 0))
    clock.set(utc(2026, 1, 12, 22, 0))  # 09:00 on Tuesday in Sydney

    assert world.offer_waitlist() == []
    assert len(world.waitlist()) == 1
