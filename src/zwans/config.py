"""Settings from ~/.zwans/config.toml, overridden by ZWANS_* environment variables.

Credentials come only from the environment, never from the config file. They use the
same variables as NexTix: ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN.
"""

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

type AuthMode = Literal["api_key", "subscription"]

DEFAULT_CONFIG_PATH = Path.home() / ".zwans" / "config.toml"

CREDENTIAL_VARS: dict[AuthMode, str] = {
    "api_key": "ANTHROPIC_API_KEY",
    "subscription": "CLAUDE_CODE_OAUTH_TOKEN",
}

CREDENTIAL_HINTS: dict[AuthMode, str] = {
    "api_key": "Create a key in the Claude Console.",
    "subscription": "Create one with `claude setup-token`.",
}


class ConfigError(Exception):
    pass


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "claude-opus-5-5"
    auth: AuthMode = "api_key"


@dataclass(frozen=True)
class Credential:
    mode: AuthMode
    token: str = field(repr=False)  # keeps the secret out of logs and tracebacks


def load_config(path: Path = DEFAULT_CONFIG_PATH, env: Mapping[str, str] = os.environ) -> Config:
    data: dict[str, Any] = {}
    if path.exists():
        with path.open("rb") as f:
            data = tomllib.load(f)
    for name in Config.model_fields:
        value = env.get(f"ZWANS_{name.upper()}")
        if value is not None:
            data[name] = value
    return Config.model_validate(data)


def load_credential(config: Config, env: Mapping[str, str] = os.environ) -> Credential:
    var = CREDENTIAL_VARS[config.auth]
    token = env.get(var, "").strip()
    if not token:
        hint = CREDENTIAL_HINTS[config.auth]
        raise ConfigError(f"auth is {config.auth!r} but {var} is not set. {hint}")
    return Credential(mode=config.auth, token=token)
