"""Reminders: a message some hours before each appointment."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from .ids import next_id
from .models import Appointment, Reminder
from .repository import Repository
from .storage import Store


class ReminderPlanner:
    def __init__(self, store: Store, repo: Repository, clock: Callable[[], datetime]) -> None:
        self.store = store
        self.repo = repo
        self.clock = clock

    def hours_for(self, appt: Appointment) -> list[int]:
        clinic = self.repo.clinic(appt.clinic)
        hours = clinic.reminder_hours
        if hours is None:
            hours = self.store.settings.reminder_hours
        return sorted(set(hours), reverse=True)

    def due_time(self, appt: Appointment, hours_before: int) -> datetime:
        return appt.start - timedelta(hours=hours_before)

    def plan(self, appt: Appointment) -> list[Reminder]:
        """Reminders for a new appointment; ones that would already be due are left out."""
        now = self.clock()
        planned = []
        for hours in self.hours_for(appt):
            due = self.due_time(appt, hours)
            if due <= now:
                continue
            reminder = Reminder(
                id=next_id(self.store.counters, "reminder"),
                appointment=appt.id,
                hours_before=hours,
                due=due,
            )
            self.store.reminders[reminder.id] = reminder
            planned.append(reminder)
        return planned

    def drop(self, appt: Appointment) -> None:
        for reminder in self.repo.reminders_of(appt.id):
            if reminder.sent is None:
                del self.store.reminders[reminder.id]

    def replan(self, appt: Appointment) -> list[Reminder]:
        self.drop(appt)
        return self.plan(appt)

    def due(self, now: datetime) -> list[Reminder]:
        found = []
        for reminder in self.store.reminders.values():
            if reminder.sent is not None or reminder.due > now:
                continue
            appt = self.store.appointments.get(reminder.appointment)
            if appt is None or not appt.active:
                continue
            found.append(reminder)
        return sorted(found, key=lambda r: (r.due, r.id))

    def mark_sent(self, reminder: Reminder, at: datetime) -> None:
        reminder.sent = at

    # -- event handlers ---------------------------------------------------------------

    def on_booked(self, appointment: Appointment, **_: Any) -> None:
        self.plan(appointment)

    def on_rescheduled(self, appointment: Appointment, **_: Any) -> None:
        self.replan(appointment)

    def on_cancelled(self, appointment: Appointment, **_: Any) -> None:
        self.drop(appointment)
