"""Orders.

Statuses:
    placed     stock is reserved, waiting to ship
    shipped    everything has left the warehouse
    cancelled  cancelled before shipping; its reservations were released
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OrderLine:
    sku: str
    qty: int
    unit_price_cents: int  # the price when the order was placed

    @property
    def subtotal_cents(self) -> int:
        return self.qty * self.unit_price_cents


@dataclass
class Order:
    id: str
    customer: str
    lines: list[OrderLine]
    discount_percent: int  # from a coupon; applies to goods only
    shipping_cents: int  # flat fee for the order
    placed_at: str
    status: str = "placed"
    shipped_at: str = ""
    cancelled_at: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def subtotal_cents(self) -> int:
        return sum(line.subtotal_cents for line in self.lines)

    def line(self, sku: str) -> OrderLine | None:
        for line in self.lines:
            if line.sku == sku:
                return line
        return None
