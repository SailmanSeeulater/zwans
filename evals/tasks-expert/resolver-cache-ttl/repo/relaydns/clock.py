"""Clocks counting whole seconds."""

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> int: ...


class MonotonicClock:
    def now(self) -> int:
        return int(time.monotonic())


class ManualClock:
    def __init__(self, start: int = 0) -> None:
        self.value = int(start)

    def now(self) -> int:
        return self.value

    def advance(self, seconds: int) -> None:
        if seconds < 0:
            raise ValueError("a ManualClock only moves forwards")
        self.value += int(seconds)

    def set(self, value: int) -> None:
        if value < self.value:
            raise ValueError("a ManualClock only moves forwards")
        self.value = int(value)
