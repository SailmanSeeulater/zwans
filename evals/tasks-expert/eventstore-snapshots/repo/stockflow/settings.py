"""Settings, read from stockflow.toml in the data directory."""

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from stockflow.errors import SettingsError

SETTINGS_FILE = "stockflow.toml"

# table -> setting -> (attribute on Settings, type, smallest value allowed)
SCHEMA: dict[str, dict[str, tuple[str, type, int | None]]] = {
    "store": {
        "fsync": ("fsync", bool, None),
    },
    "inventory": {
        "low_stock_threshold": ("low_stock_threshold", int, 0),
        "default_reorder_level": ("default_reorder_level", int, 0),
    },
}


@dataclass
class Settings:
    fsync: bool = True
    low_stock_threshold: int = 5
    default_reorder_level: int = 0

    @classmethod
    def load(cls, directory: str | Path | None) -> "Settings":
        """Settings from <directory>/stockflow.toml; the defaults if there is no such file."""
        if directory is None:
            return cls()
        path = Path(directory) / SETTINGS_FILE
        if not path.exists():
            return cls()
        try:
            data = tomllib.loads(path.read_text("utf-8"))
        except tomllib.TOMLDecodeError as error:
            raise SettingsError(f"{path}: {error}") from None
        return cls.from_dict(data, where=str(path))

    @classmethod
    def from_dict(cls, data: dict[str, Any], where: str = "settings") -> "Settings":
        values: dict[str, Any] = {}
        for table, body in data.items():
            known = SCHEMA.get(table)
            if known is None:
                raise SettingsError(f"{where}: unknown table [{table}]")
            if not isinstance(body, dict):
                raise SettingsError(f"{where}: [{table}] must be a table")
            for key, value in body.items():
                if key not in known:
                    raise SettingsError(f"{where}: unknown setting {table}.{key}")
                attribute, kind, minimum = known[key]
                if type(value) is not kind:
                    raise SettingsError(f"{where}: {table}.{key} must be a {kind.__name__}")
                if minimum is not None and value < minimum:
                    raise SettingsError(f"{where}: {table}.{key} must be at least {minimum}")
                values[attribute] = value
        return cls(**values)

    def to_dict(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        names = {field.name for field in fields(self)}
        for table, known in SCHEMA.items():
            for key, (attribute, _, _) in known.items():
                if attribute in names:
                    out.setdefault(table, {})[key] = getattr(self, attribute)
        return out
