"""Importing bookings exported from the old diary system (one CSV per clinic or all in one).

Rows are history as much as plans: they are taken as they are, without the opening-hours
and double-booking checks a new booking goes through. A row already imported (same
clinic, clinician and start) is skipped, so an export can be imported again after it grew.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..busyindex import BusyIndex
from ..errors import ClinicError, ImportFailed, ValidationError
from ..hooks import EventBus
from ..ids import next_id
from ..models import Appointment, Clinic, Patient
from ..repository import Repository
from ..search import PatientIndex
from ..storage import Store
from ..timeutil import instant, localize, parse_clock, parse_date
from ..validation import check_kind, check_name, check_phone

REQUIRED = ("clinic", "clinician", "room", "patient_name", "date", "time", "minutes")
STATUSES = {
    "booked": "booked",
    "attended": "completed",
    "completed": "completed",
    "cancelled": "cancelled",
    "dna": "no_show",
    "no_show": "no_show",
}


@dataclass
class ImportResult:
    imported: list[str] = field(default_factory=list)
    duplicates: list[int] = field(default_factory=list)  # line numbers
    errors: list[tuple[int, str]] = field(default_factory=list)
    new_patients: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"imported {len(self.imported)}, skipped {len(self.duplicates)} already imported, "
            f"{len(self.errors)} with errors, {len(self.new_patients)} new patients"
        )


class LegacyImporter:
    def __init__(
        self,
        store: Store,
        index: BusyIndex,
        patients: PatientIndex,
        bus: EventBus,
        clock: Callable[[], datetime],
    ) -> None:
        self.store = store
        self.repo = Repository(store)
        self.index = index
        self.patients = patients
        self.bus = bus
        self.clock = clock

    def import_file(self, path: str | Path) -> ImportResult:
        return self.import_text(Path(path).read_text(encoding="utf-8-sig"))

    def import_text(self, text: str) -> ImportResult:
        reader = csv.DictReader(io.StringIO(text))
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise ImportFailed(f"not a diary export: no {', '.join(missing)} column")
        result = ImportResult()
        seen = {
            (a.clinic, a.clinician, instant(a.start)) for a in self.store.appointments.values()
        }
        for line, row in enumerate(reader, start=2):
            try:
                appt = self._row(row, result)
            except (ClinicError, ValueError) as exc:
                result.errors.append((line, str(exc)))
                continue
            key = (appt.clinic, appt.clinician, instant(appt.start))
            if key in seen:
                result.duplicates.append(line)
                continue
            seen.add(key)
            appt.id = next_id(self.store.counters, "appointment")
            self.store.appointments[appt.id] = appt
            self.index.add(appt)
            result.imported.append(appt.id)
            if appt.active:
                self.bus.emit("appointment.booked", appointment=appt)
        return result

    def _start(self, row: dict[str, str], clinic: Clinic) -> datetime:
        """The row's date and time, the clinic's wall-clock time."""
        day = parse_date(row["date"])
        minutes = parse_clock(row["time"])
        naive = datetime(day.year, day.month, day.day, minutes // 60, minutes % 60)
        return localize(naive, clinic.tz)

    def _row(self, row: dict[str, str], result: ImportResult) -> Appointment:
        clinic = self.repo.clinic(row["clinic"].strip())
        clinician = self.repo.clinician(row["clinician"].strip())
        if not clinician.works_at(clinic.id):
            raise ValidationError(f"{clinician.name} does not work at {clinic.name}")
        room = self.repo.room(row["room"].strip())
        if room.clinic != clinic.id:
            raise ValidationError(f"room {room.id} is not at {clinic.name}")
        status = STATUSES.get((row.get("status") or "booked").strip().lower())
        if status is None:
            raise ValidationError(f"unknown status {row.get('status')!r}")
        kind = (row.get("kind") or "consult").strip().lower()
        check_kind(kind)
        minutes = int(row["minutes"])
        if minutes <= 0:
            raise ValidationError("minutes must be positive")
        start = self._start(row, clinic)
        return Appointment(
            id="",
            clinic=clinic.id,
            clinician=clinician.id,
            room=room.id,
            patient=self._patient(row, result),
            start=start,
            minutes=minutes,
            kind=kind,
            status=status,
            notes=(row.get("notes") or "").strip(),
            created=self.clock(),
            source="import",
        )

    def _patient(self, row: dict[str, str], result: ImportResult) -> str:
        name = check_name("patient", row["patient_name"])
        phone = check_phone(row.get("patient_phone", ""))
        if phone:
            matches = self.patients.by_phone(phone)
            if matches:
                return matches[0]
        for patient in self.store.patients.values():
            if patient.name == name and not phone:
                return patient.id
        patient = Patient(id=next_id(self.store.counters, "patient"), name=name, phone=phone,
                          channel="sms")
        self.store.patients[patient.id] = patient
        self.patients.add(patient)
        result.new_patients.append(patient.id)
        return patient.id
