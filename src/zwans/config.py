"""Settings from ~/.zwans/config.toml, overridden by ZWANS_* environment variables.

Credentials come only from environment variables, or a .env file in the folder you run
zwans from, never from the config file. They use the same variables as NexTix:
ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN.
"""

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

type AuthMode = Literal["api_key", "subscription"]
type Effort = Literal["low", "medium", "high", "xhigh", "max"]

ZWANS_HOME = Path.home() / ".zwans"
DEFAULT_CONFIG_PATH = ZWANS_HOME / "config.toml"

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
    effort: Effort = "medium"  # how much the model thinks; the main cost and latency control
    max_tokens: int = 64_000  # per model call, thinking included
    max_steps: int = 50  # model calls allowed in one turn
    shell: str | None = None  # path to bash; found automatically when unset
    transcript_dir: Path = ZWANS_HOME / "transcripts"


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


def read_dotenv(path: Path) -> dict[str, str]:
    """Read KEY=value lines from a .env file. Lines starting with # are comments."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():  # -sig: Notepad's BOM
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.removeprefix("export ").strip()] = value
    return values


def load_credential(config: Config, env: Mapping[str, str] = os.environ) -> Credential:
    var = CREDENTIAL_VARS[config.auth]
    token = env.get(var, "").strip()
    if not token:
        hint = CREDENTIAL_HINTS[config.auth]
        raise ConfigError(f"auth is {config.auth!r} but {var} is not set. {hint}")
    return Credential(mode=config.auth, token=token)
