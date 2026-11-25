"""The commands the CLI (and anything else) runs. Each one loads what it needs, checks every
rule before saving anything, and saves each aggregate it changed once."""

from collections.abc import Iterable

from stockflow.domain.inventory import StockItem
from stockflow.domain.orders import CONFIRMED, Order
from stockflow.errors import DomainError
from stockflow.repository import Repository


class Inventory:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    # -- items

    def register_item(self, sku: str, name: str, reorder_level: int | None = None) -> StockItem:
        if self.repository.exists(StockItem, sku):
            raise DomainError(f"{sku} is already registered")
        if reorder_level is None:
            reorder_level = self.repository.settings.default_reorder_level
        item = StockItem(sku)
        item.register(name, reorder_level)
        self.repository.save(item)
        return item

    def receive(self, sku: str, quantity: int, lot: str) -> StockItem:
        item = self._item(sku)
        item.receive(quantity, lot)
        self.repository.save(item)
        return item

    def adjust(self, sku: str, delta: int, reason: str) -> StockItem:
        item = self._item(sku)
        item.adjust(delta, reason)
        self.repository.save(item)
        return item

    def item(self, sku: str) -> StockItem:
        return self._item(sku)

    # -- orders

    def place_order(
        self, order_id: str, customer: str, lines: Iterable[tuple[str, int, int]] = ()
    ) -> Order:
        """A new draft order, with any first lines (sku, quantity, unit price in cents) saved
        along with it."""
        if self.repository.exists(Order, order_id):
            raise DomainError(f"order {order_id} already exists")
        order = Order(order_id)
        order.place(customer)
        for sku, quantity, price in lines:
            self._item(sku)
            order.add_line(sku, quantity, price)
        self.repository.save(order)
        return order

    def add_line(self, order_id: str, sku: str, quantity: int, unit_price_cents: int) -> Order:
        order = self._order(order_id)
        self._item(sku)  # the SKU must exist
        order.add_line(sku, quantity, unit_price_cents)
        self.repository.save(order)
        return order

    def remove_line(self, order_id: str, sku: str) -> Order:
        order = self._order(order_id)
        order.remove_line(sku)
        self.repository.save(order)
        return order

    def confirm_order(self, order_id: str) -> Order:
        """Reserve every line's stock and confirm the order, or change nothing."""
        order = self._order(order_id)
        order.confirm()
        items = {sku: self._item(sku) for sku in order.lines}
        short = [
            f"{sku} ({items[sku].available} available, {line['quantity']} wanted)"
            for sku, line in order.lines.items()
            if items[sku].available < line["quantity"]
        ]
        if short:
            raise DomainError(f"not enough stock for order {order_id}: {', '.join(short)}")
        for sku, line in order.lines.items():
            items[sku].reserve(order_id, line["quantity"])
        for item in items.values():
            self.repository.save(item)
        self.repository.save(order)
        return order

    def cancel_order(self, order_id: str, reason: str = "") -> Order:
        order = self._order(order_id)
        was_confirmed = order.status == CONFIRMED
        order.cancel(reason)
        if was_confirmed:
            items = [self._item(sku) for sku in order.lines]
            for item in items:
                item.release(order_id)
            for item in items:
                self.repository.save(item)
        self.repository.save(order)
        return order

    def ship_order(self, order_id: str) -> Order:
        order = self._order(order_id)
        order.ship()
        items = [self._item(sku) for sku in order.lines]
        for item in items:
            item.ship(order_id)
        for item in items:
            self.repository.save(item)
        self.repository.save(order)
        return order

    def order(self, order_id: str) -> Order:
        return self._order(order_id)

    # -- loading

    def _item(self, sku: str) -> StockItem:
        if not self.repository.exists(StockItem, sku):
            raise DomainError(f"unknown item {sku}")
        return self.repository.load(StockItem, sku)

    def _order(self, order_id: str) -> Order:
        if not self.repository.exists(Order, order_id):
            raise DomainError(f"unknown order {order_id}")
        return self.repository.load(Order, order_id)
