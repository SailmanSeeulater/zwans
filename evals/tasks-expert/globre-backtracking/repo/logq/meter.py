"""Counting the matcher's steps, and stopping a runaway search."""


class StepLimitExceeded(RuntimeError):
    """A match took more steps than its meter allows."""


class Meter:
    """Counts steps (see the README). With a limit, the step after the last one allowed
    raises StepLimitExceeded."""

    def __init__(self, limit: int | None = None) -> None:
        self.limit = limit
        self.steps = 0

    def step(self) -> None:
        self.steps += 1
        if self.limit is not None and self.steps > self.limit:
            raise StepLimitExceeded(f"more than {self.limit} steps")


class _Uncounted:
    def step(self) -> None:
        pass


UNCOUNTED = _Uncounted()
