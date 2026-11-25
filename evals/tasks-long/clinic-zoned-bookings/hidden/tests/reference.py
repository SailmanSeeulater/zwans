"""A small, independent model of the README's booking and time zone rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _minutes(text: str) -> int:
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def parse_hours(spec: dict[str, str]) -> dict[str, list[tuple[int, int]]]:
    week: dict[str, list[tuple[int, int]]] = {day: [] for day in WEEKDAYS}
    for day, text in spec.items():
        for part in text.split(","):
            start, end = part.strip().split("-")
            week[day].append((_minutes(start), _minutes(end)))
    return week


@dataclass
class RefAppointment:
    id: str
    clinic: str
    clinician: str
    room: str
    patient: str
    start: datetime  # UTC
    minutes: int
    status: str = "booked"

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.minutes)


class Reference:
    def __init__(self, zones: dict[str, str], hours: dict[str, dict[str, str]],
                 reminder_hours: dict[str, list[int]], default_reminders: list[int],
                 now: datetime) -> None:
        self.zones = {c: ZoneInfo(z) for c, z in zones.items()}
        self.hours = {c: parse_hours(h) for c, h in hours.items()}
        self.reminder_hours = reminder_hours
        self.default_reminders = default_reminders
        self.now = now
        self.appointments: dict[str, RefAppointment] = {}

    def localize(self, clinic: str, naive: datetime) -> datetime | None:
        """The UTC instant of a local wall-clock time, None if it doesn't exist."""
        tz = self.zones[clinic]
        aware = naive.replace(tzinfo=tz, fold=0)
        if aware.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != naive:
            return None
        return aware.astimezone(UTC)

    def local(self, clinic: str, moment: datetime) -> datetime:
        return moment.astimezone(self.zones[clinic])

    def fits(self, clinic: str, start: datetime, minutes: int) -> bool:
        begin = self.local(clinic, start)
        end = self.local(clinic, start + timedelta(minutes=minutes))
        day = begin.date()
        first = begin.hour * 60 + begin.minute
        last = (end.date() - day).days * 1440 + end.hour * 60 + end.minute
        return any(o <= first and last <= c for o, c in self.hours[clinic][WEEKDAYS[day.weekday()]])

    def clashes(self, start: datetime, minutes: int, clinician: str, room: str, patient: str,
                ignore: str | None = None) -> list[str]:
        end = start + timedelta(minutes=minutes)
        return sorted(
            a.id
            for a in self.appointments.values()
            if a.status == "booked" and a.id != ignore
            and (a.clinician == clinician or a.room == room or a.patient == patient)
            and a.start < end and start < a.end
        )

    def outcome(self, clinic: str, naive: datetime, minutes: int, clinician: str, room: str,
                patient: str, ignore: str | None = None) -> tuple[str, datetime | None]:
        start = self.localize(clinic, naive)
        if start is None:
            return "invalid", None
        if start < self.now:
            return "invalid", start
        clash = bool(self.clashes(start, minutes, clinician, room, patient, ignore))
        if not self.fits(clinic, start, minutes):
            return ("hours or clash" if clash else "hours"), start
        if clash:
            return "clash", start
        return "ok", start

    def reminders(self, appt: RefAppointment) -> list[datetime]:
        hours = self.reminder_hours.get(appt.clinic, self.default_reminders)
        due = [appt.start - timedelta(hours=h) for h in sorted(set(hours), reverse=True)]
        return [d for d in due if d > self.now]

    def agenda(self, clinic: str, day: date) -> list[str]:
        rows = [
            a for a in self.appointments.values()
            if a.clinic == clinic and a.status != "cancelled"
            and self.local(clinic, a.start).date() == day
        ]
        return [a.id for a in sorted(rows, key=lambda a: (a.start, a.id))]
