"""Loading aggregates from the store and saving their new events."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import TypeVar

from stockflow.aggregate import Aggregate
from stockflow.errors import NotFound
from stockflow.events import decode, encode
from stockflow.settings import Settings
from stockflow.store.base import EventStore
from stockflow.upcasting import upcast_stored

A = TypeVar("A", bound=Aggregate)


@dataclass
class LoadStats:
    loads: int = 0
    events_replayed: int = 0  # events applied to aggregates while loading them
    saves: int = 0
    events_saved: int = 0


class Repository:
    def __init__(self, store: EventStore, settings: Settings | None = None) -> None:
        self.store = store
        self.settings = settings if settings is not None else Settings()
        self.stats = LoadStats()

    def load(self, cls: type[A], id: str) -> A:
        """The aggregate as its events leave it. Raises NotFound if it has none."""
        aggregate = cls(id)
        replayed = 0
        for event in self._history(aggregate.stream):
            aggregate.apply(event)
            replayed += 1
        self.stats.loads += 1
        self.stats.events_replayed += replayed
        if aggregate.version == 0:
            raise NotFound(f"no {cls.__name__} {id}")
        return aggregate

    def exists(self, cls: type[Aggregate], id: str) -> bool:
        return self.store.version(cls.stream_for(id)) > 0

    def save(self, aggregate: Aggregate) -> int:
        """Append the aggregate's pending events. Raises ConcurrencyError if its stream has
        moved on since the aggregate was loaded; then nothing is written."""
        pending = aggregate.pending()
        if not pending:
            return aggregate.version
        expected = aggregate.version - len(pending)
        version = self.store.append(
            aggregate.stream, [encode(event) for event in pending], expected_version=expected
        )
        aggregate.mark_saved()
        self.stats.saves += 1
        self.stats.events_saved += len(pending)
        return version

    def _history(self, stream: str) -> Iterator[object]:
        for stored in self.store.read(stream):
            yield decode(stored.type, upcast_stored(stored))
