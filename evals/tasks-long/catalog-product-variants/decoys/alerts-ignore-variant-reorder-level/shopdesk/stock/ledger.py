"""The stock ledger. Stock is kept per variant SKU. Stock on hand is never stored: it is
the sum of the moves for a SKU in a warehouse. Every change of stock is a move with a reason and a reference.

The ledger keeps running totals per (SKU, warehouse) so lookups don't rescan the moves;
they are rebuilt from the moves whenever the ledger is created.
"""

from collections import defaultdict

from shopdesk.catalog.products import ProductCatalog
from shopdesk.clock import Clock
from shopdesk.errors import InvalidInput, OutOfStock
from shopdesk.events import EventBus
from shopdesk.models import ShopData, StockMove
from shopdesk.stock.warehouses import Warehouses

REASONS = ("receive", "sale", "return", "adjust", "count", "transfer", "opening")


class StockLedger:
    def __init__(
        self,
        data: ShopData,
        catalog: ProductCatalog,
        warehouses: Warehouses,
        bus: EventBus,
        clock: Clock,
    ) -> None:
        self._data = data
        self._catalog = catalog
        self._warehouses = warehouses
        self._bus = bus
        self._clock = clock
        self._totals: dict[tuple[str, str], int] = defaultdict(int)
        self.rebuild()

    def rebuild(self) -> None:
        self._totals.clear()
        for move in self._data.moves:
            self._totals[(move.sku, move.warehouse)] += move.qty

    # -- reading -----------------------------------------------------------------------

    def on_hand(self, sku: str, warehouse: str | None = None) -> int:
        sku = sku.strip().upper()
        if warehouse is not None:
            return self._totals.get((sku, warehouse.strip().upper()), 0)
        return sum(qty for (s, _), qty in self._totals.items() if s == sku)

    def by_warehouse(self, sku: str) -> dict[str, int]:
        sku = sku.strip().upper()
        return {code: self._totals.get((sku, code), 0) for code in self._warehouses.codes()}

    def history(self, sku: str, warehouse: str | None = None) -> list[StockMove]:
        sku = sku.strip().upper()
        return [
            m
            for m in self._data.moves
            if m.sku == sku and (warehouse is None or m.warehouse == warehouse)
        ]

    def moves_for(self, ref: str) -> list[StockMove]:
        return [m for m in self._data.moves if m.ref == ref]

    def skus_with_stock(self) -> set[str]:
        return {sku for (sku, _), qty in self._totals.items() if qty > 0}

    # -- changing ----------------------------------------------------------------------

    def record(self, sku: str, warehouse: str, qty: int, reason: str, ref: str = "") -> StockMove:
        _, variant = self._catalog.resolve(sku)
        code = self._warehouses.get(warehouse).code
        if reason not in REASONS:
            raise InvalidInput(f"Unknown stock reason {reason!r}.")
        if qty == 0:
            raise InvalidInput("A stock move needs a quantity.")
        current = self._totals.get((variant.sku, code), 0)
        if current + qty < 0:
            raise OutOfStock(variant.sku, -qty, current)
        move = StockMove(
            id=self._data.next_id("move"),
            at=self._clock(),
            sku=variant.sku,
            warehouse=code,
            qty=qty,
            reason=reason,
            ref=ref,
        )
        self._data.moves.append(move)
        self._totals[(variant.sku, code)] += qty
        self._bus.publish(
            "stock.moved", sku=variant.sku, warehouse=code, qty=qty, reason=reason, ref=ref
        )
        return move

    def receive(self, sku: str, warehouse: str, qty: int, ref: str = "") -> StockMove:
        if qty <= 0:
            raise InvalidInput("Receive a positive quantity.")
        return self.record(sku, warehouse, qty, "receive", ref)

    def adjust(self, sku: str, warehouse: str, qty: int, ref: str = "") -> StockMove:
        return self.record(sku, warehouse, qty, "adjust", ref)

    def count(self, sku: str, warehouse: str, counted: int, ref: str = "") -> StockMove | None:
        """Set the stock to what was counted. Returns None if it already matched."""
        if counted < 0:
            raise InvalidInput("A count can't be negative.")
        difference = counted - self.on_hand(sku, self._warehouses.get(warehouse).code)
        if difference == 0:
            self._catalog.resolve(sku)
            return None
        return self.record(sku, warehouse, difference, "count", ref or "stock count")

    def transfer(self, sku: str, source: str, target: str, qty: int, ref: str = "") -> str:
        if qty <= 0:
            raise InvalidInput("Transfer a positive quantity.")
        src = self._warehouses.get(source).code
        dst = self._warehouses.get(target).code
        if src == dst:
            raise InvalidInput("Transfer between two different warehouses.")
        ref = ref or f"TR-{self._data.next_id('transfer'):05d}"
        with self._bus.held():
            self.record(sku, src, -qty, "transfer", ref)
            self.record(sku, dst, qty, "transfer", ref)
        return ref
