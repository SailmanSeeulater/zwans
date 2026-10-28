"""Listeners that react when a job enters a state."""

import logging
from collections import defaultdict
from collections.abc import Callable

from jobs.model import Change, Job
from jobs.states import State

log = logging.getLogger(__name__)

Listener = Callable[[Job, Change], None]


class EventBus:
    def __init__(self) -> None:
        self._listeners: dict[State, list[Listener]] = defaultdict(list)

    def on(self, state: State, listener: Listener) -> None:
        """Call `listener(job, change)` whenever a job enters `state`."""
        self._listeners[state].append(listener)

    def publish(self, job: Job, change: Change) -> None:
        # One broken listener must not stop the others, or the job itself.
        for listener in list(self._listeners[change.new]):
            try:
                listener(job, change)
            except Exception:
                log.warning(
                    "listener %s failed on %s (%s -> %s)",
                    getattr(listener, "__qualname__", listener),
                    job.name,
                    change.old,
                    change.new,
                    exc_info=True,
                )
