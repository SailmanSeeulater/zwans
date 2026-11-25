"""Rules 1-5: zones, local input, aware output, gaps and repeats, real durations."""

from datetime import datetime

import pytest
from clinicbook import InvalidTime, ValidationError
from support import wall
from zones import offset_hours, u, utc, visit_at


@pytest.mark.parametrize("zone", ["Mars/Olympus_Mons", "Europe/Londn", "America/NewYork"])
def test_a_zone_missing_from_the_database_is_refused(world, zone):
    with pytest.raises(ValidationError):
        world.add_clinic("elsewhere", "Elsewhere Clinic", zone=zone)


def test_a_naive_start_is_the_clinics_wall_clock_time(world):
    appt = visit_at(world, "brooklyn", datetime(2026, 3, 2, 9, 0), minutes=45)

    assert u(appt.start) == utc(2026, 3, 2, 14, 0)
    assert u(appt.end) == utc(2026, 3, 2, 14, 45)
    assert wall(appt.start) == "2026-03-02 09:00" and wall(appt.end) == "2026-03-02 09:45"
    assert offset_hours(appt.start) == -5


def test_the_same_wall_clock_time_is_a_different_instant_in_each_clinic(world):
    london = visit_at(world, "camden", datetime(2026, 3, 2, 9, 0))
    sydney = visit_at(world, "bondi", datetime(2026, 3, 2, 9, 0))

    assert u(london.start) == utc(2026, 3, 2, 9, 0)
    assert u(sydney.start) == utc(2026, 3, 1, 22, 0)
    assert offset_hours(sydney.start) == 11


def test_an_aware_start_means_that_instant(world):
    appt = visit_at(world, "camden", utc(2026, 7, 6, 13, 0))

    assert u(appt.start) == utc(2026, 7, 6, 13, 0)
    assert wall(appt.start) == "2026-07-06 14:00"  # British Summer Time
    assert offset_hours(appt.start) == 1


def test_a_start_given_as_text_is_local_too(world):
    appt = visit_at(world, "bondi", "2026-03-03 08:00")

    assert u(appt.start) == utc(2026, 3, 2, 21, 0)


def test_a_local_time_that_does_not_exist_is_refused(world):
    with pytest.raises(InvalidTime):
        visit_at(world, "nightcare", datetime(2026, 3, 8, 2, 30))
    appt = visit_at(world, "nightcare", datetime(2026, 3, 8, 1, 30))
    with pytest.raises(InvalidTime):
        world.reschedule(appt.id, start=datetime(2026, 3, 8, 2, 0))
    assert u(appt.start) == utc(2026, 3, 8, 6, 30)


def test_a_local_time_that_happens_twice_means_the_first(world):
    appt = visit_at(world, "nightcare", datetime(2026, 11, 1, 1, 30))

    assert u(appt.start) == utc(2026, 11, 1, 5, 30)
    assert offset_hours(appt.start) == -4


def test_durations_are_real_time_when_the_clocks_go_back(world):
    appt = visit_at(world, "nightcare", datetime(2026, 11, 1, 1, 30), minutes=60)

    assert u(appt.end) == utc(2026, 11, 1, 6, 30)
    assert wall(appt.end) == "2026-11-01 01:30"
    assert offset_hours(appt.end) == -5


def test_durations_are_real_time_when_the_clocks_go_forward(world):
    appt = visit_at(world, "nightcare", datetime(2026, 3, 8, 1, 30), minutes=60)

    assert u(appt.end) == utc(2026, 3, 8, 7, 30)
    assert wall(appt.end) == "2026-03-08 03:30"


def test_not_in_the_past_compares_instants(world, clock):
    clock.set(utc(2026, 3, 2, 13, 30))  # 08:30 in New York, 13:30 in London

    appt = visit_at(world, "brooklyn", datetime(2026, 3, 2, 9, 0))
    assert u(appt.start) == utc(2026, 3, 2, 14, 0)
    with pytest.raises(InvalidTime):
        visit_at(world, "camden", datetime(2026, 3, 2, 13, 0), patient="P0002")


def test_a_naive_clock_means_utc(world, clock):
    clock.set(datetime(2026, 3, 2, 13, 30))

    visit_at(world, "brooklyn", datetime(2026, 3, 2, 8, 30))
    with pytest.raises(InvalidTime):
        visit_at(world, "brooklyn", datetime(2026, 3, 2, 8, 0), patient="P0002", room="B2")


def test_created_is_the_instant_of_booking(world, clock):
    clock.set(utc(2026, 2, 20, 10, 15))

    appt = visit_at(world, "bondi", datetime(2026, 3, 3, 8, 0))

    assert u(appt.created) == utc(2026, 2, 20, 10, 15)
