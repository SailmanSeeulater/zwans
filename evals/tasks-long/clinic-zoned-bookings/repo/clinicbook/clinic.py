"""ClinicBook: the one object the CLI, the tests and scripts talk to."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import backup as backups
from . import reports
from .audit import AuditLog
from .booking import BookingService
from .busyindex import BusyIndex
from .conflicts import ConflictChecker
from .errors import ValidationError
from .exporters import export_csv, export_ical
from .hooks import EventBus
from .hours import OpeningHours
from .ids import next_id
from .importers import ImportResult, LegacyImporter
from .jobs import JobReport, Jobs
from .models import (
    Appointment,
    AuditEntry,
    Clinic,
    Clinician,
    Message,
    Patient,
    Reminder,
    Room,
    WaitlistEntry,
)
from .notify import Notifier
from .recurrence import Recurrence
from .reminders import ReminderPlanner
from .repository import Repository
from .search import PatientIndex
from .series import SeriesResult, SeriesService
from .slots import Slot, SlotFinder
from .storage import Store
from .validation import (
    check_channel,
    check_email,
    check_hours_list,
    check_id,
    check_name,
    check_phone,
    check_room_id,
    check_zone,
)
from .waitlist import Waitlist
from .webhooks import Sender, WebhookDispatcher

Clock = Callable[[], datetime]


def system_clock() -> datetime:
    return datetime.now().replace(second=0, microsecond=0)


class ClinicBook:
    def __init__(
        self,
        store: Store | None = None,
        *,
        clock: Clock | None = None,
        webhook_sender: Sender | None = None,
    ) -> None:
        self.store = store if store is not None else Store.memory()
        self.clock: Clock = clock or system_clock
        self.repo = Repository(self.store)
        self.bus = EventBus()
        self.index = BusyIndex()
        self.patient_index = PatientIndex()
        self.conflicts = ConflictChecker(self.store, self.index)
        self.booking = BookingService(
            self.store, self.repo, self.index, self.conflicts, self.bus, self._now
        )
        self.series_service = SeriesService(self.store, self.repo, self.booking, self._now)
        self.planner = ReminderPlanner(self.store, self.repo, self._now)
        self.notifier = Notifier(self.store, self.repo, self._now)
        self.webhooks = WebhookDispatcher(self.store, self.repo, self._now, webhook_sender)
        self.audit = AuditLog(self.store, self._now)
        self.finder = SlotFinder(self.store, self.repo, self.conflicts, self._now)
        self.waitlist_service = Waitlist(
            self.store, self.repo, self.finder, self.booking, self.bus, self._now
        )
        self.jobs = Jobs(
            self.store, self.repo, self.booking, self.planner, self.notifier, self.webhooks,
            self.waitlist_service, self._now,
        )
        self.importer = LegacyImporter(
            self.store, self.index, self.patient_index, self.bus, self._now
        )
        self._wire()
        self._reindex()
        self.store.on_reset(self._reindex)

    def _now(self) -> datetime:
        return self.clock()

    def _wire(self) -> None:
        self.bus.subscribe("appointment.booked", self.planner.on_booked)
        self.bus.subscribe("appointment.rescheduled", self.planner.on_rescheduled)
        self.bus.subscribe("appointment.cancelled", self.planner.on_cancelled)
        self.bus.subscribe("appointment.booked", self.notifier.on_booked)
        self.bus.subscribe("appointment.cancelled", self.notifier.on_cancelled)
        self.bus.subscribe("appointment.rescheduled", self.notifier.on_rescheduled)
        self.bus.subscribe("waitlist.offered", self.notifier.on_offered)
        self.bus.subscribe_all(self.webhooks.on_event)
        self.bus.subscribe_all(self.audit.on_event)

    def _reindex(self) -> None:
        self.index.rebuild(self.store.appointments.values())
        self.patient_index.rebuild(self.store.patients.values())

    # -- files ------------------------------------------------------------------------

    @classmethod
    def open(cls, path: str | os.PathLike[str], **kwargs: Any) -> ClinicBook:
        return cls(Store.open(path), **kwargs)

    def save(self, path: str | os.PathLike[str] | None = None) -> Path:
        return self.store.save(path)

    def backup(self, path: str | os.PathLike[str]) -> Path:
        return backups.write_backup(self.store, path, self._now())

    def restore(self, path: str | os.PathLike[str]) -> None:
        """Replace everything in this book with the contents of a backup."""
        self.store.replace_with(backups.read_backup(path))
        self.audit.record("restored", "store", backup=str(path))

    # -- setting up -------------------------------------------------------------------

    def configure(self, **settings: Any) -> None:
        self.store.settings.update(**settings)

    def add_clinic(
        self,
        clinic_id: str,
        name: str,
        *,
        zone: str,
        hours: dict[str, Any] | None = None,
        address: str = "",
        phone: str = "",
        reminder_hours: list[int] | None = None,
    ) -> Clinic:
        check_id("clinic", clinic_id)
        if clinic_id in self.store.clinics:
            raise ValidationError(f"there is already a clinic {clinic_id!r}")
        clinic = Clinic(
            id=clinic_id,
            name=check_name("clinic", name),
            zone=check_zone(zone),
            hours=OpeningHours.parse(hours),
            address=address,
            phone=check_phone(phone),
            reminder_hours=None if reminder_hours is None else check_hours_list(reminder_hours),
        )
        self.store.clinics[clinic.id] = clinic
        self.audit.record("clinic.added", clinic.id, zone=clinic.zone)
        return clinic

    def set_hours(self, clinic_id: str, hours: dict[str, Any]) -> Clinic:
        clinic = self.repo.clinic(clinic_id)
        clinic.hours = OpeningHours.parse(hours)
        self.audit.record("clinic.hours", clinic.id, hours=clinic.hours.to_spec())
        return clinic

    def close_day(self, clinic_id: str, day: date, reason: str) -> None:
        clinic = self.repo.clinic(clinic_id)
        clinic.closures[day] = reason or "closed"
        self.audit.record("clinic.closed", clinic.id, day=day.isoformat(), reason=reason)

    def add_room(self, clinic_id: str, room_id: str, name: str = "") -> Room:
        self.repo.clinic(clinic_id)
        check_room_id(room_id)
        if room_id in self.store.rooms:
            raise ValidationError(f"there is already a room {room_id!r}")
        room = Room(id=room_id, clinic=clinic_id, name=check_name("room", name or room_id))
        self.store.rooms[room.id] = room
        return room

    def add_clinician(
        self, clinician_id: str, name: str, *, clinics: list[str], specialty: str = ""
    ) -> Clinician:
        check_id("clinician", clinician_id)
        if clinician_id in self.store.clinicians:
            raise ValidationError(f"there is already a clinician {clinician_id!r}")
        if not clinics:
            raise ValidationError("a clinician works at one clinic at least")
        for clinic_id in clinics:
            self.repo.clinic(clinic_id)
        clinician = Clinician(
            id=clinician_id, name=check_name("clinician", name), clinics=list(clinics),
            specialty=specialty,
        )
        self.store.clinicians[clinician.id] = clinician
        return clinician

    def add_patient(
        self, name: str, *, phone: str = "", email: str = "", channel: str | None = None
    ) -> Patient:
        phone, email = check_phone(phone), check_email(email)
        channel = check_channel(channel or ("sms" if phone else "email"))
        patient = Patient(
            id=next_id(self.store.counters, "patient"),
            name=check_name("patient", name),
            phone=phone,
            email=email,
            channel=channel,
        )
        self.store.patients[patient.id] = patient
        self.patient_index.add(patient)
        return patient

    def find_patients(self, query: str) -> list[Patient]:
        return [self.store.patients[pid] for pid in self.patient_index.find(query)]

    # -- appointments -----------------------------------------------------------------

    def book(self, **kwargs: Any) -> Appointment:
        """book(clinic=, clinician=, room=, patient=, start=, minutes=, kind=, notes=)"""
        return self.booking.book(**kwargs)

    def reschedule(self, appointment_id: str, **kwargs: Any) -> Appointment:
        return self.booking.reschedule(appointment_id, **kwargs)

    def cancel(self, appointment_id: str, reason: str = "") -> Appointment:
        return self.booking.cancel(appointment_id, reason=reason)

    def complete(self, appointment_id: str) -> Appointment:
        return self.booking.complete(appointment_id)

    def mark_no_show(self, appointment_id: str) -> Appointment:
        return self.booking.mark_no_show(appointment_id)

    def book_series(self, *, rule: Recurrence | dict[str, Any], **kwargs: Any) -> SeriesResult:
        if isinstance(rule, dict):
            rule = Recurrence.from_dict(rule)
        return self.series_service.book_series(rule=rule, **kwargs)

    def cancel_series(self, series_id: str, from_day: date | None = None) -> list[Appointment]:
        return self.series_service.cancel_series(series_id, from_day=from_day)

    def appointment(self, appointment_id: str) -> Appointment:
        return self.repo.appointment(appointment_id)

    def appointments(self, **filters: Any) -> list[Appointment]:
        return self.repo.appointments(**filters)

    def reminders(self, appointment_id: str) -> list[Reminder]:
        return self.repo.reminders_of(appointment_id)

    def due_reminders(self, now: datetime | None = None) -> list[Reminder]:
        return self.planner.due(now or self._now())

    # -- slots and the waitlist -------------------------------------------------------

    def slots(self, clinic: str, day: date, minutes: int, **kwargs: Any) -> list[Slot]:
        return self.finder.day_slots(clinic, day, minutes, **kwargs)

    def next_free_slot(self, clinic: str, minutes: int, **kwargs: Any) -> Slot | None:
        return self.finder.next_free(clinic, minutes, **kwargs)

    def waitlist_add(self, **kwargs: Any) -> WaitlistEntry:
        return self.waitlist_service.add(**kwargs)

    def waitlist(self, clinic: str | None = None, status: str = "waiting") -> list[WaitlistEntry]:
        return self.waitlist_service.entries(clinic, status)

    def offer_waitlist(self, now: datetime | None = None) -> list[Appointment]:
        return self.waitlist_service.offer(now)

    def run_jobs(self, now: datetime | None = None) -> JobReport:
        return self.jobs.run(now)

    # -- reports, exports, imports ----------------------------------------------------

    def agenda(self, clinic: str, day: date, **kwargs: Any) -> reports.Agenda:
        return reports.agenda(self.store, clinic, day, **kwargs)

    def utilisation(self, clinic: str, first: date, last: date) -> reports.Utilisation:
        return reports.utilisation(self.store, clinic, first, last)

    def no_shows(self, clinic: str | None = None) -> list[reports.NoShowLine]:
        return reports.no_show_summary(self.store, clinic)

    def export_ical(self, **filters: Any) -> str:
        return export_ical(self.store, self._now(), **filters)

    def export_csv(self, **filters: Any) -> str:
        return export_csv(self.store, **filters)

    def import_csv(self, source: str | os.PathLike[str]) -> ImportResult:
        """Import a diary export, from a file path or the CSV text itself."""
        if isinstance(source, str) and "\n" in source:
            return self.importer.import_text(source)
        return self.importer.import_file(source)

    # -- what went out ----------------------------------------------------------------

    @property
    def outbox(self) -> list[Message]:
        return list(self.store.messages)

    @property
    def webhook_deliveries(self) -> list[dict[str, Any]]:
        return list(self.webhooks.delivered)

    def history(self, entity: str) -> list[AuditEntry]:
        return self.audit.history(entity)
