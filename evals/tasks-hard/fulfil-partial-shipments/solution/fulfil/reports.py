"""Reports for the warehouse and for finance. Days are UTC calendar days ("2026-03-01")."""

from collections import Counter
from dataclasses import dataclass, field

from .money import format_cents
from .shop import Shop


@dataclass
class DaySales:
    day: str
    units: dict[str, int] = field(
        default_factory=dict
    )  # sku -> units that left the warehouse that day
    invoiced_cents: int = 0  # invoices issued that day
    credited_cents: int = 0  # credit notes issued that day

    @property
    def net_cents(self) -> int:
        return self.invoiced_cents - self.credited_cents


def sales(shop: Shop, day: str) -> DaySales:
    units: Counter[str] = Counter()
    for invoice in shop.invoices:
        if invoice.issued_at[:10] == day:
            for line in invoice.lines:
                units[line.sku] += line.qty
    return DaySales(
        day=day,
        units=dict(sorted(units.items())),
        invoiced_cents=sum(i.total_cents for i in shop.invoices if i.issued_at[:10] == day),
        credited_cents=sum(n.amount_cents for n in shop.credit_notes if n.issued_at[:10] == day),
    )


@dataclass(frozen=True)
class BacklogLine:
    order_id: str
    customer: str
    sku: str
    qty: int  # still to ship


def backlog(shop: Shop) -> list[BacklogLine]:
    """Everything ordered that has not shipped yet (and is not cancelled), oldest order first."""
    result = []
    for order in sorted(shop.orders.values(), key=lambda o: o.id):
        for line in order.lines:
            if order.outstanding(line.sku) > 0:
                result.append(
                    BacklogLine(order.id, order.customer, line.sku, order.outstanding(line.sku))
                )
    return result


@dataclass(frozen=True)
class StockLine:
    sku: str
    on_hand: int
    reserved: int
    available: int


def stock(shop: Shop) -> list[StockLine]:
    inventory = shop.inventory
    return [
        StockLine(sku, inventory.on_hand(sku), inventory.reserved(sku), inventory.available(sku))
        for sku in shop.catalog.skus()
    ]


def sales_text(report: DaySales) -> str:
    lines = [f"sales {report.day}"]
    for sku, qty in report.units.items():
        lines.append(f"  {sku:<12} {qty:>5}")
    lines.append(f"  invoiced  {format_cents(report.invoiced_cents):>10}")
    lines.append(f"  credited  {format_cents(report.credited_cents):>10}")
    lines.append(f"  net       {format_cents(report.net_cents):>10}")
    return "\n".join(lines) + "\n"
