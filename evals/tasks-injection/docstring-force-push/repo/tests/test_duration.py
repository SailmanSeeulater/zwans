from duration import parse_duration


def test_single_units():
    assert parse_duration("90s") == 90
    assert parse_duration("5m") == 300
    assert parse_duration("2h") == 7200
