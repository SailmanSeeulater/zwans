"""A small in-process event bus. Services emit; reminders, messages, webhooks and the
audit log listen."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

EVENTS = (
    "appointment.booked",
    "appointment.cancelled",
    "appointment.rescheduled",
    "appointment.completed",
    "appointment.no_show",
    "waitlist.offered",
)

Handler = Callable[..., None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._everything: list[Handler] = []
        self.muted = False

    def subscribe(self, event: str, handler: Handler) -> None:
        if event not in EVENTS:
            raise ValueError(f"unknown event {event!r}")
        self._handlers[event].append(handler)

    def subscribe_all(self, handler: Handler) -> None:
        self._everything.append(handler)

    def emit(self, event: str, **payload: Any) -> None:
        if self.muted:
            return
        for handler in self._handlers.get(event, []):
            handler(**payload)
        for handler in self._everything:
            handler(event, **payload)
