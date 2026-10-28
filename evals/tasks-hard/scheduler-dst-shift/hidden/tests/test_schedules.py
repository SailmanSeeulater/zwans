from datetime import UTC, datetime, time, timedelta

import pytest
from cronlite.schedules import (
    EVERY_DAY,
    WEEKDAYS,
    AtTime,
    Every,
    ScheduleError,
    parse_schedule,
    runs_between,
)
from cronlite.zones import get_zone

AMSTERDAM = get_zone("Europe/Amsterdam")


def local_runs(schedule, zone, start: datetime, end: datetime) -> list[str]:
    return [
        zone.to_local(m).strftime("%a %d %b %H:%M")
        for m in runs_between(schedule, zone, start, end)
    ]


def test_parse() -> None:
    assert parse_schedule("daily 02:30") == AtTime(time(2, 30), EVERY_DAY)
    assert parse_schedule("Weekdays 8:00") == AtTime(time(8, 0), WEEKDAYS)
    assert parse_schedule("mon,thu 07:15") == AtTime(time(7, 15), frozenset({0, 3}))
    assert parse_schedule("every 30m") == Every(timedelta(minutes=30))
    assert parse_schedule("every 2h") == Every(timedelta(hours=2))
    for bad in ("daily", "daily 25:00", "fortnightly 08:00", "every 0m", "mon,xyz 08:00"):
        with pytest.raises(ScheduleError):
            parse_schedule(bad)


def test_describe_round_trips() -> None:
    for text in ("daily 02:30", "weekdays 08:00", "mon,thu 07:15", "every 30m", "every 2h"):
        assert parse_schedule(text).describe() == text


def test_daily_in_summer() -> None:
    start = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    runs = local_runs(parse_schedule("daily 02:30"), AMSTERDAM, start, start + timedelta(days=3))
    assert runs == ["Wed 01 Jul 02:30", "Thu 02 Jul 02:30", "Fri 03 Jul 02:30"]


def test_next_run_is_strictly_after() -> None:
    schedule = parse_schedule("daily 08:00")
    eight = datetime(2026, 7, 1, 6, 0, tzinfo=UTC)  # 08:00 in Amsterdam
    assert schedule.next_after(eight - timedelta(seconds=1), AMSTERDAM) == eight
    assert schedule.next_after(eight, AMSTERDAM) == eight + timedelta(days=1)


def test_weekdays_skip_the_weekend() -> None:
    friday = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    runs = local_runs(
        parse_schedule("weekdays 08:00"), AMSTERDAM, friday, friday + timedelta(days=4)
    )
    assert runs == ["Mon 06 Jul 08:00", "Tue 07 Jul 08:00"]


def test_days_of_the_week_are_local_days() -> None:
    tokyo = get_zone("Asia/Tokyo")
    # 07:15 on a Monday in Tokyo is still Sunday in UTC.
    run = parse_schedule("mon 07:15").next_after(datetime(2026, 7, 4, tzinfo=UTC), tokyo)
    assert run == datetime(2026, 7, 5, 22, 15, tzinfo=UTC)


def test_every_counts_elapsed_time() -> None:
    schedule = parse_schedule("every 30m")
    start = datetime(2026, 7, 1, 9, 10, tzinfo=UTC)
    assert runs_between(schedule, AMSTERDAM, start, start + timedelta(hours=1)) == [
        datetime(2026, 7, 1, 9, 30, tzinfo=UTC),
        datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
    ]


def test_winter_and_new_york() -> None:
    new_york = get_zone("America/New_York")
    start = datetime(2026, 1, 12, 0, 0, tzinfo=UTC)
    run = parse_schedule("weekdays 09:45").next_after(start, new_york)
    assert run == datetime(2026, 1, 12, 14, 45, tzinfo=UTC)
