"""Per-key counters for the /_stats endpoint."""

from dataclasses import dataclass


@dataclass
class KeyStats:
    plan: str
    allowed: int = 0
    rejected: int = 0


class StatsBook:
    def __init__(self) -> None:
        self._keys: dict[str, KeyStats] = {}

    def entry(self, key: str, plan: str) -> KeyStats:
        stats = self._keys.get(key)
        if stats is None:
            stats = self._keys[key] = KeyStats(plan)
        stats.plan = plan
        return stats

    def allowed(self, key: str, plan: str) -> None:
        self.entry(key, plan).allowed += 1

    def rejected(self, key: str, plan: str) -> None:
        self.entry(key, plan).rejected += 1

    def forget(self, key: str) -> None:
        self._keys.pop(key, None)

    def replan(self, key: str, plan: str) -> None:
        if key in self._keys:
            self._keys[key].plan = plan

    def keys(self) -> list[str]:
        return list(self._keys)

    def report(self, held: dict[str, int]) -> dict[str, object]:
        return {
            "keys": {
                key: {
                    "plan": stats.plan,
                    "allowed": stats.allowed,
                    "rejected": stats.rejected,
                    "held": held.get(key, 0),
                }
                for key, stats in sorted(self._keys.items())
            }
        }
