"""Loading aggregates from the store and saving their new events."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import TypeVar

from stockflow.aggregate import Aggregate
from stockflow.errors import NotFound
from stockflow.events import decode, encode
from stockflow.settings import Settings
from stockflow.store.base import EventStore, Snapshot
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

    @property
    def _snapshots_on(self) -> bool:
        return self.settings.snapshot_every > 0

    def load(self, cls: type[A], id: str) -> A:
        """The aggregate as its events leave it. Raises NotFound if it has none."""
        aggregate = cls(id)
        after = 0
        rebuild = False
        if self._snapshots_on:
            snapshot = self.store.load_snapshot(aggregate.stream)
            if snapshot is not None:
                if snapshot.state_version == cls.state_version:
                    aggregate.restore_state(snapshot.state, snapshot.version)
                    after = snapshot.version
                else:
                    rebuild = True
        replayed = 0
        for event in self._history(aggregate.stream, after):
            aggregate.apply(event)
            replayed += 1
        self.stats.loads += 1
        self.stats.events_replayed += replayed
        if aggregate.version == 0:
            raise NotFound(f"no {cls.__name__} {id}")
        if rebuild:
            self._take_snapshot(aggregate)
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
        if self._snapshots_on:
            latest = self.store.load_snapshot(aggregate.stream)
            base = 0
            if latest is not None and latest.state_version == type(aggregate).state_version:
                base = latest.version
            if aggregate.version - base >= self.settings.snapshot_every:
                self._take_snapshot(aggregate)
        return version

    def _take_snapshot(self, aggregate: Aggregate) -> None:
        self.store.save_snapshot(
            Snapshot(
                aggregate.stream,
                aggregate.version,
                type(aggregate).state_version,
                aggregate.snapshot_state(),
            )
        )

    def _history(self, stream: str, after: int = 0) -> Iterator[object]:
        for stored in self.store.read(stream, after=after):
            yield decode(stored.type, upcast_stored(stored))
