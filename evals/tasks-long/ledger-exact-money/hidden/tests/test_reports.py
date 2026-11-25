from datetime import date

from billfold import Book
from billfold.reports import (
    monthly_report,
    net_worth,
    render_monthly,
    render_net_worth,
    render_yearly,
    yearly_report,
)


def test_monthly_report(household: Book) -> None:
    report = monthly_report(household, "2026-03")
    assert report.currency == "EUR"
    assert report.income == 2500
    assert report.expenses == 42.5 + 12.25 + 1100
    assert report.by_category["Rent"] == -1100
    assert report.top_payees[0] == ("Landlord", 1100)
    assert report.count == 4
    text = render_monthly(report)
    assert "2,500.00" in text and "1,154.75" in text


def test_monthly_report_by_top_level(household: Book) -> None:
    report = monthly_report(household, "2026-03", depth=1)
    assert report.by_category["Food"] == -54.75


def test_monthly_report_in_another_currency(household: Book) -> None:
    report = monthly_report(household, "2026-03", currency="USD")
    assert report.expenses == 20 and report.income == 0


def test_yearly_report(household: Book) -> None:
    household.add_transaction("Checking", "2026-01-20", "-100.00", category="Food")
    report = yearly_report(household, 2026)
    assert [row.expenses for row in report.months][:3] == [100, 0, 1154.75]
    assert report.expenses == 1254.75
    assert report.by_category["Food"] == -154.75
    assert "Average monthly spending" in render_yearly(report)


def test_net_worth_converts_into_one_currency(household: Book) -> None:
    household.set_rate("USD", "EUR", "0.5", "2026-01-01")
    report = net_worth(household, on=date(2026, 3, 31))
    by_name = {line.account: line for line in report.lines}
    assert by_name["Dollars"].balance == 230
    assert by_name["Dollars"].converted == 115
    assert report.total == 2345.25 + 5000 + 115
    assert "Net worth on 2026-03-31" in render_net_worth(report)
