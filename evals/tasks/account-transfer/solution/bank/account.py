"""A bank account that keeps a history of every change to its balance."""

from dataclasses import dataclass
from decimal import Decimal


class InvalidAmount(ValueError):
    """An amount that is zero, negative or has more than two decimal places."""


class InsufficientFunds(Exception):
    """The account does not hold enough money."""

    def __init__(self, balance: Decimal, amount: Decimal) -> None:
        super().__init__(f"cannot take {amount} from a balance of {balance}")
        self.balance = balance
        self.amount = amount


@dataclass(frozen=True)
class Entry:
    kind: str  # "deposit", "withdrawal", "transfer_out" or "transfer_in"
    amount: Decimal
    balance: Decimal  # the balance after this entry
    note: str = ""


def _check_amount(amount: Decimal | int | str) -> Decimal:
    value = Decimal(amount)
    if value <= 0 or value != value.quantize(Decimal("0.01")):
        raise InvalidAmount(f"not a valid amount: {amount}")
    return value


class Account:
    def __init__(self, owner: str, balance: Decimal | int | str = 0) -> None:
        self.owner = owner
        self._balance = Decimal(balance)
        self._history: list[Entry] = []

    @property
    def balance(self) -> Decimal:
        return self._balance

    @property
    def history(self) -> list[Entry]:
        return list(self._history)

    def _record(self, kind: str, amount: Decimal, note: str) -> Entry:
        entry = Entry(kind=kind, amount=amount, balance=self._balance, note=note)
        self._history.append(entry)
        return entry

    def deposit(self, amount: Decimal | int | str, note: str = "") -> Entry:
        value = _check_amount(amount)
        self._balance += value
        return self._record("deposit", value, note)

    def withdraw(self, amount: Decimal | int | str, note: str = "") -> Entry:
        value = _check_amount(amount)
        if value > self._balance:
            raise InsufficientFunds(self._balance, value)
        self._balance -= value
        return self._record("withdrawal", value, note)

    def transfer(self, other: "Account", amount: Decimal | int | str, note: str = "") -> Entry:
        if other is self:
            raise ValueError("cannot transfer to the same account")
        value = _check_amount(amount)
        if value > self._balance:
            raise InsufficientFunds(self._balance, value)
        self._balance -= value
        other._balance += value
        other._record("transfer_in", value, note)
        return self._record("transfer_out", value, note)

    def __repr__(self) -> str:
        return f"Account({self.owner!r}, balance={self._balance})"
