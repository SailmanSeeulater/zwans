import pytest

from timesheet.entries import EntryError, parse_clock, parse_line, parse_sheet


def test_parse_clock() -> None:
    assert parse_clock("00:00") == 0
    assert parse_clock("09:30") == 570
    assert parse_clock("23:59") == 1439


@pytest.mark.parametrize("text", ["24:00", "9.30", "09:5", "ab:cd", "12:60"])
def test_bad_clock(text: str) -> None:
    with pytest.raises(EntryError):
        parse_clock(text)


def test_parse_line() -> None:
    entry = parse_line("2024-03-04 09:00-17:30 Billing")

    assert entry.project == "billing"
    assert entry.minutes == 510


def test_sheet_errors_have_line_numbers() -> None:
    with pytest.raises(EntryError, match="line 3"):
        parse_sheet("# week 10\n2024-03-04 09:00-12:00 a\n2024-03-04 12:00\n")
