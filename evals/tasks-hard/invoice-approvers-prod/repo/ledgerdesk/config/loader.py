"""Loading ledgerdesk's configuration.

The configuration is built from TOML files in the `config/` folder at the project root:

1. `base.toml`, always;
2. `<env>.toml`, where `<env>` is the environment named by the `LEDGERDESK_ENV`
   environment variable (`dev` when it is not set);
3. `local.toml`, a developer's own overrides, if the file exists and the environment is
   *not* `prod`. Production never reads it.

Each file is merged over the result so far (see `merge`).
"""

import os
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_ENV = "dev"
ENV_VARIABLE = "LEDGERDESK_ENV"


class ConfigError(Exception):
    pass


def current_env() -> str:
    return os.environ.get(ENV_VARIABLE, DEFAULT_ENV).strip().lower() or DEFAULT_ENV


def merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge `overlay` over `base` and return the result; neither argument is changed.

    - Tables are merged key by key, recursively.
    - Any other value in the overlay replaces the base value, lists included.
    - A key written with a trailing `+`, like `"enabled+" = ["x"]`, *appends* its list to
      the base list of the key without the `+` instead of replacing it.
    """
    result = deepcopy(base)
    for key, value in overlay.items():
        if key.endswith("+"):
            name = key[:-1]
            existing = result.get(name, [])
            if not isinstance(existing, list) or not isinstance(value, list):
                raise ConfigError(f"{key}: only lists can be appended to")
            result[name] = existing + deepcopy(value)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _read(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path.name}: {exc}") from exc


def load_config(env: str | None = None, config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    env = env or current_env()
    env_file = config_dir / f"{env}.toml"
    if not env_file.is_file():
        raise ConfigError(f"no configuration for environment {env!r} ({env_file.name})")
    config = _read(config_dir / "base.toml")
    config = merge(config, _read(env_file))
    local_file = config_dir / "local.toml"
    if env != "prod" and local_file.is_file():
        config = merge(config, _read(local_file))
    config["env"] = env
    return config
