import pytest

from books.allocate import allocate
from books.invoice import Invoice
from books.ledger import Ledger
from books.money import format_amount, parse_amount, percent_of, round_cents
from books.posting import (
    BANK,
    DISCOUNTS,
    RECEIVABLE,
    SALES,
    TAX,
    post_invoice,
    post_payment,
    post_shared_expense,
)
from books.report import trial_balance_report


def invoice(items: list[tuple[int, str]], discount: str = "0", tax: str = "0") -> Invoice:
    result = Invoice("T-1", "Test", discount_percent=discount, tax_percent=tax)
    for quantity, price in items:
        result.add("item", quantity, price)
    return result


# Totals from the finance team's spreadsheet (round half up, to the cent).
SPREADSHEET = [
    ([(1, "26.75")], "0", "10", "2.68", "29.43"),
    ([(1, "1.25")], "0", "10", "0.13", "1.38"),
    ([(3, "8.95"), (2, "0.35")], "0", "10", "2.76", "30.31"),
    ([(1, "0.10"), (1, "0.20")], "0", "10", "0.03", "0.33"),
    ([(5, "4.45"), (1, "0.70"), (5, "1.10")], "5", "7", "1.89", "28.92"),
    ([(2, "9.99"), (3, "3.35"), (4, "1.10")], "10", "8.25", "2.56", "33.55"),
]


@pytest.mark.parametrize(
    ("items", "discount", "tax", "expected_tax", "expected_total"), SPREADSHEET
)
def test_invoice_matches_the_spreadsheet(
    items: list[tuple[int, str]], discount: str, tax: str, expected_tax: str, expected_total: str
) -> None:
    result = invoice(items, discount, tax)

    assert format_amount(result.tax) == expected_tax
    assert format_amount(result.total) == expected_total
    assert result.total == parse_amount(expected_total)


@pytest.mark.parametrize("items_discount_tax", [row[:3] for row in SPREADSHEET])
def test_every_spreadsheet_invoice_posts(items_discount_tax: tuple) -> None:
    items, discount, tax = items_discount_tax
    ledger = Ledger()
    result = invoice(items, discount, tax)

    post_invoice(ledger, result)

    assert ledger.balance(RECEIVABLE) == result.total
    assert ledger.balance(TAX) == -result.tax
    assert ledger.balance(SALES) == -result.subtotal
    assert ledger.trial_balance() == 0


def test_discount_rounds_half_up() -> None:
    result = invoice([(1, "26.75")], discount="10")

    assert format_amount(result.discount) == "2.68"
    assert format_amount(result.total) == "24.07"


@pytest.mark.parametrize(
    ("amount", "percent", "expected"),
    [
        ("26.75", "10", "2.68"),
        ("1.25", "10", "0.13"),
        ("0.90", "2.5", "0.02"),
        ("0.50", "5", "0.03"),
        ("27.55", "10", "2.76"),
        ("1.05", "50", "0.53"),
        ("2.01", "50", "1.01"),
        ("8.05", "10", "0.81"),
        ("1000.10", "0.05", "0.50"),
    ],
)
def test_percent_rounds_half_up(amount: str, percent: str, expected: str) -> None:
    result = percent_of(parse_amount(amount), percent)

    assert format_amount(result) == expected
    assert result == parse_amount(expected)


def test_round_cents_half_up() -> None:
    half = parse_amount("2.67") + (parse_amount("0.01") / 2)

    assert format_amount(round_cents(half)) == "2.68"


@pytest.mark.parametrize(
    ("amount", "weights", "expected"),
    [
        ("4.35", [1, 1, 1], ["1.45", "1.45", "1.45"]),
        ("0.29", [1, 1, 1], ["0.10", "0.10", "0.09"]),
        ("1.15", [1, 1, 1], ["0.39", "0.38", "0.38"]),
        ("100.00", [1, 1, 1], ["33.34", "33.33", "33.33"]),
        ("8.20", [1, 1, 1], ["2.74", "2.73", "2.73"]),
        ("10.00", [1, 2, 3], ["1.67", "3.33", "5.00"]),
        ("0.05", [1, 1, 1, 1, 1, 1], ["0.01", "0.01", "0.01", "0.01", "0.01", "0.00"]),
        ("57.35", [3, 0, 1], ["43.01", "0.00", "14.34"]),
    ],
)
def test_allocate(amount: str, weights: list[int], expected: list[str]) -> None:
    parts = allocate(parse_amount(amount), weights)

    assert [format_amount(part) for part in parts] == expected
    assert sum(parts) == parse_amount(amount)


def test_shared_expense_three_ways() -> None:
    ledger = Ledger()

    post_shared_expense(
        ledger, "coffee", parse_amount("4.35"), {"sales": 1, "support": 1, "dev": 1}
    )

    assert format_amount(ledger.balance(BANK)) == "-4.35"
    assert format_amount(ledger.balance("expenses:dev")) == "1.45"
    assert ledger.trial_balance() == 0


def test_many_small_payments_add_up_exactly() -> None:
    ledger = Ledger()
    for _ in range(1000):
        post_payment(ledger, "Kiosk", parse_amount("0.10"))

    assert ledger.balance(BANK) == parse_amount("100.00")
    assert ledger.balance(RECEIVABLE) == parse_amount("-100.00")
    assert ledger.trial_balance() == 0


def test_a_month_of_books() -> None:
    ledger = Ledger()
    for number, (items, discount, tax, _, _) in enumerate(SPREADSHEET):
        result = invoice(items, discount, tax)
        result.number = f"M-{number}"
        post_invoice(ledger, result)
        post_payment(ledger, "Test", result.total)
    post_shared_expense(ledger, "rent", parse_amount("1,000.01"), {"a": 1, "b": 1, "c": 1})
    post_shared_expense(ledger, "cleaning", parse_amount("57.35"), {"a": 3, "b": 0, "c": 1})

    assert ledger.trial_balance() == 0
    assert ledger.balance(RECEIVABLE) == 0
    assert format_amount(ledger.balance(BANK)) == "-933.44"
    assert format_amount(ledger.balance(DISCOUNTS)) == "4.86"
    last = trial_balance_report(ledger).splitlines()[-1]
    assert last.split()[1] == last.split()[2]
