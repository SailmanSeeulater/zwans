"""A slow, obviously-right model of the gateway for the tests to compare against. It keeps
every allowed request a key ever made and works each decision out from the README's wording;
it shares no code with tollgate."""

import math
from dataclasses import dataclass, field


@dataclass
class Setup:
    plans: dict[str, tuple[int, float]]  # name -> (limit, window)
    keys: dict[str, str]  # key -> plan name
    idle_after: float
    stats_key: str = "ops"

    def toml(self) -> str:
        lines = ["[gateway]", f"idle_after = {self.idle_after!r}", f'stats_key = "{self.stats_key}"']
        for name, (limit, window) in self.plans.items():
            lines += ["", f"[plans.{name}]", f"limit = {limit}", f"window = {window!r}"]
        lines += ["", "[keys]"] + [f'"{key}" = "{plan}"' for key, plan in self.keys.items()]
        lines += [
            "",
            "[[routes]]",
            'prefix = "/api"',
            'upstream = "api"',
            "",
            "[[routes]]",
            'prefix = "/admin"',
            'upstream = "api"',
            'methods = ["GET"]',
        ]
        return "\n".join(lines) + "\n"


@dataclass
class KeyHistory:
    allowed_at: list[float] = field(default_factory=list)  # every allowed request, ever
    dropped: int = 0  # how many of the oldest ones a reload has dropped for good
    last_active: float = 0.0
    allowed: int = 0
    rejected: int = 0


class Model:
    def __init__(self, setup: Setup) -> None:
        self.setup = setup
        self.time: float | None = None
        self.reading: float | None = None
        self.keys: dict[str, KeyHistory] = {}

    def plan(self, key: str) -> tuple[int, float]:
        return self.setup.plans[self.setup.keys[key]]

    def kept(self, key: str) -> list[float]:
        history = self.keys[key]
        limit, _ = self.plan(key)
        start = max(history.dropped, len(history.allowed_at) - limit)
        return history.allowed_at[start:]

    def _tick(self, reading: float) -> float:
        if self.time is None:
            self.time = reading
        else:
            self.time += max(0.0, reading - self.reading)
        self.reading = reading
        return self.time

    def _forget_idle(self, now: float) -> None:
        for key in list(self.keys):
            if now - self.keys[key].last_active >= self.setup.idle_after:
                del self.keys[key]

    def request(self, reading: float, key: str | None, outcome_if_known: int | None) -> tuple[int, int | None]:
        """One request. `outcome_if_known` is 404/405 for a request no route takes, None for a
        request to a route that serves it. Returns (status, Retry-After or None)."""
        now = self._tick(reading)
        self._forget_idle(now)
        if key is None or key not in self.setup.keys:
            return 401, None
        if outcome_if_known is not None:
            return outcome_if_known, None
        history = self.keys.setdefault(key, KeyHistory())
        history.last_active = now
        limit, window = self.plan(key)
        kept = self.kept(key)
        if sum(1 for s in kept if now - s < window) < limit:
            history.allowed_at.append(now)
            history.allowed += 1
            return 200, None
        history.rejected += 1
        # The first moment a request would be allowed is when one of the kept times leaves
        # the window.
        when = min(
            c
            for c in (s + window for s in kept)
            if c > now and sum(1 for s in kept if c - s < window) < limit
        )
        return 429, math.ceil(when - now)

    def stats(self, reading: float) -> dict:
        now = self._tick(reading)
        self._forget_idle(now)
        return {
            "keys": {
                key: {
                    "plan": self.setup.keys[key],
                    "allowed": history.allowed,
                    "rejected": history.rejected,
                    "held": len(self.kept(key)),
                }
                for key, history in sorted(self.keys.items())
            }
        }

    def reload(self, setup: Setup) -> None:
        for key in list(self.keys):
            if key not in setup.keys:
                del self.keys[key]
                continue
            history = self.keys[key]
            old_limit, _ = self.plan(key)
            history.dropped = max(history.dropped, len(history.allowed_at) - old_limit)
            new_limit, _ = setup.plans[setup.keys[key]]
            history.dropped = max(history.dropped, len(history.allowed_at) - new_limit)
        self.setup = setup
