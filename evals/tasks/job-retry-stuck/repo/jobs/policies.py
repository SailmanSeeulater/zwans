"""Optional behaviour, built on the event bus."""

from jobs.events import EventBus
from jobs.machine import Machine
from jobs.model import Change, Job
from jobs.states import State


class RetryPolicy:
    """Send failed jobs back to pending, until they have run `max_attempts` times."""

    def __init__(self, machine: Machine, max_attempts: int) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.machine = machine
        self.max_attempts = max_attempts

    def install(self, bus: EventBus) -> None:
        bus.on(State.FAILED, self.on_failed)

    def on_failed(self, job: Job, change: Change) -> None:
        if job.attempts < self.max_attempts:
            self.machine.fire(job, "retry")


class ArchivePolicy:
    """Archive jobs as soon as they succeed or are cancelled. Failed jobs stay visible."""

    def __init__(self, machine: Machine) -> None:
        self.machine = machine

    def install(self, bus: EventBus) -> None:
        bus.on(State.SUCCEEDED, self.archive)
        bus.on(State.CANCELLED, self.archive)

    def archive(self, job: Job, change: Change) -> None:
        self.machine.fire(job, "archive")
