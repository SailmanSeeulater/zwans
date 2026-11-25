"""Records to and from the plain dicts of the data file (current version only).

Older files are brought up to date by `migrations.upgrade` before they get here.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from .config import Settings
from .hours import OpeningHours
from .models import (
    Appointment,
    AuditEntry,
    Clinic,
    Clinician,
    Message,
    Patient,
    QueuedDelivery,
    Reminder,
    Room,
    Series,
    WaitlistEntry,
)
from .timeutil import UTC, format_date, format_instant, parse_date, parse_instant

if TYPE_CHECKING:
    from .storage import Store


def _time(value: datetime | None) -> str | None:
    return None if value is None else format_instant(value)


def _parse_time(text: str | None, tz: ZoneInfo | Any = UTC) -> datetime | None:
    """A stored UTC instant, handed back in `tz` (the zone of the record's clinic)."""
    return None if text is None else parse_instant(text).astimezone(tz)


# -- dumping --------------------------------------------------------------------------


def dump(store: Store, version: int) -> dict[str, Any]:
    return {
        "version": version,
        "settings": store.settings.to_dict(),
        "counters": dict(store.counters),
        "clinics": [_clinic(c) for c in store.clinics.values()],
        "rooms": [vars(r).copy() for r in store.rooms.values()],
        "clinicians": [_clinician(c) for c in store.clinicians.values()],
        "patients": [vars(p).copy() for p in store.patients.values()],
        "appointments": [_appointment(a) for a in store.appointments.values()],
        "series": [_series(s) for s in store.series.values()],
        "reminders": [_reminder(r) for r in store.reminders.values()],
        "waitlist": [_waitlist(w) for w in store.waitlist.values()],
        "messages": [_message(m) for m in store.messages],
        "webhook_queue": [_queued(q) for q in store.webhook_queue],
        "audit": [_audit(e) for e in store.audit],
    }


def _clinic(c: Clinic) -> dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "zone": c.zone,
        "hours": c.hours.to_spec(),
        "closures": {format_date(d): why for d, why in sorted(c.closures.items())},
        "address": c.address,
        "phone": c.phone,
        "reminder_hours": c.reminder_hours,
    }


def _clinician(c: Clinician) -> dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "clinics": list(c.clinics),
        "specialty": c.specialty,
        "active": c.active,
    }


def _appointment(a: Appointment) -> dict[str, Any]:
    return {
        "id": a.id,
        "clinic": a.clinic,
        "clinician": a.clinician,
        "room": a.room,
        "patient": a.patient,
        "start": _time(a.start),
        "minutes": a.minutes,
        "kind": a.kind,
        "status": a.status,
        "series": a.series,
        "notes": a.notes,
        "created": _time(a.created),
        "source": a.source,
    }


def _series(s: Series) -> dict[str, Any]:
    return {
        "id": s.id,
        "clinic": s.clinic,
        "clinician": s.clinician,
        "room": s.room,
        "patient": s.patient,
        "start": _time(s.start),
        "minutes": s.minutes,
        "rule": dict(s.rule),
        "kind": s.kind,
    }


def _reminder(r: Reminder) -> dict[str, Any]:
    return {
        "id": r.id,
        "appointment": r.appointment,
        "hours_before": r.hours_before,
        "due": _time(r.due),
        "sent": _time(r.sent),
    }


def _waitlist(w: WaitlistEntry) -> dict[str, Any]:
    return {
        "id": w.id,
        "patient": w.patient,
        "clinic": w.clinic,
        "minutes": w.minutes,
        "kind": w.kind,
        "clinician": w.clinician,
        "earliest": _time(w.earliest),
        "latest": _time(w.latest),
        "added": _time(w.added),
        "status": w.status,
        "appointment": w.appointment,
    }


def _message(m: Message) -> dict[str, Any]:
    return {
        "id": m.id,
        "to": m.to,
        "channel": m.channel,
        "template": m.template,
        "text": m.text,
        "at": _time(m.at),
        "appointment": m.appointment,
    }


def _queued(q: QueuedDelivery) -> dict[str, Any]:
    return {
        "id": q.id,
        "payload": q.payload,
        "attempts": q.attempts,
        "next_attempt": _time(q.next_attempt),
        "last_error": q.last_error,
    }


def _audit(e: AuditEntry) -> dict[str, Any]:
    return {"seq": e.seq, "at": _time(e.at), "action": e.action, "entity": e.entity,
            "details": e.details}


# -- loading --------------------------------------------------------------------------


def load(store: Store, data: dict[str, Any]) -> None:
    store.settings = Settings.from_dict(data.get("settings", {}))
    store.counters = dict(data.get("counters", {}))
    for row in data.get("clinics", []):
        clinic = Clinic(
            id=row["id"],
            name=row["name"],
            zone=row["zone"],
            hours=OpeningHours.parse(row.get("hours")),
            closures={parse_date(d): why for d, why in row.get("closures", {}).items()},
            address=row.get("address", ""),
            phone=row.get("phone", ""),
            reminder_hours=row.get("reminder_hours"),
        )
        store.clinics[clinic.id] = clinic
    for row in data.get("rooms", []):
        store.rooms[row["id"]] = Room(**row)
    for row in data.get("clinicians", []):
        store.clinicians[row["id"]] = Clinician(**row)
    for row in data.get("patients", []):
        store.patients[row["id"]] = Patient(**row)
    def tz(clinic_id: str) -> Any:
        clinic = store.clinics.get(clinic_id)
        return clinic.tz if clinic is not None else UTC

    for row in data.get("appointments", []):
        zone = tz(row["clinic"])
        store.appointments[row["id"]] = Appointment(
            **{
                **row,
                "start": _parse_time(row["start"], zone),
                "created": _parse_time(row.get("created"), zone),
            }
        )
    for row in data.get("series", []):
        store.series[row["id"]] = Series(
            **{**row, "start": _parse_time(row["start"], tz(row["clinic"]))}
        )
    for row in data.get("reminders", []):
        appt = store.appointments.get(row["appointment"])
        zone = tz(appt.clinic) if appt is not None else UTC
        store.reminders[row["id"]] = Reminder(
            **{
                **row,
                "due": _parse_time(row["due"], zone),
                "sent": _parse_time(row.get("sent"), zone),
            }
        )
    for row in data.get("waitlist", []):
        zone = tz(row["clinic"])
        store.waitlist[row["id"]] = WaitlistEntry(
            **{
                **row,
                "earliest": _parse_time(row.get("earliest"), zone),
                "latest": _parse_time(row.get("latest"), zone),
                "added": _parse_time(row.get("added"), zone),
            }
        )
    store.messages = [
        Message(**{**row, "at": _parse_time(row["at"])}) for row in data.get("messages", [])
    ]
    store.webhook_queue = [
        QueuedDelivery(**{**row, "next_attempt": _parse_time(row["next_attempt"])})
        for row in data.get("webhook_queue", [])
    ]
    store.audit = [
        AuditEntry(**{**row, "at": _parse_time(row["at"])}) for row in data.get("audit", [])
    ]
