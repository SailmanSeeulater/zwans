from conftest import MUG_EAN, TEE_EAN, sell

from shopdesk.sales.invoices import render_invoice


def test_cart_lines_are_per_variant_and_named_with_options(dressed) -> None:
    cart = dressed.new_cart()
    dressed.cart_add(cart, "TEE-M-BLUE", 1)
    dressed.cart_add(cart, "TEE-S-RED", 2)
    dressed.cart_add(cart, "tee-m-blue", 1)
    dressed.cart_add(cart, "MUG-01", 1)
    view = dressed.cart(cart)
    assert [(line.sku, line.name, line.qty, line.unit_price) for line in view.lines] == [
        ("TEE-M-BLUE", "Logo tee (colour: blue, size: M)", 2, 1700),
        ("TEE-S-RED", "Logo tee (colour: red, size: S)", 2, 1500),
        ("MUG-01", "Blue mug", 1, 1250),
    ]
    assert view.total == 3400 + 3000 + 1250


def test_order_lines_carry_the_variant_and_the_product(dressed) -> None:
    order = dressed.order(sell(dressed, "Ann", ("TEE-M-RED", 10), ("KET-02", 1)))
    tee, kettle = order.lines
    assert (tee.sku, tee.product_sku, tee.name) == (
        "TEE-M-RED", "TEE-01", "Logo tee (colour: red, size: M)",
    )
    assert [(a.warehouse, a.qty) for a in tee.allocations] == [("MAIN", 8), ("WEST", 2)]
    assert (kettle.sku, kettle.product_sku, kettle.name) == ("KET-02", "KET-02", "Red kettle")
    assert dressed.stock("TEE-M-RED") == 2
    assert dressed.stock("TEE-S-RED") == 10


def test_checkout_checks_stock_per_variant(dressed) -> None:
    cart = dressed.new_cart()
    dressed.cart_add(cart, "TEE-M-BLUE", 7)  # only 6, although the tee has 28 in all
    try:
        dressed.checkout(cart, "Ann")
    except Exception as exc:
        assert type(exc).__name__ == "OutOfStock"
    else:
        raise AssertionError("checkout should have failed")
    assert dressed.stock("TEE-M-BLUE") == 6


def test_cancelling_returns_each_variants_stock(dressed) -> None:
    number = sell(dressed, "Ann", ("TEE-M-RED", 10), ("TEE-M-BLUE", 6))
    dressed.cancel_order(number)
    assert dressed.ledger.by_warehouse("TEE-M-RED") == {"MAIN": 8, "WEST": 4}
    assert dressed.ledger.by_warehouse("TEE-M-BLUE") == {"MAIN": 0, "WEST": 6}


def test_invoice_lines_carry_variant_barcode_and_name(dressed) -> None:
    invoice = dressed.invoice_order(sell(dressed, "Ann", ("TEE-M-BLUE", 1), ("MUG-01", 2)))
    assert [(l.sku, l.product_sku, l.gtin, l.description) for l in invoice.lines] == [
        ("TEE-M-BLUE", "TEE-01", TEE_EAN["TEE-M-BLUE"], "Logo tee (colour: blue, size: M)"),
        ("MUG-01", "MUG-01", MUG_EAN, "Blue mug"),
    ]
    assert invoice.net_total == 1700 + 2500
    assert invoice.tax_total == 840
    text = render_invoice(invoice, dressed.settings)
    assert TEE_EAN["TEE-M-BLUE"] in text and "TEE-M-BLUE" in text


def test_a_variant_without_a_barcode_has_no_ean_on_the_invoice(dressed) -> None:
    dressed.add_variant("MUG-01", "MUG-01-GRN", {"glaze": "green"}, price=1350)
    dressed.receive("MUG-01-GRN", "MAIN", 3)
    invoice = dressed.invoice_order(sell(dressed, "Ann", ("MUG-01-GRN", 1)))
    [line] = invoice.lines
    assert (line.sku, line.gtin, line.description, line.unit_price) == (
        "MUG-01-GRN", None, "Blue mug (glaze: green)", 1350,
    )


def test_the_order_notification_names_variants(dressed) -> None:
    sell(dressed, "Ann", ("TEE-S-RED", 1))
    [note] = [n for n in dressed.outbox() if n.topic == "order.placed"]
    assert note.payload["lines"] == [
        {"sku": "TEE-S-RED", "name": "Logo tee (colour: red, size: S)", "qty": 1}
    ]
