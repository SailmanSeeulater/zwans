from datetime import date

import cadence
import pytest


def test_daily() -> None:
    assert cadence.expand("daily", date(2025, 3, 1), date(2025, 3, 3)) == [
        date(2025, 3, 1),
        date(2025, 3, 2),
        date(2025, 3, 3),
    ]


def test_weekly_on_given_days() -> None:
    result = cadence.expand("weekly on mon, thu", date(2025, 3, 3), date(2025, 3, 16))
    assert result == [date(2025, 3, 3), date(2025, 3, 6), date(2025, 3, 10), date(2025, 3, 13)]


def test_monthly_on_a_day() -> None:
    result = cadence.expand("monthly on day 15", date(2025, 1, 1), date(2025, 3, 31))
    assert result == [date(2025, 1, 15), date(2025, 2, 15), date(2025, 3, 15)]


def test_holiday_is_skipped() -> None:
    holidays = cadence.Holidays([date(2025, 3, 4)])
    result = cadence.expand("daily; closed: skip", date(2025, 3, 3), date(2025, 3, 5), holidays)
    assert result == [date(2025, 3, 3), date(2025, 3, 5)]


def test_nonsense_is_an_error() -> None:
    with pytest.raises(cadence.RuleError):
        cadence.expand("whenever it suits", date(2025, 1, 1), date(2025, 1, 31))
