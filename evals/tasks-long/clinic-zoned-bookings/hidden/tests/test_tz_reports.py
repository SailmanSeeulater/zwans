"""Rules 4 and 11: reports cover the clinic's local day and show local times."""

from datetime import date, datetime

from support import wall
from zones import utc, visit_at


def test_the_agenda_is_the_clinics_local_day(world):
    early = visit_at(world, "bondi", datetime(2026, 3, 3, 8, 0))  # 21:00 UTC on the 2nd
    late = visit_at(world, "bondi", datetime(2026, 3, 2, 16, 30), patient="P0002")

    tuesday = world.agenda("bondi", date(2026, 3, 3))
    monday = world.agenda("bondi", date(2026, 3, 2))

    assert [r.appointment for r in tuesday.rows] == [early.id]
    assert [r.appointment for r in monday.rows] == [late.id]
    assert tuesday.rows[0].start == utc(2026, 3, 2, 21, 0)
    assert wall(tuesday.rows[0].start) == "2026-03-03 08:00"
    assert "08:00-08:30" in tuesday.render()
    assert "Bondi Clinic, Tuesday 3 March 2026" in tuesday.render()


def test_an_evening_in_new_york_is_on_that_days_agenda(world):
    appt = visit_at(world, "brooklyn", datetime(2026, 1, 12, 21, 0))  # 02:00 UTC on the 13th

    assert [r.appointment for r in world.agenda("brooklyn", date(2026, 1, 12)).rows] == [appt.id]
    assert world.agenda("brooklyn", date(2026, 1, 13)).rows == []


def test_the_agenda_of_a_25_hour_day(world):
    ids = [
        visit_at(world, "nightcare", datetime(2026, 11, 1, 0, 30)).id,
        visit_at(world, "nightcare", datetime(2026, 11, 1, 1, 30), patient="P0002").id,
        visit_at(world, "nightcare", utc(2026, 11, 1, 6, 30), patient="P0003").id,  # 01:30 EST
        visit_at(world, "nightcare", datetime(2026, 11, 1, 23, 30), patient="P0004").id,
    ]
    visit_at(world, "nightcare", datetime(2026, 11, 2, 0, 0))

    agenda = world.agenda("nightcare", date(2026, 11, 1))

    assert [r.appointment for r in agenda.rows] == ids
    assert [wall(r.start)[11:] for r in agenda.rows] == ["00:30", "01:30", "01:30", "23:30"]


def test_the_agenda_of_a_23_hour_day(world):
    first = visit_at(world, "nightcare", datetime(2026, 3, 8, 0, 0))
    last = visit_at(world, "nightcare", datetime(2026, 3, 8, 23, 30), patient="P0002")
    visit_at(world, "nightcare", datetime(2026, 3, 7, 23, 30), patient="P0003")

    agenda = world.agenda("nightcare", date(2026, 3, 8))

    assert [r.appointment for r in agenda.rows] == [first.id, last.id]


def test_utilisation_counts_minutes_on_local_days(world):
    visit_at(world, "bondi", datetime(2026, 3, 3, 8, 0), minutes=60)
    visit_at(world, "bondi", datetime(2026, 3, 2, 16, 0), minutes=30, patient="P0002")
    visit_at(world, "bondi", datetime(2026, 3, 4, 10, 0), minutes=45, room="S2")

    report = world.utilisation("bondi", date(2026, 3, 2), date(2026, 3, 4))

    assert report.booked["S1"] == {date(2026, 3, 2): 30, date(2026, 3, 3): 60}
    assert report.booked["S2"] == {date(2026, 3, 4): 45}
