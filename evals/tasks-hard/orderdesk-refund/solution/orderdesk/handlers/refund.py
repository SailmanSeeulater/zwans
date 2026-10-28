from dataclasses import dataclass

from ..aggregate import OrderState
from ..commands import Command, Context, handler, require_positive, require_text
from ..errors import InvalidState
from ..events import Event, OrderRefunded
from ..money import format_amount


@dataclass(frozen=True)
class RefundOrder(Command):
    amount_cents: int
    reason: str

    def validate(self) -> None:
        require_positive(self.amount_cents, "amount")
        require_text(self.reason, "reason")


@handler(
    RefundOrder,
    name="refund",
    permission="orders.refund",
    summary="Give back some or all of what was paid for an order, without cancelling it",
)
def refund(state: OrderState, cmd: RefundOrder, ctx: Context) -> list[Event]:
    if state.status not in ("paid", "shipped"):
        raise InvalidState(
            f"{state.order_id} is {state.status}; only paid or shipped orders can be refunded"
        )
    if cmd.amount_cents > state.refundable_cents:
        raise InvalidState(
            f"{state.order_id} has only {format_amount(state.refundable_cents)} left to refund, "
            f"not {format_amount(cmd.amount_cents)}"
        )
    return [OrderRefunded(cmd.order_id, ctx.at, cmd.amount_cents, cmd.reason)]
