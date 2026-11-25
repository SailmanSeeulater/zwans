"""The things billfold keeps track of."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date

ACCOUNT_KINDS = ("checking", "savings", "credit", "cash", "investment")
FREQUENCIES = ("weekly", "fortnightly", "monthly", "quarterly", "yearly")
TEXT_FIELDS = ("payee", "memo", "account")
TEXT_OPS = ("contains", "equals", "starts", "regex")
NUMBER_OPS = ("eq", "lt", "le", "gt", "ge", "between")


@dataclass
class Account:
    id: str
    name: str
    currency: str = "EUR"
    kind: str = "checking"
    opening_balance: float = 0.0
    opened: date | None = None
    closed: bool = False
    notes: str = ""


@dataclass
class Split:
    category: str | None
    amount: float
    memo: str = ""


@dataclass
class Transaction:
    id: str
    account: str
    date: date
    amount: float
    payee: str = ""
    memo: str = ""
    category: str | None = None
    splits: list[Split] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    transfer_id: str | None = None
    recurring_id: str | None = None
    cleared: bool = False
    import_ref: str | None = None

    @property
    def is_split(self) -> bool:
        return bool(self.splits)

    @property
    def is_transfer(self) -> bool:
        return self.transfer_id is not None

    def category_amounts(self) -> list[tuple[str | None, float]]:
        """(category, amount) pairs: one per split, or the whole amount."""
        if self.splits:
            return [(split.category, split.amount) for split in self.splits]
        return [(self.category, self.amount)]

    def copy(self) -> Transaction:
        return copy.deepcopy(self)


@dataclass
class Budget:
    category: str
    month: str
    amount: float
    rollover: bool = False


@dataclass
class Condition:
    field: str
    op: str
    value: object

    def describe(self) -> str:
        if self.op == "between":
            low, high = self.value
            return f"{self.field} {low}..{high}"
        return f"{self.field} {self.op} {self.value}"


@dataclass
class Rule:
    id: str
    name: str
    conditions: list[Condition]
    set_category: str | None = None
    rename_payee: str | None = None
    split: dict[str, float] | None = None
    add_tags: list[str] = field(default_factory=list)
    priority: int = 100
    enabled: bool = True


@dataclass
class RecurringEntry:
    id: str
    account: str
    payee: str
    amount: float
    frequency: str
    start: date
    next_date: date
    category: str | None = None
    memo: str = ""
    end: date | None = None
    instalments: int | None = None
    done: int = 0
    active: bool = True

    @property
    def finished(self) -> bool:
        if self.instalments is not None and self.done >= self.instalments:
            return True
        return self.end is not None and self.next_date > self.end


@dataclass
class Rate:
    base: str
    quote: str
    on: date
    rate: float


@dataclass
class Settings:
    base_currency: str = "EUR"
    large_transaction: float | None = None
    history_limit: int = 50
