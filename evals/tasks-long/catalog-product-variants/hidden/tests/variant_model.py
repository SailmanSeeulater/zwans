"""A small reference model of the variant rules in the README, for the random scenarios.

It knows nothing of shopdesk's code: products and variants, stock per warehouse, picking
in warehouse order, prices with overrides, one automatic 10% product discount, orders and
cancellations, and the alert rule.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

WAREHOUSES = ("WA", "WB")


def percent_of(cents: int, percent: int) -> int:
    return int((Decimal(cents) * percent / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass
class MVariant:
    sku: str
    product: str
    options: dict[str, str]
    price: int | None = None
    reorder: int | None = None
    stock: dict[str, int] = field(default_factory=lambda: dict.fromkeys(WAREHOUSES, 0))

    @property
    def total(self) -> int:
        return sum(self.stock.values())


@dataclass
class MProduct:
    sku: str
    name: str
    price: int
    cost: int
    reorder: int
    discount: int = 0  # percent, automatic
    variants: list[str] = field(default_factory=list)


@dataclass
class MLine:
    sku: str
    product: str
    name: str
    qty: int
    net: int
    picks: list[tuple[str, int]]


@dataclass
class MOrder:
    number: str
    lines: list[MLine]
    status: str = "placed"


class Model:
    def __init__(self) -> None:
        self.products: dict[str, MProduct] = {}
        self.variants: dict[str, MVariant] = {}
        self.orders: dict[str, MOrder] = {}

    # -- rules -----------------------------------------------------------------------

    def price(self, sku: str) -> int:
        v = self.variants[sku]
        return self.products[v.product].price if v.price is None else v.price

    def level(self, sku: str) -> int:
        v = self.variants[sku]
        return self.products[v.product].reorder if v.reorder is None else v.reorder

    def name(self, sku: str) -> str:
        v = self.variants[sku]
        base = self.products[v.product].name
        if not v.options:
            return base
        return f"{base} (" + ", ".join(f"{k}: {x}" for k, x in sorted(v.options.items())) + ")"

    def open_alerts(self) -> set[str]:
        return {s for s, v in self.variants.items() if self.level(s) > 0 and v.total <= self.level(s)}

    # -- operations ------------------------------------------------------------------

    def add_product(self, product: MProduct) -> None:
        self.products[product.sku] = product

    def add_variant(self, variant: MVariant) -> None:
        self.variants[variant.sku] = variant
        self.products[variant.product].variants.append(variant.sku)

    def receive(self, sku: str, warehouse: str, qty: int) -> None:
        self.variants[sku].stock[warehouse] += qty

    def transfer(self, sku: str, source: str, target: str, qty: int) -> None:
        stock = self.variants[sku].stock
        assert stock[source] >= qty
        stock[source] -= qty
        stock[target] += qty

    def can_sell(self, lines: list[tuple[str, int]]) -> bool:
        return all(self.variants[sku].total >= qty for sku, qty in lines)

    def sell(self, number: str, lines: list[tuple[str, int]]) -> None:
        order_lines = []
        for sku, qty in lines:
            v = self.variants[sku]
            product = self.products[v.product]
            gross = self.price(sku) * qty
            off = percent_of(gross, product.discount) if product.discount else 0
            picks = []
            wanted = qty
            for warehouse in WAREHOUSES:
                take = min(wanted, v.stock[warehouse])
                if take:
                    v.stock[warehouse] -= take
                    picks.append((warehouse, take))
                    wanted -= take
            order_lines.append(MLine(sku, v.product, self.name(sku), qty, gross - off, picks))
        self.orders[number] = MOrder(number, order_lines)

    def cancel(self, number: str) -> None:
        order = self.orders[number]
        for line in order.lines:
            for warehouse, qty in line.picks:
                self.variants[line.sku].stock[warehouse] += qty
        order.status = "cancelled"

    # -- views -----------------------------------------------------------------------

    def sales(self, by_variant: bool) -> dict[str, tuple[int, int, int]]:
        units: dict[str, int] = {}
        revenue: dict[str, int] = {}
        orders: dict[str, set[str]] = {}
        for order in self.orders.values():
            if order.status == "cancelled":
                continue
            for line in order.lines:
                key = line.sku if by_variant else line.product
                units[key] = units.get(key, 0) + line.qty
                revenue[key] = revenue.get(key, 0) + line.net
                orders.setdefault(key, set()).add(order.number)
        return {k: (units[k], revenue[k], len(orders[k])) for k in units}

    def feed(self) -> list[tuple[str, str, int, bool]]:
        rows = []
        for product_sku in sorted(self.products):
            for sku in self.products[product_sku].variants:
                rows.append((sku, product_sku, self.price(sku), self.variants[sku].total > 0))
        return rows

    def valuation(self) -> int:
        return sum(
            p.cost * sum(self.variants[s].total for s in p.variants) for p in self.products.values()
        )

    def in_stock_products(self) -> set[str]:
        return {
            p.sku for p in self.products.values() if any(self.variants[s].total for s in p.variants)
        }
