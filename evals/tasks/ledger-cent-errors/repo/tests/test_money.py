import pytest

from books.money import AmountError, format_amount, parse_amount, percent_of


def test_parse_and_format() -> None:
    assert format_amount(parse_amount("1,234.5")) == "1,234.50"
    assert format_amount(parse_amount("-3")) == "-3.00"
    assert format_amount(parse_amount("(12.00)")) == "-12.00"


@pytest.mark.parametrize("text", ["", "abc", "1.234", "1.2.3", "$5"])
def test_bad_amounts(text: str) -> None:
    with pytest.raises(AmountError):
        parse_amount(text)


def test_percent_of() -> None:
    assert format_amount(percent_of(parse_amount("200.00"), "8.25")) == "16.50"
    assert format_amount(percent_of(parse_amount("10.50"), "8.25")) == "0.87"
