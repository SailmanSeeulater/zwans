"""Settings, with defaults that suit a small team. An optional orbit.toml next to the data
file can change them:

    [orbit]
    undo_limit = 50
    outbox_max_attempts = 6
    phone_match_digits = 9
"""

import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path

from orbit.errors import InvalidValue


@dataclass(frozen=True)
class Settings:
    undo_limit: int = 50
    outbox_max_attempts: int = 6
    retry_after_seconds: int = 60
    phone_match_digits: int = 9
    default_owner: str = ""


def load_settings(path: Path | None) -> Settings:
    settings = Settings()
    if path is None or not path.exists():
        return settings
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8")).get("orbit", {})
    except tomllib.TOMLDecodeError as exc:
        raise InvalidValue(f"{path}: {exc}") from None
    defaults = {f.name: getattr(settings, f.name) for f in fields(Settings)}
    changes = {}
    for key, value in data.items():
        if key not in defaults:
            raise InvalidValue(f"{path}: unknown setting {key!r}")
        expected = type(defaults[key])
        if not isinstance(value, expected) or isinstance(value, bool):
            raise InvalidValue(f"{path}: {key} must be {expected.__name__}")
        changes[key] = value
    settings = replace(settings, **changes)
    if settings.undo_limit < 1 or settings.outbox_max_attempts < 1:
        raise InvalidValue(f"{path}: limits must be at least 1")
    return settings
