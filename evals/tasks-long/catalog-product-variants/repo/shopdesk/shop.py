"""The Shop: one object wiring the services together over one ShopData.

Library users and the CLI go through it. The services are reachable as attributes
(`shop.catalog`, `shop.ledger`, ...) for the reports; the methods here are the supported
way to change things.
"""

from pathlib import Path
from typing import Any

from shopdesk.audit import AuditLog
from shopdesk.catalog.categories import CategoryTree
from shopdesk.catalog.products import ProductCatalog
from shopdesk.clock import Clock, day, utc_now
from shopdesk.config import Settings
from shopdesk.events import EventBus
from shopdesk.feeds.csvfeed import render_csv
from shopdesk.feeds.items import FeedBuilder, FeedItem
from shopdesk.feeds.xmlfeed import render_xml
from shopdesk.importers.supplier import ImportResult, SupplierImporter
from shopdesk.models import (
    Alert,
    Category,
    Discount,
    Invoice,
    Notification,
    Order,
    Product,
    ShopData,
    StockMove,
    Warehouse,
)
from shopdesk.notify import Notifier
from shopdesk.pricing.discounts import Discounts
from shopdesk.pricing.engine import PriceEngine
from shopdesk.pricing.pricelists import PriceLists
from shopdesk.sales.carts import Carts, CartView
from shopdesk.sales.invoices import Invoicing
from shopdesk.sales.orders import OrderDesk
from shopdesk.search.index import SearchResult, SearchService
from shopdesk.stock.alerts import LowStockMonitor
from shopdesk.stock.ledger import StockLedger
from shopdesk.stock.warehouses import Warehouses
from shopdesk.store.jsonstore import JsonStore


class Shop:
    def __init__(self, data: ShopData | None = None, *, clock: Clock = utc_now) -> None:
        self.data = data if data is not None else ShopData()
        self.clock = clock
        self.settings = Settings.from_dict(self.data.settings)
        self.bus = EventBus()
        self.store: JsonStore | None = None

        self.categories = CategoryTree(self.data, self.bus)
        self.catalog = ProductCatalog(self.data, self.categories, self.bus, clock)
        self.price_lists = PriceLists(self.data, self.catalog, self.bus)
        self.discounts = Discounts(self.data, self.catalog, self.categories, self.bus, clock)
        self.engine = PriceEngine(self.catalog, self.price_lists, self.discounts)
        self.warehouses = Warehouses(self.data, self.bus)
        self.ledger = StockLedger(self.data, self.catalog, self.warehouses, self.bus, clock)
        self.monitor = LowStockMonitor(self.data, self.catalog, self.ledger, self.bus, clock)
        self.carts = Carts(
            self.data,
            self.catalog,
            self.price_lists,
            self.discounts,
            self.engine,
            self.bus,
            clock,
        )
        self.order_desk = OrderDesk(
            self.data,
            self.catalog,
            self.carts,
            self.ledger,
            self.warehouses,
            self.settings,
            self.bus,
            clock,
        )
        self.invoicing = Invoicing(
            self.data, self.catalog, self.order_desk, self.settings, self.bus, clock
        )
        self.search_service = SearchService(
            self.catalog, self.categories, self.ledger, self.settings, self.bus
        )
        self.feed = FeedBuilder(
            self.catalog, self.categories, self.discounts, self.ledger, self.settings, clock
        )
        self.importer = SupplierImporter(
            self.data, self.catalog, self.categories, self.bus, clock
        )
        self.notifier = Notifier(
            self.data, self.catalog, self.ledger, self.settings, self.bus, clock
        )
        self.audit = AuditLog(self.data, self.bus, clock)

        self.monitor.attach()
        self.search_service.attach()
        self.notifier.attach()
        self.audit.attach()

    # -- files -------------------------------------------------------------------------

    @classmethod
    def open(cls, path: str | Path, *, clock: Clock = utc_now) -> "Shop":
        store = JsonStore(path, clock)
        shop = cls(store.load(), clock=clock)
        shop.store = store
        return shop

    def save(self, path: str | Path | None = None) -> None:
        if path is not None:
            self.store = JsonStore(path, self.clock)
        if self.store is None:
            raise ValueError("This shop has no file; pass a path.")
        self.data.settings = self.settings.to_dict()
        self.store.save(self.data)

    # -- catalog -----------------------------------------------------------------------

    def add_category(self, slug: str, name: str, parent: str | None = None) -> Category:
        return self.categories.add(slug, name, parent)

    def add_product(self, sku: str, name: str, price: int, **details: Any) -> Product:
        return self.catalog.add(sku, name, price, **details)

    def update_product(self, sku: str, **changes: Any) -> Product:
        return self.catalog.update(sku, **changes)

    def product(self, sku: str) -> Product:
        return self.catalog.get(sku)

    def products(self, *, active_only: bool = False) -> list[Product]:
        return self.catalog.all(active_only=active_only)

    def lookup_barcode(self, barcode: str) -> str:
        """The SKU that carries this barcode."""
        return self.catalog.by_barcode(barcode).sku

    # -- prices ------------------------------------------------------------------------

    def set_list_price(self, price_list: str, sku: str, price: int) -> None:
        self.price_lists.set_price(price_list, sku, price)

    def add_discount(self, code: str, kind: str, value: int, **options: Any) -> Discount:
        return self.discounts.add(code, kind, value, **options)

    def price_of(self, sku: str, price_list: str | None = None) -> int:
        return self.engine.unit_price(sku, price_list)

    # -- stock -------------------------------------------------------------------------

    def add_warehouse(self, code: str, name: str, priority: int = 0) -> Warehouse:
        return self.warehouses.add(code, name, priority)

    def receive(self, sku: str, warehouse: str, qty: int, ref: str = "") -> StockMove:
        return self.ledger.receive(sku, warehouse, qty, ref)

    def adjust(self, sku: str, warehouse: str, qty: int, ref: str = "") -> StockMove:
        return self.ledger.adjust(sku, warehouse, qty, ref)

    def count(self, sku: str, warehouse: str, counted: int) -> StockMove | None:
        return self.ledger.count(sku, warehouse, counted)

    def transfer(self, sku: str, source: str, target: str, qty: int) -> str:
        return self.ledger.transfer(sku, source, target, qty)

    def stock(self, sku: str, warehouse: str | None = None) -> int:
        self.catalog.get(sku)
        return self.ledger.on_hand(sku, warehouse)

    def alerts(self, *, open_only: bool = True) -> list[Alert]:
        return self.monitor.alerts(open_only=open_only)

    # -- sales -------------------------------------------------------------------------

    def new_cart(self, price_list: str | None = None) -> str:
        return self.carts.create(price_list).id

    def cart_add(self, cart_id: str, sku: str, qty: int = 1) -> None:
        self.carts.add(cart_id, sku, qty)

    def cart_set(self, cart_id: str, sku: str, qty: int) -> None:
        self.carts.set_qty(cart_id, sku, qty)

    def cart_code(self, cart_id: str, code: str | None) -> None:
        self.carts.apply_code(cart_id, code)

    def cart(self, cart_id: str) -> CartView:
        return self.carts.view(cart_id, day(self.clock()))

    def checkout(self, cart_id: str, customer: str, warehouse: str | None = None) -> Order:
        return self.order_desk.checkout(cart_id, customer, warehouse)

    def cancel_order(self, number: str) -> Order:
        return self.order_desk.cancel(number)

    def order(self, number: str) -> Order:
        return self.order_desk.get(number)

    def orders(self, status: str | None = None) -> list[Order]:
        return self.order_desk.all(status)

    def invoice_order(self, number: str) -> Invoice:
        return self.invoicing.issue(number)

    def invoice(self, number: str) -> Invoice:
        return self.invoicing.get(number)

    # -- search, feeds, imports, notifications -----------------------------------------

    def search(self, text: str = "", **filters: Any) -> SearchResult:
        return self.search_service.search(text, **filters)

    def feed_items(self) -> list[FeedItem]:
        return self.feed.items()

    def feed_xml(self) -> str:
        return render_xml(self.feed.items(), self.settings.shop_name, self.clock())

    def feed_csv(self) -> str:
        return render_csv(self.feed.items())

    def import_supplier(self, text: str, supplier: str, **options: Any) -> ImportResult:
        return self.importer.run(text, supplier, **options)

    def outbox(self, *, pending_only: bool = True) -> list[Notification]:
        return self.notifier.pending() if pending_only else self.notifier.all()
