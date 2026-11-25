"""Helpdesk-wide settings, kept in the store next to the data."""

from __future__ import annotations

from typing import Any

from .errors import ValidationError

DEFAULTS: dict[str, Any] = {
    "desk_name": "Deskline Support",
    "support_address": "support@deskline.example",
    "auto_close_days": 4,
    "survey_on_solve": True,
    "outbox_keep_days": 30,
    "default_queue": "general",
}

_TYPES: dict[str, type] = {
    "desk_name": str,
    "support_address": str,
    "auto_close_days": int,
    "survey_on_solve": bool,
    "outbox_keep_days": int,
    "default_queue": str,
}


def get(settings: dict[str, Any], key: str) -> Any:
    if key not in DEFAULTS:
        raise ValidationError(f"unknown setting {key!r}")
    return settings.get(key, DEFAULTS[key])


def coerce(key: str, raw: Any) -> Any:
    if key not in _TYPES:
        raise ValidationError(f"unknown setting {key!r}")
    wanted = _TYPES[key]
    if isinstance(raw, wanted) and not (wanted is int and isinstance(raw, bool)):
        return raw
    if isinstance(raw, str):
        if wanted is bool:
            if raw.lower() in ("1", "true", "yes", "on"):
                return True
            if raw.lower() in ("0", "false", "no", "off"):
                return False
        elif wanted is int:
            try:
                return int(raw)
            except ValueError:
                pass
        elif wanted is str:
            return raw
    raise ValidationError(f"setting {key} must be a {wanted.__name__}")


def describe(settings: dict[str, Any]) -> dict[str, Any]:
    return {key: settings.get(key, default) for key, default in DEFAULTS.items()}
