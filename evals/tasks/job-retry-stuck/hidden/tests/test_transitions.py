import pytest

from jobs.events import EventBus
from jobs.machine import Machine
from jobs.model import Change, Job
from jobs.scheduler import Scheduler
from jobs.states import InvalidTransition, State


class Flaky:
    def __init__(self, failures: int, log: list[str] | None = None, name: str = "") -> None:
        self.failures = failures
        self.calls = 0
        self.log = log
        self.name = name

    def __call__(self) -> str:
        self.calls += 1
        if self.log is not None:
            self.log.append(self.name)
        if self.calls <= self.failures:
            raise ConnectionError(f"attempt {self.calls} failed")
        return "done"


def assert_history_is_a_chain(job: Job) -> None:
    assert job.history, "no history"
    assert job.history[0].old is State.PENDING
    for before, after in zip(job.history, job.history[1:], strict=False):
        assert before.new is after.old, job.history
    assert job.history[-1].new is job.state


def test_retries_until_success() -> None:
    scheduler = Scheduler(max_attempts=3)
    flaky = Flaky(failures=2)
    job = scheduler.submit(flaky)

    scheduler.run_pending()

    assert job.state is State.SUCCEEDED
    assert job.result == "done"
    assert job.error is None
    assert job.attempts == 3
    assert flaky.calls == 3
    assert job.events() == ["start", "fail", "retry", "start", "fail", "retry", "start", "succeed"]
    assert_history_is_a_chain(job)


def test_gives_up_after_max_attempts() -> None:
    scheduler = Scheduler(max_attempts=3)
    flaky = Flaky(failures=10)
    job = scheduler.submit(flaky)

    scheduler.run_pending()

    assert job.state is State.FAILED
    assert job.attempts == 3
    assert flaky.calls == 3
    assert job.error == "ConnectionError: attempt 3 failed"
    assert job.events()[-2:] == ["start", "fail"]
    assert not scheduler.queue
    assert_history_is_a_chain(job)


def test_a_retried_job_goes_to_the_back_of_the_queue() -> None:
    order: list[str] = []
    scheduler = Scheduler(max_attempts=2)
    scheduler.submit(Flaky(1, order, "a"))
    scheduler.submit(Flaky(0, order, "b"))

    scheduler.run_pending()

    assert order == ["a", "b", "a"]
    assert scheduler.summary() == {"succeeded": 2}


def test_successful_jobs_are_archived() -> None:
    scheduler = Scheduler(archive_finished=True)
    job = scheduler.submit(len, "abc")

    scheduler.run_pending()

    assert job.state is State.ARCHIVED
    assert job.result == 3
    assert job.events() == ["start", "succeed", "archive"]
    assert_history_is_a_chain(job)


def test_cancelled_jobs_are_archived_and_failed_ones_kept() -> None:
    scheduler = Scheduler(max_attempts=2, archive_finished=True)
    cancelled = scheduler.submit(len, "x")
    failing = scheduler.submit(Flaky(5))
    flaky = scheduler.submit(Flaky(1))

    scheduler.cancel(cancelled)
    scheduler.run_pending()

    assert cancelled.state is State.ARCHIVED
    assert failing.state is State.FAILED
    assert flaky.state is State.ARCHIVED
    assert flaky.events() == ["start", "fail", "retry", "start", "succeed", "archive"]
    for job in (cancelled, failing, flaky):
        assert_history_is_a_chain(job)


def test_listeners_see_the_new_state() -> None:
    bus = EventBus()
    machine = Machine(bus)
    seen: list[tuple[State, State]] = []
    bus.on(State.RUNNING, lambda job, change: seen.append((job.state, change.new)))
    job = Job(len, ("ab",))

    machine.fire(job, "start")

    assert seen == [(State.RUNNING, State.RUNNING)]


def test_a_listener_can_move_the_job_on() -> None:
    bus = EventBus()
    machine = Machine(bus)
    bus.on(State.RUNNING, lambda job, change: machine.fire(job, "cancel"))
    bus.on(State.CANCELLED, lambda job, change: machine.fire(job, "archive"))
    job = Job(len, ("ab",))

    change = machine.fire(job, "start")

    assert change == Change(State.PENDING, State.RUNNING, "start")
    assert job.state is State.ARCHIVED
    assert job.events() == ["start", "cancel", "archive"]
    assert_history_is_a_chain(job)


def test_invalid_transition_changes_nothing() -> None:
    machine = Machine(EventBus())
    job = Job(len, ("ab",))

    with pytest.raises(InvalidTransition):
        machine.fire(job, "succeed")

    assert job.state is State.PENDING
    assert job.history == []
