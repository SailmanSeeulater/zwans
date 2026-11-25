"""The scheduler: jobs go in with submit(), workers take them out with pull()."""

from collections import deque
from collections.abc import Callable
from fractions import Fraction

from fairq.jobs import CANCELLED, DROPPED, RUNNING, WAITING, Job, Stats


class Scheduler:
    def __init__(
        self,
        clock: Callable[[], int],
        aging_period: int = 30,
        share_window: int = 60,
        stats: Stats | None = None,
    ) -> None:
        self.clock = clock
        self.aging_period = aging_period
        self.share_window = share_window
        self.stats = stats if stats is not None else Stats()
        self.dropped: list[Job] = []
        self._jobs: dict[str, Job] = {}  # every job ever submitted
        self._waiting: dict[str, Job] = {}  # in submit order
        self._weights: dict[str, int] = {}
        self._started: dict[str, deque[tuple[int, int]]] = {}  # tenant -> (time, size)

    # -- jobs in

    def submit(
        self,
        job_id: str,
        tenant: str,
        priority: int = 0,
        size: int = 1,
        deadline: int | None = None,
    ) -> Job:
        if job_id in self._jobs:
            raise ValueError(f"job {job_id!r} was already submitted")
        if size < 1:
            raise ValueError("a job's size is at least 1")
        job = Job(job_id, tenant, priority, size, deadline, self.clock(), len(self._jobs))
        self._jobs[job_id] = job
        self._waiting[job_id] = job
        return job

    def cancel(self, job_id: str) -> bool:
        job = self._waiting.pop(job_id, None)
        if job is None:
            return False
        job.state = CANCELLED
        return True

    def reprioritize(self, job_id: str, priority: int) -> bool:
        job = self._waiting.get(job_id)
        if job is None:
            return False
        job.priority = priority
        return True

    def set_weight(self, tenant: str, weight: int) -> None:
        if weight < 1:
            raise ValueError("a tenant's weight is at least 1")
        self._weights[tenant] = weight

    # -- jobs out

    def pull(self, worker: str = "worker") -> Job | None:
        now = self.clock()
        while True:
            job = self._choose(now)
            if job is None:
                return None
            del self._waiting[job.id]
            if job.deadline is not None and job.deadline < now:
                job.state = DROPPED
                self.dropped.append(job)
                continue
            job.state = RUNNING
            job.worker = worker
            job.started_at = now
            self._started.setdefault(job.tenant, deque()).append((now, job.size))
            return job

    def _choose(self, now: int) -> Job | None:
        shares: dict[str, Fraction] = {}
        best: Job | None = None
        best_key: tuple | None = None
        for job in self._waiting.values():
            self.stats.visits += 1
            if job.tenant not in shares:
                shares[job.tenant] = self._share(job.tenant, now)
            level = job.priority + (now - job.enqueued_at) // self.aging_period
            key = (shares[job.tenant], -level, job.enqueued_at, job.seq)
            if best_key is None or key < best_key:
                best, best_key = job, key
        return best

    def _share(self, tenant: str, now: int) -> Fraction:
        started = self._started.get(tenant, deque())
        while started and now - started[0][0] > self.share_window:
            started.popleft()
        return Fraction(len(started), self._weights.get(tenant, 1))

    # -- looking

    def job(self, job_id: str) -> Job:
        return self._jobs[job_id]

    def __len__(self) -> int:
        return len(self._waiting)

    def waiting(self) -> list[Job]:
        return [job for job in self._waiting.values() if job.state == WAITING]
