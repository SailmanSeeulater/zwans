import pytest
from conftest import MUG_EAN, TEA_EAN, sell

from shopdesk.errors import InvalidInput, OutOfStock, UnknownCart
from shopdesk.sales.invoices import render_invoice


def test_cart_lines_merge_and_price(stocked) -> None:
    cart = stocked.new_cart()
    stocked.cart_add(cart, "MUG-01", 2)
    stocked.cart_add(cart, "mug-01", 1)
    stocked.cart_add(cart, "TEA-07")
    view = stocked.cart(cart)
    assert [(line.sku, line.name, line.qty) for line in view.lines] == [
        ("MUG-01", "Blue mug", 3),
        ("TEA-07", "Green tea, 100 g", 1),
    ]
    assert (view.subtotal, view.total, view.units) == (4200, 4200, 4)
    stocked.cart_set(cart, "MUG-01", 0)
    assert [line.sku for line in stocked.cart(cart).lines] == ["TEA-07"]


def test_inactive_products_cant_go_in_a_cart(stocked) -> None:
    stocked.catalog.set_active("KET-02", False)
    with pytest.raises(InvalidInput):
        stocked.cart_add(stocked.new_cart(), "KET-02")


def test_checkout_picks_in_warehouse_priority_order(stocked) -> None:
    order = stocked.order(sell(stocked, "Ann", ("MUG-01", 22)))
    [line] = order.lines
    assert [(a.warehouse, a.qty) for a in line.allocations] == [("MAIN", 20), ("WEST", 2)]
    assert stocked.ledger.by_warehouse("MUG-01") == {"MAIN": 0, "WEST": 3}
    assert (order.status, order.total, order.customer) == ("placed", 22 * 1250, "Ann")


def test_checkout_from_one_warehouse(stocked) -> None:
    cart = stocked.new_cart()
    stocked.cart_add(cart, "MUG-01", 4)
    order = stocked.checkout(cart, "Ann", warehouse="WEST")
    assert [(a.warehouse, a.qty) for a in order.lines[0].allocations] == [("WEST", 4)]


def test_checkout_is_all_or_nothing(stocked) -> None:
    cart = stocked.new_cart()
    stocked.cart_add(cart, "MUG-01", 5)
    stocked.cart_add(cart, "KET-02", 7)
    with pytest.raises(OutOfStock):
        stocked.checkout(cart, "Ann")
    assert stocked.stock("MUG-01") == 25
    assert stocked.orders() == []
    assert len(stocked.cart(cart).lines) == 2


def test_checkout_empties_the_cart(stocked) -> None:
    cart = stocked.new_cart()
    stocked.cart_add(cart, "TEA-07", 2)
    stocked.checkout(cart, "Ann")
    with pytest.raises(UnknownCart):
        stocked.cart(cart)


def test_cancelling_puts_stock_back_where_it_came_from(stocked) -> None:
    number = sell(stocked, "Ann", ("MUG-01", 22), ("TEA-07", 3))
    stocked.cancel_order(number)
    assert stocked.ledger.by_warehouse("MUG-01") == {"MAIN": 20, "WEST": 5}
    assert stocked.stock("TEA-07") == 40
    assert stocked.order(number).status == "cancelled"
    with pytest.raises(InvalidInput):
        stocked.cancel_order(number)


def test_order_lines_keep_name_price_and_discount(stocked) -> None:
    stocked.add_discount("MUG10", "percent", 10, target_kind="product", target="MUG-01")
    order = stocked.order(sell(stocked, "Ann", ("MUG-01", 3), code="MUG10"))
    stocked.update_product("MUG-01", price=9999, name="Renamed")
    [line] = order.lines
    assert (line.sku, line.name, line.unit_price, line.discount, line.net) == (
        "MUG-01", "Blue mug", 1250, 375, 3375,
    )


def test_invoice_adds_vat_per_tax_class(stocked) -> None:
    number = sell(stocked, "Ann", ("MUG-01", 1), ("TEA-07", 3))
    invoice = stocked.invoice_order(number)
    assert invoice.number == "INV-2026-0001"
    assert [(t.tax_class, t.net, t.tax) for t in invoice.taxes] == [
        ("reduced", 1350, 68),
        ("standard", 1250, 250),
    ]
    assert (invoice.net_total, invoice.tax_total, invoice.gross_total) == (2600, 318, 2918)
    assert stocked.order(number).status == "invoiced"


def test_invoice_lines_show_sku_ean_and_description(stocked) -> None:
    invoice = stocked.invoice_order(sell(stocked, "Ann", ("MUG-01", 2), ("TEA-07", 1)))
    assert [(line.sku, line.gtin, line.description) for line in invoice.lines] == [
        ("MUG-01", MUG_EAN, "Blue mug"),
        ("TEA-07", TEA_EAN, "Green tea, 100 g"),
    ]
    text = render_invoice(invoice, stocked.settings)
    assert MUG_EAN in text and "Total GBP" in text and "34.73" in text


def test_vat_is_rounded_once_per_class_not_per_line(stocked) -> None:
    stocked.add_product("PEN-1", "Pen", 2)
    stocked.add_product("PAD-1", "Pad", 2)
    stocked.receive("PEN-1", "MAIN", 10)
    stocked.receive("PAD-1", "MAIN", 10)
    invoice = stocked.invoice_order(sell(stocked, "Ann", ("PEN-1", 1), ("PAD-1", 1)))
    assert invoice.tax_total == 1  # 0.4 + 0.4 per line would round to 0


def test_invoiced_orders_cant_be_cancelled_or_invoiced_twice(stocked) -> None:
    number = sell(stocked, "Ann", ("TEA-07", 1))
    stocked.invoice_order(number)
    with pytest.raises(InvalidInput):
        stocked.cancel_order(number)
    with pytest.raises(InvalidInput):
        stocked.invoice_order(number)


def test_order_numbers_count_up(stocked) -> None:
    first = sell(stocked, "Ann", ("TEA-07", 1))
    second = sell(stocked, "Bob", ("TEA-07", 1))
    assert (first, second) == ("SO-000001", "SO-000002")
    assert [n.payload["lines"] for n in stocked.outbox() if n.topic == "order.placed"][1] == [
        {"sku": "TEA-07", "name": "Green tea, 100 g", "qty": 1}
    ]
