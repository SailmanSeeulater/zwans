"""The daily agenda: one clinic's appointments for one day, printed for the front desk."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .. import formatting
from ..models import Clinic
from ..repository import Repository
from ..storage import Store


@dataclass
class AgendaRow:
    appointment: str
    start: datetime
    end: datetime
    room: str
    clinician: str
    patient: str
    kind: str
    status: str


@dataclass
class Agenda:
    clinic: Clinic
    day: date
    rows: list[AgendaRow]

    def render(self) -> str:
        title = f"{self.clinic.name}, {formatting.day_title(self.day)}"
        if self.clinic.is_closed(self.day):
            return f"{title}\nClosed: {self.clinic.closures[self.day]}\n"
        if not self.rows:
            return f"{title}\nNo appointments.\n"
        body = formatting.table(
            ["time", "room", "clinician", "patient", "kind", "status"],
            [
                [formatting.span(r.start, r.end), r.room, r.clinician, r.patient, r.kind,
                 r.status.replace("_", " ")]
                for r in self.rows
            ],
        )
        footer = formatting.plural(len(self.rows), "appointment")
        return f"{title}\n{body}\n{footer}\n"


def agenda(store: Store, clinic_id: str, day: date, *, include_cancelled: bool = False) -> Agenda:
    repo = Repository(store)
    clinic = repo.clinic(clinic_id)
    first = datetime.combine(day, time.min)
    last = first + timedelta(days=1)
    rows = []
    for appt in repo.appointments_between(clinic_id, first, last):
        if appt.status == "cancelled" and not include_cancelled:
            continue
        rows.append(
            AgendaRow(
                appointment=appt.id,
                start=appt.start,
                end=appt.end,
                room=appt.room,
                clinician=repo.clinician(appt.clinician).name,
                patient=repo.patient(appt.patient).name,
                kind=appt.kind,
                status=appt.status,
            )
        )
    return Agenda(clinic, day, rows)
