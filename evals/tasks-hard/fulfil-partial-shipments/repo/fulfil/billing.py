"""Invoices and credit notes.

The rules (see also docs/invariants.md):

- The discount on an amount of goods is the order's percentage of it, rounded half up to
  the cent (discount_for). Discounts never apply to shipping.
- What we have invoiced for an order is always exactly what its shipped goods cost: the
  subtotal of the shipped goods, less the order's discount on that subtotal, plus the
  order's shipping fee once anything has shipped (charge_for). In particular, once
  everything has shipped, the invoices add up to the order total.
- What we credit for returns works the same way: the credit notes for an order add up to
  the returned goods' subtotal less the order's discount on it. Shipping is never
  refunded.
"""

from dataclasses import dataclass

from .money import round_half_up
from .orders import Order


@dataclass(frozen=True)
class InvoiceLine:
    sku: str
    qty: int
    unit_price_cents: int

    @property
    def subtotal_cents(self) -> int:
        return self.qty * self.unit_price_cents


@dataclass(frozen=True)
class Invoice:
    number: str
    order_id: str
    issued_at: str
    lines: tuple[InvoiceLine, ...]
    subtotal_cents: int
    discount_cents: int
    shipping_cents: int

    @property
    def total_cents(self) -> int:
        return self.subtotal_cents - self.discount_cents + self.shipping_cents


@dataclass(frozen=True)
class CreditNote:
    number: str
    order_id: str
    issued_at: str
    sku: str
    qty: int
    amount_cents: int


def discount_for(subtotal_cents: int, percent: int) -> int:
    return round_half_up(subtotal_cents * percent, 100)


def goods_value(subtotal_cents: int, percent: int) -> int:
    """What goods with this subtotal cost after the discount."""
    return subtotal_cents - discount_for(subtotal_cents, percent)


def charge_for(goods_subtotal_cents: int, order: Order, *, with_shipping: bool) -> int:
    return goods_value(goods_subtotal_cents, order.discount_percent) + (
        order.shipping_cents if with_shipping else 0
    )


def order_total(order: Order) -> int:
    return charge_for(order.subtotal_cents, order, with_shipping=True)


def invoice_for_order(order: Order, number: str, at: str) -> Invoice:
    """The invoice for an order that ships in full."""
    lines = tuple(InvoiceLine(line.sku, line.qty, line.unit_price_cents) for line in order.lines)
    subtotal = sum(line.subtotal_cents for line in lines)
    return Invoice(
        number=number,
        order_id=order.id,
        issued_at=at,
        lines=lines,
        subtotal_cents=subtotal,
        discount_cents=discount_for(subtotal, order.discount_percent),
        shipping_cents=order.shipping_cents,
    )


def credit_amount(order: Order, returned_before_cents: int, returning_cents: int) -> int:
    """The credit for returning goods worth returning_cents (at order prices), when goods
    worth returned_before_cents were returned from the same order before.

    Worked out on the running total, so the credit notes for an order always add up to the
    returned goods' value after discount, whatever the rounding.
    """
    before = goods_value(returned_before_cents, order.discount_percent)
    after = goods_value(returned_before_cents + returning_cents, order.discount_percent)
    return after - before
