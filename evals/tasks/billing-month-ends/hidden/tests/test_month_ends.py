from datetime import date

import pytest

from billing.calendar import add_months, days_in_month
from billing.invoices import billing_periods
from billing.schedule import Subscription, next_renewal, renewal_dates


@pytest.mark.parametrize(
    ("year", "expected"),
    [(2023, 28), (2024, 29), (1900, 28), (2000, 29), (2100, 28), (2028, 29)],
)
def test_february(year: int, expected: int) -> None:
    assert days_in_month(year, 2) == expected


def test_december_and_year_rollover() -> None:
    assert add_months(date(2024, 11, 15), 1) == date(2024, 12, 15)
    assert add_months(date(2024, 12, 15), 1) == date(2025, 1, 15)
    assert add_months(date(2024, 1, 15), 11) == date(2024, 12, 15)
    assert add_months(date(2024, 1, 15), 12) == date(2025, 1, 15)
    assert add_months(date(2024, 12, 15), 12) == date(2025, 12, 15)
    assert add_months(date(2024, 6, 30), 30) == date(2026, 12, 30)
    assert add_months(date(2024, 6, 30), 31) == date(2027, 1, 30)


def test_add_months_with_a_day() -> None:
    assert add_months(date(2024, 2, 29), 1, day=31) == date(2024, 3, 31)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)


def test_end_of_month_subscriber() -> None:
    sub = Subscription("eve", date(2024, 1, 31))

    assert renewal_dates(sub, 6) == [
        date(2024, 2, 29),
        date(2024, 3, 31),
        date(2024, 4, 30),
        date(2024, 5, 31),
        date(2024, 6, 30),
        date(2024, 7, 31),
    ]


def test_november_subscriber() -> None:
    sub = Subscription("fay", date(2024, 11, 15))

    assert renewal_dates(sub, 3) == [date(2024, 12, 15), date(2025, 1, 15), date(2025, 2, 15)]
    assert next_renewal(sub, date(2024, 11, 20)) == date(2024, 12, 15)


def test_the_30th_across_february() -> None:
    sub = Subscription("gus", date(2023, 1, 30))

    assert renewal_dates(sub, 3) == [date(2023, 2, 28), date(2023, 3, 30), date(2023, 4, 30)]


def test_quarterly_from_november_30() -> None:
    sub = Subscription("hal", date(2023, 11, 30), plan="quarterly")

    assert renewal_dates(sub, 4) == [
        date(2024, 2, 29),
        date(2024, 5, 30),
        date(2024, 8, 30),
        date(2024, 11, 30),
    ]


def test_yearly_from_leap_day() -> None:
    sub = Subscription("ivy", date(2024, 2, 29), plan="yearly")

    assert renewal_dates(sub, 4) == [
        date(2025, 2, 28),
        date(2026, 2, 28),
        date(2027, 2, 28),
        date(2028, 2, 29),
    ]


def test_yearly_from_december() -> None:
    sub = Subscription("jo", date(2023, 12, 31), plan="yearly")

    assert renewal_dates(sub, 2) == [date(2024, 12, 31), date(2025, 12, 31)]


def test_periods_cover_every_day() -> None:
    sub = Subscription("kim", date(2024, 1, 31))

    periods = [str(period) for period in billing_periods(sub, 3)]

    assert periods == [
        "2024-01-31 to 2024-02-28",
        "2024-02-29 to 2024-03-30",
        "2024-03-31 to 2024-04-29",
    ]
