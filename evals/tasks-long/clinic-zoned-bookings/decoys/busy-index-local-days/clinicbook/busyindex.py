"""Who and what is busy when: active appointments by clinician, room and patient.

Conflict checks run on every booking and on every candidate of a slot search, so the
index buckets appointments by day and a check only looks at the days it touches.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timedelta

from .models import Appointment

Key = tuple[str, str]  # ("clinician", "dr-osei"), ("room", "C1"), ("patient", "P0001")


def keys_of(appt: Appointment) -> list[Key]:
    return [("clinician", appt.clinician), ("room", appt.room), ("patient", appt.patient)]


class BusyIndex:
    def __init__(self) -> None:
        self._buckets: dict[Key, dict[date, set[str]]] = defaultdict(lambda: defaultdict(set))
        self._placed: dict[str, list[tuple[Key, date]]] = {}

    def _day(self, moment: datetime) -> date:
        return moment.date()

    def add(self, appt: Appointment) -> None:
        if not appt.active:
            return
        self.remove(appt.id)
        day = self._day(appt.start)
        placed = []
        for key in keys_of(appt):
            self._buckets[key][day].add(appt.id)
            placed.append((key, day))
        self._placed[appt.id] = placed

    def remove(self, appointment_id: str) -> None:
        for key, day in self._placed.pop(appointment_id, []):
            self._buckets[key][day].discard(appointment_id)

    def rebuild(self, appointments: Iterable[Appointment]) -> None:
        self._buckets.clear()
        self._placed.clear()
        for appt in appointments:
            self.add(appt)

    def candidates(self, key: Key, start: datetime, end: datetime) -> set[str]:
        """Ids of appointments for `key` that might overlap [start, end)."""
        found: set[str] = set()
        buckets = self._buckets.get(key)
        if not buckets:
            return found
        day = self._day(start)
        last = self._day(end)
        while day <= last:
            found |= buckets.get(day, set())
            day += timedelta(days=1)
        return found

    def __len__(self) -> int:
        return len(self._placed)
