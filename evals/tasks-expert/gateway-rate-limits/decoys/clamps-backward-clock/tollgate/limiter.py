"""Per-key request rate limits."""

import math
from collections import deque
from dataclasses import dataclass, field

from tollgate.config import Plan


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int = 0


@dataclass
class _KeyState:
    # Times of the key's most recent allowed requests, oldest first, at most `limit` of them.
    times: deque[float] = field(default_factory=deque)
    last_active: float = 0.0


class RateLimiter:
    """A sliding window per key: at most `limit` allowed requests in any `window` seconds."""

    def __init__(self) -> None:
        self._keys: dict[str, _KeyState] = {}

    def check(self, key: str, plan: Plan, now: float) -> Decision:
        state = self._keys.get(key)
        if state is None:
            state = self._keys[key] = _KeyState()
        state.last_active = now
        times = state.times
        while len(times) > plan.limit:
            times.popleft()
        # The kept times are the newest ones, so the limit is reached exactly when all
        # `limit` of them are inside the window, which is when the oldest one is.
        if len(times) == plan.limit and now - times[0] < plan.window:
            return Decision(False, max(1, math.ceil(times[0] + plan.window - now)))
        times.append(now)
        if len(times) > plan.limit:
            times.popleft()
        return Decision(True)

    def replan(self, key: str, old: Plan, new: Plan) -> None:
        state = self._keys.get(key)
        if state is not None:
            while len(state.times) > new.limit:
                state.times.popleft()

    def forget(self, key: str) -> None:
        self._keys.pop(key, None)

    def keys(self) -> list[str]:
        return list(self._keys)

    def last_active(self, key: str) -> float | None:
        state = self._keys.get(key)
        return None if state is None else state.last_active

    def held(self, key: str) -> int:
        state = self._keys.get(key)
        return 0 if state is None else len(state.times)
