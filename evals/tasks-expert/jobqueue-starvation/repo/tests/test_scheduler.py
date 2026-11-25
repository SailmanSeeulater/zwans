import json

import pytest

from fairq import ManualClock, Scheduler, Stats
from fairq.replay import replay


def pulls(scheduler: Scheduler, count: int) -> list[str | None]:
    out = []
    for _ in range(count):
        job = scheduler.pull()
        out.append(job.id if job else None)
    return out


def test_higher_priority_first_then_oldest() -> None:
    clock = ManualClock()
    scheduler = Scheduler(clock)
    scheduler.submit("low", "a", priority=0)
    scheduler.submit("high", "a", priority=3)
    scheduler.submit("low2", "a", priority=0)

    assert pulls(scheduler, 4) == ["high", "low", "low2", None]


def test_a_waiting_job_gains_priority() -> None:
    clock = ManualClock()
    scheduler = Scheduler(clock)
    scheduler.submit("old", "a", priority=0)
    clock.advance(90)
    scheduler.submit("new", "a", priority=2)

    assert pulls(scheduler, 2) == ["old", "new"]


def test_tenants_take_turns() -> None:
    clock = ManualClock()
    scheduler = Scheduler(clock)
    for i in range(3):
        scheduler.submit(f"a{i}", "a", priority=5)
    for i in range(3):
        scheduler.submit(f"b{i}", "b", priority=0)

    assert pulls(scheduler, 6) == ["a0", "b0", "a1", "b1", "a2", "b2"]


def test_a_heavier_weight_gets_more_turns() -> None:
    clock = ManualClock()
    scheduler = Scheduler(clock)
    scheduler.set_weight("a", 2)
    for i in range(4):
        scheduler.submit(f"a{i}", "a")
        scheduler.submit(f"b{i}", "b")

    assert [job[0] for job in pulls(scheduler, 6)] == ["a", "b", "a", "b", "a", "a"]


def test_an_expired_job_is_dropped_not_run() -> None:
    clock = ManualClock()
    scheduler = Scheduler(clock)
    scheduler.submit("soon", "a", deadline=5)
    scheduler.submit("exact", "a", deadline=20)
    clock.advance(20)

    assert scheduler.pull().id == "exact"
    assert [job.id for job in scheduler.dropped] == ["soon"]
    assert scheduler.job("soon").state == "dropped"


def test_cancel_and_reprioritize() -> None:
    clock = ManualClock()
    scheduler = Scheduler(clock)
    scheduler.submit("x", "a", priority=1)
    scheduler.submit("y", "a", priority=0)
    scheduler.submit("z", "a", priority=0)

    assert scheduler.cancel("x")
    assert not scheduler.cancel("x")
    assert scheduler.reprioritize("z", 4)
    assert pulls(scheduler, 3) == ["z", "y", None]
    assert not scheduler.reprioritize("y", 1)


def test_ids_are_never_reused() -> None:
    scheduler = Scheduler(ManualClock())
    scheduler.submit("j", "a")
    scheduler.pull()

    with pytest.raises(ValueError):
        scheduler.submit("j", "a")


def test_visits_are_counted() -> None:
    stats = Stats()
    scheduler = Scheduler(ManualClock(), stats=stats)
    scheduler.submit("j", "a")
    scheduler.pull()

    assert stats.visits >= 1


def test_replay(tmp_path) -> None:
    events = [
        {"at": 0, "op": "submit", "id": "j1", "tenant": "acme", "priority": 1},
        {"at": 0, "op": "submit", "id": "j2", "tenant": "acme", "deadline": 3},
        {"at": 1, "op": "submit", "id": "j3", "tenant": "globex"},
        {"at": 2, "op": "pull", "worker": "w1"},
        {"at": 70, "op": "pull", "worker": "w2"},
        {"at": 70, "op": "cancel", "id": "j2"},
        {"at": 71, "op": "pull", "worker": "w1"},
    ]

    assert replay(json.dumps(event) for event in events) == [
        "2 w1 <- j1 (acme)",
        "70 dropped j2",
        "70 w2 <- j3 (globex)",
        "70 cancel: j2 isn't waiting",
        "71 w1 idle",
    ]
