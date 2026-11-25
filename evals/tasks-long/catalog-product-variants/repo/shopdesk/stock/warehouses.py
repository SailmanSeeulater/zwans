"""Warehouses. Orders pick from them in priority order (lowest number first)."""

from shopdesk.codes import normalize_warehouse
from shopdesk.errors import InvalidInput, UnknownWarehouse
from shopdesk.events import EventBus
from shopdesk.models import ShopData, Warehouse


class Warehouses:
    def __init__(self, data: ShopData, bus: EventBus) -> None:
        self._data = data
        self._bus = bus

    def add(self, code: str, name: str, priority: int = 0) -> Warehouse:
        code = normalize_warehouse(code)
        if code in self._data.warehouses:
            raise InvalidInput(f"Warehouse {code} already exists.")
        if not name.strip():
            raise InvalidInput("A warehouse needs a name.")
        warehouse = Warehouse(code, name.strip(), priority)
        self._data.warehouses[code] = warehouse
        self._bus.publish("warehouse.added", code=code)
        return warehouse

    def get(self, code: str) -> Warehouse:
        try:
            return self._data.warehouses[code.strip().upper()]
        except KeyError:
            raise UnknownWarehouse(code) from None

    def all(self) -> list[Warehouse]:
        """In picking order: priority, then code."""
        return sorted(self._data.warehouses.values(), key=lambda w: (w.priority, w.code))

    def codes(self) -> list[str]:
        return [w.code for w in self.all()]

    def set_priority(self, code: str, priority: int) -> None:
        self.get(code).priority = priority
        self._bus.publish("warehouse.changed", code=code)
