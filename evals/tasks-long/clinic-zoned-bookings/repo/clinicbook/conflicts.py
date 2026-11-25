"""Double-booking checks: a clinician, a room and a patient are each in one place at a time."""

from __future__ import annotations

from datetime import datetime

from .busyindex import BusyIndex, Key
from .models import Appointment
from .storage import Store


class ConflictChecker:
    def __init__(self, store: Store, index: BusyIndex) -> None:
        self.store = store
        self.index = index

    def clashes(
        self,
        *,
        start: datetime,
        end: datetime,
        clinician: str | None = None,
        room: str | None = None,
        patient: str | None = None,
        ignore: str | None = None,
    ) -> list[Appointment]:
        keys: list[Key] = []
        if clinician:
            keys.append(("clinician", clinician))
        if room:
            keys.append(("room", room))
        if patient:
            keys.append(("patient", patient))
        ids: set[str] = set()
        for key in keys:
            ids |= self.index.candidates(key, start, end)
        ids.discard(ignore or "")
        found = []
        for appointment_id in ids:
            appt = self.store.appointments.get(appointment_id)
            if appt is not None and appt.active and appt.overlaps(start, end):
                found.append(appt)
        return sorted(found, key=lambda a: a.id)

    def is_free(self, **kwargs: object) -> bool:
        return not self.clashes(**kwargs)  # type: ignore[arg-type]
