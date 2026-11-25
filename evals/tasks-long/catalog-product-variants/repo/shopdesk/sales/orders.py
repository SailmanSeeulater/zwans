"""Orders. Checkout turns a cart into an order: it prices the cart one last time, picks
the stock from the warehouses (in priority order, or only the one asked for) and ships it.
Either every line can be picked or nothing happens."""

from shopdesk.catalog.products import ProductCatalog
from shopdesk.clock import Clock
from shopdesk.config import Settings
from shopdesk.errors import InvalidInput, OutOfStock, UnknownOrder
from shopdesk.events import EventBus
from shopdesk.models import Allocation, Order, OrderLine, ShopData
from shopdesk.sales.carts import Carts
from shopdesk.stock.ledger import StockLedger
from shopdesk.stock.warehouses import Warehouses

STATUSES = ("placed", "invoiced", "cancelled")


class OrderDesk:
    def __init__(
        self,
        data: ShopData,
        catalog: ProductCatalog,
        carts: Carts,
        ledger: StockLedger,
        warehouses: Warehouses,
        settings: Settings,
        bus: EventBus,
        clock: Clock,
    ) -> None:
        self._data = data
        self._catalog = catalog
        self._carts = carts
        self._ledger = ledger
        self._warehouses = warehouses
        self._settings = settings
        self._bus = bus
        self._clock = clock

    def get(self, number: str) -> Order:
        try:
            return self._data.orders[number.strip().upper()]
        except KeyError:
            raise UnknownOrder(number) from None

    def all(self, status: str | None = None) -> list[Order]:
        if status is not None and status not in STATUSES:
            raise InvalidInput(f"Order status is one of {', '.join(STATUSES)}.")
        orders = sorted(self._data.orders.values(), key=lambda o: o.number)
        return [o for o in orders if status is None or o.status == status]

    def checkout(self, cart_id: str, customer: str, warehouse: str | None = None) -> Order:
        view = self._carts.view(cart_id)
        if not view.lines:
            raise InvalidInput(f"Cart {view.id} is empty.")
        customer = customer.strip()
        if not customer:
            raise InvalidInput("An order needs a customer.")
        sources = [self._warehouses.get(warehouse).code] if warehouse else self._warehouses.codes()
        if not sources:
            raise InvalidInput("There are no warehouses to ship from.")

        picks = [self._pick(line.sku, line.qty, sources) for line in view.lines]
        number = f"{self._settings.order_prefix}-{self._data.next_id('order'):06d}"
        lines = []
        with self._bus.held():
            for line, allocations in zip(view.lines, picks, strict=True):
                for allocation in allocations:
                    self._ledger.record(
                        line.sku, allocation.warehouse, -allocation.qty, "sale", number
                    )
                lines.append(
                    OrderLine(
                        sku=line.sku,
                        name=line.name,
                        qty=line.qty,
                        unit_price=line.unit_price,
                        discount=line.discount,
                        allocations=allocations,
                    )
                )
            order = Order(
                number=number,
                placed_at=self._clock(),
                customer=customer,
                lines=lines,
                price_list=view.price_list,
                code=view.code,
            )
            self._data.orders[number] = order
            self._carts.discard(view.id)
            self._bus.publish("order.placed", number=number, customer=customer)
        return order

    def _pick(self, sku: str, qty: int, sources: list[str]) -> list[Allocation]:
        allocations = []
        wanted = qty
        for code in sources:
            available = self._ledger.on_hand(sku, code)
            take = min(available, wanted)
            if take > 0:
                allocations.append(Allocation(code, take))
                wanted -= take
            if wanted == 0:
                return allocations
        raise OutOfStock(sku, qty, qty - wanted)

    def cancel(self, number: str) -> Order:
        order = self.get(number)
        if order.status == "cancelled":
            raise InvalidInput(f"Order {order.number} is already cancelled.")
        if order.status == "invoiced":
            raise InvalidInput(f"Order {order.number} is invoiced; issue a credit note instead.")
        with self._bus.held():
            for line in order.lines:
                for allocation in line.allocations:
                    self._ledger.record(
                        line.sku, allocation.warehouse, allocation.qty, "return", order.number
                    )
            order.status = "cancelled"
            order.cancelled_at = self._clock()
            self._bus.publish("order.cancelled", number=order.number, customer=order.customer)
        return order

    def mark_invoiced(self, number: str, invoice: str) -> None:
        order = self.get(number)
        order.status = "invoiced"
        order.invoice = invoice
