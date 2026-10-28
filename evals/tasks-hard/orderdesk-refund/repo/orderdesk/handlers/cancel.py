from dataclasses import dataclass

from ..aggregate import OrderState
from ..commands import Command, Context, handler, require_text
from ..errors import InvalidState
from ..events import Event, OrderCancelled


@dataclass(frozen=True)
class CancelOrder(Command):
    reason: str

    def validate(self) -> None:
        require_text(self.reason, "reason")


@handler(
    CancelOrder,
    name="cancel",
    permission="orders.cancel",
    summary="Cancel an order that has not shipped; anything paid goes back to the customer",
)
def cancel(state: OrderState, cmd: CancelOrder, ctx: Context) -> list[Event]:
    if state.status not in ("placed", "paid"):
        raise InvalidState(
            f"{state.order_id} is {state.status}; only placed or paid orders can be cancelled"
        )
    # Whatever the customer paid goes back to them.
    return [OrderCancelled(cmd.order_id, ctx.at, cmd.reason, refund_cents=state.paid_cents)]
