"""Orders.

Statuses:
    placed             stock is reserved, waiting to ship
    partially_shipped  some of it has left the warehouse, the rest is reserved
    shipped            everything has left the warehouse (or, after a cancellation, everything
                       that ever will)
    cancelled          cancelled before anything shipped; its reservations were released
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
    shipped: dict[str, int] = field(default_factory=dict)  # sku -> units shipped so far

    @property
    def subtotal_cents(self) -> int:
        return sum(line.subtotal_cents for line in self.lines)

    @property
    def shipped_subtotal_cents(self) -> int:
        return sum(self.shipped.get(line.sku, 0) * line.unit_price_cents for line in self.lines)

    def outstanding(self, sku: str) -> int:
        """Units of sku still to ship (0 once the order is cancelled)."""
        line = self.line(sku)
        if line is None or self.cancelled_at:
            return 0
        return line.qty - self.shipped.get(sku, 0)

    def line(self, sku: str) -> OrderLine | None:
        for line in self.lines:
            if line.sku == sku:
                return line
        return None
