from datetime import datetime

import pytest

from timer.durations import format_duration
from timer.reminders import Reminder


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0, "0s"), (45, "45s"), (5400, "1h30m"), (187200, "2d4h"), (90061, "1d1h1m1s")],
)
def test_format_duration(seconds: int, text: str) -> None:
    assert format_duration(seconds) == text


def test_format_a_negative_duration() -> None:
    with pytest.raises(ValueError):
        format_duration(-1)


def test_reminder_due_time_and_text() -> None:
    reminder = Reminder(message="stretch", seconds=600)

    assert reminder.due(datetime(2024, 1, 1, 9, 55)) == datetime(2024, 1, 1, 10, 5)
    assert str(reminder) == "in 10m: stretch"
