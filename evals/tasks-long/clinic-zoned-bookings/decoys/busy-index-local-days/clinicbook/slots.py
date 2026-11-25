"""Finding free slots: a clinician and a room free for a stretch inside opening hours."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .conflicts import ConflictChecker
from .errors import BookingError, InvalidTime
from .models import Clinic
from .repository import Repository
from .storage import Store
from .timeutil import at, end_of, in_zone, instant, local_midnight, localize


@dataclass(frozen=True)
class Slot:
    clinic: str
    start: datetime
    end: datetime
    clinician: str
    room: str


class SlotFinder:
    def __init__(
        self,
        store: Store,
        repo: Repository,
        conflicts: ConflictChecker,
        clock: Callable[[], datetime],
    ) -> None:
        self.store = store
        self.repo = repo
        self.conflicts = conflicts
        self.clock = clock

    def _starts(self, clinic: Clinic, day: date, minutes: int) -> Iterator[datetime]:
        """Candidate starts on `day`: every slot_minutes of local time from each opening,
        while the appointment still fits before the interval closes. Local times that
        don't exist that day are left out."""
        if clinic.is_closed(day):
            return
        step = self.store.settings.slot_minutes
        for interval in clinic.hours.intervals(day):
            offset = interval.open
            while offset < interval.close:
                try:
                    start = localize(at(day, offset), clinic.tz)
                except InvalidTime:
                    start = None
                if start is not None and clinic.hours.covers(start, minutes):
                    yield start
                offset += step

    def _first_free(
        self,
        clinic: Clinic,
        start: datetime,
        minutes: int,
        clinician: str | None,
        room: str | None,
        patient: str | None,
    ) -> Slot | None:
        end = end_of(start, minutes)
        people = [clinician] if clinician else [c.id for c in self.repo.clinicians_of(clinic.id)]
        rooms = [room] if room else [r.id for r in self.repo.rooms_of(clinic.id)]
        if patient and self.conflicts.clashes(start=start, end=end, patient=patient):
            return None
        for person in people:
            if self.conflicts.clashes(start=start, end=end, clinician=person):
                continue
            for place in rooms:
                if not self.conflicts.clashes(start=start, end=end, room=place):
                    return Slot(clinic.id, start, end, person, place)
        return None

    def day_slots(
        self,
        clinic_id: str,
        day: date,
        minutes: int,
        *,
        clinician: str | None = None,
        room: str | None = None,
        patient: str | None = None,
        not_before: datetime | None = None,
    ) -> list[Slot]:
        """For each candidate start on `day`, the first free clinician and room."""
        clinic = self.repo.clinic(clinic_id)
        if clinician is not None and not self.repo.clinician(clinician).works_at(clinic_id):
            raise BookingError(f"{clinician} does not work at {clinic.name}")
        now = self.clock()
        found = []
        for start in self._starts(clinic, day, minutes):
            if instant(start) < instant(now) or (
                not_before is not None and instant(start) < instant(not_before)
            ):
                continue
            slot = self._first_free(clinic, start, minutes, clinician, room, patient)
            if slot is not None:
                found.append(slot)
        return found

    def next_free(
        self,
        clinic_id: str,
        minutes: int,
        *,
        clinician: str | None = None,
        room: str | None = None,
        patient: str | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
    ) -> Slot | None:
        """The earliest free slot at or after `after` (default: now), within search_days.

        With `before`, the slot must start before that time.
        """
        clinic = self.repo.clinic(clinic_id)
        after = in_zone(after, clinic.tz) if after is not None else in_zone(self.clock(), clinic.tz)
        if before is not None:
            before = in_zone(before, clinic.tz)
        first_day = after.date()
        for offset in range(self.store.settings.search_days):
            day = first_day + timedelta(days=offset)
            if before is not None and instant(local_midnight(day, clinic.tz)) >= instant(before):
                return None
            for slot in self.day_slots(
                clinic_id, day, minutes, clinician=clinician, room=room, patient=patient,
                not_before=after,
            ):
                if before is not None and instant(slot.start) >= instant(before):
                    return None
                return slot
        return None
