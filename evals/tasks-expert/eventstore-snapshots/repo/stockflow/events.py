"""Event types, their schema versions, and the envelopes the store keeps.

Domain events are frozen dataclasses registered with @event_type. The registry maps each
event's name to its class and its *current* schema version. Stored data may be older; see
upcasting.py for how it is brought up to date.
"""

import dataclasses
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from stockflow.errors import EventShapeError

T = TypeVar("T")

_CLASSES: dict[str, type] = {}
_VERSIONS: dict[str, int] = {}
_NAMES: dict[type, str] = {}


def event_type(name: str, *, version: int = 1) -> Callable[[type[T]], type[T]]:
    """Register a dataclass as the current schema of event `name`.

    Versions are plain integers starting at 1. When an event's fields change, bump the
    version here and register an upcaster from the previous version (upcasting.py).
    """
    if not name or not name[0].isupper() or not name.isalnum():
        raise ValueError(f"event names are PascalCase words, got {name!r}")
    if version < 1:
        raise ValueError(f"{name}: schema versions start at 1")

    def register(cls: type[T]) -> type[T]:
        if not dataclasses.is_dataclass(cls):
            raise TypeError(f"{cls.__name__} must be a dataclass to be an event")
        if name in _CLASSES:
            raise ValueError(f"event type {name} is registered twice")
        _CLASSES[name] = cls
        _VERSIONS[name] = version
        _NAMES[cls] = name
        return cls

    return register


def type_name(event: object) -> str:
    try:
        return _NAMES[type(event)]
    except KeyError:
        raise EventShapeError(f"{type(event).__name__} is not a registered event") from None


def current_version(name: str) -> int:
    try:
        return _VERSIONS[name]
    except KeyError:
        raise EventShapeError(f"unknown event type {name}") from None


def known_types() -> list[str]:
    return sorted(_CLASSES)


@dataclass(frozen=True)
class NewEvent:
    """An event on its way into the store."""

    type: str
    schema: int
    data: dict[str, Any]


@dataclass(frozen=True)
class StoredEvent:
    """An event as the store keeps it. `position` counts from 1 within its stream (so the
    stream's version is the position of its last event); `global_position` counts from 1
    across the whole store."""

    stream: str
    position: int
    global_position: int
    type: str
    schema: int
    data: dict[str, Any]
    recorded_at: str = ""


def encode(event: object) -> NewEvent:
    name = type_name(event)
    return NewEvent(name, _VERSIONS[name], dataclasses.asdict(event))  # type: ignore[arg-type]


def decode(name: str, data: dict[str, Any]) -> object:
    """Build the event object from data in the current schema."""
    cls = _CLASSES.get(name)
    if cls is None:
        raise EventShapeError(f"unknown event type {name}")
    fields = {field.name for field in dataclasses.fields(cls)}
    missing = fields - set(data)
    extra = set(data) - fields
    if missing or extra:
        raise EventShapeError(
            f"{name} v{_VERSIONS[name]} data doesn't fit: missing {sorted(missing)}, "
            f"unexpected {sorted(extra)}"
        )
    return cls(**data)
