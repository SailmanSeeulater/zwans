"""The scheduler: jobs go in with submit(), workers take them out with pull().

Every waiting job ages at the same rate, so the order of two jobs never changes while
they wait: priority + (now - enqueued) / period sorts the same as
priority * period - enqueued, which doesn't depend on now. Each tenant keeps its waiting
jobs in a heap on that key. Cancelled and reprioritized jobs leave their old entries
behind; an entry is only good while it matches the job's current version, and stale ones
are thrown away when they reach the top. Deadlines are kept in one more heap, so a pull
drops exactly the jobs that have expired.
"""

import heapq
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
        self._version: dict[str, int] = {}  # job id -> version of its live heap entry
        self._queues: dict[str, list[tuple]] = {}  # tenant -> heap of (key..., version, id)
        self._counts: dict[str, int] = {}  # tenant -> waiting jobs
        self._deadlines: list[tuple[int, int, str]] = []  # heap of (deadline, seq, id)
        self._weights: dict[str, int] = {}
        self._started: dict[str, deque[tuple[int, int]]] = {}  # tenant -> (time, size)
        self._used: dict[str, int] = {}  # tenant -> sizes in _started

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
        self._version[job_id] = 0
        self._counts[tenant] = self._counts.get(tenant, 0) + 1
        self._push(job)
        if deadline is not None:
            self.stats.visits += 1
            heapq.heappush(self._deadlines, (deadline, job.seq, job_id))
        return job

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.state != WAITING:
            return False
        self._leave(job, CANCELLED)
        return True

    def reprioritize(self, job_id: str, priority: int) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.state != WAITING:
            return False
        job.priority = priority
        self._version[job_id] += 1
        self._push(job)
        return True

    def set_weight(self, tenant: str, weight: int) -> None:
        if weight < 1:
            raise ValueError("a tenant's weight is at least 1")
        self._weights[tenant] = weight

    # -- jobs out

    def pull(self, worker: str = "worker") -> Job | None:
        now = self.clock()
        deadlines = self._deadlines
        while deadlines and deadlines[0][0] < now:
            self.stats.visits += 1
            _, _, job_id = heapq.heappop(deadlines)
            job = self._jobs[job_id]
            if job.state == WAITING:
                self._leave(job, DROPPED)
                self.dropped.append(job)

        best_tenant, best_share, best_top = None, None, None
        for tenant, count in self._counts.items():
            if not count:
                continue
            top = self._top(tenant)
            share = self._share(tenant, now)
            if best_share is None or share < best_share or (share == best_share and top < best_top):
                best_tenant, best_share, best_top = tenant, share, top
        if best_tenant is None:
            return None

        self.stats.visits += 1
        heapq.heappop(self._queues[best_tenant])
        job = self._jobs[best_top[-1]]
        self._leave(job, RUNNING)
        job.worker = worker
        job.started_at = now
        self._started.setdefault(job.tenant, deque()).append((now, 1))
        self._used[job.tenant] = self._used.get(job.tenant, 0) + 1
        return job

    # -- inside

    def _push(self, job: Job) -> None:
        self.stats.visits += 1
        key = -(job.priority * self.aging_period - job.enqueued_at)
        entry = (key, job.enqueued_at, job.seq, self._version[job.id], job.id)
        heapq.heappush(self._queues.setdefault(job.tenant, []), entry)

    def _top(self, tenant: str) -> tuple:
        """The tenant's next job's entry, throwing stale entries away."""
        queue = self._queues[tenant]
        while True:
            entry = queue[0]
            job = self._jobs[entry[-1]]
            if job.state == WAITING and entry[3] == self._version[job.id]:
                return entry
            self.stats.visits += 1
            heapq.heappop(queue)

    def _leave(self, job: Job, state: str) -> None:
        job.state = state
        self._counts[job.tenant] -= 1

    def _share(self, tenant: str, now: int) -> Fraction:
        started = self._started.get(tenant)
        if started:
            while started and now - started[0][0] >= self.share_window:
                self._used[tenant] -= started.popleft()[1]
        return Fraction(self._used.get(tenant, 0), self._weights.get(tenant, 1))

    # -- looking

    def job(self, job_id: str) -> Job:
        return self._jobs[job_id]

    def __len__(self) -> int:
        return sum(self._counts.values())

    def waiting(self) -> list[Job]:
        return [job for job in self._jobs.values() if job.state == WAITING]
