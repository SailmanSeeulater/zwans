"""Carts: what a customer (or the phone-order desk) is about to buy. A cart is priced
fresh every time it is viewed, so price changes show up until checkout."""

from dataclasses import dataclass

from shopdesk.catalog.products import ProductCatalog
from shopdesk.clock import Clock
from shopdesk.errors import InvalidInput, UnknownCart
from shopdesk.events import EventBus
from shopdesk.models import Cart, CartLine, ShopData
from shopdesk.pricing.discounts import Discounts
from shopdesk.pricing.engine import PriceEngine
from shopdesk.pricing.pricelists import PriceLists

MAX_QTY = 9999


@dataclass(frozen=True)
class CartLineView:
    sku: str
    name: str
    qty: int
    unit_price: int
    discount: int
    discount_code: str | None

    @property
    def total(self) -> int:
        return self.unit_price * self.qty - self.discount


@dataclass(frozen=True)
class CartView:
    id: str
    price_list: str | None
    code: str | None
    lines: list[CartLineView]

    @property
    def subtotal(self) -> int:
        return sum(line.unit_price * line.qty for line in self.lines)

    @property
    def discount(self) -> int:
        return sum(line.discount for line in self.lines)

    @property
    def total(self) -> int:
        return self.subtotal - self.discount

    @property
    def units(self) -> int:
        return sum(line.qty for line in self.lines)


class Carts:
    def __init__(
        self,
        data: ShopData,
        catalog: ProductCatalog,
        price_lists: PriceLists,
        discounts: Discounts,
        engine: PriceEngine,
        bus: EventBus,
        clock: Clock,
    ) -> None:
        self._data = data
        self._catalog = catalog
        self._price_lists = price_lists
        self._discounts = discounts
        self._engine = engine
        self._bus = bus
        self._clock = clock

    def create(self, price_list: str | None = None) -> Cart:
        if price_list is not None:
            price_list = self._price_lists.get_list(price_list).name
        cart = Cart(f"C{self._data.next_id('cart'):04d}", self._clock(), price_list)
        self._data.carts[cart.id] = cart
        return cart

    def get(self, cart_id: str) -> Cart:
        try:
            return self._data.carts[cart_id.strip().upper()]
        except KeyError:
            raise UnknownCart(cart_id) from None

    def add(self, cart_id: str, sku: str, qty: int = 1) -> Cart:
        cart = self.get(cart_id)
        product = self._catalog.get(sku)
        if not product.active:
            raise InvalidInput(f"{product.sku} is not for sale.")
        if qty <= 0:
            raise InvalidInput("Add at least one.")
        for line in cart.lines:
            if line.sku == product.sku:
                if line.qty + qty > MAX_QTY:
                    raise InvalidInput(f"At most {MAX_QTY} of one item.")
                line.qty += qty
                break
        else:
            cart.lines.append(CartLine(product.sku, qty))
        self._bus.publish("cart.changed", cart=cart.id, sku=product.sku)
        return cart

    def set_qty(self, cart_id: str, sku: str, qty: int) -> Cart:
        cart = self.get(cart_id)
        sku = sku.strip().upper()
        if not 0 <= qty <= MAX_QTY:
            raise InvalidInput(f"Quantity must be between 0 and {MAX_QTY}.")
        for line in cart.lines:
            if line.sku == sku:
                if qty == 0:
                    cart.lines.remove(line)
                else:
                    line.qty = qty
                self._bus.publish("cart.changed", cart=cart.id, sku=sku)
                return cart
        raise InvalidInput(f"{sku} is not in cart {cart.id}.")

    def remove(self, cart_id: str, sku: str) -> Cart:
        return self.set_qty(cart_id, sku, 0)

    def apply_code(self, cart_id: str, code: str | None) -> Cart:
        cart = self.get(cart_id)
        cart.code = self._discounts.get(code).code if code else None
        return cart

    def discard(self, cart_id: str) -> None:
        del self._data.carts[self.get(cart_id).id]

    def view(self, cart_id: str, today: str | None = None) -> CartView:
        cart = self.get(cart_id)
        lines = []
        for line in cart.lines:
            product = self._catalog.get(line.sku)
            priced = self._engine.price_line(line.sku, line.qty, cart.price_list, cart.code, today)
            lines.append(
                CartLineView(
                    sku=line.sku,
                    name=product.name,
                    qty=line.qty,
                    unit_price=priced.unit_price,
                    discount=priced.discount,
                    discount_code=priced.discount_code,
                )
            )
        return CartView(cart.id, cart.price_list, cart.code, lines)
