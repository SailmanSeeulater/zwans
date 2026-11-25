"""A slow, obviously-right scheduler for the tests to compare against: it keeps every
job in a list and works out each pull from scratch, following the README word for word,
with exact fractions. It shares no code with the scheduler under test."""

from fractions import Fraction


class Oracle:
    def __init__(self, aging_period: int = 30, share_window: int = 60) -> None:
        self.aging_period = aging_period
        self.share_window = share_window
        self.jobs: dict[str, dict] = {}  # every job ever submitted, by id
        self.waiting: list[str] = []  # in submit order
        self.weights: dict[str, int] = {}
        self.started: list[tuple[int, str, int]] = []  # (time, tenant, size) of each pull
        self.dropped: list[str] = []

    def submit(self, now: int, job_id: str, tenant: str, priority: int, size: int,
               deadline: int | None) -> None:
        assert job_id not in self.jobs
        self.jobs[job_id] = dict(id=job_id, tenant=tenant, priority=priority, size=size,
                                 deadline=deadline, enqueued=now, seq=len(self.jobs))
        self.waiting.append(job_id)

    def set_weight(self, tenant: str, weight: int) -> None:
        self.weights[tenant] = weight

    def cancel(self, job_id: str) -> bool:
        if job_id in self.waiting:
            self.waiting.remove(job_id)
            return True
        return False

    def reprioritize(self, job_id: str, priority: int) -> bool:
        if job_id in self.waiting:
            self.jobs[job_id]["priority"] = priority
            return True
        return False

    def effective(self, job: dict, now: int) -> Fraction:
        return job["priority"] + Fraction(now - job["enqueued"], self.aging_period)

    def order(self, job: dict, now: int) -> tuple:
        """Sorts first for the job that should run first."""
        return (-self.effective(job, now), job["enqueued"], job["seq"])

    def pull(self, now: int) -> tuple[str | None, list[str]]:
        """The job handed out (or None) and the jobs dropped, in the order reported."""
        expired = [self.jobs[i] for i in self.waiting
                   if self.jobs[i]["deadline"] is not None and self.jobs[i]["deadline"] < now]
        expired.sort(key=lambda job: (job["deadline"], job["seq"]))
        dropped = [job["id"] for job in expired]
        for job_id in dropped:
            self.waiting.remove(job_id)
        self.dropped.extend(dropped)
        if not self.waiting:
            return None, dropped

        def share(tenant: str) -> Fraction:
            used = sum(size for at, who, size in self.started
                       if who == tenant and now - at < self.share_window)
            return Fraction(used, self.weights.get(tenant, 1))

        jobs = [self.jobs[i] for i in self.waiting]
        shares = {tenant: share(tenant) for tenant in {job["tenant"] for job in jobs}}
        lowest = min(shares.values())
        candidates = [job for job in jobs if shares[job["tenant"]] == lowest]
        chosen = min(candidates, key=lambda job: self.order(job, now))
        self.waiting.remove(chosen["id"])
        self.started.append((now, chosen["tenant"], chosen["size"]))
        return chosen["id"], dropped
