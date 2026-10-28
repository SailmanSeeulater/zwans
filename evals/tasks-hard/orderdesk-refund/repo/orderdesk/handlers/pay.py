from dataclasses import dataclass

from ..aggregate import OrderState
from ..commands import Command, Context, handler, require_positive
from ..errors import InvalidState, ValidationError
from ..events import Event, PaymentCaptured
from ..money import format_amount

METHODS = ("card", "transfer", "cash")


@dataclass(frozen=True)
class PayOrder(Command):
    amount_cents: int
    method: str

    def validate(self) -> None:
        require_positive(self.amount_cents, "amount")
        if self.method not in METHODS:
            raise ValidationError(f"payment method must be one of {', '.join(METHODS)}")


@handler(PayOrder, name="pay", permission="orders.pay", summary="Record the payment for an order")
def pay(state: OrderState, cmd: PayOrder, ctx: Context) -> list[Event]:
    if state.status != "placed":
        raise InvalidState(f"{state.order_id} is {state.status}; only placed orders can be paid")
    # We only take payment in full.
    if cmd.amount_cents != state.outstanding_cents:
        raise InvalidState(
            f"{state.order_id} needs exactly {format_amount(state.outstanding_cents)}, "
            f"not {format_amount(cmd.amount_cents)}"
        )
    return [PaymentCaptured(cmd.order_id, ctx.at, cmd.amount_cents, cmd.method)]
