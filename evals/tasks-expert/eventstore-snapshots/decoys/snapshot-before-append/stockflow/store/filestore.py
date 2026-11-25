"""An event store in a directory: one JSON object per line in events.jsonl, appended to and
never rewritten.

Several processes may use the same directory (the CLI opens it on every command): appends
take an exclusive lock on the file and read whatever other processes added first, so the
expected-version check always sees the real end of each stream.
"""

import fcntl
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from stockflow.errors import StoreError
from stockflow.events import NewEvent, StoredEvent
from stockflow.store.base import EventStore, Snapshot, check_stream, utc_now

EVENTS_FILE = "events.jsonl"
SNAPSHOTS_DIR = "snapshots"


class FileEventStore(EventStore):
    def __init__(self, directory: str | Path, *, fsync: bool = True) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / EVENTS_FILE
        self.path.touch(exist_ok=True)
        self.fsync = fsync
        self._offset = 0
        self._log: list[StoredEvent] = []
        self._streams: dict[str, list[StoredEvent]] = {}
        self._refresh()

    # -- reading the file

    def _refresh(self) -> None:
        """Index any complete lines written since we last looked (by us or anyone else)."""
        with self.path.open("rb") as handle:
            handle.seek(self._offset)
            chunk = handle.read()
        if not chunk:
            return
        end = chunk.rfind(b"\n")
        if end < 0:
            return  # a line still being written; pick it up next time
        for raw in chunk[: end + 1].splitlines():
            if raw.strip():
                self._index(self._parse(raw))
        self._offset += end + 1

    def _parse(self, raw: bytes) -> StoredEvent:
        try:
            record: dict[str, Any] = json.loads(raw)
            return StoredEvent(
                stream=record["stream"],
                position=int(record["position"]),
                global_position=int(record["global"]),
                type=record["type"],
                schema=int(record["schema"]),
                data=record["data"],
                recorded_at=record.get("at", ""),
            )
        except (ValueError, KeyError, TypeError) as error:
            raise StoreError(f"{self.path}: damaged line {raw[:60]!r}: {error}") from None

    def _index(self, event: StoredEvent) -> None:
        stream = self._streams.setdefault(event.stream, [])
        if event.position != len(stream) + 1 or event.global_position != len(self._log) + 1:
            raise StoreError(f"{self.path}: event out of order at {event.stream}#{event.position}")
        stream.append(event)
        self._log.append(event)

    # -- the EventStore interface

    def append(self, stream: str, events: Sequence[NewEvent], expected_version: int) -> int:
        check_stream(stream)
        self.check_batch(events)
        with self.path.open("ab") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                self._refresh()
                current = len(self._streams.get(stream, []))
                self.check_expected(stream, expected_version, current)
                stamp = utc_now()
                stored = [
                    StoredEvent(
                        stream,
                        current + index,
                        len(self._log) + index,
                        event.type,
                        event.schema,
                        json.loads(json.dumps(event.data)),
                        stamp,
                    )
                    for index, event in enumerate(events, start=1)
                ]
                payload = b"".join(_line(event) for event in stored)
                handle.write(payload)
                handle.flush()
                if self.fsync:
                    os.fsync(handle.fileno())
                for event in stored:
                    self._index(event)
                self._offset += len(payload)
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
        return len(self._streams[stream])

    def read(self, stream: str, after: int = 0) -> list[StoredEvent]:
        check_stream(stream)
        self._refresh()
        return [_copy(event) for event in self._streams.get(stream, [])[after:]]

    def read_all(self, after: int = 0) -> list[StoredEvent]:
        self._refresh()
        return [_copy(event) for event in self._log[after:]]

    def version(self, stream: str) -> int:
        check_stream(stream)
        self._refresh()
        return len(self._streams.get(stream, []))

    def streams(self) -> list[str]:
        self._refresh()
        return list(self._streams)

    def save_snapshot(self, snapshot: Snapshot) -> None:
        path = self._snapshot_path(snapshot.stream)
        path.parent.mkdir(exist_ok=True)
        record = {
            "stream": snapshot.stream,
            "version": snapshot.version,
            "state_version": snapshot.state_version,
            "state": snapshot.state,
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)

    def load_snapshot(self, stream: str) -> Snapshot | None:
        path = self._snapshot_path(stream)
        if not path.exists():
            return None
        record = json.loads(path.read_text("utf-8"))
        return Snapshot(record["stream"], record["version"], record["state_version"], record["state"])

    def _snapshot_path(self, stream: str) -> Path:
        return self.directory / SNAPSHOTS_DIR / f"{check_stream(stream)}.json"


def _line(event: StoredEvent) -> bytes:
    record = {
        "stream": event.stream,
        "position": event.position,
        "global": event.global_position,
        "type": event.type,
        "schema": event.schema,
        "data": event.data,
        "at": event.recorded_at,
    }
    return json.dumps(record, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"


def _copy(event: StoredEvent) -> StoredEvent:
    return StoredEvent(
        event.stream,
        event.position,
        event.global_position,
        event.type,
        event.schema,
        json.loads(json.dumps(event.data)),
        event.recorded_at,
    )
