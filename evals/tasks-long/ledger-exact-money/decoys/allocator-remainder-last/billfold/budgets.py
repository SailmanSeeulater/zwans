"""Monthly budgets per category.

A budget on a category covers everything under it ("Food" covers "Food:Groceries").
Spending is money out minus refunds, counted in the base currency's accounts only, and
transfers never count. With rollover, what is left of a month's budget (or the overspend)
carries into the next month's.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from .categories import clean, is_under
from .dates import month_bounds, parse_month, previous_month
from .errors import MoneyError, NotFound, ValidationError
from .models import Budget
from .money import decimal_number, round_half_up, to_amount, zero

if TYPE_CHECKING:
    from .book import Book


@dataclass
class BudgetLine:
    category: str
    month: str
    budgeted: Decimal
    carried: Decimal
    spent: Decimal

    @property
    def available(self) -> Decimal:
        return self.budgeted + self.carried

    @property
    def remaining(self) -> Decimal:
        return self.available - self.spent

    @property
    def over(self) -> bool:
        return self.remaining < 0


class BudgetBook:
    def __init__(self, book: Book) -> None:
        self.book = book
        self._budgets: dict[tuple[str, str], Budget] = {}

    @property
    def currency(self) -> str:
        return self.book.settings.base_currency

    def set(self, category: str, month: str, amount: object, rollover: bool = False) -> Budget:
        parse_month(month)
        category = self.book.categories.add(category)
        value = to_amount(amount, self.currency)
        if value < 0:
            raise ValidationError("a budget can't be negative")
        budget = Budget(category, month, value, rollover)
        self._budgets[(category, month)] = budget
        return budget

    def load(self, budget: Budget) -> None:
        self._budgets[(budget.category, budget.month)] = budget

    def remove(self, category: str, month: str) -> Budget:
        try:
            return self._budgets.pop((clean(category), month))
        except KeyError:
            raise NotFound(f"no budget for {category} in {month}") from None

    def get(self, category: str, month: str) -> Budget | None:
        return self._budgets.get((category, month))

    def all(self) -> list[Budget]:
        return [self._budgets[key] for key in sorted(self._budgets, key=lambda k: (k[1], k[0]))]

    def for_month(self, month: str) -> list[Budget]:
        return [b for (category, key), b in sorted(self._budgets.items()) if key == month]

    def spent(self, category: str, month: str) -> Decimal:
        start, end = month_bounds(month)
        total = zero(self.currency)
        for txn in self.book.transactions.values():
            if txn.is_transfer or not start <= txn.date <= end:
                continue
            if self.book.accounts[txn.account].currency != self.currency:
                continue
            for name, amount in txn.category_amounts():
                if is_under(name, category):
                    total -= amount
        return total

    def carried(self, category: str, month: str) -> Decimal:
        previous = previous_month(month)
        budget = self.get(category, previous)
        if budget is None or not budget.rollover:
            return zero(self.currency)
        return self.line(category, previous).remaining

    def line(self, category: str, month: str) -> BudgetLine:
        budget = self.get(category, month)
        budgeted = budget.amount if budget else zero(self.currency)
        return BudgetLine(
            category=category,
            month=month,
            budgeted=budgeted,
            carried=self.carried(category, month),
            spent=self.spent(category, month),
        )

    def status(self, month: str) -> list[BudgetLine]:
        return [self.line(budget.category, month) for budget in self.for_month(month)]

    def allocate(
        self, total: object, weights: dict[str, object], month: str, rollover: bool = False
    ) -> dict[str, Decimal]:
        """Share `total` out over categories in proportion to their weights, as budgets."""
        if not weights:
            raise ValidationError("allocate over at least one category")
        amount = to_amount(total, self.currency)
        if amount < 0:
            raise ValidationError("allocate a positive amount")
        try:
            parsed = {clean(name): decimal_number(weight, "weight")
                      for name, weight in weights.items()}
        except MoneyError as error:
            raise ValidationError(str(error)) from None
        if any(weight <= 0 for weight in parsed.values()):
            raise ValidationError("weights must be positive")
        weight_sum = sum(parsed.values())
        shares: dict[str, Decimal] = {}
        given = zero(self.currency)
        items = list(parsed.items())
        for index, (category, weight) in enumerate(items):
            if index == len(items) - 1:
                share = amount - given
            else:
                share = round_half_up(amount * weight / weight_sum, self.currency)
            given += share
            shares[category] = share
        for category, share in shares.items():
            self.set(category, month, share, rollover)
        return shares

    def over_budget(self, month: str) -> list[BudgetLine]:
        return [line for line in self.status(month) if line.over]

    def copy_month(self, source: str, target: str) -> list[Budget]:
        """Start a month with the same budgets as another one."""
        copied = []
        for budget in self.for_month(source):
            copied.append(self.set(budget.category, target, budget.amount, budget.rollover))
        return copied
