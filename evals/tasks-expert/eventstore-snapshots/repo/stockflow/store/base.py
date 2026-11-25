"""What every event store does."""

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import UTC, datetime

from stockflow.errors import ConcurrencyError, StoreError
from stockflow.events import NewEvent, StoredEvent

STREAM_NAME = re.compile(r"^[a-z]+-[A-Za-z0-9_.-]+$")


def check_stream(stream: str) -> str:
    if not STREAM_NAME.match(stream):
        raise StoreError(f"bad stream name {stream!r}: expected <kind>-<id>")
    return stream


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class EventStore(ABC):
    """An append-only log of events, split into streams (one per aggregate).

    A stream's version is the number of events in it. append() takes the version the
    writer last saw; if the stream has moved on since, the append is refused with
    ConcurrencyError and nothing is written. Events are never changed or removed.
    """

    @abstractmethod
    def append(self, stream: str, events: Sequence[NewEvent], expected_version: int) -> int:
        """Append events to a stream; returns the stream's new version."""

    @abstractmethod
    def read(self, stream: str, after: int = 0) -> list[StoredEvent]:
        """The stream's events with a position greater than `after`, oldest first."""

    @abstractmethod
    def read_all(self, after: int = 0) -> list[StoredEvent]:
        """Every event with a global position greater than `after`, oldest first."""

    @abstractmethod
    def version(self, stream: str) -> int:
        """How many events the stream has (0 for a stream never written)."""

    @abstractmethod
    def streams(self) -> list[str]:
        """Every stream with at least one event."""

    @staticmethod
    def check_expected(stream: str, expected: int, actual: int) -> None:
        if expected != actual:
            raise ConcurrencyError(stream, expected, actual)

    @staticmethod
    def check_batch(events: Sequence[NewEvent]) -> None:
        if not events:
            raise StoreError("nothing to append")
        for event in events:
            if event.schema < 1:
                raise StoreError(f"{event.type}: schema versions start at 1")
