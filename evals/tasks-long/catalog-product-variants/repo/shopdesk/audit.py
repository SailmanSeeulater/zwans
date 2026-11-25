"""The audit log: who changed what, as a list of events kept in the data file.

The shop subscribes the log to every event, so nothing has to remember to write to it.
"""

from typing import Any

from shopdesk.clock import Clock
from shopdesk.events import EventBus
from shopdesk.models import AuditEntry, ShopData

# Events that happen too often to be worth a line each.
QUIET = {"stock.moved"}

SUBJECT_KEYS = ("sku", "number", "code", "slug", "name", "cart")


class AuditLog:
    def __init__(self, data: ShopData, bus: EventBus, clock: Clock, *, limit: int = 5000) -> None:
        self._data = data
        self._bus = bus
        self._clock = clock
        self._limit = limit

    def attach(self) -> None:
        self._bus.subscribe("*", self._on_event)

    def _on_event(self, topic: str, payload: dict[str, Any]) -> None:
        if topic in QUIET:
            return
        subject = next((str(payload[k]) for k in SUBJECT_KEYS if k in payload), "")
        detail = {k: v for k, v in payload.items() if _plain(v)}
        self.record(topic, subject, **detail)

    def record(self, action: str, subject: str, **detail: Any) -> AuditEntry:
        entry = AuditEntry(self._clock(), action, subject, detail)
        self._data.audit.append(entry)
        if len(self._data.audit) > self._limit:
            del self._data.audit[: len(self._data.audit) - self._limit]
        return entry

    def entries(self, subject: str | None = None, action: str | None = None) -> list[AuditEntry]:
        return [
            e
            for e in self._data.audit
            if (subject is None or e.subject == subject)
            and (action is None or e.action.startswith(action))
        ]


def _plain(value: Any) -> bool:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return True
    if isinstance(value, (list, tuple)):
        return all(_plain(v) for v in value)
    return False
