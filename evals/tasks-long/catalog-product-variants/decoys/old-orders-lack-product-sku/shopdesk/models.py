"""The records shopdesk keeps. Plain dataclasses: the services own the rules, the store
owns the file format. Money is in cents."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Category:
    slug: str
    name: str
    parent: str | None = None


@dataclass
class Variant:
    """One sellable, stockable version of a product (a size, a colour...)."""

    sku: str
    options: dict[str, str] = field(default_factory=dict)
    price: int | None = None  # None: the product's price
    barcode: str | None = None
    reorder_level: int | None = None  # None: the product's reorder level


@dataclass
class Product:
    sku: str
    name: str
    price: int
    category: str | None = None
    brand: str = ""
    tax_class: str = "standard"
    cost: int = 0
    reorder_level: int = 0
    description: str = ""
    supplier: str | None = None
    supplier_ref: str | None = None
    active: bool = True
    created_at: str = ""
    variants: list[Variant] = field(default_factory=list)

    def find_variant(self, sku: str) -> Variant | None:
        for variant in self.variants:
            if variant.sku == sku:
                return variant
        return None

    def price_of(self, variant: Variant) -> int:
        return self.price if variant.price is None else variant.price

    def reorder_level_of(self, variant: Variant) -> int:
        return self.reorder_level if variant.reorder_level is None else variant.reorder_level

    def display_name(self, variant: Variant) -> str:
        """"Logo tee (colour: red, size: M)"; just the name for a variant without options."""
        if not variant.options:
            return self.name
        options = ", ".join(f"{k}: {v}" for k, v in sorted(variant.options.items()))
        return f"{self.name} ({options})"


@dataclass
class Warehouse:
    code: str
    name: str
    priority: int = 0


@dataclass
class StockMove:
    id: int
    at: str
    sku: str
    warehouse: str
    qty: int  # positive in, negative out
    reason: str  # receive, sale, return, adjust, count, transfer, opening
    ref: str = ""


@dataclass
class Alert:
    id: int
    sku: str
    raised_at: str
    stock: int
    reorder_level: int
    cleared_at: str | None = None

    @property
    def is_open(self) -> bool:
        return self.cleared_at is None


@dataclass
class PriceList:
    name: str
    entries: dict[str, int] = field(default_factory=dict)


@dataclass
class Discount:
    code: str
    kind: str  # "percent" or "amount" (cents off each unit)
    value: int
    target_kind: str = "all"  # "all", "category" or "product"
    target: str | None = None
    min_qty: int = 1
    auto: bool = False  # applies without the code being entered
    starts: str | None = None  # first day, inclusive
    ends: str | None = None  # last day, inclusive
    active: bool = True


@dataclass
class CartLine:
    sku: str
    qty: int


@dataclass
class Cart:
    id: str
    created_at: str
    price_list: str | None = None
    code: str | None = None
    lines: list[CartLine] = field(default_factory=list)


@dataclass
class Allocation:
    warehouse: str
    qty: int


@dataclass
class OrderLine:
    sku: str
    name: str
    qty: int
    unit_price: int
    discount: int = 0
    allocations: list[Allocation] = field(default_factory=list)
    product_sku: str = ""

    @property
    def gross(self) -> int:
        return self.unit_price * self.qty

    @property
    def net(self) -> int:
        return self.gross - self.discount


@dataclass
class Order:
    number: str
    placed_at: str
    customer: str
    lines: list[OrderLine]
    status: str = "placed"  # placed, invoiced, cancelled
    price_list: str | None = None
    code: str | None = None
    invoice: str | None = None
    cancelled_at: str | None = None

    @property
    def total(self) -> int:
        return sum(line.net for line in self.lines)

    @property
    def units(self) -> int:
        return sum(line.qty for line in self.lines)


@dataclass
class InvoiceLine:
    sku: str
    gtin: str | None
    description: str
    qty: int
    unit_price: int
    discount: int
    tax_class: str
    product_sku: str = ""

    @property
    def net(self) -> int:
        return self.unit_price * self.qty - self.discount


@dataclass
class TaxLine:
    tax_class: str
    rate: str  # e.g. "0.20"
    net: int
    tax: int


@dataclass
class Invoice:
    number: str
    order: str
    issued_at: str
    customer: str
    lines: list[InvoiceLine]
    taxes: list[TaxLine]

    @property
    def net_total(self) -> int:
        return sum(line.net for line in self.lines)

    @property
    def tax_total(self) -> int:
        return sum(t.tax for t in self.taxes)

    @property
    def gross_total(self) -> int:
        return self.net_total + self.tax_total


@dataclass
class AuditEntry:
    at: str
    action: str
    subject: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImportRun:
    at: str
    supplier: str
    created: int
    updated: int
    unchanged: int
    errors: int


@dataclass
class Notification:
    id: int
    at: str
    topic: str
    payload: dict[str, Any]
    sent_at: str | None = None


@dataclass
class ShopData:
    """Everything in one shop's file."""

    products: dict[str, Product] = field(default_factory=dict)
    categories: dict[str, Category] = field(default_factory=dict)
    warehouses: dict[str, Warehouse] = field(default_factory=dict)
    moves: list[StockMove] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    price_lists: dict[str, PriceList] = field(default_factory=dict)
    discounts: dict[str, Discount] = field(default_factory=dict)
    carts: dict[str, Cart] = field(default_factory=dict)
    orders: dict[str, Order] = field(default_factory=dict)
    invoices: dict[str, Invoice] = field(default_factory=dict)
    audit: list[AuditEntry] = field(default_factory=list)
    imports: list[ImportRun] = field(default_factory=list)
    outbox: list[Notification] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)

    def next_id(self, series: str) -> int:
        self.counters[series] = self.counters.get(series, 0) + 1
        return self.counters[series]
