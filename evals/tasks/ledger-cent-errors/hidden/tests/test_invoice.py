from books.invoice import Invoice
from books.money import format_amount


def test_invoice_with_tax() -> None:
    invoice = Invoice("A-1", "Acme", tax_percent="8.25")
    invoice.add("Mug", 2, "12.50")
    invoice.add("Poster", 1, "19.95")

    assert format_amount(invoice.subtotal) == "44.95"
    assert format_amount(invoice.tax) == "3.71"
    assert format_amount(invoice.total) == "48.66"


def test_invoice_with_discount() -> None:
    invoice = Invoice("A-2", "Acme", discount_percent="10", tax_percent="8.25")
    invoice.add("Lamp", 2, "9.99")
    invoice.add("Bulb", 3, "3.35")
    invoice.add("Cable", 4, "1.10")

    assert format_amount(invoice.subtotal) == "34.43"
    assert format_amount(invoice.discount) == "3.44"
    assert format_amount(invoice.tax) == "2.56"
    assert format_amount(invoice.total) == "33.55"
