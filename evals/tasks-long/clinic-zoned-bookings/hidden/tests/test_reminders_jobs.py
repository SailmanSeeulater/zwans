from datetime import datetime

from support import visit, wall


def test_reminders_are_planned_from_the_setting(book):
    appt = visit(book, datetime(2026, 1, 12, 9, 0))

    reminders = book.reminders(appt.id)

    assert [(r.hours_before, wall(r.due)) for r in reminders] == [
        (24, "2026-01-11 09:00"),
        (2, "2026-01-12 07:00"),
    ]


def test_a_clinic_can_have_its_own_reminder_hours(book):
    book.store.clinics["camden"].reminder_hours = [72]
    appt = visit(book, datetime(2026, 1, 12, 9, 0))

    assert [wall(r.due) for r in book.reminders(appt.id)] == ["2026-01-09 09:00"]


def test_reminders_already_due_are_not_planned(book):
    appt = visit(book, datetime(2026, 1, 5, 9, 0))  # in an hour

    assert book.reminders(appt.id) == []


def test_moving_replans_and_cancelling_drops_reminders(book):
    appt = visit(book, datetime(2026, 1, 12, 9, 0))
    book.reschedule(appt.id, start=datetime(2026, 1, 14, 15, 0))

    assert [wall(r.due) for r in book.reminders(appt.id)] == ["2026-01-13 15:00",
                                                              "2026-01-14 13:00"]
    book.cancel(appt.id)
    assert book.reminders(appt.id) == []


def test_due_reminders_and_sending_them(book, clock):
    a = visit(book, datetime(2026, 1, 12, 9, 0))
    b = visit(book, datetime(2026, 1, 12, 14, 0), patient="P0002")

    assert book.due_reminders(datetime(2026, 1, 11, 8, 59)) == []
    assert [r.appointment for r in book.due_reminders(datetime(2026, 1, 11, 14, 0))] == [
        a.id, b.id,
    ]

    clock.set(datetime(2026, 1, 11, 9, 30))
    report = book.run_jobs()

    assert len(report.reminders_sent) == 1
    sent = [m for m in book.outbox if m.template == "reminder"]
    assert len(sent) == 1
    assert sent[0].to == "+44 7700 900001"
    assert sent[0].text == (
        "Reminder: your consult with Dr Ama Osei at Camden Clinic is on Mon 12 Jan at 09:00."
    )
    assert book.run_jobs().reminders_sent == []  # not sent twice


def test_booking_sends_a_confirmation(book):
    visit(book, datetime(2026, 1, 12, 9, 0), patient="P0002")

    (message,) = book.outbox
    assert message.channel == "email" and message.to == "sam@example.org"
    assert message.text == (
        "Sam, your consult with Dr Ama Osei at Camden Clinic is booked for Mon 12 Jan at 09:00."
    )


def test_jobs_mark_no_shows_after_the_grace_period(book, clock):
    appt = visit(book, datetime(2026, 1, 12, 9, 0))
    done = visit(book, datetime(2026, 1, 12, 10, 0))

    clock.set(datetime(2026, 1, 12, 9, 44))
    assert book.run_jobs().no_shows == []
    book.complete(done.id)
    clock.set(datetime(2026, 1, 12, 10, 45))
    assert book.run_jobs().no_shows == [appt.id]
    assert appt.status == "no_show" and done.status == "completed"


def test_the_audit_log_records_events(book):
    appt = visit(book, datetime(2026, 1, 12, 9, 0))
    book.reschedule(appt.id, start=datetime(2026, 1, 12, 10, 0))
    book.cancel(appt.id, reason="unwell")

    actions = [e.action for e in book.history(appt.id)]
    assert actions == ["appointment.booked", "appointment.rescheduled", "appointment.cancelled"]
    assert book.history(appt.id)[-1].details["reason"] == "unwell"
