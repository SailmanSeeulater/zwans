from datetime import date
from pathlib import Path

import cadence
import pytest
from payroll.schedule import next_pay_date, pay_dates


def d(text: str) -> date:
    return date.fromisoformat(text)


def load(tmp_path: Path, text: str) -> cadence.Holidays:
    path = tmp_path / "holidays.txt"
    path.write_text(text, encoding="utf-8")
    return cadence.load_holidays(path)


def test_dates_names_and_comments(tmp_path: Path) -> None:
    holidays = load(
        tmp_path,
        "# office holidays\n\n2025-04-18 Good Friday # moves\n   2025-05-29\tAscension Day\n2025-06-09#whit\n",
    )
    assert d("2025-04-18") in holidays
    assert d("2025-05-29") in holidays
    assert d("2025-06-09") in holidays
    assert d("2025-04-17") not in holidays
    assert d("2026-04-18") not in holidays


def test_ranges_are_inclusive(tmp_path: Path) -> None:
    holidays = load(tmp_path, "2025-12-24..2025-12-26 Christmas\n2025-08-01..2025-08-01\n")
    for day in ["2025-12-24", "2025-12-25", "2025-12-26", "2025-08-01"]:
        assert d(day) in holidays
    assert d("2025-12-23") not in holidays
    assert d("2025-12-27") not in holidays


def test_every_year(tmp_path: Path) -> None:
    holidays = load(tmp_path, "*-05-01 Labour Day\n")
    assert d("2025-05-01") in holidays
    assert d("2031-05-01") in holidays
    assert d("1999-05-01") in holidays


def test_every_year_on_a_weekend_is_observed(tmp_path: Path) -> None:
    holidays = load(tmp_path, "*-12-25\n*-12-26\n*-01-01\n")
    # 2027-12-25 is a Saturday, 2027-12-26 a Sunday.
    assert d("2027-12-25") in holidays
    assert d("2027-12-24") in holidays
    assert d("2027-12-26") in holidays
    assert d("2027-12-27") in holidays
    # 2023-01-01 is a Sunday; 2026-01-01 a Thursday.
    assert d("2023-01-02") in holidays
    assert d("2025-12-31") not in holidays
    assert d("2026-01-02") not in holidays


def test_observed_day_can_be_in_the_year_before(tmp_path: Path) -> None:
    holidays = load(tmp_path, "*-01-01\n")
    # 2028-01-01 is a Saturday.
    assert d("2027-12-31") in holidays


def test_dated_holidays_on_a_weekend_are_not_observed(tmp_path: Path) -> None:
    holidays = load(tmp_path, "2025-05-31 Saturday holiday\n2025-06-01\n")
    assert d("2025-05-30") not in holidays
    assert d("2025-06-02") not in holidays


def test_february_29_every_year(tmp_path: Path) -> None:
    holidays = load(tmp_path, "*-02-29 Leap Day\n")
    assert d("2028-02-29") in holidays
    assert d("2027-02-28") not in holidays
    assert d("2027-03-01") not in holidays
    # 2020-02-29 was a Saturday.
    assert d("2020-02-28") in holidays


@pytest.mark.parametrize(
    ("text", "line"),
    [
        ("2025-01-01\n\n2025-13-01\n", 3),
        ("# x\n2025-04-18..2025-04-17\n", 2),
        ("tomorrow\n", 1),
        ("2025-01-01\n*-02-30\n", 2),
        ("2025/04/18\n", 1),
        ("\n\n\n2025-02-29 not a leap year\n", 4),
        ("2025-01-01..\n", 1),
        ("*-1-01\n", 1),
    ],
)
def test_bad_lines(tmp_path: Path, text: str, line: int) -> None:
    with pytest.raises(cadence.HolidayFileError) as caught:
        load(tmp_path, text)
    assert caught.value.line == line
    assert isinstance(caught.value, ValueError)


def test_observed_holiday_is_a_closed_day(tmp_path: Path) -> None:
    holidays = load(tmp_path, "*-01-01\n")
    result = cadence.expand("monthly on business day 1", d("2023-01-01"), d("2023-01-31"), holidays)
    assert result == [d("2023-01-03")]


def test_payroll_staff_dates() -> None:
    dates = pay_dates("staff", 2025)
    assert len(dates) == 12
    assert dates[4] == d("2025-05-30")
    assert dates[-1] == d("2025-12-23")


def test_payroll_board_dates() -> None:
    assert pay_dates("board", 2025) == [
        d("2025-01-15"),
        d("2025-04-15"),
        d("2025-07-15"),
        d("2025-10-15"),
    ]
    assert next_pay_date("board", d("2026-02-01")) == d("2026-04-15")


def test_payroll_contractors() -> None:
    dates = pay_dates("contractors", 2025)
    assert len(dates) == 26
    assert dates[-1] == d("2025-12-19")
    assert next_pay_date("contractors", d("2025-12-20")) == d("2026-01-02")
