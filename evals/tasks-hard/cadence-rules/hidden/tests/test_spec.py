from datetime import date

import cadence
import pytest


def d(text: str) -> date:
    return date.fromisoformat(text)


def ex(rule: str, start: str, end: str, holidays=()) -> list[str]:
    return [day.isoformat() for day in cadence.expand(rule, d(start), d(end), holidays)]


# -- days -------------------------------------------------------------------------------------


def test_every_n_days_from_an_anchor() -> None:
    assert ex("every 3 days; from 2025-03-02", "2025-03-01", "2025-03-12") == [
        "2025-03-02",
        "2025-03-05",
        "2025-03-08",
        "2025-03-11",
    ]


def test_anchor_defaults_to_start() -> None:
    assert ex("every 3 days", "2025-03-01", "2025-03-07") == [
        "2025-03-01",
        "2025-03-04",
        "2025-03-07",
    ]
    assert ex("every 3 days", "2025-03-02", "2025-03-07") == ["2025-03-02", "2025-03-05"]


def test_nothing_before_the_anchor() -> None:
    assert ex("daily; from 2025-03-05", "2025-03-01", "2025-03-06") == ["2025-03-05", "2025-03-06"]


def test_start_after_end() -> None:
    assert ex("daily", "2025-03-05", "2025-03-01") == []


# -- weeks ------------------------------------------------------------------------------------


def test_every_two_weeks_on_days_drops_days_before_the_anchor() -> None:
    assert ex("every 2 weeks on mon, fri; from 2025-03-05", "2025-03-01", "2025-03-31") == [
        "2025-03-07",
        "2025-03-17",
        "2025-03-21",
        "2025-03-31",
    ]


def test_weekly_defaults_to_the_anchor_weekday() -> None:
    assert ex("weekly; from 2025-03-05", "2025-03-01", "2025-03-20") == [
        "2025-03-05",
        "2025-03-12",
        "2025-03-19",
    ]
    assert ex("every 2 weeks; from 2025-03-05", "2025-03-01", "2025-03-31") == [
        "2025-03-05",
        "2025-03-19",
    ]


def test_weeks_run_monday_to_sunday() -> None:
    # Anchored on a Sunday: the next Saturday is already in week 1, so it is skipped.
    assert ex("every 2 weeks on sat, sun; from 2025-03-09", "2025-03-01", "2025-03-31") == [
        "2025-03-09",
        "2025-03-22",
        "2025-03-23",
    ]


# -- months -----------------------------------------------------------------------------------


def test_monthly_default_day_is_clamped() -> None:
    assert ex("monthly; from 2024-01-31", "2024-01-01", "2024-05-31") == [
        "2024-01-31",
        "2024-02-29",
        "2024-03-31",
        "2024-04-30",
        "2024-05-31",
    ]


def test_days_from_the_end() -> None:
    assert ex("monthly on day -1", "2025-01-01", "2025-04-30") == [
        "2025-01-31",
        "2025-02-28",
        "2025-03-31",
        "2025-04-30",
    ]
    assert ex("monthly on day -3", "2025-02-01", "2025-02-28") == ["2025-02-26"]


def test_days_from_the_end_are_clamped_to_the_first() -> None:
    assert ex("monthly on day -31", "2025-02-01", "2025-03-31") == ["2025-02-01", "2025-03-01"]


def test_day_31_in_april_and_same_dates_merge() -> None:
    assert ex("monthly on day 30, day 31", "2025-04-01", "2025-05-31") == [
        "2025-04-30",
        "2025-05-30",
        "2025-05-31",
    ]


def test_fifth_weekday_is_never_moved() -> None:
    assert ex("monthly on 5th fri", "2025-01-01", "2025-06-30") == ["2025-01-31", "2025-05-30"]


def test_nth_and_last_weekday() -> None:
    assert ex("monthly on last fri, 2nd tue", "2025-01-01", "2025-02-28") == [
        "2025-01-14",
        "2025-01-31",
        "2025-02-11",
        "2025-02-28",
    ]


def test_every_three_months_counts_from_the_anchor_month() -> None:
    assert ex("every 3 months on day 15; from 2025-02-10", "2025-01-01", "2025-12-31") == [
        "2025-02-15",
        "2025-05-15",
        "2025-08-15",
        "2025-11-15",
    ]


def test_every_two_months_period_zero_drops_days_before_the_anchor() -> None:
    assert ex("every 2 months on day 1, day 20; from 2025-01-10", "2025-01-01", "2025-05-31") == [
        "2025-01-20",
        "2025-03-01",
        "2025-03-20",
        "2025-05-01",
        "2025-05-20",
    ]


def test_business_days_of_the_month() -> None:
    holidays = {d("2025-01-01"), d("2025-01-31")}
    assert ex(
        "monthly on business day 1, business day -1", "2025-01-01", "2025-01-31", holidays
    ) == [
        "2025-01-02",
        "2025-01-30",
    ]


def test_third_business_day_skips_holidays() -> None:
    assert ex("monthly on business day 3", "2025-02-01", "2025-02-28") == ["2025-02-05"]
    assert ex("monthly on business day 3", "2025-02-01", "2025-02-28", {d("2025-02-04")}) == [
        "2025-02-06"
    ]


def test_month_without_enough_business_days() -> None:
    assert ex("monthly on business day 23", "2025-01-01", "2025-02-28") == ["2025-01-31"]


# -- years ------------------------------------------------------------------------------------


def test_february_29_in_other_years() -> None:
    assert ex("yearly on feb 29; from 2024-01-01", "2024-01-01", "2026-12-31") == [
        "2024-02-29",
        "2025-02-28",
        "2026-02-28",
    ]


def test_yearly_default_and_interval() -> None:
    assert ex("every 2 years; from 2023-07-04", "2023-01-01", "2028-12-31") == [
        "2023-07-04",
        "2025-07-04",
        "2027-07-04",
    ]


def test_yearly_on_several_days() -> None:
    assert ex("yearly on sep 30, mar 31", "2025-01-01", "2025-12-31") == [
        "2025-03-31",
        "2025-09-30",
    ]


# -- closed days ------------------------------------------------------------------------------


def test_next_moves_into_the_next_month() -> None:
    assert ex("monthly on day -1; closed: next", "2025-05-01", "2025-06-30") == [
        "2025-06-02",
        "2025-06-30",
    ]


def test_window_looks_at_the_final_date() -> None:
    rule = "monthly on day -1; from 2025-01-01; closed: next"
    assert ex(rule, "2025-06-01", "2025-06-30") == ["2025-06-02", "2025-06-30"]
    assert ex(rule, "2025-05-01", "2025-05-31") == []


def test_previous_can_pull_a_later_occurrence_into_the_window() -> None:
    assert ex("monthly on day 1; closed: previous", "2025-02-01", "2025-02-28") == ["2025-02-28"]


def test_previous_can_move_before_the_window() -> None:
    assert ex("monthly on day 1; closed: previous", "2025-02-01", "2025-03-31") == ["2025-02-28"]


def test_moved_occurrences_merge() -> None:
    assert ex("daily; closed: next", "2025-03-07", "2025-03-10") == ["2025-03-07", "2025-03-10"]


def test_skip() -> None:
    assert ex("weekly on sat, mon; closed: skip", "2025-03-01", "2025-03-16") == [
        "2025-03-03",
        "2025-03-10",
    ]


def test_keep_is_the_default() -> None:
    assert ex("weekly on sat", "2025-03-01", "2025-03-08") == ["2025-03-01", "2025-03-08"]
    assert ex("weekly on sat; closed: keep", "2025-03-01", "2025-03-08") == [
        "2025-03-01",
        "2025-03-08",
    ]


def test_every_business_day() -> None:
    holidays = {d("2025-04-18"), d("2025-04-21")}
    assert ex("every business day", "2025-04-17", "2025-04-22", holidays) == [
        "2025-04-17",
        "2025-04-22",
    ]


def test_holidays_object() -> None:
    holidays = cadence.Holidays([d("2025-03-04")])
    assert ex("daily; closed: next", "2025-03-03", "2025-03-05", holidays) == [
        "2025-03-03",
        "2025-03-05",
    ]


# -- options ----------------------------------------------------------------------------------


def test_until_looks_at_the_scheduled_date() -> None:
    rule = "daily; from 2025-03-27; until 2025-03-29; closed: next"
    assert ex(rule, "2025-03-01", "2025-04-30") == ["2025-03-27", "2025-03-28", "2025-03-31"]


def test_until_is_inclusive() -> None:
    assert ex("weekly on mon; until 2025-03-17", "2025-03-01", "2025-03-31") == [
        "2025-03-03",
        "2025-03-10",
        "2025-03-17",
    ]


def test_count_starts_at_the_anchor_not_the_window() -> None:
    rule = "weekly on mon; from 2025-03-03; count 3"
    assert ex(rule, "2025-03-10", "2025-03-31") == ["2025-03-10", "2025-03-17"]


def test_count_is_applied_after_skip_and_except() -> None:
    rule = "daily; from 2025-03-06; count 3; closed: skip; except 2025-03-10"
    assert ex(rule, "2025-03-01", "2025-03-31") == ["2025-03-06", "2025-03-07", "2025-03-11"]


def test_count_counts_merged_occurrences_once() -> None:
    rule = "daily; from 2025-03-07; count 3; closed: next"
    assert ex(rule, "2025-03-01", "2025-03-31") == ["2025-03-07", "2025-03-10", "2025-03-11"]


def test_except_looks_at_the_scheduled_date() -> None:
    base = "weekly on sat; from 2025-03-01; closed: next"
    assert ex(base + "; except 2025-03-08", "2025-03-01", "2025-03-20") == [
        "2025-03-03",
        "2025-03-17",
    ]
    assert ex(base + "; except 2025-03-10", "2025-03-01", "2025-03-20") == [
        "2025-03-03",
        "2025-03-10",
        "2025-03-17",
    ]


def test_except_several_dates() -> None:
    rule = "weekly on mon; except 2025-03-10, 2025-03-24"
    assert ex(rule, "2025-03-01", "2025-03-31") == ["2025-03-03", "2025-03-17", "2025-03-31"]


def test_options_in_any_order() -> None:
    rule = "every 2 weeks on mon, fri; closed: skip; count 2; from 2025-03-05"
    assert ex(rule, "2025-03-01", "2025-03-31") == ["2025-03-07", "2025-03-17"]


# -- syntax -----------------------------------------------------------------------------------


def test_case_and_whitespace_do_not_matter() -> None:
    rule = "  Every 2   WEEKS on Mon , FRI ;  FROM 2025-03-05 "
    assert ex(rule, "2025-03-01", "2025-03-31") == [
        "2025-03-07",
        "2025-03-17",
        "2025-03-21",
        "2025-03-31",
    ]


def test_full_weekday_names_and_units_either_way() -> None:
    assert ex("monthly on last friday", "2025-01-01", "2025-01-31") == ["2025-01-31"]
    assert ex("every 1 days", "2025-03-01", "2025-03-02") == ["2025-03-01", "2025-03-02"]
    assert ex("every 2 week on monday; from 2025-03-03", "2025-03-01", "2025-03-20") == [
        "2025-03-03",
        "2025-03-17",
    ]


@pytest.mark.parametrize(
    "rule",
    [
        "every 0 days",
        "every two days",
        "daily on mon",
        "every 3 days on mon",
        "every business day on mon",
        "every 2 weeks on day 3",
        "weekly on 2nd tue",
        "weekly on",
        "monthly on mon",
        "monthly on 6th tue",
        "monthly on day 0",
        "monthly on day 32",
        "monthly on day -32",
        "monthly on business day 0",
        "monthly on day 1,, day 2",
        "yearly on feb 30",
        "yearly on apr 31",
        "yearly on day 5",
        "yearly on march 3",
        "daily; from 2025-02-30",
        "daily; from 2025-3-1",
        "daily; count 3; until 2025-05-01",
        "daily; from 2025-01-01; from 2025-02-01",
        "daily; from 2025-05-01; until 2025-04-30",
        "daily; count 0",
        "daily; closed: sometimes",
        "daily; every day",
        "daily;",
        "; daily",
        "daily;; count 2",
    ],
)
def test_bad_rules(rule: str) -> None:
    with pytest.raises(cadence.RuleError):
        cadence.expand(rule, d("2025-01-01"), d("2025-12-31"))


def test_rule_error_is_a_value_error() -> None:
    assert issubclass(cadence.RuleError, ValueError)
