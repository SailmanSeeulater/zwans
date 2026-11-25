"""Stock reports: what's where, what's running low, and what it's all worth."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shopdesk.shop import Shop


@dataclass(frozen=True)
class StockRow:
    sku: str
    name: str
    warehouses: dict[str, int]
    total: int
    reorder_level: int

    @property
    def low(self) -> bool:
        return self.reorder_level > 0 and self.total <= self.reorder_level


@dataclass(frozen=True)
class ValuationRow:
    sku: str
    name: str
    units: int
    cost: int

    @property
    def value(self) -> int:
        return self.units * self.cost


def stock_report(shop: "Shop", *, include_inactive: bool = False, low_only: bool = False) -> list[StockRow]:
    """One row per variant, with its stock in every warehouse."""
    rows = []
    for product, variant in shop.catalog.all_variants(active_only=not include_inactive):
        by_warehouse = shop.ledger.by_warehouse(variant.sku)
        row = StockRow(
            sku=variant.sku,
            name=product.display_name(variant),
            warehouses=by_warehouse,
            total=sum(by_warehouse.values()),
            reorder_level=product.reorder_level_of(variant),
        )
        if row.low or not low_only:
            rows.append(row)
    return rows


def valuation(shop: "Shop") -> tuple[list[ValuationRow], int]:
    """Stock at cost, one row per product that has any (all its variants together); and
    the grand total."""
    rows = []
    for product in shop.catalog.all():
        units = shop.ledger.on_hand(product.sku)
        if units:
            rows.append(ValuationRow(product.sku, product.name, units, product.cost))
    return rows, sum(r.value for r in rows)
