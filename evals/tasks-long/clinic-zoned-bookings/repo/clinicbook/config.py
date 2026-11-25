"""Settings, stored in the data file's `settings` table."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

from .errors import ValidationError
from .validation import check_hours_list


@dataclass
class Settings:
    grid_minutes: int = 5  # appointments start and last multiples of this
    slot_minutes: int = 15  # slot searches try a start every this many minutes
    search_days: int = 28  # how far ahead a slot search looks
    reminder_hours: list[int] = field(default_factory=lambda: [24, 2])
    no_show_grace: int = 15  # minutes after the end before a booking counts as a no-show
    waitlist_expiry_days: int = 60
    webhook_url: str = ""
    webhook_secret: str = ""
    webhook_max_attempts: int = 6

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        settings = cls()
        settings.update(**data)
        return settings

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def update(self, **changes: Any) -> None:
        known = {f.name: f for f in fields(self)}
        for key, value in changes.items():
            if key not in known:
                raise ValidationError(f"unknown setting {key!r}")
            setattr(self, key, self._clean(key, value))

    def _clean(self, key: str, value: Any) -> Any:
        if key == "reminder_hours":
            return check_hours_list(value)
        if key in ("webhook_url", "webhook_secret"):
            if not isinstance(value, str):
                raise ValidationError(f"{key} must be text")
            if key == "webhook_url" and value and not value.startswith(("http://", "https://")):
                raise ValidationError(f"webhook_url must be an http(s) URL, not {value!r}")
            return value
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValidationError(f"{key} must be a whole number >= 0, not {value!r}")
        if key in ("grid_minutes", "slot_minutes") and (value == 0 or 60 % value):
            raise ValidationError(f"{key} must divide an hour, not {value}")
        return value
