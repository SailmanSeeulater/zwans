"""Jobs and their history."""

import itertools
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from jobs.states import State

_ids = itertools.count(1)


@dataclass(frozen=True)
class Change:
    old: State
    new: State
    event: str


@dataclass(eq=False)
class Job:
    func: Callable[..., Any]
    args: tuple[Any, ...] = ()
    name: str = ""
    id: int = field(default_factory=lambda: next(_ids))
    state: State = State.PENDING
    attempts: int = 0  # how many times it has started running
    result: Any = None
    error: str | None = None
    history: list[Change] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"job-{self.id}"

    def events(self) -> list[str]:
        return [change.event for change in self.history]
