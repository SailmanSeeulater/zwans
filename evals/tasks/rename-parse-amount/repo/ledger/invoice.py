"""Invoices made of line items whose prices come in as text."""

from ledger.money import format_cents, parse_amt


def line_total(quantity: int, unit_price: str) -> int:
    return quantity * parse_amt(unit_price)


def invoice_total(lines: list[tuple[int, str]], discount: str = "0") -> int:
    subtotal = sum(line_total(quantity, price) for quantity, price in lines)
    return subtotal - parse_amt(discount)


def render_invoice(lines: list[tuple[int, str]], discount: str = "0") -> str:
    rows = [f"{quantity} x {price}" for quantity, price in lines]
    rows.append(f"total {format_cents(invoice_total(lines, discount))}")
    return "\n".join(rows)
