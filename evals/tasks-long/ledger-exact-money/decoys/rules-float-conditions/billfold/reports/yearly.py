"""The yearly report: a row per month, totals, the monthly average, top categories."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from ..dates import month_key
from ..money import format_amount, round_half_up, zero
from .common import category_label, in_currency, report_currency
from .render import heading, table

if TYPE_CHECKING:
    from ..book import Book


@dataclass
class MonthRow:
    month: str
    income: Decimal = Decimal(0)
    expenses: Decimal = Decimal(0)

    @property
    def net(self) -> Decimal:
        return self.income - self.expenses


@dataclass
class YearlyReport:
    year: int
    currency: str
    months: list[MonthRow] = field(default_factory=list)
    income: Decimal = Decimal(0)
    expenses: Decimal = Decimal(0)
    average_expenses: Decimal = Decimal(0)
    by_category: dict[str, Decimal] = field(default_factory=dict)

    @property
    def net(self) -> Decimal:
        return self.income - self.expenses


def yearly_report(
    book: Book, year: int, currency: str | None = None, depth: int | None = 1
) -> YearlyReport:
    currency = report_currency(book, currency)
    nothing = zero(currency)
    rows = {
        f"{year:04d}-{m:02d}": MonthRow(f"{year:04d}-{m:02d}", nothing, nothing)
        for m in range(1, 13)
    }
    categories: dict[str, Decimal] = {}
    for txn in in_currency(book, currency, date(year, 1, 1), date(year, 12, 31)):
        row = rows[month_key(txn.date)]
        for category, amount in txn.category_amounts():
            if amount >= 0:
                row.income += amount
            else:
                row.expenses -= amount
            label = category_label(category, depth)
            categories[label] = categories.get(label, nothing) + amount
    report = YearlyReport(year, currency, income=nothing, expenses=nothing)
    for key in sorted(rows):
        row = rows[key]
        report.months.append(row)
        report.income += row.income
        report.expenses += row.expenses
    report.average_expenses = round_half_up(report.expenses / 12, currency)
    report.by_category = dict(sorted(categories.items(), key=lambda item: item[1]))
    return report


def render_yearly(report: YearlyReport) -> str:
    cur = report.currency
    rows = [
        (row.month, format_amount(row.income, cur), format_amount(row.expenses, cur),
         format_amount(row.net, cur, plus=True))
        for row in report.months
    ]
    footer = ("Total", format_amount(report.income, cur), format_amount(report.expenses, cur),
              format_amount(report.net, cur, plus=True))
    lines = [heading(f"{report.year} ({cur})"), ""]
    lines.append(table(("Month", "Income", "Spending", "Net"), rows, "lrrr", footer))
    lines.append("")
    lines.append(f"Average monthly spending: {format_amount(report.average_expenses, cur)}")
    if report.by_category:
        lines.append("")
        cat_rows = [(name, format_amount(amount, cur)) for name, amount in report.by_category.items()]
        lines.append(table(("Category", "Net"), cat_rows, "lr"))
    return "\n".join(lines)


def to_dict(report: YearlyReport) -> dict:
    return {
        "year": report.year,
        "currency": report.currency,
        "months": [
            {"month": r.month, "income": r.income, "expenses": r.expenses, "net": r.net}
            for r in report.months
        ],
        "income": report.income,
        "expenses": report.expenses,
        "net": report.net,
        "average_expenses": report.average_expenses,
        "by_category": dict(report.by_category),
    }
