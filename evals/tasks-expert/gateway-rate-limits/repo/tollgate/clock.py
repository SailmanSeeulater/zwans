"""Where the gateway gets the time from."""

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Seconds, as a float. Only differences between readings mean anything."""
        ...


class SystemClock:
    """The wall clock. It can jump, in either direction, when the host's time is corrected."""

    def now(self) -> float:
        return time.time()


class ManualClock:
    """A clock that only moves when told to, for tests and log replays."""

    def __init__(self, start: float = 0.0) -> None:
        self.value = float(start)

    def now(self) -> float:
        return self.value

    def set(self, value: float) -> None:
        self.value = float(value)

    def advance(self, seconds: float) -> None:
        self.value += seconds
