"""A small least-recently-used cache.

The database keeps one LookupCache for product records, so looking a product up by SKU
does not scan the whole table every time. Whoever changes a product must invalidate its
entry; a rollback clears the whole cache.
"""

from collections import OrderedDict
from collections.abc import Hashable
from typing import Any


class LookupCache:
    def __init__(self, capacity: int = 256) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._entries: OrderedDict[Hashable, Any] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: Hashable) -> Any | None:
        try:
            value = self._entries[key]
        except KeyError:
            self.misses += 1
            return None
        self._entries.move_to_end(key)
        self.hits += 1
        return value

    def put(self, key: Hashable, value: Any) -> None:
        self._entries[key] = value
        self._entries.move_to_end(key)
        while len(self._entries) > self.capacity:
            self._entries.popitem(last=False)

    def invalidate(self, key: Hashable) -> None:
        self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: Hashable) -> bool:
        return key in self._entries
