from jobs.scheduler import Scheduler
from jobs.states import State


class Flaky:
    """Fails the first `failures` times it is called, then returns "done"."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError(f"attempt {self.calls} failed")
        return "done"


def test_a_flaky_job_succeeds_on_its_second_attempt() -> None:
    scheduler = Scheduler(max_attempts=2)
    flaky = Flaky(failures=1)
    job = scheduler.submit(flaky)

    scheduler.run_pending()

    assert job.state is State.SUCCEEDED
    assert job.result == "done"
    assert job.attempts == 2
