"""Changing helpdesk-wide settings."""

from __future__ import annotations

from typing import Any

from .. import config
from ..context import Context
from ..permissions import require


def set_setting(ctx: Context, key: str, value: Any) -> Any:
    require(ctx, "admin", target=key)
    value = config.coerce(key, value)
    with ctx.store.transaction():
        old = config.get(ctx.store.settings, key)
        ctx.store.settings[key] = value
        if old != value:
            ctx.record("setting.changed", key, **{"from": old, "to": value})
    return value


def all_settings(ctx: Context) -> dict[str, Any]:
    return config.describe(ctx.store.settings)
