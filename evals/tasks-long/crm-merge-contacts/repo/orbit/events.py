"""The in-process event bus.

Services publish an Event after every change. The payload is exactly what a webhook for
that event carries; `contact_ids` names the contacts the event is about, which is what the
timeline, the indexes and contact-filtered webhook subscriptions go by.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

type Handler = Callable[["Event"], None]


@dataclass(frozen=True)
class Event:
    name: str
    payload: dict
    contact_ids: tuple[str, ...] = ()


class Bus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, name: str, handler: Handler) -> None:
        """Call `handler` for every event called `name` ("*" for every event)."""
        self._handlers[name].append(handler)

    def publish(self, event: Event) -> None:
        for handler in [*self._handlers.get(event.name, ()), *self._handlers.get("*", ())]:
            handler(event)
