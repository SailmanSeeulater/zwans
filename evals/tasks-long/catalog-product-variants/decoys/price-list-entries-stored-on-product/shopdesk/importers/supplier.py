"""Importing a supplier's price file into the catalog.

A row whose SKU we already have updates that product (only the columns the file has,
only when they differ); a new SKU becomes a new product, which needs at least a name and
a price. Rows that fail are reported by line and skipped; the rest still go in. With
`dry_run` nothing changes, but the result says what would have.

A row with a `parent_sku` is a variant of that product: a new SKU becomes a new variant
(and the product is created from the row if it doesn't exist yet), an existing variant
gets the row's price and barcode. A row without one whose SKU is a variant of some
product updates that variant.
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
from shopdesk.models import ImportRun, Product, ShopData, Variant

UPDATABLE = ("name", "price", "cost", "brand", "category", "supplier_ref")


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
        self._planned: set[str] = set()
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
        if row.parent_sku is not None:
            self._apply_variant(row, supplier, result, dry_run, create_categories)
            return
        if row.sku not in self._data.products and self._catalog.is_variant(row.sku):
            product, variant = self._catalog.resolve(row.sku)
            self._update_variant(product, variant, row, result, dry_run)
            return
        category = self._category(row, dry_run, create_categories)
        if row.sku in self._data.products:
            product = self._catalog.get(row.sku)
            changes = self._changes(product, row, category)
            if product.supplier is None:
                changes["supplier"] = supplier
            own = product.find_variant(product.sku)
            new_barcode = row.barcode is not None and own is not None and own.barcode != row.barcode
            if not changes and not new_barcode:
                result.unchanged.append(product.sku)
                return
            if not dry_run:
                self._catalog.update(product.sku, **changes)
                if new_barcode:
                    self._catalog.update_variant(own.sku, barcode=row.barcode)
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

    def _apply_variant(
        self,
        row: SupplierRow,
        supplier: str,
        result: ImportResult,
        dry_run: bool,
        create_categories: bool,
    ) -> None:
        parent = row.parent_sku
        assert parent is not None
        if self._catalog.is_variant(row.sku):
            product, variant = self._catalog.resolve(row.sku)
            if product.sku != parent:
                raise InvalidInput(f"{row.sku} is a variant of {product.sku}, not {parent}.")
            self._update_variant(product, variant, row, result, dry_run)
            return
        if parent in self._data.products:
            product = self._data.products[parent]
            override = row.price if row.price is not None and row.price != product.price else None
            if not dry_run:
                self._catalog.add_variant(
                    parent, row.sku, row.options, price=override, barcode=row.barcode
                )
            result.created.append(row.sku)
            return
        if parent in self._planned:
            result.created.append(row.sku)
            return
        if row.name is None or row.price is None:
            raise InvalidInput(f"New product {parent} needs a name and a price.")
        category = self._category(row, dry_run, create_categories)
        if not dry_run:
            self._catalog.add(
                parent,
                row.name,
                row.price,
                category=category,
                brand=row.brand or "",
                cost=row.cost or 0,
                supplier=supplier,
                supplier_ref=row.supplier_ref,
                variants=[{"sku": row.sku, "options": row.options, "barcode": row.barcode}],
            )
        else:
            self._planned.add(parent)
        result.created.append(row.sku)

    def _update_variant(
        self,
        product: Product,
        variant: Variant,
        row: SupplierRow,
        result: ImportResult,
        dry_run: bool,
    ) -> None:
        changes: dict[str, Any] = {}
        if row.price is not None and product.price_of(variant) != row.price:
            changes["price"] = None if row.price == product.price else row.price
        if row.barcode is not None and variant.barcode != row.barcode:
            changes["barcode"] = row.barcode
        if row.options and row.options != variant.options:
            changes["options"] = row.options
        if not changes:
            result.unchanged.append(variant.sku)
            return
        if not dry_run:
            self._catalog.update_variant(variant.sku, **changes)
        result.updated.append(variant.sku)

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
