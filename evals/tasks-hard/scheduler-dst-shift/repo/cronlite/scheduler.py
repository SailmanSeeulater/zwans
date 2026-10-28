"""The scheduler: which jobs are due, running them, and remembering when they ran."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cronlite.jobs import Job
from cronlite.timeutil import floor_minute

Runner = Callable[[Job, datetime], None]


@dataclass(frozen=True)
class Run:
    job: str
    at: datetime  # UTC, when the run was due

    def local(self, job: Job) -> datetime:
        return job.zone.to_local(self.at)


class State:
    """When each job is next due. Saved as JSON so a restart doesn't rerun anything."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.next_due: dict[str, datetime] = {}
        if path is not None and path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.next_due = {name: datetime.fromisoformat(value) for name, value in data.items()}

    def save(self) -> None:
        if self.path is None:
            return
        data = {name: moment.isoformat() for name, moment in sorted(self.next_due.items())}
        self.path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


class Scheduler:
    def __init__(self, jobs: list[Job], runner: Runner, state: State | None = None) -> None:
        self.jobs = {job.name: job for job in jobs}
        self.runner = runner
        self.state = state or State()
        self.history: list[Run] = []

    def start(self, now: datetime) -> None:
        """Pick up where we left off. New jobs are first due at their next run after now."""
        for job in self.jobs.values():
            if job.name not in self.state.next_due:
                self.state.next_due[job.name] = job.schedule.next_after(now, job.zone)
        for name in list(self.state.next_due):
            if name not in self.jobs:
                del self.state.next_due[name]  # a job removed from jobs.toml
        self.state.save()

    def tick(self, now: datetime) -> list[Run]:
        """Run every job that is due at `now`. A job that missed several runs while the
        scheduler was down runs once, and is then next due at its first run after now."""
        now = floor_minute(now)
        runs = []
        for job in sorted(self.jobs.values(), key=lambda job: job.name):
            due = self.state.next_due.get(job.name)
            if due is None or due > now or not job.enabled:
                continue
            run = Run(job.name, due)
            self.runner(job, due)
            runs.append(run)
            self.state.next_due[job.name] = job.schedule.next_after(max(due, now), job.zone)
        if runs:
            self.history.extend(runs)
            self.state.save()
        return runs

    def upcoming(self) -> list[tuple[Job, datetime]]:
        pairs = [
            (self.jobs[name], due) for name, due in self.state.next_due.items() if name in self.jobs
        ]
        return sorted(pairs, key=lambda pair: (pair[1], pair[0].name))
