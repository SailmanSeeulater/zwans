"""Projections: read models built by folding the whole event log.

A projection is a class registered under a name with @PROJECTIONS.register("name"). It
handles an event type by defining on_<event_type_in_snake_case>(stream, data); the data
is always upcast to the current schema. The Projector feeds every projection each event of
the global log once, in order, and remembers how far it got.
"""

import re
from typing import Any, Callable, ClassVar, TypeVar

from stockflow.settings import Settings
from stockflow.store.base import EventStore
from stockflow.upcasting import upcast_stored

P = TypeVar("P", bound="Projection")


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class Projection:
    name: ClassVar[str] = ""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def handle(self, event_type: str, stream: str, data: dict[str, Any]) -> None:
        method = getattr(self, "on_" + snake(event_type), None)
        if method is not None:
            method(stream, data)

    def result(self) -> Any:
        raise NotImplementedError


class ProjectionRegistry:
    def __init__(self) -> None:
        self._classes: dict[str, type[Projection]] = {}

    def register(self, name: str) -> Callable[[type[P]], type[P]]:
        def add(cls: type[P]) -> type[P]:
            if name in self._classes:
                raise ValueError(f"projection {name} is registered twice")
            cls.name = name
            self._classes[name] = cls
            return cls

        return add

    def names(self) -> list[str]:
        return sorted(self._classes)

    def create_all(self, settings: Settings) -> dict[str, Projection]:
        return {name: cls(settings) for name, cls in sorted(self._classes.items())}


PROJECTIONS = ProjectionRegistry()


class Projector:
    def __init__(
        self, store: EventStore, settings: Settings | None = None, registry: ProjectionRegistry = PROJECTIONS
    ) -> None:
        self.store = store
        self.settings = settings if settings is not None else Settings()
        self.registry = registry
        self.projections = registry.create_all(self.settings)
        self.position = 0

    def catch_up(self) -> int:
        """Feed the projections every event they haven't seen. Returns how many."""
        seen = 0
        for stored in self.store.read_all(after=self.position):
            data = upcast_stored(stored)
            for projection in self.projections.values():
                projection.handle(stored.type, stored.stream, data)
            self.position = stored.global_position
            seen += 1
        return seen

    def rebuild(self) -> None:
        self.projections = self.registry.create_all(self.settings)
        self.position = 0
        self.catch_up()

    def result(self, name: str) -> Any:
        self.catch_up()
        return self.projections[name].result()
