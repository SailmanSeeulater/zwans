import pytest

from timer.durations import DurationError, format_duration, parse_duration
from timer.reminders import Reminder


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("45s", 45),
        ("1h30m", 5400),
        ("2d 4h", 187200),
        ("1d1h1m1s", 90061),
        ("90m", 5400),
        ("0s", 0),
        ("1H30M", 5400),
        ("  2d4h ", 187200),
        ("1h   5s", 3605),
        ("007m", 420),
        ("3d", 259200),
    ],
)
def test_parse_duration(text: str, seconds: int) -> None:
    assert parse_duration(text) == seconds


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "90",
        "h",
        "3w",
        "-5m",
        "+5m",
        "1.5h",
        "1h, 30m",
        "30m1h",
        "1h1h",
        "1 h",
        "1h30",
        "1hh",
        "m5",
    ],
)
def test_invalid_durations(text: str) -> None:
    with pytest.raises(DurationError):
        parse_duration(text)


def test_duration_error_is_a_value_error() -> None:
    assert issubclass(DurationError, ValueError)


@pytest.mark.parametrize("seconds", [0, 1, 59, 60, 3599, 3600, 86399, 86400, 987654])
def test_round_trip(seconds: int) -> None:
    assert parse_duration(format_duration(seconds)) == seconds


def test_reminder_from_text() -> None:
    reminder = Reminder.from_text("1h30m water the plants")

    assert reminder == Reminder(message="water the plants", seconds=5400)


def test_reminder_with_a_bad_duration() -> None:
    with pytest.raises(DurationError):
        Reminder.from_text("soon water the plants")
