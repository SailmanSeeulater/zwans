"""The scheduler against the README: the exact jobs handed out and dropped over random
workloads, compared with a from-scratch scheduler, and no more job visits than "What a
pull costs" allows."""

import random

import pytest
from oracle import Oracle

from fairq import ManualClock, Scheduler


class OverBudget(AssertionError):
    pass


class Stats:
    """Counts visits like fairq.Stats, and stops the test as soon as they go over the
    README's limit: 6 visits per submit and reprioritize call so far."""

    def __init__(self) -> None:
        self._visits = 0
        self.calls = 0

    @property
    def visits(self) -> int:
        return self._visits

    @visits.setter
    def visits(self, value: int) -> None:
        if value > 6 * self.calls:
            raise OverBudget(f"{value} visits after {self.calls} submit/reprioritize calls")
        self._visits = value


def replay(seed: int, steps: int, tenants: int, deadlines: float = 0.3) -> None:
    rng = random.Random(seed)
    clock = ManualClock(rng.randint(0, 1000))
    stats = Stats()
    scheduler = Scheduler(clock, stats=stats)
    oracle = Oracle()
    names = [f"t{i}" for i in range(tenants)]
    ids: list[str] = []
    log: list[str] = []
    for step in range(steps):
        clock.advance(rng.choice([0, 0, 0, 1, 2, 5, 10, 15, 29, 30, 31, 45, 59, 60, 61]))
        now = clock()
        roll = rng.random()
        if roll < 0.45 or not ids:
            job_id = f"j{len(ids)}"
            ids.append(job_id)
            tenant = rng.choice(names[: rng.randint(1, tenants)])
            priority = rng.randint(0, 4)
            size = rng.choice([1, 1, 1, 2, 3, 5])
            deadline = now + rng.randint(0, 120) if rng.random() < deadlines else None
            log.append(f"t={now} submit {job_id} {tenant} p={priority} size={size} deadline={deadline}")
            stats.calls += 1
            scheduler.submit(job_id, tenant, priority=priority, size=size, deadline=deadline)
            oracle.submit(now, job_id, tenant, priority, size, deadline)
            continue
        if roll < 0.8:
            log.append(f"t={now} pull")
            before = len(scheduler.dropped)
            job = scheduler.pull(f"w{step % 3}")
            got = job.id if job is not None else None
            got_dropped = [j.id for j in scheduler.dropped[before:]]
            want, want_dropped = oracle.pull(now)
            assert got_dropped == want_dropped, (
                f"seed {seed}: this pull should drop {want_dropped}, not {got_dropped}.\n"
                + "\n".join(log[-40:])
            )
            assert got == want, (
                f"seed {seed}: the pull handed out {got}, the README says {want}.\n"
                + "\n".join(log[-40:])
            )
            if job is not None:
                assert job.started_at == now and job.state == "running"
            continue
        job_id = rng.choice(ids)
        if roll < 0.88:
            log.append(f"t={now} cancel {job_id}")
            assert scheduler.cancel(job_id) == oracle.cancel(job_id), "\n".join(log[-40:])
        elif roll < 0.97:
            priority = rng.randint(0, 6)
            log.append(f"t={now} reprioritize {job_id} p={priority}")
            stats.calls += 1
            assert scheduler.reprioritize(job_id, priority) == oracle.reprioritize(job_id, priority)
        else:
            tenant, weight = rng.choice(names), rng.randint(1, 3)
            log.append(f"t={now} weight {tenant}={weight}")
            scheduler.set_weight(tenant, weight)
            oracle.set_weight(tenant, weight)


@pytest.mark.parametrize("seed", range(120))
def test_random_workloads_hand_out_the_readme_order(seed: int) -> None:
    replay(seed, steps=250, tenants=1 + seed % 4)


@pytest.mark.parametrize("seed", range(5))
def test_long_workloads_with_deep_queues(seed: int) -> None:
    replay(1000 + seed, steps=3000, tenants=3, deadlines=0.15)


# -- targeted cases


def test_a_low_priority_job_catches_up_continuously() -> None:
    clock = ManualClock()
    scheduler = Scheduler(clock)
    scheduler.submit("old", "a", priority=0)
    clock.advance(45)  # old is now at 1.5
    scheduler.submit("new", "a", priority=1)

    assert scheduler.pull().id == "old"


def test_equal_effective_priority_goes_to_the_older_job() -> None:
    clock = ManualClock()
    scheduler = Scheduler(clock)
    scheduler.submit("first", "a", priority=0)
    clock.advance(30)
    scheduler.submit("second", "a", priority=1)  # both at 1 from now on
    clock.advance(7)

    assert [scheduler.pull().id, scheduler.pull().id] == ["first", "second"]


def test_fair_share_counts_size_over_weight_in_the_window() -> None:
    clock = ManualClock()
    scheduler = Scheduler(clock)
    scheduler.set_weight("b", 2)
    for i in range(4):
        scheduler.submit(f"a{i}", "a", size=3)
        scheduler.submit(f"b{i}", "b", size=4)

    order = [scheduler.pull().tenant for _ in range(4)]

    # a: 0, b: 0 -> tie, a's job is older; then a=3 vs b=0 -> b; a=3 vs b=2 -> b;
    # a=3 vs b=4 -> a
    assert order == ["a", "b", "b", "a"]
    clock.advance(59)
    assert scheduler.pull().tenant == "b"  # a=6, b=4: nothing has left the window yet
    clock.advance(1)
    assert scheduler.pull().tenant == "a"  # the first pulls (60 s ago) no longer count


def test_an_expired_job_is_dropped_by_the_next_pull_whatever_runs() -> None:
    clock = ManualClock()
    scheduler = Scheduler(clock)
    scheduler.submit("urgent", "a", priority=5)
    scheduler.submit("late", "b", deadline=10)
    scheduler.submit("later", "a", deadline=5)
    clock.advance(10)

    assert scheduler.pull().id == "urgent"
    assert [job.id for job in scheduler.dropped] == ["later"]
    clock.advance(1)
    assert scheduler.pull() is None
    assert [job.id for job in scheduler.dropped] == ["later", "late"]
    assert scheduler.job("late").state == "dropped"


def test_reprioritize_and_cancel_take_effect_at_once() -> None:
    clock = ManualClock()
    scheduler = Scheduler(clock)
    for name in "abc":
        scheduler.submit(name, "t", priority=1)
    assert scheduler.reprioritize("c", 3)
    assert scheduler.cancel("a")

    assert [scheduler.pull().id, scheduler.pull().id] == ["c", "b"]
    assert not scheduler.reprioritize("a", 9) and not scheduler.cancel("c")


def test_a_big_queue_costs_a_few_visits_per_job() -> None:
    clock = ManualClock()
    stats = Stats()
    scheduler = Scheduler(clock, stats=stats)
    rng = random.Random(5)
    for i in range(20000):
        stats.calls += 1
        scheduler.submit(f"j{i}", f"t{i % 5}", priority=rng.randint(0, 9), size=rng.randint(1, 4),
                         deadline=None if i % 3 else 10**6)
        if i % 4 == 0:
            clock.advance(1)
    handed = 0
    while scheduler.pull() is not None:
        handed += 1
        if handed % 50 == 0:
            clock.advance(1)
    assert handed == 20000
