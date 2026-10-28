"""The states a job moves through, and which events move it."""

from enum import StrEnum


class State(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


TRANSITIONS: dict[tuple[State, str], State] = {
    (State.PENDING, "start"): State.RUNNING,
    (State.PENDING, "cancel"): State.CANCELLED,
    (State.RUNNING, "succeed"): State.SUCCEEDED,
    (State.RUNNING, "fail"): State.FAILED,
    (State.RUNNING, "cancel"): State.CANCELLED,
    (State.FAILED, "retry"): State.PENDING,
    (State.SUCCEEDED, "archive"): State.ARCHIVED,
    (State.FAILED, "archive"): State.ARCHIVED,
    (State.CANCELLED, "archive"): State.ARCHIVED,
}


class InvalidTransition(Exception):
    pass


def next_state(state: State, event: str) -> State:
    try:
        return TRANSITIONS[(state, event)]
    except KeyError:
        raise InvalidTransition(f"cannot {event} a job that is {state}") from None
