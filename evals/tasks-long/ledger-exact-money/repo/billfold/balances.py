"""Cached account balances.

Adding up every transaction for every `balance` call gets slow with years of data, so the
book keeps each account's current balance here, together with the number of transactions
it was computed from. The cache is saved in the data file and trusted on load as long as
the transaction count still matches.
"""

from __future__ import annotations


class BalanceCache:
    def __init__(self) -> None:
        self._values: dict[str, float] = {}
        self._counts: dict[str, int] = {}

    def get(self, account_id: str, count: int) -> float | None:
        """The cached balance, if it was computed from `count` transactions."""
        if self._counts.get(account_id) != count:
            return None
        return self._values.get(account_id)

    def put(self, account_id: str, value: float, count: int) -> None:
        self._values[account_id] = value
        self._counts[account_id] = count

    def apply(self, account_id: str, delta: float, count_delta: int) -> None:
        """Move a cached balance along with a change, instead of recomputing it."""
        if account_id not in self._values:
            return
        self._values[account_id] += delta
        self._counts[account_id] += count_delta

    def drop(self, account_id: str | None = None) -> None:
        if account_id is None:
            self._values.clear()
            self._counts.clear()
        else:
            self._values.pop(account_id, None)
            self._counts.pop(account_id, None)

    def snapshot(self) -> dict[str, tuple[float, int]]:
        return {key: (self._values[key], self._counts[key]) for key in sorted(self._values)}

    def __contains__(self, account_id: str) -> bool:
        return account_id in self._values
