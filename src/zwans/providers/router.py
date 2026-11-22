"""The session's provider: sends each request to wherever the current model runs, so /model
can switch between Claude and any OpenAI-compatible server mid-session."""

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from typing import Any

from zwans.config import Config, load_credential
from zwans.messages import Message
from zwans.providers.anthropic import AnthropicProvider
from zwans.providers.base import Provider, StreamItem
from zwans.providers.catalog import ANTHROPIC, Resolved, register_prices, resolve
from zwans.providers.openai_compat import OpenAICompatProvider
from zwans.tools.base import Tool

type Backend = AnthropicProvider | OpenAICompatProvider


class ModelRouter:
    def __init__(
        self,
        config: Config,
        env: Mapping[str, str],
        model: str,
        make_backend: Callable[[Resolved], Backend] | None = None,
    ) -> None:
        """Raises ModelError (a ConfigError) when `model` can't be used."""
        self.config = config
        self.env = env
        self._make_backend = make_backend or self._backend_for
        self._backends: dict[str, Backend] = {}  # by provider, made when first needed
        self._helpers: dict[str, ModelRouter] = {}  # other models' routers, by model name
        register_prices(config)
        self.set_model(model)

    def set_model(self, model: str) -> None:
        """Switch to `model`. Raises ModelError, keeping the current model, when it can't be
        used."""
        resolved = resolve(model, self.config, self.env)
        backend = self._backends.get(resolved.provider)
        if backend is None:
            backend = self._make_backend(resolved)
            self._backends[resolved.provider] = backend
        backend.set_model(resolved.model_id)
        self.resolved = resolved
        self.current = backend
        self.model = resolved.name

    @property
    def context_window(self) -> int | None:
        """The current model's context, when the config gives it, so compaction comes first."""
        return self.resolved.context_window

    @property
    def last_request(self) -> dict[str, Any] | None:
        return self.current.last_request

    def stream(
        self, system: str, messages: Sequence[Message], tools: Sequence[Tool[Any]]
    ) -> AsyncIterator[StreamItem]:
        return self.current.stream(system, messages, self._offered(tools))

    def _offered(self, tools: Sequence[Tool[Any]]) -> Sequence[Tool[Any]]:
        """The tools the current model is told about. Claude's web tools run on Anthropic's
        servers, so with those on, Zwans's own stand-ins (WebFetch, WebSearch) are left out:
        the model would otherwise have two ways to do one thing."""
        if self.resolved.provider == ANTHROPIC and self.config.web:
            return [tool for tool in tools if not getattr(tool, "local_web", False)]
        return tools

    def helper(self, model: str | None) -> "ModelRouter":
        """A router fixed on `model`, for work the session hands to another model (subagents,
        compaction): itself when `model` is unset. Its own backends, so /model switching this
        router leaves it alone. Raises ModelError when `model` can't be used."""
        if not model:
            return self
        name = resolve(model, self.config, self.env).name
        if name not in self._helpers:
            self._helpers[name] = ModelRouter(self.config, self.env, model, self._make_backend)
        return self._helpers[name]

    async def aclose(self) -> None:
        for backend in self._backends.values():
            await backend.aclose()
        for helper in self._helpers.values():
            await helper.aclose()

    def _backend_for(self, resolved: Resolved) -> Backend:
        config = self.config
        if resolved.provider == ANTHROPIC:
            return AnthropicProvider(
                load_credential(config, self.env),
                resolved.model_id,
                config.effort,
                config.max_tokens,
                config.prompt_cache,
                config.web,
            )
        assert resolved.info is not None
        return OpenAICompatProvider(
            resolved.info.endpoint(self.env), resolved.model_id, config.effort
        )


def helper(provider: Provider, model: str | None) -> Provider:
    """The provider for work handed to `model`: a router of its own when `provider` routes,
    and `provider` itself otherwise (a scripted model in tests, where there's only one)."""
    return provider.helper(model) if isinstance(provider, ModelRouter) else provider
