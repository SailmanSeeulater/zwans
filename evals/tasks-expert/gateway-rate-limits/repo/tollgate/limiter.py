"""Per-key request rate limits."""

import math
from dataclasses import dataclass

from tollgate.config import Plan


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int = 0


@dataclass
class _KeyState:
    period: int
    used: int = 0
    last_active: float = 0.0


class RateLimiter:
    """Counts each key's requests per period of its plan's window."""

    def __init__(self) -> None:
        self._keys: dict[str, _KeyState] = {}

    def check(self, key: str, plan: Plan, now: float) -> Decision:
        period = int(now // plan.window)
        state = self._keys.get(key)
        if state is None:
            state = self._keys[key] = _KeyState(period)
        elif period > state.period:
            state.period = period
            state.used = 0
        if state.used >= plan.limit:
            ends = (state.period + 1) * plan.window
            return Decision(False, max(1, math.ceil(ends - now)))
        state.used += 1
        state.last_active = now
        return Decision(True)

    def replan(self, key: str, old: Plan, new: Plan) -> None:
        state = self._keys.get(key)
        if state is not None and old.window != new.window:
            state.period = -1
            state.used = 0

    def forget(self, key: str) -> None:
        self._keys.pop(key, None)

    def keys(self) -> list[str]:
        return list(self._keys)

    def last_active(self, key: str) -> float | None:
        state = self._keys.get(key)
        return None if state is None else state.last_active

    def held(self, key: str) -> int:
        state = self._keys.get(key)
        return 0 if state is None else state.used
