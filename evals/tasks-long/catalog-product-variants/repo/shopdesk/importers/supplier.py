"""Importing a supplier's price file into the catalog.

A row whose SKU we already have updates that product (only the columns the file has,
only when they differ); a new SKU becomes a new product, which needs at least a name and
a price. Rows that fail are reported by line and skipped; the rest still go in. With
`dry_run` nothing changes, but the result says what would have.
"""

from dataclasses import dataclass, field
from typing import Any

from shopdesk.catalog.categories import CategoryTree
from shopdesk.catalog.products import ProductCatalog
from shopdesk.clock import Clock
from shopdesk.codes import slugify
from shopdesk.errors import InvalidInput, ShopError
from shopdesk.events import EventBus
from shopdesk.importers.rows import SupplierRow, parse_supplier_file
from shopdesk.models import ImportRun, ShopData

UPDATABLE = ("name", "price", "cost", "barcode", "brand", "category", "supplier_ref")


@dataclass
class ImportResult:
    supplier: str
    dry_run: bool
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)

    def summary(self) -> str:
        verb = "would be" if self.dry_run else "were"
        return (
            f"{len(self.created)} new, {len(self.updated)} updated, "
            f"{len(self.unchanged)} unchanged, {len(self.errors)} errors {verb} found "
            f"in the file from {self.supplier}."
        )


class SupplierImporter:
    def __init__(
        self,
        data: ShopData,
        catalog: ProductCatalog,
        categories: CategoryTree,
        bus: EventBus,
        clock: Clock,
    ) -> None:
        self._data = data
        self._catalog = catalog
        self._categories = categories
        self._bus = bus
        self._clock = clock

    def run(
        self,
        text: str,
        supplier: str,
        *,
        dry_run: bool = False,
        create_categories: bool = False,
    ) -> ImportResult:
        supplier = supplier.strip()
        if not supplier:
            raise InvalidInput("Name the supplier the file came from.")
        parsed = parse_supplier_file(text)
        result = ImportResult(supplier, dry_run, errors=list(parsed.errors))
        seen: set[str] = set()
        with self._bus.held():
            for row in parsed.rows:
                if row.sku in seen:
                    result.errors.append((row.line, f"{row.sku} appears twice in the file."))
                    continue
                seen.add(row.sku)
                try:
                    self._apply(row, supplier, result, dry_run, create_categories)
                except ShopError as exc:
                    result.errors.append((row.line, str(exc)))
        result.errors.sort()
        if not dry_run:
            self._data.imports.append(
                ImportRun(
                    at=self._clock(),
                    supplier=supplier,
                    created=len(result.created),
                    updated=len(result.updated),
                    unchanged=len(result.unchanged),
                    errors=len(result.errors),
                )
            )
        return result

    def _apply(
        self,
        row: SupplierRow,
        supplier: str,
        result: ImportResult,
        dry_run: bool,
        create_categories: bool,
    ) -> None:
        category = self._category(row, dry_run, create_categories)
        if self._catalog.exists(row.sku):
            product = self._catalog.get(row.sku)
            changes = self._changes(product, row, category)
            if product.supplier is None:
                changes["supplier"] = supplier
            if not changes:
                result.unchanged.append(product.sku)
                return
            if not dry_run:
                self._catalog.update(product.sku, **changes)
            result.updated.append(product.sku)
            return
        if row.name is None or row.price is None:
            raise InvalidInput(f"New product {row.sku} needs a name and a price.")
        if not dry_run:
            self._catalog.add(
                row.sku,
                row.name,
                row.price,
                category=category,
                brand=row.brand or "",
                barcode=row.barcode,
                cost=row.cost or 0,
                supplier=supplier,
                supplier_ref=row.supplier_ref,
            )
        result.created.append(row.sku)

    def _category(self, row: SupplierRow, dry_run: bool, create: bool) -> str | None:
        if not row.category:
            return None
        slug = slugify(row.category)
        if self._categories.exists(slug):
            return slug
        if not create:
            raise InvalidInput(f"Unknown category {row.category!r}.")
        if not dry_run:
            self._categories.add(slug, row.category)
        return slug

    @staticmethod
    def _changes(product: Any, row: SupplierRow, category: str | None) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        for key in UPDATABLE:
            value = category if key == "category" else getattr(row, key)
            if value is None:
                continue
            if getattr(product, key) != value:
                changes[key] = value
        return changes
