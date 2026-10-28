from dataclasses import dataclass

from ..aggregate import OrderState
from ..commands import Command, Context, handler, require_text
from ..errors import InvalidState
from ..events import Event, OrderShipped


@dataclass(frozen=True)
class ShipOrder(Command):
    carrier: str
    tracking: str

    def validate(self) -> None:
        require_text(self.carrier, "carrier")
        require_text(self.tracking, "tracking number")


@handler(ShipOrder, name="ship", permission="orders.ship", summary="Mark a paid order as shipped")
def ship(state: OrderState, cmd: ShipOrder, ctx: Context) -> list[Event]:
    if state.status != "paid":
        raise InvalidState(f"{state.order_id} is {state.status}; only paid orders can ship")
    return [OrderShipped(cmd.order_id, ctx.at, cmd.carrier, cmd.tracking)]
