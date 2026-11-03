"""Settings from ~/.zwans/config.toml, overridden by ZWANS_* environment variables.
ZWANS_CONFIG names a different config file.

Credentials come only from environment variables, or a .env file in the folder you run
zwans from, never from the config file. They use the same variables as NexTix:
ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN.
"""

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

type AuthMode = Literal["api_key", "subscription"]
type Effort = Literal["low", "medium", "high", "xhigh", "max"]
# What prompt caching covers: the system prompt and tools plus the conversation so far, only
# the system prompt and tools, or nothing (to measure what caching saves)
type PromptCache = Literal["conversation", "system", "off"]

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


class McpServerConfig(BaseModel):
    """One MCP server; see mcp/tools.py."""

    model_config = ConfigDict(extra="forbid")

    command: str | None = None  # a program to start, talking over stdio
    args: list[str] = []
    env: dict[str, str] = {}
    url: str | None = None  # or a server to reach over streamable HTTP
    headers: dict[str, str] = {}
    timeout: float = Field(default=120, gt=0)  # seconds a tool call may take

    @model_validator(mode="after")
    def _one_transport(self) -> Self:
        if (self.command is None) == (self.url is None):
            raise ValueError("set either command (for stdio) or url (for HTTP), not both")
        return self


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "claude-opus-5-5"
    auth: AuthMode = "api_key"
    effort: Effort = "medium"  # how much the model thinks; the main cost and latency control
    max_tokens: int = 64_000  # per model call, thinking included
    max_steps: int = 50  # model calls allowed in one turn
    subagents: bool = True  # offer the Task tool
    subagent_max_steps: int = 30  # model calls allowed in one subagent's task
    compact_at: int = 200_000  # estimated context tokens that trigger a compaction
    keep_messages: int = 8  # recent messages kept word for word when compacting
    prompt_cache: PromptCache = "conversation"
    shell: str | None = None  # path to bash; found automatically when unset
    # Where commands run: on this machine, in a Docker container (executor/docker.py), or in
    # zwans-jail, Zwans's own sandbox (executor/jail.py, Linux only)
    executor: Literal["local", "docker", "jail"] = "local"
    home: Path = ZWANS_HOME  # transcripts, saved sessions, and saved tool output live here
    mcp_servers: dict[str, McpServerConfig] = {}  # tools from MCP servers, by server name


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
        other: AuthMode = "subscription" if config.auth == "api_key" else "api_key"
        if env.get(CREDENTIAL_VARS[other], "").strip():
            hint = f"{CREDENTIAL_VARS[other]} is set, so to use it, set ZWANS_AUTH={other}."
        raise ConfigError(f"auth is {config.auth!r} but {var} is not set. {hint}")
    return Credential(mode=config.auth, token=token)


def load_settings() -> tuple[Config, dict[str, str]]:
    """The config, and the environment with a .env file from the current folder merged in.

    Real environment variables win over the .env file. The merged values stay in the returned
    dictionary rather than os.environ, so commands the agent runs never inherit them.
    """
    env = {**read_dotenv(Path(".env")), **os.environ}
    path = Path(env["ZWANS_CONFIG"]).expanduser() if env.get("ZWANS_CONFIG") else None
    return load_config(path or DEFAULT_CONFIG_PATH, env=env), env
