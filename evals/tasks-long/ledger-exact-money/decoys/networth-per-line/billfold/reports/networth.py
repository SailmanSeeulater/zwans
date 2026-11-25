"""Net worth: every account's balance on a day, converted into one currency."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from ..money import format_amount, round_half_up, zero
from .common import report_currency
from .render import heading, table

if TYPE_CHECKING:
    from ..book import Book


@dataclass
class NetWorthLine:
    account: str
    currency: str
    balance: Decimal
    converted: Decimal


@dataclass
class NetWorth:
    on: date
    currency: str
    lines: list[NetWorthLine] = field(default_factory=list)
    total: Decimal = Decimal(0)


def net_worth(
    book: Book, on: date | None = None, currency: str | None = None, include_closed: bool = False
) -> NetWorth:
    on = on or book.clock.today()
    currency = report_currency(book, currency)
    report = NetWorth(on, currency)
    exact_total = Decimal(0)
    for account in book.list_accounts(include_closed):
        balance = book.balance(account, on)
        exact = book.rates.exact(balance, account.currency, currency, on)
        converted = round_half_up(exact, currency)
        report.lines.append(NetWorthLine(account.name, account.currency, balance, converted))
        exact_total += converted
    report.total = round_half_up(exact_total, currency) if report.lines else zero(currency)
    return report


def render_net_worth(report: NetWorth) -> str:
    rows = []
    for line in report.lines:
        own = format_amount(line.balance, line.currency, code=True)
        rows.append((line.account, own, format_amount(line.converted, report.currency)))
    footer = ("Total", "", format_amount(report.total, report.currency))
    lines = [heading(f"Net worth on {report.on.isoformat()} ({report.currency})"), ""]
    lines.append(table(("Account", "Balance", report.currency), rows, "lrr", footer))
    return "\n".join(lines)


def to_dict(report: NetWorth) -> dict:
    return {
        "on": report.on.isoformat(),
        "currency": report.currency,
        "accounts": [
            {"account": l.account, "currency": l.currency, "balance": l.balance,
             "converted": l.converted}
            for l in report.lines
        ],
        "total": report.total,
    }
