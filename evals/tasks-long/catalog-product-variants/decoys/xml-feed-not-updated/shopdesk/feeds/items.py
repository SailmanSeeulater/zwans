"""The product feed the shopping-comparison sites read, as items common to both formats.

One item per variant of every active product, in product SKU order and then variant
order; `item_group_id` ties a product's variants together. `sale_price` is set when an
automatic discount (one that needs no code) lowers the price of a single unit today.
"""

from dataclasses import dataclass

from shopdesk.catalog.categories import CategoryTree
from shopdesk.catalog.products import ProductCatalog
from shopdesk.clock import Clock, day
from shopdesk.config import Settings
from shopdesk.models import Product, Variant
from shopdesk.money import format_money
from shopdesk.pricing.discounts import Discounts
from shopdesk.stock.ledger import StockLedger


@dataclass(frozen=True)
class FeedItem:
    id: str
    item_group_id: str
    title: str
    description: str
    link: str
    price: str
    sale_price: str | None
    availability: str  # "in stock" or "out of stock"
    gtin: str | None
    brand: str
    product_type: str
    options: tuple[tuple[str, str], ...] = ()

    @property
    def options_text(self) -> str:
        return ";".join(f"{name}={value}" for name, value in self.options)


class FeedBuilder:
    def __init__(
        self,
        catalog: ProductCatalog,
        categories: CategoryTree,
        discounts: Discounts,
        ledger: StockLedger,
        settings: Settings,
        clock: Clock,
    ) -> None:
        self._catalog = catalog
        self._categories = categories
        self._discounts = discounts
        self._ledger = ledger
        self._settings = settings
        self._clock = clock

    def items(self) -> list[FeedItem]:
        today = day(self._clock())
        return [
            self._item(product, variant, today)
            for product, variant in self._catalog.all_variants(active_only=True)
        ]

    def _item(self, product: Product, variant: Variant, today: str) -> FeedItem:
        currency = self._settings.currency
        price = product.price_of(variant)
        _, off = self._discounts.best_for_line(variant.sku, product, price, 1, None, today)
        in_stock = self._ledger.on_hand(variant.sku) > 0
        return FeedItem(
            id=variant.sku,
            item_group_id=product.sku,
            title=self._title(product.display_name(variant)),
            description=product.description or product.name,
            link=f"{self._settings.base_url.rstrip('/')}/p/{product.sku.lower()}",
            price=format_money(price, currency),
            sale_price=format_money(price - off, currency) if off else None,
            availability="in stock" if in_stock else "out of stock",
            gtin=variant.barcode,
            brand=product.brand,
            product_type=self._categories.breadcrumb(product.category) if product.category else "",
            options=tuple(sorted(variant.options.items())),
        )

    def _title(self, title: str) -> str:
        limit = self._settings.feed_title_limit
        if len(title) <= limit:
            return title
        cut = title[: limit - 1]
        if title[limit - 1] != " " and " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        return cut.rstrip() + "…"
