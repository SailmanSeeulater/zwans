"""Plugins add rules to the policy engine.

A plugin is a class registered under a name with `@register("name")`. Only the plugins
named in the configuration's `plugins.enabled` list are loaded and run. A plugin can:

- `grants(ctx, user, at)`: give `user` extra roles at the instant `at`;
- `check(ctx, request)`: veto a request by returning the reason, or return None.

A request is allowed only when no enabled plugin vetoes it.
"""

import importlib
from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ledgerdesk.context import Context
    from ledgerdesk.directory import User
    from ledgerdesk.policy.engine import Request

# Plugin name -> the module in this package that defines it.
MODULES = {
    "four_eyes": "four_eyes",
    "conflicts": "conflicts",
    "availability": "availability",
    "business_hours": "hours",
    "legacy_superuser": "legacy",
    "debug_grants": "debug",
}

REGISTRY: dict[str, "Plugin"] = {}


class PluginError(Exception):
    pass


class Plugin:
    name = ""

    def grants(self, ctx: "Context", user: "User", at: datetime) -> list[str]:
        return []

    def check(self, ctx: "Context", request: "Request") -> str | None:
        return None


def register(name: str):
    def decorate(cls: type[Plugin]) -> type[Plugin]:
        instance = cls()
        instance.name = name
        REGISTRY[name] = instance
        return cls

    return decorate


def load_plugins(names: Iterable[str]) -> list[Plugin]:
    plugins = []
    for name in names:
        if name not in MODULES:
            raise PluginError(f"unknown plugin {name!r}")
        importlib.import_module(f"{__name__}.{MODULES[name]}")
        if name not in REGISTRY:
            raise PluginError(f"module {MODULES[name]} does not register {name!r}")
        if REGISTRY[name] not in plugins:
            plugins.append(REGISTRY[name])
    return plugins
