"""The read models behind `stockflow report ...`."""

from typing import Any

from stockflow.projections.registry import PROJECTIONS, Projection


def id_of(stream: str) -> str:
    return stream.split("-", 1)[1]


@PROJECTIONS.register("stock_levels")
class StockLevels(Projection):
    """Per SKU: on hand, reserved, and available."""

    def __init__(self, settings) -> None:
        super().__init__(settings)
        self.items: dict[str, dict[str, Any]] = {}
        self.reservations: dict[str, dict[str, int]] = {}

    def _item(self, stream: str) -> dict[str, Any]:
        sku = id_of(stream)
        return self.items.setdefault(
            sku, {"name": None, "on_hand": 0, "reserved": 0, "reorder_level": 0}
        )

    def on_item_registered(self, stream: str, data: dict[str, Any]) -> None:
        item = self._item(stream)
        item["name"] = data["name"]
        item["reorder_level"] = data["reorder_level"]

    def on_stock_received(self, stream: str, data: dict[str, Any]) -> None:
        self._item(stream)["on_hand"] += data["quantity"]

    def on_stock_adjusted(self, stream: str, data: dict[str, Any]) -> None:
        self._item(stream)["on_hand"] += data["delta"]

    def on_stock_reserved(self, stream: str, data: dict[str, Any]) -> None:
        self.reservations.setdefault(stream, {})[data["order_id"]] = data["quantity"]
        self._item(stream)["reserved"] += data["quantity"]

    def on_reservation_released(self, stream: str, data: dict[str, Any]) -> None:
        quantity = self.reservations.get(stream, {}).pop(data["order_id"], 0)
        self._item(stream)["reserved"] -= quantity

    def on_stock_shipped(self, stream: str, data: dict[str, Any]) -> None:
        quantity = self.reservations.get(stream, {}).pop(data["order_id"], 0)
        item = self._item(stream)
        item["reserved"] -= quantity
        item["on_hand"] -= quantity

    def result(self) -> dict[str, dict[str, Any]]:
        return {
            sku: {**item, "available": item["on_hand"] - item["reserved"]}
            for sku, item in sorted(self.items.items())
        }


@PROJECTIONS.register("low_stock")
class LowStock(StockLevels):
    """SKUs whose available stock is at or below their reorder level (or the configured
    threshold, for items registered without one)."""

    def result(self) -> list[str]:
        low = []
        for sku, item in super().result().items():
            level = item["reorder_level"] or self.settings.low_stock_threshold
            if item["available"] <= level:
                low.append(sku)
        return low


@PROJECTIONS.register("open_orders")
class OpenOrders(Projection):
    """Orders that are still draft or confirmed, with their totals."""

    def __init__(self, settings) -> None:
        super().__init__(settings)
        self.orders: dict[str, dict[str, Any]] = {}

    def on_order_placed(self, stream: str, data: dict[str, Any]) -> None:
        self.orders[id_of(stream)] = {"customer": data["customer"], "status": "draft", "lines": {}}

    def on_line_added(self, stream: str, data: dict[str, Any]) -> None:
        lines = self.orders[id_of(stream)]["lines"]
        line = lines.setdefault(data["sku"], {"quantity": 0, "unit_price_cents": 0})
        line["quantity"] += data["quantity"]
        line["unit_price_cents"] = data["unit_price_cents"]

    def on_line_removed(self, stream: str, data: dict[str, Any]) -> None:
        self.orders[id_of(stream)]["lines"].pop(data["sku"], None)

    def on_order_confirmed(self, stream: str, data: dict[str, Any]) -> None:
        self.orders[id_of(stream)]["status"] = "confirmed"

    def on_order_cancelled(self, stream: str, data: dict[str, Any]) -> None:
        self.orders.pop(id_of(stream), None)

    def on_order_shipped(self, stream: str, data: dict[str, Any]) -> None:
        self.orders.pop(id_of(stream), None)

    def result(self) -> dict[str, dict[str, Any]]:
        out = {}
        for order_id, order in sorted(self.orders.items()):
            total = sum(l["quantity"] * l["unit_price_cents"] for l in order["lines"].values())
            out[order_id] = {
                "customer": order["customer"],
                "status": order["status"],
                "total_cents": total,
            }
        return out
