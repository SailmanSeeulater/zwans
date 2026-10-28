from jobs.model import Job
from jobs.scheduler import Scheduler
from jobs.states import State


def test_a_job_runs_and_succeeds() -> None:
    scheduler = Scheduler()
    job = scheduler.submit(sum, [1, 2, 3])

    scheduler.run_pending()

    assert job.state is State.SUCCEEDED
    assert job.result == 6
    assert job.attempts == 1
    assert job.events() == ["start", "succeed"]


def test_a_failing_job_without_retries() -> None:
    scheduler = Scheduler()
    job = scheduler.submit(int, "not a number")

    scheduler.run_pending()

    assert job.state is State.FAILED
    assert job.error is not None and job.error.startswith("ValueError")
    assert job.events() == ["start", "fail"]


def test_a_cancelled_job_does_not_run() -> None:
    ran = []
    scheduler = Scheduler()
    job = scheduler.submit(ran.append, "x")

    scheduler.cancel(job)
    scheduler.run_pending()

    assert ran == []
    assert job.state is State.CANCELLED


def test_a_broken_listener_does_not_stop_the_job() -> None:
    scheduler = Scheduler()

    def broken(job: Job, change: object) -> None:
        raise RuntimeError("boom")

    scheduler.bus.on(State.RUNNING, broken)
    job = scheduler.submit(len, "abc")

    scheduler.run_pending()

    assert job.state is State.SUCCEEDED
    assert job.result == 3


def test_summary() -> None:
    scheduler = Scheduler()
    scheduler.submit(len, "ok")
    scheduler.submit(len, 5)
    scheduler.submit(len, "")

    scheduler.run_pending()

    assert scheduler.summary() == {"failed": 1, "succeeded": 2}
