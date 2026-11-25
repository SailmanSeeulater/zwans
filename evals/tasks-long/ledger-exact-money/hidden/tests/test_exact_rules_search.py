"""Rule conditions, rule splits and search terms read amounts like any other amount."""

from decimal import Decimal

import pytest
from conftest import exact

from billfold import Book


def test_rule_amount_conditions_match_exactly(book: Book) -> None:
    book.add_account("Checking")
    book.add_rule("Streaming", ["amount=19.99"], category="Subscriptions")
    book.add_rule("Cheap", ["amount<=0.30"], category="Small")
    book.add_rule("Big", ["amount=1,234.50"], category="Big")
    assert book.add_transaction("Checking", "2026-03-02", "-19.99").category == "Subscriptions"
    assert book.add_transaction("Checking", "2026-03-02", "-0.30").category == "Small"
    assert book.add_transaction("Checking", "2026-03-02", "-0.31").category is None
    assert book.add_transaction("Checking", "2026-03-02", "1234.50").category == "Big"


def test_rule_amount_ranges_include_both_ends(book: Book) -> None:
    book.add_account("Checking")
    book.add_rule("Groceries", ["amount=0.10..19.99", "payee~market"], category="Food")
    assert book.add_transaction("Checking", "2026-03-02", "-0.10", payee="Market").category == "Food"
    assert book.add_transaction("Checking", "2026-03-02", "-19.99", payee="Market").category == "Food"
    assert book.add_transaction("Checking", "2026-03-02", "-20.00", payee="Market").category is None


def test_percentage_split_gives_leftover_cents_to_largest_remainders(book: Book) -> None:
    book.add_account("Checking")
    book.add_rule("Shared", ["payee~flat"],
                  split={"A": "25", "B": "25", "C": "25", "D": "25"})
    txn = book.add_transaction("Checking", "2026-03-02", "-10.05", payee="Flat costs")
    assert [str(s.amount) for s in txn.splits] == ["-2.52", "-2.51", "-2.51", "-2.51"]
    assert sum(s.amount for s in txn.splits) == Decimal("-10.05")


def test_percentage_split_leftover_is_not_simply_the_first(book: Book) -> None:
    book.add_account("Checking")
    book.add_rule("Thirds", ["payee~shop"], split={"Small": "20", "Big": "80"})
    txn = book.add_transaction("Checking", "2026-03-02", "-0.07", payee="Shop")
    # exact shares 1.4 and 5.6 cents: 1 + 5, and the leftover cent goes to Big (0.6 > 0.4)
    assert [str(s.amount) for s in txn.splits] == ["-0.01", "-0.06"]


def test_percentage_split_halves(book: Book) -> None:
    book.add_account("Checking")
    book.add_rule("Halves", ["payee~costco"], split={"Food": "50", "Household": "50"})
    txn = book.add_transaction("Checking", "2026-03-02", "-9.99", payee="COSTCO")
    assert [str(s.amount) for s in txn.splits] == ["-5.00", "-4.99"]


def test_split_percentages_are_exact(book: Book) -> None:
    book.add_account("Checking")
    book.add_rule("Thirds", ["payee~x"], split={"A": "33.3", "B": "33.3", "C": "33.4"})
    txn = book.add_transaction("Checking", "2026-03-02", "-10.00", payee="x")
    assert [str(s.amount) for s in txn.splits] == ["-3.33", "-3.33", "-3.34"]
    with pytest.raises(TypeError):
        book.add_rule("Floats", ["payee~y"], split={"A": 50.0, "B": 50.0})


def test_search_amounts_are_exact(pennies: Book) -> None:
    assert [t.payee for t in pennies.search("amount:19.99")] == ["Streamly"]
    assert [t.payee for t in pennies.search("amount:0.10")] == ["Kiosk"]
    assert [t.payee for t in pennies.search("amount<=0.20")] == ["Kiosk", "Kiosk"]
    assert [t.payee for t in pennies.search("amount>=19.99 acct:Checking")] == [
        "Streamly", "ACME GmbH"]
    assert [t.payee for t in pennies.search("amount:1,234.56")] == ["ACME GmbH"]
    assert [t.payee for t in pennies.search("amount:0.20..19.99")] == ["Kiosk", "Streamly"]


def test_search_results_carry_decimals(pennies: Book) -> None:
    (txn,) = pennies.search("amount:19.99")
    exact(txn.amount, "-19.99")
