"""What a SKU costs: its price (or its price list's price) and the best discount."""

from dataclasses import dataclass

from shopdesk.catalog.products import ProductCatalog
from shopdesk.pricing.discounts import Discounts
from shopdesk.pricing.pricelists import PriceLists


@dataclass(frozen=True)
class PricedLine:
    sku: str
    qty: int
    unit_price: int
    discount: int
    discount_code: str | None

    @property
    def gross(self) -> int:
        return self.unit_price * self.qty

    @property
    def net(self) -> int:
        return self.gross - self.discount


class PriceEngine:
    def __init__(
        self, catalog: ProductCatalog, price_lists: PriceLists, discounts: Discounts
    ) -> None:
        self._catalog = catalog
        self._price_lists = price_lists
        self._discounts = discounts

    def unit_price(self, sku: str, price_list: str | None = None) -> int:
        product = self._catalog.get(sku)
        listed = self._price_lists.lookup(price_list, product.sku)
        return product.price if listed is None else listed

    def price_line(
        self,
        sku: str,
        qty: int,
        price_list: str | None = None,
        code: str | None = None,
        today: str | None = None,
    ) -> PricedLine:
        line_sku = sku.strip().upper()
        product = self._catalog.get(line_sku)
        unit = self.unit_price(line_sku, price_list)
        discount, off = self._discounts.best_for_line(line_sku, product, unit, qty, code, today)
        return PricedLine(line_sku, qty, unit, off, discount.code if discount else None)
