"""The domain's events, in their current schemas. Older schemas: see upcasters.py."""

from dataclasses import dataclass

from stockflow.events import event_type

# -- stock items (stream "item-<sku>")


@event_type("ItemRegistered")
@dataclass(frozen=True)
class ItemRegistered:
    sku: str
    name: str
    reorder_level: int


@event_type("StockReceived", version=2)
@dataclass(frozen=True)
class StockReceived:
    quantity: int
    lot: str


@event_type("StockReserved")
@dataclass(frozen=True)
class StockReserved:
    order_id: str
    quantity: int


@event_type("ReservationReleased")
@dataclass(frozen=True)
class ReservationReleased:
    order_id: str


@event_type("StockShipped")
@dataclass(frozen=True)
class StockShipped:
    order_id: str


@event_type("StockAdjusted", version=3)
@dataclass(frozen=True)
class StockAdjusted:
    delta: int
    reason: str


# -- orders (stream "order-<id>")


@event_type("OrderPlaced")
@dataclass(frozen=True)
class OrderPlaced:
    customer: str


@event_type("LineAdded", version=2)
@dataclass(frozen=True)
class LineAdded:
    sku: str
    quantity: int
    unit_price_cents: int


@event_type("LineRemoved")
@dataclass(frozen=True)
class LineRemoved:
    sku: str


@event_type("OrderConfirmed")
@dataclass(frozen=True)
class OrderConfirmed:
    pass


@event_type("OrderCancelled")
@dataclass(frozen=True)
class OrderCancelled:
    reason: str


@event_type("OrderShipped")
@dataclass(frozen=True)
class OrderShipped:
    pass
