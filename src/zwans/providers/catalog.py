"""Which models Zwans can use, and where each one runs.

A model's name says where it runs. Claude models go by their own names ("claude-opus-5-5",
or "anthropic/claude-opus-5-5"). Every other model is "<provider>/<model ID>", where the
provider is a server with an OpenAI-compatible API: one of the built-in ones below, or one
set up in the config under [providers.<name>]. The model ID is whatever that server calls
it, slashes and all, as "openrouter/qwen/qwen3-coder" or "ollama/qwen3-coder:30b".
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse

from zwans import pricing
from zwans.config import CREDENTIAL_HINTS, CREDENTIAL_VARS, Config, ConfigError
from zwans.pricing import Price
from zwans.providers.base import ProviderError
from zwans.providers.openai_compat import Endpoint, list_models

ANTHROPIC = "anthropic"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
# The Claude models /model offers; older ones still work by name.
CLAUDE_MODELS = (
    "claude-opus-5-5",
    "claude-fable-5-2",
    "claude-sonnet-5-5",
    "claude-haiku-5-5",
)


@dataclass(frozen=True)
class Preset:
    base_url: str
    about: str
    key_env: str | None = None
    key_required: bool = True  # local servers take a key only if they were started with one
    hint: str = ""  # what to check when it can't be reached
    reasoning_effort: bool = False
    context_window: int | None = None  # what it runs models with unless told otherwise


PRESETS: dict[str, Preset] = {
    "ollama": Preset(
        "http://localhost:11434/v1",
        "Ollama, on this machine",
        hint="Is Ollama running? Start it with `ollama serve`, or open the Ollama app.",
        # Ollama's default on a machine like a 32 GB Mac. Past it, Ollama silently drops the
        # start of the conversation, so Zwans compacts first. Raise it with
        # OLLAMA_CONTEXT_LENGTH, then set context_window under [providers.ollama] to match.
        context_window=32_768,
    ),
    "lmstudio": Preset(
        "http://localhost:1234/v1",
        "LM Studio, on this machine",
        hint="Is LM Studio's server on? Start it in the app's Developer tab or with "
        "`lms server start`.",
    ),
    "llamacpp": Preset(
        "http://localhost:8080/v1",
        "llama.cpp's llama-server, on this machine",
        hint="Is llama-server running? Start it with `llama-server -m <model.gguf> --jinja`.",
    ),
    "vllm": Preset(
        "http://localhost:8000/v1",
        "vLLM, on this machine (set base_url for one on a rented GPU)",
        key_env="VLLM_API_KEY",
        key_required=False,
        hint="Is `vllm serve` running?",
    ),
    "openrouter": Preset(
        "https://openrouter.ai/api/v1", "OpenRouter: hundreds of models", "OPENROUTER_API_KEY"
    ),
    "together": Preset("https://api.together.xyz/v1", "Together AI", "TOGETHER_API_KEY"),
    "fireworks": Preset(
        "https://api.fireworks.ai/inference/v1", "Fireworks AI", "FIREWORKS_API_KEY"
    ),
    "groq": Preset("https://api.groq.com/openai/v1", "Groq", "GROQ_API_KEY"),
    "deepinfra": Preset("https://api.deepinfra.com/v1/openai", "DeepInfra", "DEEPINFRA_API_KEY"),
    "deepseek": Preset("https://api.deepseek.com/v1", "DeepSeek", "DEEPSEEK_API_KEY"),
    "mistral": Preset("https://api.mistral.ai/v1", "Mistral", "MISTRAL_API_KEY"),
    "openai": Preset(
        "https://api.openai.com/v1", "OpenAI", "OPENAI_API_KEY", reasoning_effort=True
    ),
    "gemini": Preset(
        "https://generativelanguage.googleapis.com/v1beta/openai", "Google Gemini", "GEMINI_API_KEY"
    ),
    "xai": Preset("https://api.x.ai/v1", "xAI", "XAI_API_KEY"),
}


class ModelError(ConfigError):
    """A model name Zwans can't use as it stands: no such provider, or no key for it."""


@dataclass(frozen=True)
class ProviderInfo:
    """A provider, built in or from the config, with the config's settings applied."""

    name: str
    base_url: str
    about: str
    key_env: str | None
    key_required: bool
    local: bool
    hint: str = ""
    reasoning_effort: bool = False
    headers: dict[str, str] = field(default_factory=dict)
    models: tuple[str, ...] = ()
    context_window: int | None = None
    max_tokens: int | None = None
    prices: dict[str, tuple[float, float]] = field(default_factory=dict)

    def key(self, env: Mapping[str, str]) -> str | None:
        return (env.get(self.key_env, "").strip() or None) if self.key_env else None

    def problem(self, env: Mapping[str, str]) -> str | None:
        """Why its models can't be used now, or None."""
        if self.key_required and self.key_env and not self.key(env):
            return (
                f"{self.name} needs an API key in {self.key_env}: set it in the environment, "
                "a .env file in this folder, or ~/.zwans/.env."
            )
        return None

    def endpoint(self, env: Mapping[str, str]) -> Endpoint:
        return Endpoint(
            name=self.name,
            base_url=self.base_url,
            api_key=self.key(env),
            headers=self.headers,
            max_tokens=self.max_tokens,
            reasoning_effort=self.reasoning_effort,
            hint=self.hint,
        )


@dataclass(frozen=True)
class Resolved:
    """A model name, sorted out: which provider runs it and what that provider calls it."""

    name: str  # the full name, as Zwans shows and saves it
    provider: str  # "anthropic", or an OpenAI-compatible provider's name
    model_id: str  # the provider's own name for it
    info: ProviderInfo | None = None  # None for Claude

    @property
    def context_window(self) -> int | None:
        return self.info.context_window if self.info else None


def providers(config: Config) -> dict[str, ProviderInfo]:
    """Every OpenAI-compatible provider: the built-in ones, with the config's changes, and the
    config's own."""
    found: dict[str, ProviderInfo] = {}
    for name in [*PRESETS, *(n for n in config.providers if n not in PRESETS)]:
        preset = PRESETS.get(name)
        settings = config.providers.get(name)
        base_url = (settings.base_url if settings else None) or (preset.base_url if preset else "")
        if not base_url:
            continue  # reported by resolve(), which knows the model that needs it
        key_env = (settings.api_key_env if settings else None) or (
            preset.key_env if preset else None
        )
        # A key named in the config is meant to be used; a preset's own may be optional.
        required = bool(settings and settings.api_key_env) or (
            preset.key_required if preset else False
        )
        effort = settings.reasoning_effort if settings else None
        found[name] = ProviderInfo(
            name=name,
            base_url=base_url,
            about=preset.about if preset else "from the config",
            key_env=key_env,
            key_required=required,
            local=is_local(base_url),
            hint=preset.hint if preset and not (settings and settings.base_url) else "",
            reasoning_effort=effort
            if effort is not None
            else bool(preset and preset.reasoning_effort),
            headers=dict(settings.headers) if settings else {},
            models=tuple(settings.models) if settings else (),
            context_window=(settings.context_window if settings else None)
            or (preset.context_window if preset else None),
            max_tokens=settings.max_tokens if settings else None,
            prices=dict(settings.prices) if settings else {},
        )
    return found


def is_embedding(model_id: str) -> bool:
    """Whether a listed model only makes embeddings, so it can't chat."""
    return "embed" in model_id.lower()


def is_local(base_url: str) -> bool:
    return (urlparse(base_url).hostname or "") in LOCAL_HOSTS


def split(name: str) -> tuple[str | None, str]:
    """(provider, model ID) from a model's name; the provider is None when the name has none."""
    name = name.strip()
    if name.startswith("claude-") and "/" not in name:
        return ANTHROPIC, name
    provider, slash, model_id = name.partition("/")
    if not slash or not provider or not model_id:
        return None, name
    return provider, model_id


def canonical(name: str) -> str:
    """The name Zwans shows and saves: "anthropic/claude-x" is just "claude-x"."""
    provider, model_id = split(name)
    return model_id if provider == ANTHROPIC else name.strip()


def resolve(name: str, config: Config, env: Mapping[str, str]) -> Resolved:
    """Where `name` runs. Raises ModelError when it can't be used: no such provider, or the
    key it needs isn't set."""
    provider, model_id = split(name)
    if provider == ANTHROPIC:
        var = CREDENTIAL_VARS[config.auth]
        if not env.get(var, "").strip():
            hint = CREDENTIAL_HINTS[config.auth]
            raise ModelError(f"{model_id} is a Claude model, and {var} is not set. {hint}")
        return Resolved(name=model_id, provider=ANTHROPIC, model_id=model_id)
    known = providers(config)
    if provider is None:
        raise ModelError(
            f"{name!r} doesn't say where it runs. Name another model as <provider>/<model>, "
            f"as ollama/{name} or openrouter/{name}; `zwans models` lists the providers."
        )
    info = known.get(provider)
    if info is None:
        if provider in config.providers:
            raise ModelError(f"[providers.{provider}] in the config needs a base_url.")
        raise ModelError(
            f"There's no provider called {provider!r}. Built in: {', '.join(PRESETS)}. "
            f"To add one, set base_url under [providers.{provider}] in the config."
        )
    problem = info.problem(env)
    if problem:
        raise ModelError(problem)
    return Resolved(name=f"{provider}/{model_id}", provider=provider, model_id=model_id, info=info)


def is_known(name: str) -> bool:
    """Whether a model name is one Zwans recognizes rather than a possible typo: a Claude
    model it has a price for, or any model of a named provider (those come and go)."""
    provider, model_id = split(name)
    if provider == ANTHROPIC:
        return pricing.price_of(model_id) is not None
    return provider is not None


def register_prices(config: Config) -> None:
    """Tell the cost meter what other models cost: what the config says, and nothing for
    models on this machine."""
    for info in providers(config).values():
        if info.local:
            pricing.FREE_PROVIDERS.add(info.name)
        for model_id, (input_price, output_price) in info.prices.items():
            pricing.EXTRA_PRICES[f"{info.name}/{model_id}"] = Price(
                input=input_price,
                output=output_price,
                cache_write=input_price,
                cache_read=input_price,
            )


@dataclass
class Listing:
    """What one provider offers, for `zwans models`, /model and the web UI."""

    provider: str
    about: str
    models: list[str]  # full names
    ready: bool  # its models can be used now, as far as Zwans can tell
    note: str = ""  # why it isn't ready, or how to see more
    local: bool = False


async def list_all(
    config: Config, env: Mapping[str, str], only: str | None = None, timeout: float = 2.0
) -> list[Listing]:
    """Every provider and its models. Servers on this machine are asked what they have;
    remote ones only when `only` names them, since some list hundreds."""
    listings: list[Listing] = []
    if only in (None, ANTHROPIC):
        var = CREDENTIAL_VARS[config.auth]
        ready = bool(env.get(var, "").strip())
        listings.append(
            Listing(ANTHROPIC, "Claude", list(CLAUDE_MODELS), ready, "" if ready else f"set {var}")
        )
    known = providers(config)
    if only not in (None, ANTHROPIC) and only not in known:
        raise ModelError(f"There's no provider called {only!r}. Built in: {', '.join(PRESETS)}.")

    async def one(info: ProviderInfo) -> Listing:
        configured = [f"{info.name}/{m}" for m in info.models]
        problem = info.problem(env)
        if problem:
            return Listing(
                info.name, info.about, configured, False, f"set {info.key_env}", info.local
            )
        if not (info.local or only == info.name):
            note = "" if configured else f"`zwans models {info.name}` lists its models"
            return Listing(info.name, info.about, configured, True, note, info.local)
        try:
            found = await list_models(info.endpoint(env), timeout)
        except ProviderError as exc:
            note = "not running" if info.local else str(exc)
            return Listing(info.name, info.about, configured, False, note, info.local)
        chat = [m for m in found if m not in info.models and not is_embedding(m)]
        models = configured + [f"{info.name}/{m}" for m in chat]
        note = ""
        if not models:
            note = "no models yet" + (
                ": `ollama pull <model>` gets one" if info.name == "ollama" else ""
            )
        return Listing(info.name, info.about, models, bool(models), note, info.local)

    chosen = [info for name, info in known.items() if only in (None, name)]
    listings += await asyncio.gather(*(one(info) for info in chosen))
    return listings
