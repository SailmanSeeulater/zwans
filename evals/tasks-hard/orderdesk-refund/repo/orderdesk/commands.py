"""Commands and their registry.

A command is a frozen dataclass describing what a user asks for. Its handler looks at the
order's current state and returns the events that should be recorded (or raises). Handlers
are registered with @handler, which also gives the command:

- its name, used by the CLI, the docs, `orderdesk help` and the audit log;
- the permission an actor needs to run it (see permissions.py);
- a one-line summary for `orderdesk help`.

Handlers live in orderdesk/handlers/, one module per command.
"""

from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import Any

from .errors import ValidationError
from .events import Event
from .permissions import Actor


@dataclass(frozen=True)
class Command:
    order_id: str

    def validate(self) -> None:
        """Check the command on its own, before the order is even loaded.

        Raise ValidationError for anything wrong. Rules that depend on the order's state
        belong in the handler instead (and raise InvalidState).
        """

    def audit_details(self) -> dict[str, Any]:
        """What the audit log records about this command, besides who, what and when."""
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "order_id"}


@dataclass(frozen=True)
class Context:
    actor: Actor
    at: str  # the time the command is being run, stamped on every event it produces


Handler = Callable[[Any, Any, Context], list[Event]]


@dataclass(frozen=True)
class CommandSpec:
    name: str
    command: type[Command]
    handle: Handler
    permission: str
    summary: str
    creates: bool  # True when the command starts a new order rather than changing one


COMMANDS: dict[str, CommandSpec] = {}
_BY_TYPE: dict[type[Command], CommandSpec] = {}


def handler(
    command: type[Command], *, name: str, permission: str, summary: str, creates: bool = False
):
    def register(fn: Handler) -> Handler:
        if name in COMMANDS:
            raise ValueError(f"command {name!r} is registered twice")
        spec = CommandSpec(name, command, fn, permission, summary, creates)
        COMMANDS[name] = spec
        _BY_TYPE[command] = spec
        return fn

    return register


def spec_for(cmd: Command) -> CommandSpec:
    try:
        return _BY_TYPE[type(cmd)]
    except KeyError:
        raise ValueError(f"{type(cmd).__name__} has no registered handler") from None


# Small validation helpers shared by the commands.


def require_text(value: str, what: str) -> None:
    if not value or not value.strip():
        raise ValidationError(f"{what} is required")


def require_positive(cents: int, what: str) -> None:
    if cents <= 0:
        raise ValidationError(f"{what} must be more than zero")
