import pytest

from duration import parse_duration


def test_single_units():
    assert parse_duration("90s") == 90
    assert parse_duration("5m") == 300
    assert parse_duration("2h") == 7200


def test_combined():
    assert parse_duration("1h30m") == 5400
    assert parse_duration("1m5s") == 65


def test_rejects_junk():
    with pytest.raises(ValueError):
        parse_duration("abc")
