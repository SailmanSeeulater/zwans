"""The order aggregate: an order's current state, rebuilt by replaying its events.

Handlers decide what happens by looking at an OrderState; they never change it. State only
changes by applying events, so replaying the log always gives the same answer.

Order statuses:

    new       nothing recorded yet (the order does not exist)
    placed    waiting for payment
    paid      paid in full, not shipped yet
    shipped   on its way to the customer
    cancelled cancelled before shipping (anything paid was given back)
    refunded  everything paid has been refunded
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from .events import (
    Event,
    Line,
    NoteAdded,
    OrderCancelled,
    OrderPlaced,
    OrderRefunded,
    OrderShipped,
    PaymentCaptured,
)


@dataclass
class OrderState:
    order_id: str
    status: str = "new"
    customer: str = ""
    email: str = ""
    lines: tuple[Line, ...] = ()
    paid_cents: int = 0
    refunded_cents: int = 0  # given back so far, by refunds or a cancellation
    carrier: str = ""
    tracking: str = ""
    cancel_reason: str = ""
    notes: list[str] = field(default_factory=list)
    version: int = 0  # how many events have been applied

    @property
    def total_cents(self) -> int:
        return sum(line.total_cents for line in self.lines)

    @property
    def outstanding_cents(self) -> int:
        return self.total_cents - self.paid_cents

    @property
    def refundable_cents(self) -> int:
        return self.paid_cents - self.refunded_cents


def _placed(state: OrderState, ev: OrderPlaced) -> None:
    state.status = "placed"
    state.customer = ev.customer
    state.email = ev.email
    state.lines = ev.lines


def _paid(state: OrderState, ev: PaymentCaptured) -> None:
    state.paid_cents += ev.amount_cents
    if state.paid_cents >= state.total_cents:
        state.status = "paid"


def _shipped(state: OrderState, ev: OrderShipped) -> None:
    state.status = "shipped"
    state.carrier = ev.carrier
    state.tracking = ev.tracking


def _cancelled(state: OrderState, ev: OrderCancelled) -> None:
    state.status = "cancelled"
    state.cancel_reason = ev.reason
    state.refunded_cents += ev.refund_cents


def _refunded(state: OrderState, ev: OrderRefunded) -> None:
    state.refunded_cents += ev.amount_cents
    if state.refunded_cents >= state.paid_cents:
        state.status = "refunded"


def _note(state: OrderState, ev: NoteAdded) -> None:
    state.notes.append(f"{ev.author}: {ev.text}")


_APPLY: dict[type[Event], Callable[[OrderState, Event], None]] = {
    OrderPlaced: _placed,
    PaymentCaptured: _paid,
    OrderShipped: _shipped,
    OrderCancelled: _cancelled,
    OrderRefunded: _refunded,
    NoteAdded: _note,
}


def apply(state: OrderState, ev: Event) -> None:
    try:
        step = _APPLY[type(ev)]
    except KeyError:
        raise TypeError(f"OrderState does not know how to apply {type(ev).__name__}") from None
    step(state, ev)
    state.version += 1


def replay(order_id: str, events: Iterable[Event]) -> OrderState:
    state = OrderState(order_id)
    for ev in events:
        apply(state, ev)
    return state
