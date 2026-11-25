"""The answer cache."""

from dataclasses import dataclass

from relaydns.message import Answer

Key = tuple[str, str]


@dataclass
class Entry:
    answer: Answer
    fetched: int
    lifetime: int

    @property
    def expires(self) -> int:
        return self.fetched + self.lifetime

    def fresh(self, now: int) -> bool:
        return now < self.expires


class Cache:
    def __init__(self, max_entries: int = 10_000) -> None:
        self.max_entries = max_entries
        self._entries: dict[Key, Entry] = {}

    def get(self, key: Key) -> Entry | None:
        return self._entries.get(key)

    def put(self, key: Key, answer: Answer, fetched: int, lifetime: int) -> Entry:
        if key not in self._entries and len(self._entries) >= self.max_entries:
            self._evict_one()
        entry = self._entries[key] = Entry(answer, fetched, lifetime)
        return entry

    def drop(self, key: Key) -> None:
        self._entries.pop(key, None)

    def _evict_one(self) -> None:
        # The entry closest to expiring goes first.
        oldest = min(self._entries, key=lambda key: self._entries[key].expires)
        del self._entries[oldest]

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: object) -> bool:
        return key in self._entries
