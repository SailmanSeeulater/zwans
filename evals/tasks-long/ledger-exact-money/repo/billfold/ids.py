"""Short, readable ids: acc-1, txn-42, rule-3. Counters live in the data file."""

from __future__ import annotations


class IdSource:
    def __init__(self, counters: dict[str, int] | None = None) -> None:
        self._counters: dict[str, int] = dict(counters or {})

    def next(self, prefix: str) -> str:
        value = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = value
        return f"{prefix}-{value}"

    def seen(self, ident: str) -> None:
        """Make sure ids loaded from elsewhere are never handed out again."""
        prefix, _, number = ident.rpartition("-")
        if prefix and number.isdigit():
            self._counters[prefix] = max(self._counters.get(prefix, 0), int(number))

    def to_dict(self) -> dict[str, int]:
        return dict(sorted(self._counters.items()))
