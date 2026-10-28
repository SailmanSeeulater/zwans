from decimal import Decimal

import pytest

from bank import Account, Entry, InsufficientFunds, InvalidAmount


def test_transfer_moves_money_and_records_both_sides() -> None:
    ana = Account("ana", balance=100)
    ben = Account("ben", balance=5)

    entry = ana.transfer(ben, "30.25", note="rent")

    assert ana.balance == Decimal("69.75")
    assert ben.balance == Decimal("35.25")
    assert entry == Entry("transfer_out", Decimal("30.25"), Decimal("69.75"), "rent")
    assert ana.history == [entry]
    assert ben.history == [Entry("transfer_in", Decimal("30.25"), Decimal("35.25"), "rent")]


def test_transfer_note_is_optional() -> None:
    ana = Account("ana", balance=10)
    ben = Account("ben")

    ana.transfer(ben, 10)

    assert ana.balance == 0
    assert ben.balance == 10
    assert ana.history[0].note == ""
    assert ben.history[0].note == ""


def test_transfer_more_than_the_balance() -> None:
    ana = Account("ana", balance=10)
    ben = Account("ben", balance=1)

    with pytest.raises(InsufficientFunds):
        ana.transfer(ben, "10.01")

    assert ana.balance == 10
    assert ben.balance == 1
    assert ana.history == []
    assert ben.history == []


@pytest.mark.parametrize("amount", [0, -5, "1.234"])
def test_transfer_a_bad_amount(amount: object) -> None:
    ana = Account("ana", balance=10)
    ben = Account("ben")

    with pytest.raises(InvalidAmount):
        ana.transfer(ben, amount)  # type: ignore[arg-type]

    assert ana.balance == 10
    assert ben.balance == 0
    assert ana.history == []
    assert ben.history == []


def test_transfer_to_the_same_account() -> None:
    ana = Account("ana", balance=10)

    with pytest.raises(ValueError):
        ana.transfer(ana, 5)

    assert ana.balance == 10
    assert ana.history == []
