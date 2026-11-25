"""The inventory and orders domain. Importing it registers its events and upcasters."""

from stockflow.domain import events, upcasters  # noqa: F401  (registration)
from stockflow.domain.inventory import StockItem
from stockflow.domain.orders import CANCELLED, CONFIRMED, DRAFT, SHIPPED, Order

__all__ = ["CANCELLED", "CONFIRMED", "DRAFT", "SHIPPED", "Order", "StockItem"]
