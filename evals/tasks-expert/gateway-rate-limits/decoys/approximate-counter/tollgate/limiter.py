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
    current: int = 0
    previous: int = 0
    last_active: float = 0.0


class RateLimiter:
    """A sliding window counter: this period's count plus the previous period's, weighted by
    how much of it the window still covers. Two numbers per key, however busy."""

    def __init__(self) -> None:
        self._keys: dict[str, _KeyState] = {}

    def check(self, key: str, plan: Plan, now: float) -> Decision:
        period = int(now // plan.window)
        state = self._keys.get(key)
        if state is None:
            state = self._keys[key] = _KeyState(period)
        state.last_active = now
        if period == state.period + 1:
            state.previous, state.current = state.current, 0
        elif period > state.period + 1:
            state.previous, state.current = 0, 0
        state.period = max(state.period, period)
        into = (now - state.period * plan.window) / plan.window
        estimate = state.previous * (1 - into) + state.current
        if estimate >= plan.limit:
            ends = (state.period + 1) * plan.window
            return Decision(False, max(1, math.ceil(ends - now)))
        state.current += 1
        return Decision(True)

    def replan(self, key: str, old: Plan, new: Plan) -> None:
        pass

    def forget(self, key: str) -> None:
        self._keys.pop(key, None)

    def keys(self) -> list[str]:
        return list(self._keys)

    def last_active(self, key: str) -> float | None:
        state = self._keys.get(key)
        return None if state is None else state.last_active

    def held(self, key: str) -> int:
        return 2 if key in self._keys else 0
