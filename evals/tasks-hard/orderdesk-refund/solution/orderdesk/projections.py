"""Read models (projections) for the CLI's views and reports.

Each read model is a callable taking one event. At start-up it is fed the whole event log,
then it is subscribed to the bus. Read models never look at the aggregate: everything they
know comes from the events, which is why each one keeps the little bits of state it needs.
Events a read model does not care about are ignored.
"""

from dataclasses import dataclass

from .events import Event, OrderCancelled, OrderPlaced, OrderRefunded, OrderShipped, PaymentCaptured


@dataclass
class OrderRow:
    order_id: str
    customer: str
    status: str
    total_cents: int
    paid_cents: int = 0
    refunded_cents: int = 0


class OrderList:
    """One row per order, for `orderdesk list`. Statuses match OrderState's."""

    def __init__(self) -> None:
        self._rows: dict[str, OrderRow] = {}

    def __call__(self, ev: Event) -> None:
        if isinstance(ev, OrderPlaced):
            self._rows[ev.order_id] = OrderRow(ev.order_id, ev.customer, "placed", ev.total_cents)
        elif isinstance(ev, PaymentCaptured):
            row = self._rows[ev.order_id]
            row.paid_cents += ev.amount_cents
            if row.paid_cents >= row.total_cents:
                row.status = "paid"
        elif isinstance(ev, OrderShipped):
            self._rows[ev.order_id].status = "shipped"
        elif isinstance(ev, OrderCancelled):
            row = self._rows[ev.order_id]
            row.status = "cancelled"
            row.refunded_cents += ev.refund_cents
        elif isinstance(ev, OrderRefunded):
            row = self._rows[ev.order_id]
            row.refunded_cents += ev.amount_cents
            if row.refunded_cents >= row.paid_cents:
                row.status = "refunded"

    def rows(self, status: str | None = None) -> list[OrderRow]:
        rows = sorted(self._rows.values(), key=lambda row: row.order_id)
        return [row for row in rows if status is None or row.status == status]


@dataclass
class DayTotals:
    day: str
    gross_cents: int = 0  # money in
    refunds_cents: int = 0  # money given back

    @property
    def net_cents(self) -> int:
        return self.gross_cents - self.refunds_cents


class SalesReport:
    """Money in and out per calendar day (UTC), for `orderdesk report`.

    A payment counts on the day it was captured. Money given back counts on the day it was
    given back, not on the day it was originally paid, so a closed day never changes.
    """

    def __init__(self) -> None:
        self._days: dict[str, DayTotals] = {}

    def _day(self, day: str) -> DayTotals:
        return self._days.setdefault(day, DayTotals(day))

    def __call__(self, ev: Event) -> None:
        if isinstance(ev, PaymentCaptured):
            self._day(ev.day).gross_cents += ev.amount_cents
        elif isinstance(ev, OrderCancelled) and ev.refund_cents:
            self._day(ev.day).refunds_cents += ev.refund_cents
        elif isinstance(ev, OrderRefunded):
            self._day(ev.day).refunds_cents += ev.amount_cents

    def days(self) -> list[DayTotals]:
        return [self._days[day] for day in sorted(self._days)]

    def total(self) -> DayTotals:
        total = DayTotals("total")
        for day in self._days.values():
            total.gross_cents += day.gross_cents
            total.refunds_cents += day.refunds_cents
        return total


@dataclass
class CustomerFigures:
    customer: str
    orders: int = 0
    spent_cents: int = 0  # what they paid us, minus what we gave back


class CustomerLedger:
    """Lifetime figures per customer, for `orderdesk customers`."""

    def __init__(self) -> None:
        self._customers: dict[str, CustomerFigures] = {}
        self._customer_of: dict[str, str] = {}  # order id -> customer

    def __call__(self, ev: Event) -> None:
        if isinstance(ev, OrderPlaced):
            self._customer_of[ev.order_id] = ev.customer
            figures = self._customers.setdefault(ev.customer, CustomerFigures(ev.customer))
            figures.orders += 1
        elif isinstance(ev, PaymentCaptured):
            self._figures(ev.order_id).spent_cents += ev.amount_cents
        elif isinstance(ev, OrderCancelled):
            self._figures(ev.order_id).spent_cents -= ev.refund_cents
        elif isinstance(ev, OrderRefunded):
            self._figures(ev.order_id).spent_cents -= ev.amount_cents

    def _figures(self, order_id: str) -> CustomerFigures:
        return self._customers[self._customer_of[order_id]]

    def customers(self) -> list[CustomerFigures]:
        return [self._customers[name] for name in sorted(self._customers)]
