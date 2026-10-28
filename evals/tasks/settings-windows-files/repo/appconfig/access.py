"""Typed access to values in loaded settings."""

from appconfig.settings import Settings, SettingsError

_TRUE = {"1", "yes", "true", "on"}
_FALSE = {"0", "no", "false", "off"}


def get_str(settings: Settings, section: str, key: str, default: str | None = None) -> str:
    value = settings.get(section.lower(), {}).get(key.lower(), default)
    if value is None:
        raise SettingsError(f"missing setting {section}.{key}")
    return value


def get_int(settings: Settings, section: str, key: str, default: int | None = None) -> int:
    raw = get_str(settings, section, key, None if default is None else str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise SettingsError(f"{section}.{key} should be a whole number, not {raw!r}") from exc


def get_bool(settings: Settings, section: str, key: str, default: bool | None = None) -> bool:
    fallback = None if default is None else ("yes" if default else "no")
    raw = get_str(settings, section, key, fallback).lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise SettingsError(f"{section}.{key} should be yes or no, not {raw!r}")
