"""Reports total exactly, round averages once, and convert account balances once."""

from datetime import date
from decimal import Decimal

from conftest import exact

from billfold import Book
from billfold.reports import budget_report, monthly_report, net_worth, render_net_worth, yearly_report
from billfold.reports import monthly as monthly_module
from billfold.reports import networth as networth_module


def test_monthly_report_totals_are_exact(pennies: Book) -> None:
    report = monthly_report(pennies, "2026-03")
    exact(report.income, "1234.56")
    exact(report.expenses, "20.29")
    exact(report.net, "1214.27")
    exact(report.by_category["Food:Snacks"], "-0.30")
    exact(report.by_category["Subscriptions"], "-19.99")
    assert report.top_payees[0][0] == "Streamly"
    exact(report.top_payees[1][1], "0.30")


def test_monthly_report_by_top_level_and_in_yen(pennies: Book) -> None:
    exact(monthly_report(pennies, "2026-03", depth=1).by_category["Food"], "-0.30")
    yen = monthly_report(pennies, "2026-03", currency="JPY")
    exact(yen.expenses, "1200")
    exact(yen.daily_average, "39")


def test_daily_average_rounds_half_away_from_zero(book: Book) -> None:
    book.add_account("Checking")
    book.add_transaction("Checking", "2026-02-03", "-280.00", category="Rent")
    book.add_transaction("Checking", "2026-02-04", "-0.14", category="Fees")
    report = monthly_report(book, "2026-02")
    exact(report.expenses, "280.14")
    exact(report.daily_average, "10.01")
    april = book.add_transaction("Checking", "2026-04-04", "-300.15", category="Rent")
    assert april
    exact(monthly_report(book, "2026-04").daily_average, "10.01")


def as_amount(value: object) -> object:
    """A report dict may hold an amount as a Decimal or as its export-form string; the
    README only fixes what `--json` prints."""
    return Decimal(value) if isinstance(value, str) else value


def test_monthly_report_dict_is_exact(pennies: Book) -> None:
    data = monthly_module.to_dict(monthly_report(pennies, "2026-03"))
    exact(as_amount(data["expenses"]), "20.29")
    exact(as_amount(data["by_category"]["Food:Snacks"]), "-0.30")


def test_yearly_report_is_exact(book: Book) -> None:
    book.add_account("Checking")
    for day in (3, 4, 5):
        book.add_transaction("Checking", f"2026-01-0{day}", "-0.10", category="Food:Snacks")
    book.add_transaction("Checking", "2026-02-01", "-1199.76", category="Rent")
    book.add_transaction("Checking", "2026-02-02", "0.10", category="Refunds")
    report = yearly_report(book, 2026)
    exact(report.months[0].expenses, "0.30")
    exact(report.months[1].income, "0.10")
    exact(report.expenses, "1200.06")
    exact(report.income, "0.10")
    exact(report.average_expenses, "100.01")
    exact(report.by_category["Food"], "-0.30")


def test_net_worth_total_is_converted_from_exact_figures(book: Book) -> None:
    book.add_account("Checking", opening_balance="1.00")
    book.add_account("Wallet A", currency="USD", opening_balance="0.10")
    book.add_account("Wallet B", currency="USD", opening_balance="0.10")
    book.set_rate("USD", "EUR", "0.25", "2026-01-01")
    report = net_worth(book, on=date(2026, 3, 31))
    lines = {line.account: line for line in report.lines}
    exact(lines["Wallet A"].balance, "0.10")
    exact(lines["Wallet A"].converted, "0.03")
    exact(lines["Wallet B"].converted, "0.03")
    exact(lines["Checking"].converted, "1.00")
    exact(report.total, "1.05")
    assert "1.05" in render_net_worth(report)


def test_net_worth_converts_each_balance_once(book: Book) -> None:
    book.add_account("Checking")
    book.add_account("Dollars", currency="USD")
    book.set_rate("USD", "EUR", "0.5", "2026-01-01")
    for _ in range(3):
        book.add_transaction("Dollars", "2026-03-02", "0.01")
    report = net_worth(book, on=date(2026, 3, 31))
    dollars = next(line for line in report.lines if line.account == "Dollars")
    exact(dollars.balance, "0.03")
    exact(dollars.converted, "0.02")
    exact(report.total, "0.02")


def test_net_worth_through_the_opposite_rate(pennies: Book) -> None:
    pennies.set_rate("EUR", "JPY", "161.5", "2026-01-01")
    report = net_worth(pennies, on=date(2026, 3, 31))
    yen = next(line for line in report.lines if line.account == "Yen")
    exact(yen.balance, "13800")
    exact(yen.converted, "85.45")
    exact(report.total, "1300.42")
    data = networth_module.to_dict(report)
    exact(as_amount(data["total"]), "1300.42")


def test_budget_report_lines(pennies: Book) -> None:
    pennies.budgets.set("Food", "2026-03", "0.40")
    (line,) = budget_report(pennies, "2026-03")
    exact(line.remaining, "0.10")
