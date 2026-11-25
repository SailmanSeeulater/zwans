"""The product catalog: adding, finding and changing products."""

from collections.abc import Iterable
from typing import Any

from shopdesk.catalog.categories import CategoryTree
from shopdesk.clock import Clock
from shopdesk.codes import normalize_barcode, normalize_sku
from shopdesk.errors import DuplicateBarcode, DuplicateSku, InvalidInput, UnknownSku
from shopdesk.events import EventBus
from shopdesk.models import Product, ShopData

TAX_CLASSES = ("standard", "reduced", "zero")

EDITABLE = (
    "name",
    "price",
    "category",
    "brand",
    "barcode",
    "tax_class",
    "cost",
    "reorder_level",
    "description",
    "supplier",
    "supplier_ref",
    "active",
)


class ProductCatalog:
    def __init__(
        self, data: ShopData, categories: CategoryTree, bus: EventBus, clock: Clock
    ) -> None:
        self._data = data
        self._categories = categories
        self._bus = bus
        self._clock = clock

    # -- reading -----------------------------------------------------------------------

    def get(self, sku: str) -> Product:
        try:
            return self._data.products[sku.strip().upper()]
        except KeyError:
            raise UnknownSku(sku) from None

    def exists(self, sku: str) -> bool:
        return sku.strip().upper() in self._data.products

    def all(self, *, active_only: bool = False) -> list[Product]:
        products = sorted(self._data.products.values(), key=lambda p: p.sku)
        return [p for p in products if p.active] if active_only else products

    def in_category(self, slug: str, *, active_only: bool = True) -> list[Product]:
        wanted = self._categories.descendants(slug)
        return [p for p in self.all(active_only=active_only) if p.category in wanted]

    def by_barcode(self, barcode: str) -> Product:
        code = normalize_barcode(barcode)
        for product in self._data.products.values():
            if product.barcode == code:
                return product
        raise InvalidInput(f"No product has barcode {code}.")

    def by_supplier_ref(self, supplier: str, ref: str) -> Product | None:
        for product in self._data.products.values():
            if product.supplier == supplier and product.supplier_ref == ref:
                return product
        return None

    # -- changing ----------------------------------------------------------------------

    def add(
        self,
        sku: str,
        name: str,
        price: int,
        *,
        category: str | None = None,
        brand: str = "",
        barcode: str | None = None,
        tax_class: str = "standard",
        cost: int = 0,
        reorder_level: int = 0,
        description: str = "",
        supplier: str | None = None,
        supplier_ref: str | None = None,
    ) -> Product:
        sku = normalize_sku(sku)
        if sku in self._data.products:
            raise DuplicateSku(sku)
        product = Product(
            sku=sku,
            name=self._clean_name(name),
            price=self._clean_amount(price, "Price"),
            category=self._clean_category(category),
            brand=brand.strip(),
            barcode=self._clean_barcode(barcode, sku),
            tax_class=self._clean_tax_class(tax_class),
            cost=self._clean_amount(cost, "Cost"),
            reorder_level=self._clean_level(reorder_level),
            description=description.strip(),
            supplier=supplier,
            supplier_ref=supplier_ref,
            created_at=self._clock(),
        )
        self._data.products[sku] = product
        self._bus.publish("product.added", sku=sku)
        return product

    def update(self, sku: str, **changes: Any) -> Product:
        product = self.get(sku)
        unknown = set(changes) - set(EDITABLE)
        if unknown:
            raise InvalidInput(f"Can't change {', '.join(sorted(unknown))}.")
        cleaned = self._clean_changes(product, changes)
        changed = {k: v for k, v in cleaned.items() if getattr(product, k) != v}
        for key, value in changed.items():
            setattr(product, key, value)
        if changed:
            self._bus.publish("product.changed", sku=product.sku, fields=sorted(changed))
        return product

    def set_active(self, sku: str, active: bool) -> Product:
        return self.update(sku, active=active)

    def bulk_update(self, rows: Iterable[tuple[str, dict[str, Any]]]) -> int:
        """Apply several updates; events go out once all of them succeeded."""
        count = 0
        with self._bus.held():
            for sku, changes in rows:
                self.update(sku, **changes)
                count += 1
        return count

    # -- validation --------------------------------------------------------------------

    def _clean_changes(self, product: Product, changes: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for key, value in changes.items():
            if key == "name":
                cleaned[key] = self._clean_name(value)
            elif key in ("price", "cost"):
                cleaned[key] = self._clean_amount(value, key.capitalize())
            elif key == "category":
                cleaned[key] = self._clean_category(value)
            elif key == "barcode":
                cleaned[key] = self._clean_barcode(value, product.sku)
            elif key == "tax_class":
                cleaned[key] = self._clean_tax_class(value)
            elif key == "reorder_level":
                cleaned[key] = self._clean_level(value)
            elif key == "active":
                cleaned[key] = bool(value)
            elif key in ("brand", "description"):
                cleaned[key] = (value or "").strip()
            else:
                cleaned[key] = value
        return cleaned

    @staticmethod
    def _clean_name(name: str) -> str:
        name = " ".join(name.split())
        if not name:
            raise InvalidInput("A product needs a name.")
        if len(name) > 200:
            raise InvalidInput("Product names are at most 200 characters.")
        return name

    @staticmethod
    def _clean_amount(value: int, what: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise InvalidInput(f"{what} must be a whole number of cents.")
        if value < 0:
            raise InvalidInput(f"{what} can't be negative.")
        return value

    @staticmethod
    def _clean_level(value: int) -> int:
        if not isinstance(value, int) or value < 0:
            raise InvalidInput("Reorder level must be zero or more.")
        return value

    def _clean_category(self, slug: str | None) -> str | None:
        if slug is None or slug == "":
            return None
        return self._categories.get(slug).slug

    def _clean_barcode(self, barcode: str | None, owner: str) -> str | None:
        if barcode is None or barcode == "":
            return None
        code = normalize_barcode(barcode)
        for product in self._data.products.values():
            if product.barcode == code and product.sku != owner:
                raise DuplicateBarcode(code, product.sku)
        return code

    @staticmethod
    def _clean_tax_class(tax_class: str) -> str:
        if tax_class not in TAX_CLASSES:
            raise InvalidInput(f"Tax class must be one of {', '.join(TAX_CLASSES)}.")
        return tax_class
