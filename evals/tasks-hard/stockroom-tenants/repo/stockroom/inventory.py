"""The inventory service: what the CLI (and anything else) uses to change or read stock.

Stock on hand is never stored; it is the sum of a product's movements. Every change runs in
a database transaction, so a failed check leaves nothing behind.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from .errors import InsufficientStock, ProductInUse
from .models import Alert, Movement, Product
from .repos import AlertRepo, MovementRepo, ProductRepo
from .storage import Database
from .validation import check_name, check_non_negative, check_positive, check_sku


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Inventory:
    def __init__(self, db: Database, *, clock: Callable[[], str] = utc_now) -> None:
        self.db = db
        self.clock = clock
        self.products = ProductRepo(db)
        self.movements = MovementRepo(db)
        self.alert_log = AlertRepo(db)

    # -------------------------------------------------------------- products

    def add_product(
        self, sku: str, name: str, unit_cost_cents: int, reorder_level: int = 0, unit: str = "pcs"
    ) -> Product:
        sku = check_sku(sku)
        product = Product(
            sku,
            check_name(name),
            check_non_negative(unit_cost_cents, "unit cost"),
            check_non_negative(reorder_level, "reorder level"),
            unit,
        )
        with self.db.transaction():
            self.products.add(product)
        return product

    def rename(self, sku: str, name: str) -> Product:
        with self.db.transaction():
            product = self.products.get(sku)
            renamed = Product(
                product.sku,
                check_name(name),
                product.unit_cost_cents,
                product.reorder_level,
                product.unit,
            )
            self.products.update(renamed)
        return renamed

    def set_cost(self, sku: str, unit_cost_cents: int) -> Product:
        with self.db.transaction():
            product = self.products.get(sku)
            changed = Product(
                product.sku,
                product.name,
                check_non_negative(unit_cost_cents, "unit cost"),
                product.reorder_level,
                product.unit,
            )
            self.products.update(changed)
        return changed

    def set_reorder_level(self, sku: str, level: int) -> Product:
        with self.db.transaction():
            product = self.products.get(sku)
            changed = Product(
                product.sku,
                product.name,
                product.unit_cost_cents,
                check_non_negative(level, "reorder level"),
                product.unit,
            )
            self.products.update(changed)
        return changed

    def remove_product(self, sku: str) -> None:
        """Only products that never had any stock movement can be removed."""
        with self.db.transaction():
            self.products.get(sku)
            if self.movements.for_sku(sku):
                raise ProductInUse(f"{sku} has stock history and cannot be removed")
            self.products.remove(sku)

    def product(self, sku: str) -> Product:
        return self.products.get(sku)

    def all_products(self) -> list[Product]:
        return self.products.all()

    def search(self, query: str) -> list[Product]:
        return self.products.search(query)

    # ----------------------------------------------------------------- stock

    def on_hand(self, sku: str) -> int:
        self.products.get(sku)
        return self.movements.on_hand(sku)

    def levels(self) -> list[tuple[Product, int]]:
        totals = self.movements.on_hand_by_sku()
        return [(product, totals.get(product.sku, 0)) for product in self.products.all()]

    def receive(self, sku: str, qty: int, ref: str = "") -> Movement:
        check_positive(qty, "quantity")
        with self.db.transaction():
            self.products.get(sku)
            return self._move(sku, "receive", qty, ref)

    def ship(self, sku: str, qty: int, ref: str = "") -> Movement:
        check_positive(qty, "quantity")
        with self.db.transaction():
            product = self.products.get(sku)
            before = self.movements.on_hand(sku)
            if qty > before:
                raise InsufficientStock(
                    f"only {before} {product.unit} of {sku} on hand, cannot ship {qty}"
                )
            movement = self._move(sku, "ship", -qty, ref)
            self._check_reorder(product, before)
            return movement

    def count(self, sku: str, counted: int, ref: str = "stocktake") -> Movement | None:
        """Record a stock count: adjusts stock on hand to what was counted.

        Returns the adjustment, or None when the count matched.
        """
        check_non_negative(counted, "counted quantity")
        with self.db.transaction():
            product = self.products.get(sku)
            before = self.movements.on_hand(sku)
            if counted == before:
                return None
            movement = self._move(sku, "adjust", counted - before, ref)
            self._check_reorder(product, before)
            return movement

    def history(self, sku: str | None = None) -> list[Movement]:
        if sku is None:
            return self.movements.all()
        self.products.get(sku)
        return self.movements.for_sku(sku)

    def _move(self, sku: str, kind: str, qty: int, ref: str) -> Movement:
        movement = Movement(self.movements.next_id(), sku, kind, qty, ref, self.clock())
        self.movements.add(movement)
        return movement

    # -------------------------------------------------------------- warnings

    def _check_reorder(self, product: Product, before: int) -> None:
        """Raise an alert when stock has just dropped to the reorder level or below."""
        if product.reorder_level <= 0:
            return
        after = self.movements.on_hand(product.sku)
        if after <= product.reorder_level < before:
            self.alert_log.add(Alert(product.sku, after, product.reorder_level, self.clock()))

    def low_stock(self) -> list[tuple[Product, int]]:
        return [
            (p, qty) for p, qty in self.levels() if p.reorder_level > 0 and qty <= p.reorder_level
        ]

    def alerts(self) -> list[Alert]:
        return self.alert_log.all()

    def valuation_cents(self) -> int:
        return sum(product.unit_cost_cents * qty for product, qty in self.levels())
