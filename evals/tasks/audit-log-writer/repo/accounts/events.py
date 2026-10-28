"""A tiny in-process event bus. Handlers subscribe to an event class name."""

from collections import defaultdict
from dataclasses import dataclass

_handlers: dict[str, list] = defaultdict(list)


@dataclass
class Event:
    user_id: int


@dataclass
class CredentialEvent(Event):
    pass


@dataclass
class PasswordReset(CredentialEvent):
    by_admin: bool = False


@dataclass
class PasswordChanged(CredentialEvent):
    pass


@dataclass
class SignedUp(Event):
    email: str


def subscribe(event_name: str):
    def register(handler):
        _handlers[event_name].append(handler)
        return handler

    return register


def publish(event: Event, context) -> None:
    # Handlers for the event's own class run first, then those for its base classes.
    for cls in type(event).__mro__:
        for handler in _handlers.get(cls.__name__, []):
            handler(event, context)
