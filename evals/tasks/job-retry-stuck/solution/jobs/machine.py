"""Moves jobs between states and tells the listeners."""

from jobs.events import EventBus
from jobs.model import Change, Job
from jobs.states import next_state


class Machine:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus

    def fire(self, job: Job, event: str) -> Change:
        """Apply `event` to `job`. Raises InvalidTransition if it doesn't apply now."""
        change = Change(job.state, next_state(job.state, event), event)
        # Commit before telling anyone: a listener may fire the next event itself (a retry
        # policy sends a failed job back to pending), and it must start from the new state.
        job.state = change.new
        job.history.append(change)
        self.bus.publish(job, change)
        return change
