"""assert_consistent(shop) checks every invariant in docs/invariants.md.

It works things out from first principles (what the invoices list, what the movements
say), not from the code it is checking.
"""

from collections import Counter

from fulfil import Shop


def _round_half_up(numerator: int, denominator: int) -> int:
    return (2 * numerator + denominator) // (2 * denominator)


def _after_discount(subtotal: int, percent: int) -> int:
    return subtotal - _round_half_up(subtotal * percent, 100)


def shipped(shop: Shop, order_id: str) -> Counter:
    """sku -> units shipped for the order, according to its invoices."""
    units: Counter = Counter()
    for invoice in shop.invoices:
        if invoice.order_id == order_id:
            for line in invoice.lines:
                units[line.sku] += line.qty
    return units


def returned(shop: Shop, order_id: str) -> Counter:
    units: Counter = Counter()
    for note in shop.credit_notes:
        if note.order_id == order_id:
            units[note.sku] += note.qty
    return units


def assert_consistent(shop: Shop) -> None:
    inventory = shop.inventory
    skus = shop.catalog.skus()

    # 1. reserved = what open orders still have to ship
    outstanding: Counter = Counter()
    for order in shop.orders.values():
        if order.status == "cancelled" or order.cancelled_at:
            continue
        sent = shipped(shop, order.id)
        for line in order.lines:
            outstanding[line.sku] += line.qty - sent[line.sku]
    for sku in skus:
        assert inventory.reserved(sku) == outstanding[sku], (
            f"{sku}: reserved {inventory.reserved(sku)}, open {outstanding[sku]}"
        )
        # 2.
        assert 0 <= inventory.reserved(sku) <= inventory.on_hand(sku), sku

    # 3. on_hand is explained by the movements; 4. shipments match invoices
    moved: Counter = Counter()
    shipped_out: Counter = Counter()
    for movement in inventory.movements:
        assert movement.qty > 0, movement
        sign = -1 if movement.kind == "ship" else 1
        moved[movement.sku] += sign * movement.qty
        if movement.kind == "ship":
            shipped_out[movement.sku] += movement.qty
    invoiced_units: Counter = Counter()
    for order_id in shop.orders:
        invoiced_units.update(shipped(shop, order_id))
    for sku in skus:
        assert inventory.on_hand(sku) == moved[sku], sku
        assert shipped_out[sku] == invoiced_units[sku], (
            f"{sku}: shipped {shipped_out[sku]}, invoiced {invoiced_units[sku]}"
        )

    for order in shop.orders.values():
        prices = {line.sku: line.unit_price_cents for line in order.lines}
        ordered = {line.sku: line.qty for line in order.lines}
        invoices = shop.invoices_for(order.id)
        sent = shipped(shop, order.id)

        # 5. invoices are well-formed and list the order's goods at its prices
        for invoice in invoices:
            assert invoice.lines, invoice
            for line in invoice.lines:
                assert line.qty > 0, invoice
                assert line.unit_price_cents == prices[line.sku], invoice
            assert invoice.subtotal_cents == sum(
                line.qty * line.unit_price_cents for line in invoice.lines
            ), invoice
            assert (
                invoice.total_cents
                == invoice.subtotal_cents - invoice.discount_cents + invoice.shipping_cents
            )
            assert invoice.discount_cents >= 0 and invoice.shipping_cents >= 0, invoice
        for sku, qty in sent.items():
            assert qty <= ordered[sku], (
                f"{order.id}: shipped {qty} of {sku}, ordered {ordered[sku]}"
            )

        # 6. invoiced = what the shipped goods cost, shipping once
        shipped_subtotal = sum(qty * prices[sku] for sku, qty in sent.items())
        expected = _after_discount(shipped_subtotal, order.discount_percent)
        if sum(sent.values()):
            expected += order.shipping_cents
        assert sum(i.total_cents for i in invoices) == expected, (
            f"{order.id}: invoiced vs. shipped goods"
        )
        assert sum(i.shipping_cents for i in invoices) == (order.shipping_cents if sent else 0), (
            order.id
        )

        # 7. only shipped goods come back, once; 8. credits follow the same rule
        back = returned(shop, order.id)
        for sku, qty in back.items():
            assert qty <= sent[sku], f"{order.id}: returned {qty} of {sku}, shipped {sent[sku]}"
        returned_subtotal = sum(qty * prices[sku] for sku, qty in back.items())
        credited = sum(note.amount_cents for note in shop.credit_notes_for(order.id))
        assert credited == _after_discount(returned_subtotal, order.discount_percent), order.id
