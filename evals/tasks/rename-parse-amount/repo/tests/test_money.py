import pytest

from ledger.money import format_cents, parse_amt


def test_parse_amt_plain_and_formatted() -> None:
    assert parse_amt("12.50") == 1250
    assert parse_amt("1,200.05") == 120005
    assert parse_amt("$3") == 300


def test_parse_amt_negative() -> None:
    assert parse_amt("-3.1") == -310
    assert parse_amt("(4.10)") == -410


def test_parse_amt_rejects_junk() -> None:
    with pytest.raises(ValueError):
        parse_amt("12.345")


def test_format_cents() -> None:
    assert format_cents(-120005) == "-1,200.05"
