"""The audit log: who changed what, in order. Kept in the data file's `audit` table."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from .models import Appointment, AuditEntry
from .storage import Store
from .timeutil import format_datetime


class AuditLog:
    def __init__(self, store: Store, clock: Callable[[], datetime]) -> None:
        self.store = store
        self.clock = clock

    def record(self, action: str, entity: str, **details: Any) -> AuditEntry:
        seq = self.store.audit[-1].seq + 1 if self.store.audit else 1
        entry = AuditEntry(seq=seq, at=self.clock(), action=action, entity=entity,
                           details=details)
        self.store.audit.append(entry)
        return entry

    def history(self, entity: str) -> list[AuditEntry]:
        return [e for e in self.store.audit if e.entity == entity]

    def on_event(self, event: str, appointment: Appointment | None = None, **extra: Any) -> None:
        if appointment is None:
            return
        details: dict[str, Any] = {
            "start": format_datetime(appointment.start),
            "minutes": appointment.minutes,
            "room": appointment.room,
        }
        if "previous_start" in extra:
            details["previous_start"] = format_datetime(extra["previous_start"])
        if extra.get("reason"):
            details["reason"] = extra["reason"]
        self.record(event, appointment.id, **details)
