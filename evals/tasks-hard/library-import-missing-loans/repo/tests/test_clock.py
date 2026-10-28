from datetime import UTC, date, datetime, timedelta

import pytest
from libsys.clock import TimestampError, format_day, local_date, parse_utc


def test_parse_utc() -> None:
    assert parse_utc("2026-02-07T10:15:00Z") == datetime(2026, 2, 7, 10, 15, tzinfo=UTC)
    assert parse_utc("2026-02-07T23:15:00+13:00") == datetime(2026, 2, 7, 10, 15, tzinfo=UTC)
    with pytest.raises(TimestampError, match="no time zone"):
        parse_utc("2026-02-07T10:15:00")
    with pytest.raises(TimestampError):
        parse_utc("yesterday")


def test_local_date_can_be_the_next_day() -> None:
    evening_utc = datetime(2026, 2, 5, 22, 5, tzinfo=UTC)
    assert local_date(evening_utc, timedelta(hours=13)) == date(2026, 2, 6)
    assert local_date(evening_utc, timedelta(hours=-5)) == date(2026, 2, 5)


def test_format_day() -> None:
    assert format_day(date(2026, 3, 2)) == "2 Mar 2026"
