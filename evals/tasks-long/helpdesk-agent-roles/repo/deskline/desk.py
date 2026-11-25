"""The entry point for programs using deskline: a store, a clock and contexts."""

from __future__ import annotations

from pathlib import Path

from . import store as storage
from .clock import Clock, system_clock
from .context import Context
from .errors import NotFound
from .services import queues
from .store import Store


class Desk:
    def __init__(self, store: Store, clock: Clock | None = None) -> None:
        self.store = store
        self.clock = clock or system_clock
        if not store.queues:
            with store.transaction():
                queues.ensure_default(store)

    @classmethod
    def memory(cls, clock: Clock | None = None) -> Desk:
        return cls(Store(), clock)

    @classmethod
    def create(cls, path: str | Path, clock: Clock | None = None) -> Desk:
        return cls(storage.create(Path(path)), clock)

    @classmethod
    def open(cls, path: str | Path, clock: Clock | None = None) -> Desk:
        return cls(storage.load(Path(path)), clock)

    def context(self, actor: str | None = None) -> Context:
        """A context acting as agent ``actor``, or as the system when it is None."""
        if actor is not None and actor not in self.store.agents:
            raise NotFound("agent", actor)
        return Context(self.store, self.clock, actor)

    @property
    def system(self) -> Context:
        return self.context()
