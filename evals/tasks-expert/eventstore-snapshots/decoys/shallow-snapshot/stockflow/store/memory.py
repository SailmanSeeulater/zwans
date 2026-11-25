"""An event store in memory, for tests and one-off scripts."""

import copy
from collections.abc import Sequence

from stockflow.events import NewEvent, StoredEvent
from stockflow.store.base import EventStore, Snapshot, check_stream, utc_now


class InMemoryEventStore(EventStore):
    def __init__(self) -> None:
        self._log: list[StoredEvent] = []
        self._streams: dict[str, list[StoredEvent]] = {}
        self._snapshots: dict[str, Snapshot] = {}

    def append(self, stream: str, events: Sequence[NewEvent], expected_version: int) -> int:
        check_stream(stream)
        self.check_batch(events)
        existing = self._streams.setdefault(stream, [])
        self.check_expected(stream, expected_version, len(existing))
        stamp = utc_now()
        for event in events:
            stored = StoredEvent(
                stream=stream,
                position=len(existing) + 1,
                global_position=len(self._log) + 1,
                type=event.type,
                schema=event.schema,
                data=copy.deepcopy(event.data),
                recorded_at=stamp,
            )
            existing.append(stored)
            self._log.append(stored)
        return len(existing)

    def read(self, stream: str, after: int = 0) -> list[StoredEvent]:
        check_stream(stream)
        return [_copy(event) for event in self._streams.get(stream, [])[after:]]

    def read_all(self, after: int = 0) -> list[StoredEvent]:
        return [_copy(event) for event in self._log[after:]]

    def version(self, stream: str) -> int:
        return len(self._streams.get(check_stream(stream), []))

    def streams(self) -> list[str]:
        return [name for name, events in self._streams.items() if events]

    def save_snapshot(self, snapshot: Snapshot) -> None:
        check_stream(snapshot.stream)
        self._snapshots[snapshot.stream] = snapshot

    def load_snapshot(self, stream: str) -> Snapshot | None:
        snapshot = self._snapshots.get(check_stream(stream))
        return snapshot


def _copy(event: StoredEvent) -> StoredEvent:
    # Readers get their own data, so nothing they do can change what the store holds.
    return StoredEvent(
        event.stream,
        event.position,
        event.global_position,
        event.type,
        event.schema,
        copy.deepcopy(event.data),
        event.recorded_at,
    )
