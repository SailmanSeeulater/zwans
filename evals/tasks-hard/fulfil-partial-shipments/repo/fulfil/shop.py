"""The shop: the one place orders, stock and billing change together.

    shop = Shop()
    shop.add_product("MUG-01", "Blue mug", 950)
    shop.receive("MUG-01", 20)
    order = shop.place_order("alice", {"MUG-01": 2}, coupon="SPRING15")
    invoice = shop.ship(order.id)

Every method either does everything it should or raises a FulfilError and changes nothing.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from .billing import CreditNote, Invoice, credit_amount, invoice_for_order
from .catalog import Catalog, coupon_percent
from .errors import InvalidRequest, InvalidState, OutOfStock, UnknownOrder
from .inventory import Inventory
from .orders import Order, OrderLine

SHIPPING_CENTS = 495  # flat, per order


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Shop:
    def __init__(self, clock: Callable[[], str] = utc_now) -> None:
        self.clock = clock
        self.catalog = Catalog()
        self.inventory = Inventory()
        self.orders: dict[str, Order] = {}
        self.invoices: list[Invoice] = []
        self.credit_notes: list[CreditNote] = []

    # --------------------------------------------------------------- stock

    def add_product(self, sku: str, name: str, price_cents: int) -> None:
        self.catalog.add(sku, name, price_cents)

    def receive(self, sku: str, qty: int) -> None:
        self.catalog.get(sku)
        self.inventory.receive(sku, qty, self.clock())

    # -------------------------------------------------------------- orders

    def order(self, order_id: str) -> Order:
        try:
            return self.orders[order_id]
        except KeyError:
            raise UnknownOrder(f"no order {order_id}") from None

    def place_order(self, customer: str, items: dict[str, int], coupon: str | None = None) -> Order:
        """Place an order and reserve its stock. All of it must be available."""
        if not customer.strip():
            raise InvalidRequest("an order needs a customer")
        if not items:
            raise InvalidRequest("an order needs at least one item")
        percent = coupon_percent(coupon)
        lines = []
        for sku, qty in items.items():
            product = self.catalog.get(sku)
            if qty <= 0:
                raise InvalidRequest(f"{sku}: quantities must be more than zero")
            if qty > self.inventory.available(sku):
                raise OutOfStock(
                    f"only {self.inventory.available(sku)} of {sku} available, {qty} wanted"
                )
            lines.append(OrderLine(sku, qty, product.price_cents))
        for line in lines:
            self.inventory.reserve(line.sku, line.qty)
        order = Order(
            id=f"SO-{len(self.orders) + 1:04d}",
            customer=customer.strip(),
            lines=lines,
            discount_percent=percent,
            shipping_cents=SHIPPING_CENTS,
            placed_at=self.clock(),
        )
        self.orders[order.id] = order
        return order

    def ship(self, order_id: str) -> Invoice:
        """Ship the order and invoice it."""
        order = self.order(order_id)
        if order.status != "placed":
            raise InvalidState(f"{order_id} is {order.status}; only placed orders can ship")
        at = self.clock()
        for line in order.lines:
            self.inventory.ship(line.sku, line.qty, at)
        invoice = invoice_for_order(order, f"INV-{len(self.invoices) + 1:05d}", at)
        self.invoices.append(invoice)
        order.status = "shipped"
        order.shipped_at = at
        return invoice

    def cancel(self, order_id: str) -> None:
        order = self.order(order_id)
        if order.status != "placed":
            raise InvalidState(f"{order_id} is {order.status}; only placed orders can be cancelled")
        for line in order.lines:
            self.inventory.release(line.sku, line.qty)
        order.status = "cancelled"
        order.cancelled_at = self.clock()

    # ------------------------------------------------------------- returns

    def returned(self, order_id: str, sku: str) -> int:
        return sum(
            note.qty for note in self.credit_notes if note.order_id == order_id and note.sku == sku
        )

    def return_items(self, order_id: str, sku: str, qty: int) -> CreditNote:
        """The customer sent shipped goods back: restock them and credit the customer."""
        order = self.order(order_id)
        if order.status != "shipped":
            raise InvalidState(f"{order_id} is {order.status}; only shipped goods can be returned")
        line = order.line(sku)
        if line is None:
            raise InvalidRequest(f"{sku} is not on {order_id}")
        if qty <= 0:
            raise InvalidRequest("quantities must be more than zero")
        returnable = line.qty - self.returned(order_id, sku)
        if qty > returnable:
            raise InvalidRequest(f"only {returnable} of {sku} can still be returned on {order_id}")

        returned_before = sum(
            note.qty * order.line(note.sku).unit_price_cents
            for note in self.credit_notes
            if note.order_id == order_id
        )
        amount = credit_amount(order, returned_before, qty * line.unit_price_cents)
        at = self.clock()
        self.inventory.restock(sku, qty, at)
        note = CreditNote(f"CN-{len(self.credit_notes) + 1:05d}", order_id, at, sku, qty, amount)
        self.credit_notes.append(note)
        return note

    # ------------------------------------------------------------- lookups

    def invoices_for(self, order_id: str) -> list[Invoice]:
        return [invoice for invoice in self.invoices if invoice.order_id == order_id]

    def credit_notes_for(self, order_id: str) -> list[CreditNote]:
        return [note for note in self.credit_notes if note.order_id == order_id]
