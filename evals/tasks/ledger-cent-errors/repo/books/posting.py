"""Turn business events into ledger entries."""

from books.allocate import allocate
from books.invoice import Invoice
from books.ledger import Ledger, Line
from books.money import ZERO, Money

RECEIVABLE = "assets:receivable"
BANK = "assets:bank"
SALES = "income:sales"
DISCOUNTS = "income:discounts"
TAX = "liabilities:sales-tax"


def post_invoice(ledger: Ledger, invoice: Invoice) -> None:
    """Receivable for the total; each line to sales; discount and tax to their accounts."""
    lines = [Line(RECEIVABLE, debit=invoice.total)]
    if invoice.discount > ZERO:
        lines.append(Line(DISCOUNTS, debit=invoice.discount))
    lines += [Line(SALES, credit=item.amount) for item in invoice.lines]
    if invoice.tax > ZERO:
        lines.append(Line(TAX, credit=invoice.tax))
    ledger.post(f"invoice {invoice.number} for {invoice.customer}", lines)


def post_payment(ledger: Ledger, customer: str, amount: Money) -> None:
    ledger.post(
        f"payment from {customer}",
        [Line(BANK, debit=amount), Line(RECEIVABLE, credit=amount)],
    )


def post_shared_expense(ledger: Ledger, memo: str, amount: Money, centres: dict[str, int]) -> None:
    """Pay an expense from the bank, split across cost centres by weight."""
    parts = allocate(amount, list(centres.values()))
    lines = [
        Line(f"expenses:{centre}", debit=part)
        for centre, part in zip(centres, parts, strict=True)
        if part > ZERO
    ]
    ledger.post(memo, [*lines, Line(BANK, credit=amount)])
