"""Reminders written as "<duration> <message>", like "20m take the bread out"."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from timer.durations import format_duration, parse_duration


@dataclass(frozen=True)
class Reminder:
    message: str
    seconds: int

    @classmethod
    def from_text(cls, text: str) -> "Reminder":
        when, _, message = text.strip().partition(" ")
        if not message.strip():
            raise ValueError("a reminder needs a message after the duration")
        return cls(message=message.strip(), seconds=parse_duration(when))

    def due(self, now: datetime) -> datetime:
        return now + timedelta(seconds=self.seconds)

    def __str__(self) -> str:
        return f"in {format_duration(self.seconds)}: {self.message}"
