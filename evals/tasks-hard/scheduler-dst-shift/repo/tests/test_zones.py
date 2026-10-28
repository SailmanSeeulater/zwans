from datetime import UTC, date, datetime, timedelta

import pytest
from cronlite.rules import EURule, USRule, nth_weekday
from cronlite.zones import UnknownZone, get_zone


def test_nth_weekday() -> None:
    assert nth_weekday(2026, 3, 6, -1) == date(2026, 3, 29)
    assert nth_weekday(2026, 10, 6, -1) == date(2026, 10, 25)
    assert nth_weekday(2026, 3, 6, 2) == date(2026, 3, 8)
    assert nth_weekday(2026, 11, 6, 1) == date(2026, 11, 1)
    assert nth_weekday(2026, 12, 3, -1) == date(2026, 12, 31)


def test_summer_time_rules() -> None:
    assert EURule().summer(2026, timedelta(hours=1)) == (
        datetime(2026, 3, 29, 1, tzinfo=UTC),
        datetime(2026, 10, 25, 1, tzinfo=UTC),
    )
    assert USRule().summer(2026, timedelta(hours=-5)) == (
        datetime(2026, 3, 8, 7, tzinfo=UTC),
        datetime(2026, 11, 1, 6, tzinfo=UTC),
    )


def test_offsets_change_at_the_transitions() -> None:
    amsterdam = get_zone("Europe/Amsterdam")
    assert amsterdam.offset_at(datetime(2026, 10, 25, 0, 59, tzinfo=UTC)) == timedelta(hours=2)
    assert amsterdam.offset_at(datetime(2026, 10, 25, 1, 0, tzinfo=UTC)) == timedelta(hours=1)
    assert get_zone("Asia/Tokyo").offset_at(datetime(2026, 7, 1, tzinfo=UTC)) == timedelta(hours=9)


def test_to_local() -> None:
    amsterdam = get_zone("Europe/Amsterdam")
    assert amsterdam.to_local(datetime(2026, 7, 1, 6, 0, tzinfo=UTC)) == datetime(2026, 7, 1, 8, 0)
    assert amsterdam.to_local(datetime(2026, 12, 1, 6, 0, tzinfo=UTC)) == datetime(
        2026, 12, 1, 7, 0
    )
    new_york = get_zone("America/New_York")
    assert new_york.to_local(datetime(2026, 7, 1, 2, 0, tzinfo=UTC)) == datetime(2026, 6, 30, 22, 0)


def test_to_utc_on_ordinary_days() -> None:
    amsterdam = get_zone("Europe/Amsterdam")
    assert amsterdam.to_utc(datetime(2026, 7, 1, 8, 0)) == datetime(2026, 7, 1, 6, 0, tzinfo=UTC)
    assert amsterdam.to_utc(datetime(2026, 12, 1, 8, 0)) == datetime(2026, 12, 1, 7, 0, tzinfo=UTC)
    kolkata = get_zone("Asia/Kolkata")
    assert kolkata.to_utc(datetime(2026, 1, 1, 0, 0)) == datetime(2025, 12, 31, 18, 30, tzinfo=UTC)


def test_unknown_zone() -> None:
    with pytest.raises(UnknownZone, match="Mars/Olympus"):
        get_zone("Mars/Olympus")
