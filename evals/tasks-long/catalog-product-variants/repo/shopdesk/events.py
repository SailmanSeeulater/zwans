"""A small synchronous event bus.

Services publish what happened ("stock.moved", "product.changed", ...); the shop wires
listeners to it: the low-stock monitor, the search index, notifications, the audit log.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

Handler = Callable[[str, dict[str, Any]], None]


def matches(pattern: str, topic: str) -> bool:
    if pattern in ("*", topic):
        return True
    return pattern.endswith(".*") and topic.startswith(pattern[:-1])


class EventBus:
    def __init__(self) -> None:
        self._handlers: list[tuple[str, Handler]] = []
        self._held: list[tuple[str, dict[str, Any]]] | None = None

    def subscribe(self, pattern: str, handler: Handler) -> None:
        self._handlers.append((pattern, handler))

    def publish(self, topic: str, **payload: Any) -> None:
        if self._held is not None:
            self._held.append((topic, payload))
            return
        self._dispatch(topic, payload)

    @contextmanager
    def held(self) -> Iterator[None]:
        """Queue events raised inside the block and deliver them, in order, at its end.
        Nested blocks deliver at the outermost end. Nothing is delivered if it raises."""
        if self._held is not None:
            yield
            return
        self._held = []
        try:
            yield
            queued = self._held
        finally:
            self._held = None
        for topic, payload in queued:
            self._dispatch(topic, payload)

    def _dispatch(self, topic: str, payload: dict[str, Any]) -> None:
        for pattern, handler in list(self._handlers):
            if matches(pattern, topic):
                handler(topic, payload)
