"""Rule 5: clashes are judged on real time spans, across clinics and zones."""

from datetime import datetime

import pytest
from clinicbook import ClinicBook, Conflict
from zones import u, utc, visit_at


def test_a_clinician_cannot_be_in_new_york_and_london_at_the_same_moment(world):
    first = visit_at(world, "brooklyn", datetime(2026, 1, 12, 10, 0))  # 15:00 UTC

    with pytest.raises(Conflict) as caught:
        visit_at(world, "camden", datetime(2026, 1, 12, 15, 0), clinician="dr-park",
                 patient="P0002")
    assert caught.value.clashes == [first]

    with pytest.raises(Conflict):
        visit_at(world, "camden", datetime(2026, 1, 12, 14, 45), clinician="dr-park",
                 patient="P0002")


def test_the_same_wall_clock_time_in_two_zones_is_no_clash(world):
    visit_at(world, "brooklyn", datetime(2026, 1, 12, 10, 0))
    other = visit_at(world, "camden", datetime(2026, 1, 12, 10, 0), clinician="dr-park",
                     patient="P0002")

    assert other.status == "booked"


def test_a_clash_across_a_local_date_line_is_found(world):
    # 13:00 on Tuesday in Sydney is 21:00 on Monday in New York.
    first = visit_at(world, "bondi", datetime(2026, 3, 3, 13, 0))

    with pytest.raises(Conflict) as caught:
        visit_at(world, "brooklyn", datetime(2026, 3, 2, 21, 0), clinician="dr-hale",
                 patient="P0002")
    assert caught.value.clashes == [first]


def test_a_clash_across_a_local_date_line_is_found_the_other_way_round(world):
    visit_at(world, "brooklyn", datetime(2026, 3, 2, 21, 0), clinician="dr-hale")

    with pytest.raises(Conflict):
        visit_at(world, "bondi", datetime(2026, 3, 3, 13, 15), patient="P0002")
    visit_at(world, "bondi", datetime(2026, 3, 3, 13, 30), patient="P0002")


def test_a_patient_cannot_be_in_two_cities_at_once(world):
    visit_at(world, "brooklyn", datetime(2026, 1, 12, 10, 0), patient="P0002")

    with pytest.raises(Conflict):
        visit_at(world, "camden", datetime(2026, 1, 12, 15, 0), patient="P0002")


def test_times_in_the_repeated_hour_are_told_apart(world):
    # 01:00-01:30 in the first (daylight) 01:00 hour; 01:10 in the second hour is later.
    visit_at(world, "nightcare", datetime(2026, 11, 1, 1, 0))
    later = visit_at(world, "nightcare", utc(2026, 11, 1, 6, 10), patient="P0002")

    assert u(later.start) == utc(2026, 11, 1, 6, 10)
    with pytest.raises(Conflict):
        visit_at(world, "nightcare", utc(2026, 11, 1, 5, 15), patient="P0003")


def test_a_long_appointment_over_the_repeated_hour_blocks_all_of_it(world):
    visit_at(world, "nightcare", datetime(2026, 11, 1, 1, 0), minutes=120)  # 05:00-07:00 UTC

    with pytest.raises(Conflict):
        visit_at(world, "nightcare", utc(2026, 11, 1, 6, 30), patient="P0002")
    visit_at(world, "nightcare", datetime(2026, 11, 1, 2, 0), patient="P0002")  # 07:00 UTC


def test_rescheduling_checks_other_zones(world):
    visit_at(world, "brooklyn", datetime(2026, 1, 12, 10, 0))
    appt = visit_at(world, "camden", datetime(2026, 1, 12, 9, 0), clinician="dr-park",
                    patient="P0002")

    with pytest.raises(Conflict):
        world.reschedule(appt.id, start=datetime(2026, 1, 12, 15, 0))
    world.reschedule(appt.id, start=datetime(2026, 1, 12, 15, 30))
    assert u(appt.start) == utc(2026, 1, 12, 15, 30)


def test_a_reopened_book_still_sees_clashes_across_zones(world, clock, tmp_path):
    visit_at(world, "bondi", datetime(2026, 3, 3, 13, 0))
    world.save(tmp_path / "book.json")

    again = ClinicBook.open(tmp_path / "book.json", clock=clock)

    with pytest.raises(Conflict):
        visit_at(again, "brooklyn", datetime(2026, 3, 2, 21, 0), clinician="dr-hale",
                 patient="P0002")
