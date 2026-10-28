"""Repositories: the only code that touches the database's tables directly.

Each repository wraps one table for one tenant and hands out model objects; it never sees
another tenant's rows. Product lookups by SKU go through the database's lookup cache;
every change to a product keeps the cache and the search index in step with the table.
Cache and index keys are (tenant, sku), since SKUs are only unique within a tenant.
"""

from collections import defaultdict
from typing import Any

from .errors import DuplicateSku, UnknownSku
from .models import Alert, Movement, Product
from .storage import DEFAULT_TENANT, Database, search_text, tenant_of


class _TenantTable:
    table = ""

    def __init__(self, db: Database, tenant: str = DEFAULT_TENANT) -> None:
        self._db = db
        self.tenant = tenant

    @property
    def _all_rows(self) -> list[dict[str, Any]]:
        return self._db.tables[self.table]

    @property
    def _rows(self) -> list[dict[str, Any]]:
        return [r for r in self._all_rows if tenant_of(r) == self.tenant]

    def _insert(self, record: dict[str, Any]) -> dict[str, Any]:
        record = {**record, "tenant": self.tenant}
        self._all_rows.append(record)
        return record


class ProductRepo(_TenantTable):
    table = "products"

    def _key(self, sku: str) -> tuple[str, str]:
        return (self.tenant, sku)

    def _position(self, sku: str) -> int | None:
        for position, record in enumerate(self._all_rows):
            if record["sku"] == sku and tenant_of(record) == self.tenant:
                return position
        return None

    def find(self, sku: str) -> Product | None:
        record = self._db.cache.get(self._key(sku))
        if record is None:
            position = self._position(sku)
            if position is None:
                return None
            record = self._all_rows[position]
            self._db.cache.put(self._key(sku), record)
        return Product.from_record(record)

    def get(self, sku: str) -> Product:
        product = self.find(sku)
        if product is None:
            raise UnknownSku(sku)
        return product

    def add(self, product: Product) -> None:
        if self._position(product.sku) is not None:
            raise DuplicateSku(product.sku)
        record = self._insert(product.to_record())
        self._db.index.add(self._key(product.sku), search_text(record))

    def update(self, product: Product) -> None:
        position = self._position(product.sku)
        if position is None:
            raise UnknownSku(product.sku)
        new = {**product.to_record(), "tenant": self.tenant}
        self._all_rows[position] = new
        self._db.cache.invalidate(self._key(product.sku))
        self._db.index.add(self._key(product.sku), search_text(new))

    def remove(self, sku: str) -> None:
        position = self._position(sku)
        if position is None:
            raise UnknownSku(sku)
        del self._all_rows[position]
        self._db.cache.invalidate(self._key(sku))
        self._db.index.remove(self._key(sku))

    def all(self) -> list[Product]:
        return sorted((Product.from_record(r) for r in self._rows), key=lambda p: p.sku)

    def search(self, query: str) -> list[Product]:
        return [
            self.get(sku) for tenant, sku in self._db.index.search(query) if tenant == self.tenant
        ]


class MovementRepo(_TenantTable):
    table = "movements"

    def add(self, movement: Movement) -> None:
        self._insert(movement.to_record())

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


class AlertRepo(_TenantTable):
    table = "alerts"

    def add(self, alert: Alert) -> None:
        self._insert(alert.to_record())

    def all(self) -> list[Alert]:
        return [Alert.from_record(r) for r in self._rows]
