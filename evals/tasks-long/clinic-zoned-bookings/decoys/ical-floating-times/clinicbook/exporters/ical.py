"""iCalendar (RFC 5545) export, for clinicians who want their list in a calendar app."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from ..models import Appointment
from ..repository import Repository
from ..storage import Store

PRODID = "-//clinicbook//appointments//EN"
STAMP_FORMAT = "%Y%m%dT%H%M%S"


def escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    )


def fold(line: str) -> list[str]:
    """Split a content line into 75-octet pieces; continuation lines start with a space."""
    pieces: list[str] = []
    current = ""
    for char in line:
        limit = 75 if not pieces else 74
        if len((current + char).encode("utf-8")) > limit:
            pieces.append(current)
            current = char
        else:
            current += char
    pieces.append(current)
    return [pieces[0]] + [" " + p for p in pieces[1:]]


def stamp(value: datetime) -> str:
    return value.strftime(STAMP_FORMAT)


def event_lines(repo: Repository, appt: Appointment, now: datetime) -> list[str]:
    clinic = repo.clinic(appt.clinic)
    room = repo.room(appt.room)
    patient = repo.patient(appt.patient)
    clinician = repo.clinician(appt.clinician)
    status = {"cancelled": "CANCELLED"}.get(appt.status, "CONFIRMED")
    lines = [
        "BEGIN:VEVENT",
        f"UID:{appt.id}@clinicbook",
        f"DTSTAMP:{stamp(now)}",
        f"DTSTART:{stamp(appt.start)}",
        f"DTEND:{stamp(appt.end)}",
        f"SUMMARY:{escape(f'{appt.kind.capitalize()}: {patient.name} with {clinician.name}')}",
        f"LOCATION:{escape(f'{clinic.name}, {room.name}')}",
        f"STATUS:{status}",
    ]
    if appt.notes:
        lines.append(f"DESCRIPTION:{escape(appt.notes)}")
    lines.append("END:VEVENT")
    return lines


def export_ical(
    store: Store,
    now: datetime,
    *,
    clinic: str | None = None,
    clinician: str | None = None,
    patient: str | None = None,
    first: date | None = None,
    last: date | None = None,
    include_cancelled: bool = False,
) -> str:
    """The selected appointments as one VCALENDAR. `first`/`last` are days, both included."""
    repo = Repository(store)
    chosen: Iterable[Appointment] = repo.appointments(
        clinic=clinic, clinician=clinician, patient=patient
    )
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN"]
    for appt in chosen:
        if appt.status == "cancelled" and not include_cancelled:
            continue
        if first is not None and appt.start.date() < first:
            continue
        if last is not None and appt.start.date() > last:
            continue
        lines.extend(event_lines(repo, appt, now))
    lines.append("END:VCALENDAR")
    return "".join(piece + "\r\n" for line in lines for piece in fold(line))
