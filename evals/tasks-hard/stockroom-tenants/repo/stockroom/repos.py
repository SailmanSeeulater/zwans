"""Repositories: the only code that touches the database's tables directly.

Each repository wraps one table and hands out model objects. Product lookups by SKU go
through the database's lookup cache; every change to a product keeps the cache and the
search index in step with the table.
"""

from collections import defaultdict
from typing import Any

from .errors import DuplicateSku, UnknownSku
from .models import Alert, Movement, Product
from .storage import Database, search_text


class ProductRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    @property
    def _rows(self) -> list[dict[str, Any]]:
        return self._db.tables["products"]

    def _find_record(self, sku: str) -> dict[str, Any] | None:
        for record in self._rows:
            if record["sku"] == sku:
                return record
        return None

    def find(self, sku: str) -> Product | None:
        record = self._db.cache.get(sku)
        if record is None:
            record = self._find_record(sku)
            if record is None:
                return None
            self._db.cache.put(sku, record)
        return Product.from_record(record)

    def get(self, sku: str) -> Product:
        product = self.find(sku)
        if product is None:
            raise UnknownSku(sku)
        return product

    def add(self, product: Product) -> None:
        if self._find_record(product.sku) is not None:
            raise DuplicateSku(product.sku)
        record = product.to_record()
        self._rows.append(record)
        self._db.index.add(product.sku, search_text(record))

    def update(self, product: Product) -> None:
        for position, record in enumerate(self._rows):
            if record["sku"] == product.sku:
                new = product.to_record()
                self._rows[position] = new
                self._db.cache.invalidate(product.sku)
                self._db.index.add(product.sku, search_text(new))
                return
        raise UnknownSku(product.sku)

    def remove(self, sku: str) -> None:
        for position, record in enumerate(self._rows):
            if record["sku"] == sku:
                del self._rows[position]
                self._db.cache.invalidate(sku)
                self._db.index.remove(sku)
                return
        raise UnknownSku(sku)

    def all(self) -> list[Product]:
        return sorted((Product.from_record(r) for r in self._rows), key=lambda p: p.sku)

    def search(self, query: str) -> list[Product]:
        return [self.get(sku) for sku in self._db.index.search(query)]


class MovementRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    @property
    def _rows(self) -> list[dict[str, Any]]:
        return self._db.tables["movements"]

    def add(self, movement: Movement) -> None:
        self._rows.append(movement.to_record())

    def all(self) -> list[Movement]:
        """Every movement, oldest first."""
        return [Movement.from_record(r) for r in self._rows]

    def for_sku(self, sku: str) -> list[Movement]:
        return [Movement.from_record(r) for r in self._rows if r["sku"] == sku]

    def on_hand(self, sku: str) -> int:
        return sum(r["qty"] for r in self._rows if r["sku"] == sku)

    def on_hand_by_sku(self) -> dict[str, int]:
        totals: defaultdict[str, int] = defaultdict(int)
        for record in self._rows:
            totals[record["sku"]] += record["qty"]
        return dict(totals)

    def next_id(self) -> str:
        return f"MV-{self._db.next_id('movement'):06d}"


class AlertRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, alert: Alert) -> None:
        self._db.tables["alerts"].append(alert.to_record())

    def all(self) -> list[Alert]:
        return [Alert.from_record(r) for r in self._db.tables["alerts"]]
