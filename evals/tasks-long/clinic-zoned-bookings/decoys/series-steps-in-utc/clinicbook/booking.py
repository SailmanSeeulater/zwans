"""Booking, moving, cancelling and closing appointments."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from .busyindex import BusyIndex
from .conflicts import ConflictChecker
from .errors import BookingError, Conflict, InvalidTime, OutsideOpeningHours, StatusError
from .hooks import EventBus
from .ids import next_id
from .models import ACTIVE, Appointment, Clinic
from .repository import Repository
from .storage import Store
from .timeutil import end_of, format_date, in_zone, instant, on_grid, parse_when
from .validation import check_kind, check_minutes

Clock = Callable[[], datetime]


class BookingService:
    def __init__(
        self,
        store: Store,
        repo: Repository,
        index: BusyIndex,
        conflicts: ConflictChecker,
        bus: EventBus,
        clock: Clock,
    ) -> None:
        self.store = store
        self.repo = repo
        self.index = index
        self.conflicts = conflicts
        self.bus = bus
        self.clock = clock

    # -- checks -----------------------------------------------------------------------

    def when(self, clinic: Clinic, value: datetime | str) -> datetime:
        """A time as given by a caller, in the clinic's zone: a naive time is the clinic's
        wall-clock time (and must exist), an aware one is that instant."""
        if isinstance(value, str):
            try:
                value = parse_when(value)
            except ValueError as exc:
                raise InvalidTime(str(exc)) from None
        return in_zone(value, clinic.tz)

    def check_open(self, clinic: Clinic, start: datetime, minutes: int) -> None:
        day = start.date()
        if clinic.is_closed(day):
            raise OutsideOpeningHours(
                f"{clinic.name} is closed on {format_date(day)} ({clinic.closures[day]})"
            )
        if not clinic.hours.covers(start, minutes):
            raise OutsideOpeningHours(f"{clinic.name} is not open for all of that time")

    def _check(
        self,
        clinic: Clinic,
        clinician: str,
        room: str,
        patient: str,
        start: datetime,
        minutes: int,
        *,
        ignore: str | None = None,
    ) -> None:
        person = self.repo.clinician(clinician)
        if not person.active or not person.works_at(clinic.id):
            raise BookingError(f"{person.name} does not work at {clinic.name}")
        place = self.repo.room(room)
        if place.clinic != clinic.id or not place.active:
            raise BookingError(f"room {room} is not in use at {clinic.name}")
        self.repo.patient(patient)
        grid = self.store.settings.grid_minutes
        check_minutes(minutes, grid)
        if not on_grid(start, grid):
            raise InvalidTime(f"appointments start on a {grid}-minute boundary")
        if instant(start) < instant(self.clock()):
            raise InvalidTime("that time has already passed")
        self.check_open(clinic, start, minutes)
        end = end_of(start, minutes)
        clashes = self.conflicts.clashes(
            start=start, end=end, clinician=clinician, room=room, patient=patient, ignore=ignore
        )
        if clashes:
            raise Conflict(clashes)

    # -- operations -------------------------------------------------------------------

    def book(
        self,
        *,
        clinic: str,
        clinician: str,
        room: str,
        patient: str,
        start: datetime | str,
        minutes: int,
        kind: str = "consult",
        notes: str = "",
        series: str | None = None,
        source: str = "desk",
    ) -> Appointment:
        place = self.repo.clinic(clinic)
        start = self.when(place, start)
        check_kind(kind)
        self._check(place, clinician, room, patient, start, minutes)
        appt = Appointment(
            id=next_id(self.store.counters, "appointment"),
            clinic=clinic,
            clinician=clinician,
            room=room,
            patient=patient,
            start=start,
            minutes=minutes,
            kind=kind,
            notes=notes,
            series=series,
            created=self.clock(),
            source=source,
        )
        self.store.appointments[appt.id] = appt
        self.index.add(appt)
        self.bus.emit("appointment.booked", appointment=appt)
        return appt

    def reschedule(
        self,
        appointment_id: str,
        *,
        start: datetime | str,
        minutes: int | None = None,
        room: str | None = None,
    ) -> Appointment:
        appt = self._active(appointment_id)
        place = self.repo.clinic(appt.clinic)
        start = self.when(place, start)
        minutes = appt.minutes if minutes is None else minutes
        room = appt.room if room is None else room
        self._check(place, appt.clinician, room, appt.patient, start, minutes, ignore=appt.id)
        previous = appt.start
        appt.start, appt.minutes, appt.room = start, minutes, room
        self.index.add(appt)
        self.bus.emit("appointment.rescheduled", appointment=appt, previous_start=previous)
        return appt

    def cancel(self, appointment_id: str, *, reason: str = "") -> Appointment:
        appt = self._active(appointment_id)
        appt.status = "cancelled"
        if reason:
            appt.notes = f"{appt.notes}\ncancelled: {reason}".strip()
        self.index.remove(appt.id)
        self.bus.emit("appointment.cancelled", appointment=appt, reason=reason)
        return appt

    def complete(self, appointment_id: str) -> Appointment:
        appt = self._active(appointment_id)
        appt.status = "completed"
        self.index.remove(appt.id)
        self.bus.emit("appointment.completed", appointment=appt)
        return appt

    def mark_no_show(self, appointment_id: str) -> Appointment:
        appt = self._active(appointment_id)
        appt.status = "no_show"
        self.index.remove(appt.id)
        self.bus.emit("appointment.no_show", appointment=appt)
        return appt

    def _active(self, appointment_id: str) -> Appointment:
        appt = self.repo.appointment(appointment_id)
        if appt.status != ACTIVE:
            raise StatusError(f"{appt.id} is {appt.status.replace('_', ' ')}")
        return appt
