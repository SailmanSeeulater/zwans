"""The product catalog: adding, finding and changing products and their variants.

Every product has one or more variants, the things actually sold and stocked. A product
made without variants gets one whose SKU is the product's own.
"""

from collections.abc import Iterable
from typing import Any

from shopdesk.catalog.categories import CategoryTree
from shopdesk.clock import Clock
from shopdesk.codes import normalize_barcode, normalize_sku
from shopdesk.errors import DuplicateBarcode, DuplicateSku, InvalidInput, ShopError, UnknownSku
from shopdesk.events import EventBus
from shopdesk.models import Product, ShopData, Variant

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

VARIANT_EDITABLE = ("price", "barcode", "reorder_level", "options")


class ProductCatalog:
    def __init__(
        self, data: ShopData, categories: CategoryTree, bus: EventBus, clock: Clock
    ) -> None:
        self._data = data
        self._categories = categories
        self._bus = bus
        self._clock = clock
        self._owners: dict[str, str] = {}  # variant SKU -> product SKU
        self.reindex()

    def reindex(self) -> None:
        self._owners = {
            variant.sku: product.sku
            for product in self._data.products.values()
            for variant in product.variants
        }

    # -- reading -----------------------------------------------------------------------

    def get(self, sku: str) -> Product:
        """The product with this SKU, or the product owning the variant with this SKU."""
        key = sku.strip().upper()
        product = self._data.products.get(key)
        if product is None and key in self._owners:
            product = self._data.products[self._owners[key]]
        if product is None:
            raise UnknownSku(sku)
        return product

    def resolve(self, sku: str) -> tuple[Product, Variant]:
        """The variant with this SKU and its product. Only variant SKUs resolve."""
        key = sku.strip().upper()
        owner = self._owners.get(key)
        if owner is None:
            raise UnknownSku(sku)
        product = self._data.products[owner]
        variant = product.find_variant(key)
        assert variant is not None
        return product, variant

    def variant(self, sku: str) -> Variant:
        return self.resolve(sku)[1]

    def exists(self, sku: str) -> bool:
        key = sku.strip().upper()
        return key in self._data.products or key in self._owners

    def is_variant(self, sku: str) -> bool:
        return sku.strip().upper() in self._owners

    def all(self, *, active_only: bool = False) -> list[Product]:
        products = sorted(self._data.products.values(), key=lambda p: p.sku)
        return [p for p in products if p.active] if active_only else products

    def all_variants(self, *, active_only: bool = False) -> list[tuple[Product, Variant]]:
        return [(p, v) for p in self.all(active_only=active_only) for v in p.variants]

    def in_category(self, slug: str, *, active_only: bool = True) -> list[Product]:
        wanted = self._categories.descendants(slug)
        return [p for p in self.all(active_only=active_only) if p.category in wanted]

    def by_barcode(self, barcode: str) -> tuple[Product, Variant]:
        code = normalize_barcode(barcode)
        for product in self._data.products.values():
            for variant in product.variants:
                if variant.barcode == code:
                    return product, variant
        raise InvalidInput(f"No product has barcode {code}.")

    def by_supplier_ref(self, supplier: str, ref: str) -> Product | None:
        for product in self._data.products.values():
            if product.supplier == supplier and product.supplier_ref == ref:
                return product
        return None

    # -- changing products -------------------------------------------------------------

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
        variants: list[dict[str, Any]] | None = None,
    ) -> Product:
        sku = normalize_sku(sku)
        if sku in self._data.products or sku in self._owners:
            raise DuplicateSku(sku)
        product = Product(
            sku=sku,
            name=self._clean_name(name),
            price=self._clean_amount(price, "Price"),
            category=self._clean_category(category),
            brand=brand.strip(),
            tax_class=self._clean_tax_class(tax_class),
            cost=self._clean_amount(cost, "Cost"),
            reorder_level=self._clean_level(reorder_level),
            description=description.strip(),
            supplier=supplier,
            supplier_ref=supplier_ref,
            created_at=self._clock(),
        )
        if variants is None:
            product.variants = [Variant(sku, {}, None, self._clean_barcode(barcode, sku))]
        else:
            if barcode:
                raise InvalidInput("With variants, barcodes go on the variants.")
            if not variants:
                raise InvalidInput("A product needs at least one variant.")
            for spec in variants:
                spec = dict(spec)
                product.variants.append(
                    self._new_variant(
                        product,
                        spec.pop("sku", ""),
                        spec.pop("options", None) or {},
                        price=spec.pop("price", None),
                        barcode=spec.pop("barcode", None),
                        reorder_level=spec.pop("reorder_level", None),
                        extra=spec,
                    )
                )
        self._data.products[sku] = product
        self.reindex()
        self._bus.publish("product.added", sku=sku)
        return product

    def update(self, sku: str, **changes: Any) -> Product:
        product = self.get(sku)
        unknown = set(changes) - set(EDITABLE)
        if unknown:
            raise InvalidInput(f"Can't change {', '.join(sorted(unknown))}.")
        if "barcode" in changes:
            own = product.find_variant(product.sku)
            if own is None:
                raise InvalidInput(f"{product.sku} has variants; set the barcode on one of them.")
            self.update_variant(own.sku, barcode=changes.pop("barcode"))
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

    # -- changing variants -------------------------------------------------------------

    def add_variant(
        self,
        product_sku: str,
        sku: str,
        options: dict[str, str] | None = None,
        *,
        price: int | None = None,
        barcode: str | None = None,
        reorder_level: int | None = None,
    ) -> Variant:
        product = self.get(product_sku)
        variant = self._new_variant(
            product, sku, options or {}, price=price, barcode=barcode, reorder_level=reorder_level
        )
        product.variants.append(variant)
        self._owners[variant.sku] = product.sku
        self._bus.publish(
            "product.changed", sku=product.sku, fields=["variants"], variant=variant.sku
        )
        return variant

    def update_variant(self, sku: str, **changes: Any) -> Variant:
        product, variant = self.resolve(sku)
        unknown = set(changes) - set(VARIANT_EDITABLE)
        if unknown:
            raise InvalidInput(f"Can't change {', '.join(sorted(unknown))} of a variant.")
        cleaned: dict[str, Any] = {}
        for key, value in changes.items():
            if key == "price":
                cleaned[key] = None if value is None else self._clean_amount(value, "Price")
            elif key == "reorder_level":
                cleaned[key] = None if value is None else self._clean_level(value)
            elif key == "barcode":
                cleaned[key] = self._clean_barcode(value, variant.sku)
            else:
                cleaned[key] = self._clean_options(product, value, variant.sku)
        changed = sorted(k for k, v in cleaned.items() if getattr(variant, k) != v)
        for key in changed:
            setattr(variant, key, cleaned[key])
        if changed:
            self._bus.publish(
                "product.changed",
                sku=product.sku,
                fields=["variants", *changed],
                variant=variant.sku,
            )
        return variant

    def remove_variant(self, sku: str) -> Variant:
        product, variant = self.resolve(sku)
        if len(product.variants) == 1:
            raise ShopError(f"{variant.sku} is the last variant of {product.sku}.")
        product.variants.remove(variant)
        del self._owners[variant.sku]
        self._bus.publish(
            "product.changed", sku=product.sku, fields=["variants"], variant=variant.sku
        )
        return variant

    def _new_variant(
        self,
        product: Product,
        sku: str,
        options: dict[str, str],
        *,
        price: int | None,
        barcode: str | None,
        reorder_level: int | None,
        extra: dict[str, Any] | None = None,
    ) -> Variant:
        if extra:
            raise InvalidInput(f"Unknown variant fields: {', '.join(sorted(extra))}.")
        sku = normalize_sku(sku)
        taken = (
            sku in self._owners
            or any(v.sku == sku for v in product.variants)
            or (sku in self._data.products and sku != product.sku)
        )
        if taken:
            raise DuplicateSku(sku)
        for other in product.variants:
            if other.barcode is not None and barcode and other.barcode == normalize_barcode(barcode):
                raise DuplicateBarcode(other.barcode, other.sku)
        return Variant(
            sku=sku,
            options=self._clean_options(product, options, sku),
            price=None if price is None else self._clean_amount(price, "Price"),
            barcode=self._clean_barcode(barcode, sku),
            reorder_level=None if reorder_level is None else self._clean_level(reorder_level),
        )

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
    def _clean_options(product: Product, options: dict[str, str], owner: str) -> dict[str, str]:
        if not isinstance(options, dict):
            raise InvalidInput("Variant options are a mapping of option name to value.")
        cleaned: dict[str, str] = {}
        for name, value in options.items():
            name, value = str(name).strip(), str(value).strip()
            if not name or not value:
                raise InvalidInput("Option names and values can't be empty.")
            cleaned[name] = value
        for other in product.variants:
            if other.sku != owner and other.options == cleaned:
                raise InvalidInput(f"{other.sku} already has those options.")
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
            for variant in product.variants:
                if variant.barcode == code and variant.sku != owner:
                    raise DuplicateBarcode(code, variant.sku)
        return code

    @staticmethod
    def _clean_tax_class(tax_class: str) -> str:
        if tax_class not in TAX_CLASSES:
            raise InvalidInput(f"Tax class must be one of {', '.join(TAX_CLASSES)}.")
        return tax_class
