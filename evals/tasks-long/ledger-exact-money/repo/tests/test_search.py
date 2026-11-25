from billfold import Book


def ids(found) -> list[str]:
    return [t.payee for t in found]


def test_words_payee_and_category(household: Book) -> None:
    assert ids(household.search("rewe")) == ["REWE Markt"]
    assert ids(household.search("payee:cafe")) == ["Cafe Lotte"]
    assert ids(household.search("cat:Food acct:Checking")) == ["REWE Markt", "Cafe Lotte"]


def test_amount_terms(household: Book) -> None:
    assert ids(household.search("amount:42.50")) == ["REWE Markt"]
    assert ids(household.search("amount>1000")) == ["ACME GmbH", "Landlord"]
    assert ids(household.search("amount:10..50")) == ["REWE Markt", "Diner", "Cafe Lotte"]
    assert ids(household.search("amount<=12.25 acct:Checking")) == ["Cafe Lotte"]


def test_dates_and_tags(household: Book) -> None:
    household.add_transaction("Checking", "2026-03-20", "-30.00", payee="Hotel",
                              tags=["holiday"])
    assert ids(household.search("since:2026-03-05 until:2026-03-09")) == ["Cafe Lotte", "Landlord"]
    assert ids(household.search("#holiday")) == ["Hotel"]


def test_index_follows_edits(household: Book) -> None:
    txn = household.search("rewe")[0]
    household.edit_transaction(txn.id, payee="Aldi")
    assert household.search("rewe") == []
    assert ids(household.search("aldi")) == ["Aldi"]
