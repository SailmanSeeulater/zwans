import pytest

from books.ledger import Ledger, Line, UnbalancedEntry
from books.money import format_amount, parse_amount
from books.posting import BANK, RECEIVABLE, post_invoice, post_payment
from books.invoice import Invoice


def test_post_and_balance() -> None:
    ledger = Ledger()
    ledger.post(
        "rent",
        [
            Line("expenses:rent", debit=parse_amount("800.00")),
            Line(BANK, credit=parse_amount("800.00")),
        ],
    )

    assert format_amount(ledger.balance(BANK)) == "-800.00"
    assert ledger.trial_balance() == 0


def test_unbalanced_entry_is_rejected() -> None:
    ledger = Ledger()

    with pytest.raises(UnbalancedEntry):
        ledger.post(
            "oops",
            [Line(BANK, debit=parse_amount("5.00")), Line(RECEIVABLE, credit=parse_amount("4.00"))],
        )
    assert ledger.entries == []


def test_post_invoice_and_payment() -> None:
    ledger = Ledger()
    invoice = Invoice("A-2", "Acme", discount_percent="10", tax_percent="8.25")
    invoice.add("Lamp", 2, "9.99")
    invoice.add("Bulb", 3, "3.35")
    invoice.add("Cable", 4, "1.10")

    post_invoice(ledger, invoice)
    post_payment(ledger, "Acme", invoice.total)

    assert format_amount(ledger.balance(BANK)) == "33.55"
    assert ledger.balance(RECEIVABLE) == 0
    assert ledger.trial_balance() == 0
