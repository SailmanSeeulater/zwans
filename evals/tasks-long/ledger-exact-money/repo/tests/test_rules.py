import pytest

from billfold import Book, ValidationError
from billfold.rules import condition_text, parse_condition


@pytest.mark.parametrize("text", [
    "payee~netflix", "payee=Netflix", "memo^rent", "payee/^ACME \\d+/", "account=Checking",
    "amount=9.5", "amount<20", "amount<=20", "amount>5", "amount>=5", "amount=10..20",
])
def test_conditions_read_back_the_same(text: str) -> None:
    condition = parse_condition(text)
    assert parse_condition(condition_text(condition)) == condition


def test_bad_conditions_are_refused() -> None:
    for text in ("payee", "amount=abc", "colour=red", "payee/(/"):
        with pytest.raises(ValidationError):
            parse_condition(text)


def test_rules_categorise_new_transactions(book: Book) -> None:
    book.add_account("Checking")
    book.add_rule("Streaming", ["payee~netflix"], category="Subscriptions")
    book.add_rule("Small coffee", ["payee~cafe", "amount<5"], category="Food:Coffee")
    a = book.add_transaction("Checking", "2026-03-02", "-15.99", payee="NETFLIX.COM")
    b = book.add_transaction("Checking", "2026-03-02", "-3.50", payee="Cafe Lotte")
    c = book.add_transaction("Checking", "2026-03-02", "-23.50", payee="Cafe Lotte")
    d = book.add_transaction("Checking", "2026-03-02", "-3.50", payee="Cafe Lotte",
                             category="Gifts")
    assert (a.category, b.category, c.category, d.category) == (
        "Subscriptions", "Food:Coffee", None, "Gifts")


def test_priority_decides_between_rules(book: Book) -> None:
    book.add_account("Checking")
    book.add_rule("Shop", ["payee~amazon"], category="Shopping", priority=100)
    book.add_rule("Books", ["payee~amazon", "memo~book"], category="Books", priority=10)
    txn = book.add_transaction("Checking", "2026-03-02", "-12.00", payee="Amazon",
                               memo="book order")
    assert txn.category == "Books"


def test_amount_ranges_ignore_the_sign(book: Book) -> None:
    book.add_account("Checking")
    book.add_rule("Mid", ["amount=10..20"], category="Mid")
    assert book.add_transaction("Checking", "2026-03-02", "-10.00").category == "Mid"
    assert book.add_transaction("Checking", "2026-03-02", "20.00").category == "Mid"
    assert book.add_transaction("Checking", "2026-03-02", "-20.50").category is None


def test_split_rule_shares_by_percent(book: Book) -> None:
    book.add_account("Checking")
    book.add_rule("Costco", ["payee~costco"],
                  split={"Food:Groceries": "75", "Household": "25"})
    txn = book.add_transaction("Checking", "2026-03-02", "-80.00", payee="COSTCO 123")
    assert [(s.category, s.amount) for s in txn.splits] == [
        ("Food:Groceries", -60), ("Household", -20)]


def test_split_percentages_must_make_100(book: Book) -> None:
    with pytest.raises(ValidationError):
        book.add_rule("Bad", ["payee~x"], split={"A": "60", "B": "30"})


def test_rename_and_tags(book: Book) -> None:
    book.add_account("Checking")
    book.add_rule("Tidy", ["payee/^PAYPAL \\*SPOTIFY/"], rename="Spotify",
                  category="Subscriptions", tags=["music"])
    txn = book.add_transaction("Checking", "2026-03-02", "-9.50", payee="PAYPAL *SPOTIFY 991")
    assert (txn.payee, txn.category, txn.tags) == ("Spotify", "Subscriptions", ["music"])


def test_recategorise_runs_rules_over_old_transactions(book: Book) -> None:
    book.add_account("Checking")
    txn = book.add_transaction("Checking", "2026-03-02", "-9.50", payee="Spotify")
    book.add_rule("Music", ["payee=spotify"], category="Subscriptions")
    assert book.recategorise() == 1
    assert book.transaction(txn.id).category == "Subscriptions"
    book.undo()
    assert book.transaction(txn.id).category is None
