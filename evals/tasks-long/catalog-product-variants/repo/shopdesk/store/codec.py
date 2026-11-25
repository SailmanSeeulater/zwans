"""Turning ShopData into the JSON document in the data file and back.

Records are written as objects with every field. When reading, fields a record doesn't
have take their defaults and fields we don't know are ignored, so a file written by a
slightly newer or older release still opens.
"""

from dataclasses import asdict, fields
from typing import Any

from shopdesk.errors import StoreError
from shopdesk.models import (
    Alert,
    Allocation,
    AuditEntry,
    Cart,
    CartLine,
    Category,
    Discount,
    ImportRun,
    Invoice,
    InvoiceLine,
    Notification,
    Order,
    OrderLine,
    PriceList,
    Product,
    ShopData,
    StockMove,
    TaxLine,
    Warehouse,
)


def _take[T](cls: type[T], raw: dict[str, Any], **nested: Any) -> T:
    if not isinstance(raw, dict):
        raise StoreError(f"Expected an object for a {cls.__name__}, got {raw!r}.")
    known = {f.name for f in fields(cls)}  # type: ignore[arg-type]
    values = {k: v for k, v in raw.items() if k in known}
    values.update(nested)
    try:
        return cls(**values)
    except TypeError as exc:
        raise StoreError(f"Bad {cls.__name__} record: {exc}") from None


# -- encoding ----------------------------------------------------------------------------


def encode(data: ShopData) -> dict[str, Any]:
    return {
        "settings": data.settings,
        "counters": data.counters,
        "categories": [asdict(c) for c in data.categories.values()],
        "products": [asdict(p) for p in data.products.values()],
        "warehouses": [asdict(w) for w in data.warehouses.values()],
        "moves": [asdict(m) for m in data.moves],
        "alerts": [asdict(a) for a in data.alerts],
        "price_lists": [asdict(p) for p in data.price_lists.values()],
        "discounts": [asdict(d) for d in data.discounts.values()],
        "carts": [asdict(c) for c in data.carts.values()],
        "orders": [asdict(o) for o in data.orders.values()],
        "invoices": [asdict(i) for i in data.invoices.values()],
        "audit": [asdict(a) for a in data.audit],
        "imports": [asdict(i) for i in data.imports],
        "outbox": [asdict(n) for n in data.outbox],
    }


# -- decoding ----------------------------------------------------------------------------


def decode_product(raw: dict[str, Any]) -> Product:
    return _take(Product, raw)


def decode_cart(raw: dict[str, Any]) -> Cart:
    return _take(Cart, raw, lines=[_take(CartLine, line) for line in raw.get("lines", [])])


def decode_order_line(raw: dict[str, Any]) -> OrderLine:
    allocations = [_take(Allocation, a) for a in raw.get("allocations", [])]
    return _take(OrderLine, raw, allocations=allocations)


def decode_order(raw: dict[str, Any]) -> Order:
    return _take(Order, raw, lines=[decode_order_line(line) for line in raw.get("lines", [])])


def decode_invoice(raw: dict[str, Any]) -> Invoice:
    return _take(
        Invoice,
        raw,
        lines=[_take(InvoiceLine, line) for line in raw.get("lines", [])],
        taxes=[_take(TaxLine, t) for t in raw.get("taxes", [])],
    )


def decode(raw: dict[str, Any]) -> ShopData:
    data = ShopData()
    data.settings = dict(raw.get("settings", {}))
    data.counters = {str(k): int(v) for k, v in raw.get("counters", {}).items()}
    for item in raw.get("categories", []):
        category = _take(Category, item)
        data.categories[category.slug] = category
    for item in raw.get("products", []):
        product = decode_product(item)
        data.products[product.sku] = product
    for item in raw.get("warehouses", []):
        warehouse = _take(Warehouse, item)
        data.warehouses[warehouse.code] = warehouse
    data.moves = [_take(StockMove, m) for m in raw.get("moves", [])]
    data.alerts = [_take(Alert, a) for a in raw.get("alerts", [])]
    for item in raw.get("price_lists", []):
        price_list = _take(PriceList, item)
        data.price_lists[price_list.name] = price_list
    for item in raw.get("discounts", []):
        discount = _take(Discount, item)
        data.discounts[discount.code] = discount
    for item in raw.get("carts", []):
        cart = decode_cart(item)
        data.carts[cart.id] = cart
    for item in raw.get("orders", []):
        order = decode_order(item)
        data.orders[order.number] = order
    for item in raw.get("invoices", []):
        invoice = decode_invoice(item)
        data.invoices[invoice.number] = invoice
    data.audit = [_take(AuditEntry, a) for a in raw.get("audit", [])]
    data.imports = [_take(ImportRun, i) for i in raw.get("imports", [])]
    data.outbox = [_take(Notification, n) for n in raw.get("outbox", [])]
    _check(data)
    return data


def _check(data: ShopData) -> None:
    """Catch files edited by hand into something the services would trip over."""
    for move in data.moves:
        if move.warehouse not in data.warehouses:
            raise StoreError(f"Stock move {move.id} names unknown warehouse {move.warehouse}.")
    for product in data.products.values():
        if product.category is not None and product.category not in data.categories:
            raise StoreError(f"{product.sku} is in unknown category {product.category}.")
