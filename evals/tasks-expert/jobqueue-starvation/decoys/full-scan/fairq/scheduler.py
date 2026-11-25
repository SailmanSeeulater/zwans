"""The scheduler: jobs go in with submit(), workers take them out with pull().

Each pull looks at the waiting jobs and works the choice out exactly as the README says,
with exact fractions: expired jobs dropped first, then the tenant with the lowest share,
then that tenant's job with the highest effective priority.
"""

from collections import deque
from collections.abc import Callable
from fractions import Fraction

from fairq.jobs import CANCELLED, DROPPED, RUNNING, WAITING, Job, Stats, effective_priority


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
        self._jobs: dict[str, Job] = {}
        self._waiting: dict[str, Job] = {}
        self._weights: dict[str, int] = {}
        self._started: dict[str, deque[tuple[int, int]]] = {}

    def submit(self, job_id: str, tenant: str, priority: int = 0, size: int = 1,
               deadline: int | None = None) -> Job:
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

    def pull(self, worker: str = "worker") -> Job | None:
        now = self.clock()
        expired = []
        for job in self._waiting.values():
            self.stats.visits += 1
            if job.deadline is not None and job.deadline < now:
                expired.append(job)
        for job in sorted(expired, key=lambda j: (j.deadline, j.seq)):
            del self._waiting[job.id]
            job.state = DROPPED
            self.dropped.append(job)

        shares: dict[str, Fraction] = {}
        best, best_key = None, None
        for job in self._waiting.values():
            self.stats.visits += 1
            if job.tenant not in shares:
                shares[job.tenant] = self._share(job.tenant, now)
            key = (shares[job.tenant], -effective_priority(job, now, self.aging_period),
                   job.enqueued_at, job.seq)
            if best_key is None or key < best_key:
                best, best_key = job, key
        if best is None:
            return None
        del self._waiting[best.id]
        best.state = RUNNING
        best.worker = worker
        best.started_at = now
        self._started.setdefault(best.tenant, deque()).append((now, best.size))
        return best

    def _share(self, tenant: str, now: int) -> Fraction:
        started = self._started.get(tenant, deque())
        while started and now - started[0][0] >= self.share_window:
            started.popleft()
        return Fraction(sum(size for _, size in started), self._weights.get(tenant, 1))

    def job(self, job_id: str) -> Job:
        return self._jobs[job_id]

    def __len__(self) -> int:
        return len(self._waiting)

    def waiting(self) -> list[Job]:
        return list(self._waiting.values())
