from decimal import Decimal

import pytest

from bank import Account, InsufficientFunds, InvalidAmount


def test_deposit_and_withdraw() -> None:
    account = Account("ana")
    account.deposit("10.50", note="pocket money")
    entry = account.withdraw(4)

    assert account.balance == Decimal("6.50")
    assert entry.kind == "withdrawal"
    assert entry.balance == Decimal("6.50")
    assert [e.kind for e in account.history] == ["deposit", "withdrawal"]
    assert account.history[0].note == "pocket money"


def test_cannot_overdraw() -> None:
    account = Account("ana", balance=5)

    with pytest.raises(InsufficientFunds):
        account.withdraw(6)
    assert account.balance == 5
    assert account.history == []


@pytest.mark.parametrize("amount", [0, -1, "0.001"])
def test_bad_amounts(amount: object) -> None:
    with pytest.raises(InvalidAmount):
        Account("ana").deposit(amount)  # type: ignore[arg-type]
