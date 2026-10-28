"""Event stores. One stream of events per order, plus the global order of everything.

append() takes the version the caller loaded (the number of events in the stream then) and
refuses to write if the stream has moved on since: optimistic concurrency.
"""

import json
from collections.abc import Sequence
from pathlib import Path

from .errors import ConcurrencyError
from .events import Event, from_record, to_record


class MemoryEventStore:
    def __init__(self) -> None:
        self._streams: dict[str, list[Event]] = {}
        self._log: list[Event] = []

    def load(self, order_id: str) -> list[Event]:
        return list(self._streams.get(order_id, []))

    def append(self, order_id: str, events: Sequence[Event], expected_version: int) -> None:
        stream = self._streams.setdefault(order_id, [])
        if len(stream) != expected_version:
            raise ConcurrencyError(
                f"{order_id} changed while you were working on it "
                f"(expected version {expected_version}, found {len(stream)})"
            )
        for ev in events:
            if ev.order_id != order_id:
                raise ValueError(f"event for {ev.order_id} appended to stream {order_id}")
        stream.extend(events)
        self._log.extend(events)

    def all_events(self) -> list[Event]:
        """Every event of every order, in the order they were appended."""
        return list(self._log)

    def order_ids(self) -> list[str]:
        return sorted(self._streams)


class JsonlEventStore(MemoryEventStore):
    """Events kept in one JSON-lines file, one event per line, in append order."""

    def __init__(self, path: Path | str) -> None:
        super().__init__()
        self.path = Path(path)
        if self.path.exists():
            with self.path.open(encoding="utf-8") as file:
                for number, line in enumerate(file, start=1):
                    if not line.strip():
                        continue
                    try:
                        ev = from_record(json.loads(line))
                    except (ValueError, TypeError, KeyError) as exc:
                        raise ValueError(f"{self.path}:{number}: {exc}") from exc
                    self._streams.setdefault(ev.order_id, []).append(ev)
                    self._log.append(ev)

    def append(self, order_id: str, events: Sequence[Event], expected_version: int) -> None:
        super().append(order_id, events, expected_version)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            for ev in events:
                file.write(json.dumps(to_record(ev), sort_keys=True) + "\n")
