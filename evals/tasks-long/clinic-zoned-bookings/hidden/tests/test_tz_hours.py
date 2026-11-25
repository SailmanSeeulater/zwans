"""Rule 6: opening hours are judged on the local start and the local (real) end."""

from datetime import date, datetime

import pytest
from clinicbook import OutsideOpeningHours
from support import wall
from zones import u, utc, visit_at


def test_an_appointment_over_the_lost_hour_ends_an_hour_later_on_the_clock(world):
    # Night care closes at 06:00. Four hours from 01:30 is 06:30 when the clocks go forward.
    with pytest.raises(OutsideOpeningHours):
        visit_at(world, "nightcare", datetime(2026, 3, 8, 1, 30), minutes=240)
    appt = visit_at(world, "nightcare", datetime(2026, 3, 8, 1, 0), minutes=240)
    assert wall(appt.end) == "2026-03-08 06:00"


def test_an_appointment_over_the_repeated_hour_ends_an_hour_earlier_on_the_clock(world):
    # Five hours from 01:30 is 05:30 when the clocks go back, so it fits before 06:00.
    appt = visit_at(world, "nightcare", datetime(2026, 11, 1, 1, 30), minutes=300)

    assert u(appt.end) == utc(2026, 11, 1, 10, 30)
    assert wall(appt.end) == "2026-11-01 05:30"


def test_the_weekday_is_the_clinics_local_day(world):
    # 22:00 UTC on Saturday 10 January is 09:00 on Sunday in Sydney: closed.
    with pytest.raises(OutsideOpeningHours):
        visit_at(world, "bondi", utc(2026, 1, 10, 22, 0))
    appt = visit_at(world, "bondi", utc(2026, 1, 11, 22, 0))
    assert wall(appt.start) == "2026-01-12 09:00"


def test_closures_are_local_days(world):
    world.close_day("bondi", date(2026, 1, 26), "Australia Day")

    with pytest.raises(OutsideOpeningHours, match="Australia Day"):
        visit_at(world, "bondi", utc(2026, 1, 25, 22, 0))
    visit_at(world, "bondi", datetime(2026, 1, 27, 9, 0))


def test_local_hours_hold_in_summer_and_winter(world):
    # Camden opens at 08:00 local time, whatever that is in UTC.
    with pytest.raises(OutsideOpeningHours):
        visit_at(world, "camden", utc(2026, 7, 6, 6, 30))  # 07:30 BST
    appt = visit_at(world, "camden", utc(2026, 7, 6, 7, 0))  # 08:00 BST
    assert wall(appt.start) == "2026-07-06 08:00"
