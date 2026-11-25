"""Low-stock alerts.

A product with a reorder level above zero gets one alert when its stock (all warehouses
together) falls to the reorder level or below. The alert stays open until stock rises
above the level again; then it is cleared, and the next fall raises a new one.
"""

from typing import Any

from shopdesk.catalog.products import ProductCatalog
from shopdesk.clock import Clock
from shopdesk.events import EventBus
from shopdesk.models import Alert, ShopData
from shopdesk.stock.ledger import StockLedger


class LowStockMonitor:
    def __init__(
        self,
        data: ShopData,
        catalog: ProductCatalog,
        ledger: StockLedger,
        bus: EventBus,
        clock: Clock,
    ) -> None:
        self._data = data
        self._catalog = catalog
        self._ledger = ledger
        self._bus = bus
        self._clock = clock

    def attach(self) -> None:
        self._bus.subscribe("stock.moved", self._on_moved)
        self._bus.subscribe("product.changed", self._on_product_changed)

    def _on_moved(self, topic: str, payload: dict[str, Any]) -> None:
        self.check(payload["sku"])

    def _on_product_changed(self, topic: str, payload: dict[str, Any]) -> None:
        if "reorder_level" in payload.get("fields", ()):
            self.check(payload["sku"])

    def open_alert(self, sku: str) -> Alert | None:
        for alert in reversed(self._data.alerts):
            if alert.sku == sku and alert.is_open:
                return alert
        return None

    def check(self, sku: str) -> Alert | None:
        """Raise or clear the SKU's alert to match its stock now. Returns a new alert."""
        product = self._catalog.get(sku)
        level = product.reorder_level
        stock = self._ledger.on_hand(product.sku)
        current = self.open_alert(product.sku)
        if level > 0 and stock <= level:
            if current is not None:
                current.stock = stock
                return None
            alert = Alert(
                id=self._data.next_id("alert"),
                sku=product.sku,
                raised_at=self._clock(),
                stock=stock,
                reorder_level=level,
            )
            self._data.alerts.append(alert)
            self._bus.publish(
                "stock.low", sku=product.sku, stock=stock, reorder_level=level, alert=alert.id
            )
            return alert
        if current is not None:
            current.cleared_at = self._clock()
            self._bus.publish("stock.recovered", sku=product.sku, stock=stock, alert=current.id)
        return None

    def recheck_all(self) -> list[Alert]:
        raised = []
        for product in self._catalog.all():
            alert = self.check(product.sku)
            if alert is not None:
                raised.append(alert)
        return raised

    def alerts(self, *, open_only: bool = True) -> list[Alert]:
        return [a for a in self._data.alerts if a.is_open or not open_only]
