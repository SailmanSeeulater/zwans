"""The monthly report: income, spending and where it went, for one currency."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from ..dates import days_in_month, month_bounds, parse_month
from ..money import format_amount, round_half_up, zero
from .common import category_label, in_currency, report_currency
from .render import heading, table

if TYPE_CHECKING:
    from ..book import Book


@dataclass
class MonthlyReport:
    month: str
    currency: str
    income: Decimal = Decimal(0)
    expenses: Decimal = Decimal(0)
    by_category: dict[str, Decimal] = field(default_factory=dict)
    top_payees: list[tuple[str, Decimal]] = field(default_factory=list)
    daily_average: Decimal = Decimal(0)
    count: int = 0

    @property
    def net(self) -> Decimal:
        return self.income - self.expenses


def monthly_report(
    book: Book, month: str, currency: str | None = None, depth: int | None = None
) -> MonthlyReport:
    currency = report_currency(book, currency)
    start, end = month_bounds(month)
    nothing = zero(currency)
    report = MonthlyReport(month, currency, income=nothing, expenses=nothing,
                           daily_average=nothing)
    payees: dict[str, Decimal] = {}
    for txn in in_currency(book, currency, start, end):
        report.count += 1
        for category, amount in txn.category_amounts():
            if amount >= 0:
                report.income += amount
            else:
                report.expenses -= amount
            label = category_label(category, depth)
            report.by_category[label] = report.by_category.get(label, nothing) + amount
        if txn.amount < 0 and txn.payee:
            payees[txn.payee] = payees.get(txn.payee, nothing) - txn.amount
    year, number = parse_month(month)
    report.daily_average = round_half_up(report.expenses / days_in_month(year, number), currency)
    report.top_payees = sorted(payees.items(), key=lambda item: (-item[1], item[0]))[:5]
    report.by_category = dict(sorted(report.by_category.items()))
    return report


def render_monthly(report: MonthlyReport) -> str:
    cur = report.currency
    lines = [heading(f"{report.month} ({cur})"), ""]
    lines.append(f"Income     {format_amount(report.income, cur):>14}")
    lines.append(f"Spending   {format_amount(report.expenses, cur):>14}")
    lines.append(f"Net        {format_amount(report.net, cur, plus=True):>14}")
    lines.append(f"Per day    {format_amount(report.daily_average, cur):>14}")
    if report.by_category:
        lines.append("")
        rows = [(name, format_amount(amount, cur)) for name, amount in report.by_category.items()]
        lines.append(table(("Category", "Amount"), rows, "lr"))
    if report.top_payees:
        lines.append("")
        rows = [(name, format_amount(amount, cur)) for name, amount in report.top_payees]
        lines.append(table(("Top payees", "Spent"), rows, "lr"))
    return "\n".join(lines)


def to_dict(report: MonthlyReport) -> dict:
    return {
        "month": report.month,
        "currency": report.currency,
        "income": report.income,
        "expenses": report.expenses,
        "net": report.net,
        "daily_average": report.daily_average,
        "by_category": dict(report.by_category),
        "top_payees": [[name, amount] for name, amount in report.top_payees],
        "transactions": report.count,
    }
