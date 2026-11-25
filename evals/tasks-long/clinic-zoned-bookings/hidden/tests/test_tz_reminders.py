"""Rules 8 and 9: reminders are due a number of real hours before the start."""

from datetime import datetime

from support import wall
from zones import offset_hours, u, utc, visit_at


def test_a_48_hour_reminder_over_the_new_york_change(world):
    appt = visit_at(world, "brooklyn", datetime(2026, 3, 9, 9, 0))  # 13:00 UTC

    first, second = world.reminders(appt.id)

    assert (first.hours_before, first.due) == (48, utc(2026, 3, 7, 13, 0))
    assert wall(first.due) == "2026-03-07 08:00"
    assert offset_hours(first.due) == -5
    assert (second.hours_before, second.due) == (2, utc(2026, 3, 9, 11, 0))


def test_a_48_hour_reminder_over_the_london_change(world):
    world.configure(reminder_hours=[48])
    appt = visit_at(world, "camden", datetime(2026, 3, 30, 9, 0))  # 08:00 UTC

    (reminder,) = world.reminders(appt.id)

    assert u(reminder.due) == utc(2026, 3, 28, 8, 0)
    assert wall(reminder.due) == "2026-03-28 08:00"


def test_a_reminder_over_the_sydney_change(world):
    world.configure(reminder_hours=[48, 2])
    appt = visit_at(world, "bondi", datetime(2026, 4, 6, 9, 0))  # 23:00 UTC on the 5th

    due = [r.due for r in world.reminders(appt.id)]

    assert due == [utc(2026, 4, 3, 23, 0), utc(2026, 4, 5, 21, 0)]
    assert wall(due[0]) == "2026-04-04 10:00"


def test_due_reminders_compare_instants(world):
    ny = visit_at(world, "brooklyn", datetime(2026, 3, 9, 9, 0))
    visit_at(world, "bondi", datetime(2026, 3, 10, 9, 0), patient="P0003")  # 24h: 22:00 UTC 8th

    assert world.due_reminders(utc(2026, 3, 7, 12, 59)) == []
    due = world.due_reminders(utc(2026, 3, 7, 13, 0))
    assert [(r.appointment, r.hours_before) for r in due] == [(ny.id, 48)]
    assert len(world.due_reminders(utc(2026, 3, 8, 22, 0))) == 2


def test_jobs_send_a_reminder_at_the_right_moment(world, clock):
    visit_at(world, "brooklyn", datetime(2026, 3, 9, 9, 0), patient="P0003")

    clock.set(utc(2026, 3, 7, 12, 55))
    assert world.run_jobs().reminders_sent == []
    clock.set(utc(2026, 3, 7, 13, 0))
    assert len(world.run_jobs().reminders_sent) == 1

    reminder = [m for m in world.outbox if m.template == "reminder"][0]
    assert reminder.text.endswith("Brooklyn Clinic is on Mon 9 Mar at 09:00.")
    assert reminder.at == utc(2026, 3, 7, 13, 0)


def test_reminders_that_would_already_be_due_are_left_out_by_instant(world, clock):
    clock.set(utc(2026, 3, 7, 12, 0))  # 07:00 in New York on Saturday

    appt = visit_at(world, "brooklyn", datetime(2026, 3, 9, 9, 0))

    assert [r.hours_before for r in world.reminders(appt.id)] == [48, 2]


def test_moving_an_appointment_moves_its_reminders(world):
    appt = visit_at(world, "brooklyn", datetime(2026, 3, 2, 9, 0))
    world.reschedule(appt.id, start=datetime(2026, 3, 9, 9, 0))

    assert [r.due for r in world.reminders(appt.id)] == [
        utc(2026, 3, 7, 13, 0), utc(2026, 3, 9, 11, 0),
    ]


def test_confirmations_show_the_clinics_local_time(world):
    visit_at(world, "bondi", utc(2026, 3, 2, 21, 0), patient="P0003")

    (message,) = world.outbox
    assert message.text.endswith("Bondi Clinic is booked for Tue 3 Mar at 08:00.")
