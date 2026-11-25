"""The waitlist: patients waiting for a slot, booked into the first one that frees up."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from .booking import BookingService
from .errors import BookingError, NotFound, ValidationError
from .hooks import EventBus
from .ids import next_id
from .models import Appointment, WaitlistEntry
from .repository import Repository
from .slots import SlotFinder
from .storage import Store
from .timeutil import parse_datetime
from .validation import check_kind, check_minutes


class Waitlist:
    def __init__(
        self,
        store: Store,
        repo: Repository,
        finder: SlotFinder,
        booking: BookingService,
        bus: EventBus,
        clock: Callable[[], datetime],
    ) -> None:
        self.store = store
        self.repo = repo
        self.finder = finder
        self.booking = booking
        self.bus = bus
        self.clock = clock

    def _local(self, value: datetime | str | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = parse_datetime(value)
        if value.tzinfo is not None:
            raise ValidationError("give waitlist times as the clinic's local time")
        return value

    def add(
        self,
        *,
        patient: str,
        clinic: str,
        minutes: int,
        kind: str = "consult",
        clinician: str | None = None,
        earliest: datetime | str | None = None,
        latest: datetime | str | None = None,
    ) -> WaitlistEntry:
        self.repo.patient(patient)
        place = self.repo.clinic(clinic)
        if clinician is not None and not self.repo.clinician(clinician).works_at(clinic):
            raise ValidationError(f"{clinician} does not work at {place.name}")
        check_minutes(minutes, self.store.settings.grid_minutes)
        check_kind(kind)
        first, last = self._local(earliest), self._local(latest)
        if first is not None and last is not None and last <= first:
            raise ValidationError("the waitlist window ends before it starts")
        entry = WaitlistEntry(
            id=next_id(self.store.counters, "waitlist"),
            patient=patient,
            clinic=clinic,
            minutes=minutes,
            kind=kind,
            clinician=clinician,
            earliest=first,
            latest=last,
            added=self.clock(),
        )
        self.store.waitlist[entry.id] = entry
        return entry

    def remove(self, entry_id: str) -> WaitlistEntry:
        entry = self._entry(entry_id)
        entry.status = "removed"
        return entry

    def entries(self, clinic: str | None = None, status: str = "waiting") -> list[WaitlistEntry]:
        found = [
            w
            for w in self.store.waitlist.values()
            if w.status == status and (clinic is None or w.clinic == clinic)
        ]
        return sorted(found, key=lambda w: (w.added or datetime.min, w.id))

    def offer(self, now: datetime | None = None) -> list[Appointment]:
        """Book every waiting patient a slot can be found for, longest-waiting first."""
        now = now or self.clock()
        booked = []
        for entry in self.entries():
            if entry.latest is not None and entry.latest <= now:
                continue
            after = max(now, entry.earliest) if entry.earliest else now
            slot = self.finder.next_free(
                entry.clinic,
                entry.minutes,
                clinician=entry.clinician,
                patient=entry.patient,
                after=after,
                before=entry.latest,
            )
            if slot is None:
                continue
            try:
                appt = self.booking.book(
                    clinic=entry.clinic,
                    clinician=slot.clinician,
                    room=slot.room,
                    patient=entry.patient,
                    start=slot.start,
                    minutes=entry.minutes,
                    kind=entry.kind,
                    source="waitlist",
                )
            except BookingError:
                continue
            entry.status = "offered"
            entry.appointment = appt.id
            self.bus.emit("waitlist.offered", appointment=appt, entry=entry)
            booked.append(appt)
        return booked

    def expire(self, now: datetime | None = None) -> list[WaitlistEntry]:
        now = now or self.clock()
        cutoff = now - timedelta(days=self.store.settings.waitlist_expiry_days)
        expired = []
        for entry in self.entries():
            if entry.added is not None and entry.added < cutoff:
                entry.status = "expired"
                expired.append(entry)
        return expired

    def _entry(self, entry_id: str) -> WaitlistEntry:
        try:
            return self.store.waitlist[entry_id]
        except KeyError:
            raise NotFound("waitlist entry", entry_id) from None
