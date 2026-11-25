"""Per-key request rate limits."""

import math
from dataclasses import dataclass, field

from tollgate.config import Plan


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int = 0


@dataclass
class _KeyState:
    times: list[float] = field(default_factory=list)
    last_active: float = 0.0


class RateLimiter:
    """A sliding log per key: every allowed request's time, checked against the window."""

    def __init__(self) -> None:
        self._keys: dict[str, _KeyState] = {}

    def check(self, key: str, plan: Plan, now: float) -> Decision:
        state = self._keys.get(key)
        if state is None:
            state = self._keys[key] = _KeyState()
        state.last_active = now
        recent = [t for t in state.times if now - t < plan.window]
        if len(recent) >= plan.limit:
            oldest = recent[-plan.limit]
            return Decision(False, max(1, math.ceil(oldest + plan.window - now)))
        state.times.append(now)
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
        state = self._keys.get(key)
        return 0 if state is None else len(state.times)
