"""A tiny synchronous event bus. Newly recorded events are published here after they are
safely in the store; read models and notifications subscribe to it."""

from collections.abc import Callable, Iterable

from .events import Event

Subscriber = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []

    def subscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.append(subscriber)

    def publish(self, events: Iterable[Event]) -> None:
        for ev in events:
            for subscriber in self._subscribers:
                subscriber(ev)
