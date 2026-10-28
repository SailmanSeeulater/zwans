"""The desk runs commands: the one way anything changes in orderdesk.

For every command it:

1. checks the actor's permission,
2. validates the command on its own,
3. loads the order and replays it,
4. asks the handler for the new events,
5. appends them to the store (optimistic concurrency),
6. writes the audit entry (also for denied and rejected commands),
7. publishes the new events on the bus, for read models and notifications.
"""

from collections.abc import Callable

from .aggregate import OrderState, replay
from .audit import AuditLog
from .bus import EventBus
from .commands import Command, Context, spec_for
from .errors import NotFound, OrderDeskError, PermissionDenied
from .events import Event
from .permissions import Actor, require
from .store import MemoryEventStore


class Desk:
    def __init__(
        self,
        store: MemoryEventStore,
        *,
        clock: Callable[[], str],
        audit: AuditLog,
        bus: EventBus,
    ) -> None:
        self._store = store
        self._clock = clock
        self._audit = audit
        self._bus = bus

    def execute(self, cmd: Command, actor: Actor) -> list[Event]:
        spec = spec_for(cmd)
        at = self._clock()

        def audit(outcome: str, error: str = "") -> None:
            self._audit.record(
                at=at,
                actor=actor.name,
                role=actor.role,
                command=spec.name,
                order_id=cmd.order_id,
                outcome=outcome,
                details=cmd.audit_details(),
                error=error,
            )

        try:
            require(actor, spec.permission)
            cmd.validate()
            history = self._store.load(cmd.order_id)
            state = replay(cmd.order_id, history)
            if state.status == "new" and not spec.creates:
                raise NotFound(f"there is no order {cmd.order_id}")
            events = spec.handle(state, cmd, Context(actor, at))
            self._store.append(cmd.order_id, events, expected_version=len(history))
        except PermissionDenied as exc:
            audit("denied", str(exc))
            raise
        except OrderDeskError as exc:
            audit("rejected", str(exc))
            raise
        audit("ok")
        self._bus.publish(events)
        return events

    def state(self, order_id: str) -> OrderState:
        state = replay(order_id, self._store.load(order_id))
        if state.status == "new":
            raise NotFound(f"there is no order {order_id}")
        return state

    def next_order_id(self) -> str:
        return f"ORD-{len(self._store.order_ids()) + 1:04d}"
