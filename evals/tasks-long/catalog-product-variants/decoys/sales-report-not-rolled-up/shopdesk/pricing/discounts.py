"""Discounts. A discount takes a percentage or a fixed amount off each unit, for every
product, one category (and the categories below it) or one product (all its variants).
Automatic discounts apply by themselves; the others when their code is entered on the
cart. A cart line gets the single best discount it qualifies for; discounts never stack."""

from shopdesk.catalog.categories import CategoryTree
from shopdesk.catalog.products import ProductCatalog
from shopdesk.clock import Clock, day, parse_day
from shopdesk.errors import InvalidInput, UnknownDiscount
from shopdesk.events import EventBus
from shopdesk.models import Discount, Product, ShopData
from shopdesk.money import percent_of

KINDS = ("percent", "amount")
TARGETS = ("all", "category", "product")


class Discounts:
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

    def add(
        self,
        code: str,
        kind: str,
        value: int,
        *,
        target_kind: str = "all",
        target: str | None = None,
        min_qty: int = 1,
        auto: bool = False,
        starts: str | None = None,
        ends: str | None = None,
    ) -> Discount:
        code = code.strip().upper()
        if not code or not code.replace("-", "").isalnum():
            raise InvalidInput(f"{code!r} is not a valid discount code.")
        if code in self._data.discounts:
            raise InvalidInput(f"Discount {code} already exists.")
        if kind not in KINDS:
            raise InvalidInput(f"Discount kind must be one of {', '.join(KINDS)}.")
        if kind == "percent" and not 0 < value <= 100:
            raise InvalidInput("A percentage discount is between 1 and 100.")
        if kind == "amount" and value <= 0:
            raise InvalidInput("An amount discount must be positive.")
        if target_kind not in TARGETS:
            raise InvalidInput(f"Discount target must be one of {', '.join(TARGETS)}.")
        if target_kind == "category":
            target = self._categories.get(target or "").slug
        elif target_kind == "product":
            target = self._catalog.get(target or "").sku
        else:
            target = None
        if min_qty < 1:
            raise InvalidInput("Minimum quantity is at least 1.")
        starts = parse_day(starts) if starts else None
        ends = parse_day(ends) if ends else None
        if starts and ends and ends < starts:
            raise InvalidInput("A discount can't end before it starts.")
        discount = Discount(code, kind, value, target_kind, target, min_qty, auto, starts, ends)
        self._data.discounts[code] = discount
        self._bus.publish("discount.added", code=code)
        return discount

    def get(self, code: str) -> Discount:
        try:
            return self._data.discounts[code.strip().upper()]
        except KeyError:
            raise UnknownDiscount(code) from None

    def all(self) -> list[Discount]:
        return sorted(self._data.discounts.values(), key=lambda d: d.code)

    def deactivate(self, code: str) -> None:
        self.get(code).active = False
        self._bus.publish("discount.changed", code=code)

    # -- applying ----------------------------------------------------------------------

    def is_live(self, discount: Discount, today: str) -> bool:
        if not discount.active:
            return False
        if discount.starts and today < discount.starts:
            return False
        return not (discount.ends and today > discount.ends)

    def applies_to(self, discount: Discount, sku: str, product: Product) -> bool:
        if discount.target_kind == "all":
            return True
        if discount.target_kind == "category":
            if product.category is None or discount.target is None:
                return False
            return product.category in self._categories.descendants(discount.target)
        return discount.target == product.sku

    @staticmethod
    def amount_off(discount: Discount, unit_price: int, qty: int) -> int:
        gross = unit_price * qty
        if discount.kind == "percent":
            return percent_of(gross, discount.value)
        return min(gross, discount.value * qty)

    def best_for_line(
        self,
        sku: str,
        product: Product,
        unit_price: int,
        qty: int,
        code: str | None,
        today: str | None = None,
    ) -> tuple[Discount | None, int]:
        """The best discount for a line and how much it takes off, in cents."""
        today = today or day(self._clock())
        entered = code.strip().upper() if code else None
        best: tuple[Discount | None, int] = (None, 0)
        for discount in self.all():
            if not (discount.auto or discount.code == entered):
                continue
            if not self.is_live(discount, today) or qty < discount.min_qty:
                continue
            if not self.applies_to(discount, sku, product):
                continue
            off = self.amount_off(discount, unit_price, qty)
            if off > best[1]:
                best = (discount, off)
        return best
