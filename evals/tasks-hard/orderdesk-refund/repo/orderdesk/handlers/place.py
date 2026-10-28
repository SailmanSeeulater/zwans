from dataclasses import dataclass

from ..aggregate import OrderState
from ..commands import Command, Context, handler, require_text
from ..errors import InvalidState, ValidationError
from ..events import Event, Line, OrderPlaced


@dataclass(frozen=True)
class PlaceOrder(Command):
    customer: str
    email: str
    lines: tuple[Line, ...]

    def validate(self) -> None:
        require_text(self.customer, "customer")
        if "@" not in self.email:
            raise ValidationError(f"{self.email!r} does not look like an email address")
        if not self.lines:
            raise ValidationError("an order needs at least one line")
        for line in self.lines:
            require_text(line.sku, "sku")
            if line.qty <= 0:
                raise ValidationError(f"{line.sku}: quantity must be more than zero")
            if line.unit_cents < 0:
                raise ValidationError(f"{line.sku}: price cannot be negative")

    def audit_details(self) -> dict:
        details = super().audit_details()
        details["lines"] = [f"{line.sku}:{line.qty}:{line.unit_cents}" for line in self.lines]
        return details


@handler(
    PlaceOrder, name="place", permission="orders.place", summary="Place a new order", creates=True
)
def place(state: OrderState, cmd: PlaceOrder, ctx: Context) -> list[Event]:
    if state.status != "new":
        raise InvalidState(f"{cmd.order_id} already exists")
    return [OrderPlaced(cmd.order_id, ctx.at, cmd.customer, cmd.email, cmd.lines)]
