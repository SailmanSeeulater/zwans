"""The base class for aggregates: objects whose state is the sum of their events.

An aggregate never changes its state directly. A command method checks the rules, then
records an event; recording applies the event (through the handler registered for its
type) and keeps it as pending until the repository saves it. Loading applies the stored
events through the same handlers, so state is always what the events say.
"""

import copy
from collections.abc import Callable
from typing import Any, ClassVar, TypeVar

from stockflow.errors import EventShapeError

F = TypeVar("F", bound=Callable[..., Any])


def handles(event_class: type) -> Callable[[F], F]:
    """Mark a method as the handler that applies events of `event_class`."""

    def mark(method: F) -> F:
        method._handles = event_class  # type: ignore[attr-defined]
        return method

    return mark


class Aggregate:
    # Streams are named "<stream_prefix>-<id>".
    stream_prefix: ClassVar[str] = ""
    # Event class -> name of the method that applies it. Looked up by name on every apply,
    # so a subclass can override a handler by defining a method of the same name.
    _handlers: ClassVar[dict[type, str]] = {}
    # Bump when what the state means changes; snapshots taken under another one are ignored.
    state_version: ClassVar[int] = 1

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        handlers: dict[type, str] = {}
        for klass in reversed(cls.__mro__):
            for name, attribute in vars(klass).items():
                event_class = getattr(attribute, "_handles", None)
                if event_class is not None:
                    handlers[event_class] = name
        cls._handlers = handlers

    def __init__(self, id: str) -> None:
        self.id = id
        self.version = 0
        self._pending: list[object] = []

    @classmethod
    def stream_for(cls, id: str) -> str:
        return f"{cls.stream_prefix}-{id}"

    @property
    def stream(self) -> str:
        return self.stream_for(self.id)

    def apply(self, event: object) -> None:
        """Apply one event to the state. Used for new events and for replaying old ones."""
        name = self._handlers.get(type(event))
        if name is None:
            raise EventShapeError(f"{type(self).__name__} has no handler for {type(event).__name__}")
        getattr(self, name)(event)
        self.version += 1

    def _record(self, event: object) -> None:
        self.apply(event)
        self._pending.append(event)

    def pending(self) -> list[object]:
        return list(self._pending)

    def mark_saved(self) -> None:
        self._pending.clear()

    # -- snapshots

    _NOT_STATE = ("id", "version", "_pending")

    def snapshot_state(self) -> dict[str, Any]:
        """A deep copy of everything the handlers maintain."""
        return copy.deepcopy(
            {key: value for key, value in vars(self).items() if key not in self._NOT_STATE}
        )

    def restore_state(self, state: dict[str, Any], version: int) -> None:
        self.__dict__.update(copy.deepcopy(state))
        self.version = version

    def as_dict(self) -> dict[str, Any]:
        """The aggregate's state as plain data (for the CLI, reports and tests)."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.id} v{self.version}>"
