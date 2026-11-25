"""Lookups over the store's tables, raising NotFound for unknown ids."""

from __future__ import annotations

from datetime import datetime

from .errors import NotFound
from .models import Appointment, Clinic, Clinician, Patient, Reminder, Room, Series
from .storage import Store
from .timeutil import instant


class Repository:
    def __init__(self, store: Store) -> None:
        self.store = store

    def clinic(self, clinic_id: str) -> Clinic:
        try:
            return self.store.clinics[clinic_id]
        except KeyError:
            raise NotFound("clinic", clinic_id) from None

    def room(self, room_id: str) -> Room:
        try:
            return self.store.rooms[room_id]
        except KeyError:
            raise NotFound("room", room_id) from None

    def clinician(self, clinician_id: str) -> Clinician:
        try:
            return self.store.clinicians[clinician_id]
        except KeyError:
            raise NotFound("clinician", clinician_id) from None

    def patient(self, patient_id: str) -> Patient:
        try:
            return self.store.patients[patient_id]
        except KeyError:
            raise NotFound("patient", patient_id) from None

    def appointment(self, appointment_id: str) -> Appointment:
        try:
            return self.store.appointments[appointment_id]
        except KeyError:
            raise NotFound("appointment", appointment_id) from None

    def series(self, series_id: str) -> Series:
        try:
            return self.store.series[series_id]
        except KeyError:
            raise NotFound("series", series_id) from None

    def rooms_of(self, clinic_id: str, *, active_only: bool = True) -> list[Room]:
        rooms = [r for r in self.store.rooms.values() if r.clinic == clinic_id]
        if active_only:
            rooms = [r for r in rooms if r.active]
        return sorted(rooms, key=lambda r: r.id)

    def clinicians_of(self, clinic_id: str, *, active_only: bool = True) -> list[Clinician]:
        people = [c for c in self.store.clinicians.values() if c.works_at(clinic_id)]
        if active_only:
            people = [c for c in people if c.active]
        return sorted(people, key=lambda c: c.id)

    def appointments(
        self,
        *,
        clinic: str | None = None,
        clinician: str | None = None,
        room: str | None = None,
        patient: str | None = None,
        status: str | None = None,
        series: str | None = None,
    ) -> list[Appointment]:
        found = [
            a
            for a in self.store.appointments.values()
            if (clinic is None or a.clinic == clinic)
            and (clinician is None or a.clinician == clinician)
            and (room is None or a.room == room)
            and (patient is None or a.patient == patient)
            and (status is None or a.status == status)
            and (series is None or a.series == series)
        ]
        return sorted(found, key=lambda a: (instant(a.start), a.id))

    def appointments_between(
        self, clinic: str, start: datetime, end: datetime, *, status: str | None = None
    ) -> list[Appointment]:
        """The clinic's appointments starting at or after `start` and before `end`."""
        return [
            a
            for a in self.appointments(clinic=clinic, status=status)
            if instant(start) <= instant(a.start) < instant(end)
        ]

    def reminders_of(self, appointment_id: str) -> list[Reminder]:
        found = [r for r in self.store.reminders.values() if r.appointment == appointment_id]
        return sorted(found, key=lambda r: (instant(r.due), r.id))
