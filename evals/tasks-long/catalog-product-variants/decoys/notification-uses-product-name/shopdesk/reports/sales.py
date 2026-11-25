"""Sales reports, read straight from the orders. Cancelled orders don't count; invoiced
and merely placed ones do. Revenue is net of discounts and before tax. Dates are the
day the order was placed, both ends inclusive."""

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from shopdesk.clock import day, in_range
from shopdesk.errors import UnknownSku
from shopdesk.models import Order, OrderLine

if TYPE_CHECKING:
    from shopdesk.shop import Shop


@dataclass(frozen=True)
class SalesRow:
    sku: str
    name: str
    units: int
    revenue: int
    orders: int


@dataclass(frozen=True)
class CategoryRow:
    category: str
    name: str
    units: int
    revenue: int


@dataclass(frozen=True)
class DayRow:
    day: str
    orders: int
    units: int
    revenue: int


def counted_orders(shop: "Shop", start: str | None, end: str | None) -> Iterator[Order]:
    for order in shop.orders():
        if order.status != "cancelled" and in_range(order.placed_at, start, end):
            yield order


def sales_report(
    shop: "Shop",
    start: str | None = None,
    end: str | None = None,
    *,
    by_variant: bool = False,
) -> list[SalesRow]:
    """One row per product sold (all its variants together), or with `by_variant` one
    row per variant SKU; best sellers (by revenue) first."""
    units: dict[str, int] = defaultdict(int)
    revenue: dict[str, int] = defaultdict(int)
    orders: dict[str, set[str]] = defaultdict(set)
    names: dict[str, str] = {}
    for order in counted_orders(shop, start, end):
        for line in order.lines:
            key = line.sku if by_variant else line.product_sku
            units[key] += line.qty
            revenue[key] += line.net
            orders[key].add(order.number)
            names.setdefault(key, line.name if by_variant else _product_name(shop, line))
    rows = [
        SalesRow(sku, names[sku], units[sku], revenue[sku], len(orders[sku])) for sku in units
    ]
    rows.sort(key=lambda r: (-r.revenue, r.sku))
    return rows


def _product_name(shop: "Shop", line: OrderLine) -> str:
    try:
        return shop.catalog.get(line.product_sku).name
    except UnknownSku:
        return line.name


def _category_of(shop: "Shop", line: OrderLine) -> str | None:
    try:
        return shop.catalog.get(line.product_sku).category
    except UnknownSku:
        return None


def category_report(shop: "Shop", start: str | None = None, end: str | None = None) -> list[CategoryRow]:
    """Sales per top-level category; products without a category under "(none)"."""
    units: dict[str, int] = defaultdict(int)
    revenue: dict[str, int] = defaultdict(int)
    for order in counted_orders(shop, start, end):
        for line in order.lines:
            slug = _category_of(shop, line)
            top = shop.categories.path(slug)[0].slug if slug else "(none)"
            units[top] += line.qty
            revenue[top] += line.net
    rows = []
    for slug in units:
        name = shop.categories.get(slug).name if slug != "(none)" else "(none)"
        rows.append(CategoryRow(slug, name, units[slug], revenue[slug]))
    rows.sort(key=lambda r: (-r.revenue, r.category))
    return rows


def daily_report(shop: "Shop", start: str | None = None, end: str | None = None) -> list[DayRow]:
    per_day: dict[str, list[Order]] = defaultdict(list)
    for order in counted_orders(shop, start, end):
        per_day[day(order.placed_at)].append(order)
    return [
        DayRow(
            date,
            len(orders),
            sum(o.units for o in orders),
            sum(o.total for o in orders),
        )
        for date, orders in sorted(per_day.items())
    ]


def totals(rows: list[SalesRow]) -> tuple[int, int]:
    return sum(r.units for r in rows), sum(r.revenue for r in rows)
