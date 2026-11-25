"""The records clinicbook keeps. Plain dataclasses; the services own the rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from .hours import OpeningHours

ACTIVE = "booked"
STATUSES = ("booked", "completed", "cancelled", "no_show")


@dataclass
class Clinic:
    id: str
    name: str
    zone: str  # IANA name, shown on the website and in exports
    hours: OpeningHours
    closures: dict[date, str] = field(default_factory=dict)
    address: str = ""
    phone: str = ""
    reminder_hours: list[int] | None = None  # None: the setting applies

    def is_closed(self, day: date) -> bool:
        return day in self.closures


@dataclass
class Room:
    id: str
    clinic: str
    name: str
    active: bool = True


@dataclass
class Clinician:
    id: str
    name: str
    clinics: list[str]
    specialty: str = ""
    active: bool = True

    def works_at(self, clinic: str) -> bool:
        return clinic in self.clinics


@dataclass
class Patient:
    id: str
    name: str
    phone: str = ""
    email: str = ""
    channel: str = "sms"

    def address(self) -> str:
        return self.phone if self.channel == "sms" else self.email


@dataclass
class Appointment:
    id: str
    clinic: str
    clinician: str
    room: str
    patient: str
    start: datetime
    minutes: int
    kind: str = "consult"
    status: str = ACTIVE
    series: str | None = None
    notes: str = ""
    created: datetime | None = None
    source: str = "desk"  # desk, series, waitlist, import

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.minutes)

    @property
    def active(self) -> bool:
        return self.status == ACTIVE

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return self.start < end and start < self.end


@dataclass
class Series:
    id: str
    clinic: str
    clinician: str
    room: str
    patient: str
    start: datetime
    minutes: int
    rule: dict[str, Any]
    kind: str = "consult"


@dataclass
class Reminder:
    id: str
    appointment: str
    hours_before: int
    due: datetime
    sent: datetime | None = None


@dataclass
class WaitlistEntry:
    id: str
    patient: str
    clinic: str
    minutes: int
    kind: str = "consult"
    clinician: str | None = None
    earliest: datetime | None = None
    latest: datetime | None = None
    added: datetime | None = None
    status: str = "waiting"  # waiting, offered, expired, removed
    appointment: str | None = None


@dataclass
class Message:
    id: str
    to: str
    channel: str
    template: str
    text: str
    at: datetime
    appointment: str | None = None


@dataclass
class QueuedDelivery:
    id: str
    payload: dict[str, Any]
    attempts: int
    next_attempt: datetime
    last_error: str = ""


@dataclass
class AuditEntry:
    seq: int
    at: datetime
    action: str
    entity: str
    details: dict[str, Any] = field(default_factory=dict)
