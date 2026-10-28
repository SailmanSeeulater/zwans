"""Run queued jobs one at a time, in order."""

from collections import Counter, deque
from collections.abc import Callable
from typing import Any

from jobs.events import EventBus
from jobs.machine import Machine
from jobs.model import Change, Job
from jobs.policies import ArchivePolicy, RetryPolicy
from jobs.states import State


class Scheduler:
    def __init__(self, max_attempts: int = 1, archive_finished: bool = False) -> None:
        self.bus = EventBus()
        self.machine = Machine(self.bus)
        self.queue: deque[Job] = deque()
        self.jobs: list[Job] = []
        self.bus.on(State.PENDING, self._enqueue)  # jobs coming back for another try
        RetryPolicy(self.machine, max_attempts).install(self.bus)
        if archive_finished:
            ArchivePolicy(self.machine).install(self.bus)

    def submit(self, func: Callable[..., Any], *args: Any, name: str = "") -> Job:
        job = Job(func, args, name)
        self.jobs.append(job)
        self.queue.append(job)
        return job

    def cancel(self, job: Job) -> None:
        self.machine.fire(job, "cancel")

    def run_pending(self) -> None:
        while self.queue:
            job = self.queue.popleft()
            if job.state is State.PENDING:  # skip jobs cancelled while queued
                self._run(job)

    def summary(self) -> dict[str, int]:
        return dict(sorted(Counter(job.state.value for job in self.jobs).items()))

    def _enqueue(self, job: Job, change: Change) -> None:
        self.queue.append(job)

    def _run(self, job: Job) -> None:
        job.attempts += 1
        self.machine.fire(job, "start")
        try:
            result = job.func(*job.args)
        except Exception as exc:
            job.error = f"{type(exc).__name__}: {exc}"
            self.machine.fire(job, "fail")
        else:
            job.result, job.error = result, None
            self.machine.fire(job, "succeed")
