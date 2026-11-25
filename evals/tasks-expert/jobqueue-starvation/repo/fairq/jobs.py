"""Jobs, the clock, and the scheduler's counters."""

from dataclasses import dataclass
from fractions import Fraction

WAITING = "waiting"
RUNNING = "running"
CANCELLED = "cancelled"
DROPPED = "dropped"


@dataclass
class Job:
    id: str
    tenant: str
    priority: int
    size: int
    deadline: int | None
    enqueued_at: int
    seq: int  # submit order, from 0
    state: str = WAITING
    worker: str | None = None
    started_at: int | None = None


def effective_priority(job: Job, now: int, aging_period: int) -> Fraction:
    """The job's priority plus one for every `aging_period` seconds it has waited."""
    return job.priority + Fraction(now - job.enqueued_at, aging_period)


@dataclass
class Stats:
    visits: int = 0  # job records handled while scheduling (see the README)


class ManualClock:
    """A clock that only moves when told to: for tests, replays and simulations."""

    def __init__(self, start: int = 0) -> None:
        self.now = start

    def __call__(self) -> int:
        return self.now

    def advance(self, seconds: int) -> None:
        if seconds < 0:
            raise ValueError("the clock doesn't go backwards")
        self.now += seconds

    def set(self, now: int) -> None:
        self.advance(now - self.now)
