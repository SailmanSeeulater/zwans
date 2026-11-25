"""Reading and checking the gateway's TOML config."""

import math
import tomllib
from dataclasses import dataclass, field
from typing import Any

DEFAULT_IDLE_AFTER = 3600.0
METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


class ConfigError(ValueError):
    """The config can't be used; the message says where."""


@dataclass(frozen=True)
class Plan:
    name: str
    limit: int
    window: float


@dataclass(frozen=True)
class Route:
    prefix: str
    upstream: str
    methods: frozenset[str] | None = None
    strip_prefix: bool = False

    def allows(self, method: str) -> bool:
        return self.methods is None or method in self.methods


@dataclass
class Config:
    plans: dict[str, Plan] = field(default_factory=dict)
    keys: dict[str, str] = field(default_factory=dict)
    routes: list[Route] = field(default_factory=list)
    idle_after: float = DEFAULT_IDLE_AFTER
    stats_key: str | None = None

    def plan_for(self, key: str) -> Plan | None:
        name = self.keys.get(key)
        return None if name is None else self.plans[name]


def parse_config(text: str) -> Config:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"not valid TOML: {error}") from None
    unknown = set(data) - {"gateway", "plans", "keys", "routes"}
    if unknown:
        raise ConfigError(f"unknown section(s): {', '.join(sorted(unknown))}")
    config = Config()
    _read_gateway(_table(data, "gateway"), config)
    config.plans = _read_plans(_table(data, "plans"))
    config.keys = _read_keys(_table(data, "keys"), config.plans, config.stats_key)
    config.routes = _read_routes(data.get("routes", []))
    return config


def _table(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a table")
    return value


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{where} must be a number")
    if not math.isfinite(value):
        raise ConfigError(f"{where} must be finite")
    return float(value)


def _read_gateway(table: dict[str, Any], config: Config) -> None:
    unknown = set(table) - {"idle_after", "stats_key"}
    if unknown:
        raise ConfigError(f"unknown [gateway] setting(s): {', '.join(sorted(unknown))}")
    if "idle_after" in table:
        idle_after = _number(table["idle_after"], "gateway.idle_after")
        if idle_after <= 0:
            raise ConfigError("gateway.idle_after must be greater than 0")
        config.idle_after = idle_after
    if "stats_key" in table:
        stats_key = table["stats_key"]
        if not isinstance(stats_key, str) or not stats_key.strip():
            raise ConfigError("gateway.stats_key must be a non-empty string")
        config.stats_key = stats_key.strip()


def _read_plans(table: dict[str, Any]) -> dict[str, Plan]:
    plans: dict[str, Plan] = {}
    for name, body in table.items():
        if not isinstance(body, dict):
            raise ConfigError(f"[plans.{name}] must be a table")
        unknown = set(body) - {"limit", "window"}
        if unknown:
            raise ConfigError(f"unknown setting(s) in plans.{name}: {', '.join(sorted(unknown))}")
        limit = body.get("limit")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ConfigError(f"plans.{name}.limit must be a whole number, at least 1")
        if "window" not in body:
            raise ConfigError(f"plans.{name}.window is missing")
        window = _number(body["window"], f"plans.{name}.window")
        if window <= 0:
            raise ConfigError(f"plans.{name}.window must be greater than 0")
        plans[name] = Plan(name, limit, window)
    return plans


def _read_keys(
    table: dict[str, Any], plans: dict[str, Plan], stats_key: str | None
) -> dict[str, str]:
    keys: dict[str, str] = {}
    for key, plan in table.items():
        if not key.strip():
            raise ConfigError("an API key can't be blank")
        if not isinstance(plan, str):
            raise ConfigError(f"keys.{key} must name a plan")
        if plan not in plans:
            raise ConfigError(f"keys.{key} uses plan {plan!r}, which isn't defined")
        if key == stats_key:
            raise ConfigError("the stats key can't also be an API key")
        keys[key.strip()] = plan
    return keys


def _read_routes(items: Any) -> list[Route]:
    if not isinstance(items, list):
        raise ConfigError("routes must be an array of tables ([[routes]])")
    routes: list[Route] = []
    seen: set[str] = set()
    for number, body in enumerate(items, start=1):
        where = f"route {number}"
        if not isinstance(body, dict):
            raise ConfigError(f"{where} must be a table")
        unknown = set(body) - {"prefix", "upstream", "methods", "strip_prefix"}
        if unknown:
            raise ConfigError(f"unknown setting(s) in {where}: {', '.join(sorted(unknown))}")
        prefix = body.get("prefix")
        if not isinstance(prefix, str) or not prefix.startswith("/"):
            raise ConfigError(f"{where}: prefix must be a path starting with /")
        prefix = prefix.rstrip("/") or "/"
        if prefix == "/_stats" or prefix.startswith("/_stats/"):
            raise ConfigError(f"{where}: /_stats is reserved")
        if prefix in seen:
            raise ConfigError(f"{where}: prefix {prefix} is used twice")
        seen.add(prefix)
        upstream = body.get("upstream")
        if not isinstance(upstream, str) or not upstream:
            raise ConfigError(f"{where}: upstream must be a name")
        methods = body.get("methods")
        if methods is not None:
            if not isinstance(methods, list) or not methods:
                raise ConfigError(f"{where}: methods must be a non-empty list")
            upper = {str(method).upper() for method in methods}
            bad = upper - METHODS
            if bad:
                raise ConfigError(f"{where}: unknown method(s) {', '.join(sorted(bad))}")
            methods = frozenset(upper)
        strip = body.get("strip_prefix", False)
        if not isinstance(strip, bool):
            raise ConfigError(f"{where}: strip_prefix must be true or false")
        routes.append(Route(prefix, upstream, methods, strip))
    return routes
