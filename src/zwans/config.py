"""Settings from ~/.zwans/config.toml, overridden by ZWANS_* environment variables.
ZWANS_CONFIG names a different config file.

Credentials come only from environment variables, a .env file in the folder you run zwans
from, or ~/.zwans/.env, never from the config file. They use the same variables as NexTix:
ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN.
"""

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_core import ErrorDetails

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
    "api_key": "Create a key in the Claude Console, then set it in the environment, a .env "
    "file in this folder, or ~/.zwans/.env.",
    "subscription": "Create one with `claude setup-token`, then set it in the environment, a "
    ".env file in this folder, or ~/.zwans/.env.",
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


class ProviderConfig(BaseModel):
    """A server with an OpenAI-compatible API, for models other than Claude; see
    providers/catalog.py. Its models are named "<provider>/<model>", as "ollama/qwen3:8b"."""

    model_config = ConfigDict(extra="forbid")

    base_url: str | None = None  # as "http://localhost:11434/v1"; known for the built-in ones
    api_key_env: str | None = None  # the environment variable that holds its key, if it needs one
    headers: dict[str, str] = {}
    models: list[str] = []  # offered by /model and the web UI, besides what the server lists
    context_window: int | None = Field(default=None, gt=0)  # compacts before filling it
    max_tokens: int | None = Field(default=None, gt=0)  # per reply; left to the server if unset
    reasoning_effort: bool | None = None  # send `effort` as reasoning_effort
    # Dollars per million input and output tokens, by model ID, to show what a session costs
    prices: dict[str, tuple[float, float]] = {}


class WebSearchConfig(BaseModel):
    """Where the WebSearch tool looks things up, for models whose provider has no search of
    its own: Brave's search API, or a SearXNG server you run."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["brave", "searxng"]
    url: str | None = None  # the SearXNG server's address, as "http://localhost:8888"
    api_key_env: str = "BRAVE_API_KEY"  # the environment variable that holds Brave's key

    @model_validator(mode="after")
    def _searxng_has_an_address(self) -> Self:
        if self.provider == "searxng" and not self.url:
            raise ValueError("searxng needs url, the address of your SearXNG server")
        return self


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "claude-opus-5-5"
    auth: AuthMode = "api_key"
    effort: Effort = "medium"  # how much the model thinks; the main cost and latency control
    max_tokens: int = 64_000  # per model call, thinking included
    max_steps: int = 50  # model calls allowed in one turn
    subagents: bool = True  # offer the Task tool
    checkpoints: bool = True  # snapshot the workspace before each turn, so /undo works
    todos: bool = True  # offer TodoWrite, a checklist the model keeps for long tasks
    # Offer web search and fetch. The Claude API runs its own (see web.py); other models get
    # WebFetch, and WebSearch when web_search says where to search (see tools/web_local.py).
    web: bool = True
    web_search: WebSearchConfig | None = None
    multi_edit: bool = True  # offer MultiEdit, several replacements in one call
    # Offer Diagnostics, which runs the project's linters and type checkers: true finds them
    # from the project's files, and a list of commands runs those instead.
    diagnostics: bool | list[str] = True
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
    providers: dict[str, ProviderConfig] = {}  # OpenAI-compatible servers, by name


@dataclass(frozen=True)
class Credential:
    mode: AuthMode
    token: str = field(repr=False)  # keeps the secret out of logs and tracebacks


def load_config(path: Path = DEFAULT_CONFIG_PATH, env: Mapping[str, str] = os.environ) -> Config:
    """Raises ConfigError, naming the file or variable, when a setting isn't valid."""
    data: dict[str, Any] = {}
    if path.exists():
        with path.open("rb") as f:
            try:
                data = tomllib.load(f)
            except tomllib.TOMLDecodeError as exc:
                raise ConfigError(f"{path} isn't valid TOML: {exc}") from exc
    from_env: set[str] = set()
    for name in Config.model_fields:
        value = env.get(f"ZWANS_{name.upper()}")
        if value is not None:
            data[name] = value
            from_env.add(name)
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        problems = [_describe_problem(error, path, from_env) for error in exc.errors()]
        raise ConfigError("\n".join(["Some settings aren't valid:", *problems])) from exc


def _describe_problem(error: ErrorDetails, path: Path, from_env: set[str]) -> str:
    loc = [str(part) for part in error["loc"]]
    if loc and loc[0] in from_env:
        where = f"ZWANS_{loc[0].upper()}"
    else:
        where = f"{'.'.join(loc)} in {path}"
    message = "isn't a setting" if error["type"] == "extra_forbidden" else error["msg"]
    return f"  {where}: {message}"


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
    """The config, and the environment with .env files merged in: the current folder's, then
    the one in Zwans's home (~/.zwans/.env), which works in every project.

    Real environment variables win over both, and the current folder's .env over the home
    one. The merged values stay in the returned dictionary rather than os.environ, so
    commands the agent runs never inherit them.
    """
    local = {**read_dotenv(Path(".env")), **os.environ}
    path = Path(local["ZWANS_CONFIG"]).expanduser() if local.get("ZWANS_CONFIG") else None
    if path is not None and not path.is_file():
        raise ConfigError(f"ZWANS_CONFIG names {path}, which doesn't exist.")
    config = load_config(path or DEFAULT_CONFIG_PATH, env=local)
    env = {**read_dotenv(config.home / ".env"), **local}
    if env != local:  # the home .env may set ZWANS_* settings too
        config = load_config(path or DEFAULT_CONFIG_PATH, env=env)
    return config, env
