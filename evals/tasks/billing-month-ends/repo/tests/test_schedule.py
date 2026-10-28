from datetime import date

import pytest

from billing.calendar import add_months, days_in_month
from billing.invoices import billing_periods
from billing.schedule import Subscription, next_renewal, renewal_dates


def test_days_in_month() -> None:
    assert days_in_month(2023, 1) == 31
    assert days_in_month(2023, 4) == 30
    assert days_in_month(2023, 2) == 28


def test_add_months() -> None:
    assert add_months(date(2023, 3, 15), 1) == date(2023, 4, 15)
    assert add_months(date(2023, 5, 31), 1) == date(2023, 6, 30)
    assert add_months(date(2023, 3, 15), 0) == date(2023, 3, 15)


def test_negative_months() -> None:
    with pytest.raises(ValueError):
        add_months(date(2023, 3, 15), -1)


def test_monthly_renewals() -> None:
    sub = Subscription("ada", date(2023, 3, 15))

    assert renewal_dates(sub, 3) == [date(2023, 4, 15), date(2023, 5, 15), date(2023, 6, 15)]


def test_quarterly_renewals() -> None:
    sub = Subscription("bob", date(2023, 1, 10), plan="quarterly")

    assert renewal_dates(sub, 2) == [date(2023, 4, 10), date(2023, 7, 10)]


def test_next_renewal() -> None:
    sub = Subscription("cy", date(2023, 2, 5))

    assert next_renewal(sub, date(2023, 4, 20)) == date(2023, 5, 5)


def test_billing_periods() -> None:
    sub = Subscription("di", date(2023, 3, 1))

    periods = [str(period) for period in billing_periods(sub, 2)]

    assert periods == ["2023-03-01 to 2023-03-31", "2023-04-01 to 2023-04-30"]
