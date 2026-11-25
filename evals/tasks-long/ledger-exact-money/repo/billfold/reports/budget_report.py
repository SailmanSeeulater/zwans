"""The budget report: each budget in a month, what's been spent and what's left."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..budgets import BudgetLine
from ..money import format_amount
from .render import heading, table

if TYPE_CHECKING:
    from ..book import Book


def budget_report(book: Book, month: str) -> list[BudgetLine]:
    return book.budgets.status(month)


def render_budget(lines: list[BudgetLine], month: str, currency: str) -> str:
    out = [heading(f"Budgets for {month} ({currency})"), ""]
    if not lines:
        out.append("No budgets set for this month.")
        return "\n".join(out)
    rows = []
    for line in lines:
        flag = "  OVER" if line.over else ""
        rows.append((
            line.category,
            format_amount(line.budgeted, currency),
            format_amount(line.carried, currency, plus=True),
            format_amount(line.spent, currency),
            format_amount(line.remaining, currency) + flag,
        ))
    total_budget = sum(line.available for line in lines)
    total_spent = sum(line.spent for line in lines)
    footer = ("Total", "", "", format_amount(total_spent, currency),
              format_amount(total_budget - total_spent, currency))
    out.append(table(("Category", "Budget", "Carried", "Spent", "Left"), rows, "lrrrr", footer))
    return "\n".join(out)


def to_dict(lines: list[BudgetLine]) -> list[dict]:
    return [
        {
            "category": line.category,
            "month": line.month,
            "budgeted": line.budgeted,
            "carried": line.carried,
            "available": line.available,
            "spent": line.spent,
            "remaining": line.remaining,
        }
        for line in lines
    ]
