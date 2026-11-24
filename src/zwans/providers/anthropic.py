"""Calls Claude through the Messages API and streams the reply."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

import anthropic
import httpx2
from anthropic.types.beta import BetaMessage

from zwans.config import Credential, Effort, PromptCache
from zwans.events import TextDelta, ThinkingDelta
from zwans.messages import (
    ContentBlock,
    Message,
    RawBlock,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from zwans.providers.base import ModelResponse, ProviderError, ServerBlock, StreamItem
from zwans.tools.base import Tool, input_schema
from zwans.tools.on_demand import NAME as SEARCH
from zwans.tools.on_demand import searched, split
from zwans.web import SERVER_TYPES
from zwans.web import tool_params as web_tool_params

FALLBACK_BETA = "server-side-fallback-2026-07-01"  # if a classifier declines, use another model
PROGRESS_NOTES_BETA = "thinking-display-updates-2026-08-18"  # short notes between tool calls
BINDING_BETA = "thinking-binding-controls-2026-08-01"  # lets us choose drop_block, below
INTERLEAVED_BETA = "interleaved-thinking-2025-05-14"  # budgeted thinking between tool calls


@dataclass(frozen=True)
class Traits:
    """What a model accepts. The current Opus and Sonnet take everything; Haikus less."""

    adaptive_thinking: bool = True  # otherwise thinking takes a token budget
    effort: bool = True
    progress_notes: bool = True
    block_binding: bool = True
    fallbacks: bool = True
    web_filtering: bool = True  # the web tool versions that filter results with code


TRAITS: dict[str, Traits] = {
    "claude-haiku-5-5": Traits(progress_notes=False, fallbacks=False, web_filtering=False),
    "claude-haiku-4-5": Traits(
        adaptive_thinking=False,
        effort=False,
        progress_notes=False,
        block_binding=False,
        fallbacks=False,
        web_filtering=False,
    ),
}

# For models that take a thinking budget instead of an effort level: the budget that stands
# in for each effort level, in tokens.
THINKING_BUDGETS = {"low": 2_048, "medium": 8_000, "high": 16_000, "xhigh": 32_000, "max": 48_000}
MIN_THINKING_BUDGET = 1_024
EPHEMERAL: dict[str, Any] = {"type": "ephemeral"}  # a 5-minute prompt-cache entry
OAUTH_BETA = "oauth-2025-04-20"  # required when signing in with a Claude plan token
JSON_ATTEMPTS = 3
# The SDK retries a request that fails to connect, but not a stream cut off partway through.
# Ask again this many times in all, waiting 1, 2, ... seconds in between.
CUT_OFF_ATTEMPTS = 3


class AnthropicProvider:
    def __init__(
        self,
        credential: Credential,
        model: str,
        effort: Effort,
        max_tokens: int,
        prompt_cache: PromptCache = "conversation",
        web: bool = False,
    ) -> None:
        self.effort = effort
        self.max_tokens = max_tokens
        self.prompt_cache = prompt_cache
        self.web = web  # offer web search and fetch, which the API runs (see zwans/web.py)
        self.plan_token = credential.mode == "subscription"
        self.set_model(model)
        # The last request body, as sent, for the web UI's inspector. The credential is on
        # the client, never in here.
        self.last_request: dict[str, Any] | None = None
        # The SDK retries rate limits, overloads, and connection errors with backoff.
        if credential.mode == "api_key":
            self._client = anthropic.AsyncAnthropic(api_key=credential.token, max_retries=4)
        else:
            self._client = anthropic.AsyncAnthropic(auth_token=credential.token, max_retries=4)

    def set_model(self, model: str) -> None:
        self.model = model
        self.traits = TRAITS.get(model, Traits())
        self.betas = _betas(self.traits)
        if self.plan_token:
            self.betas.append(OAUTH_BETA)

    async def stream(
        self, system: str, messages: Sequence[Message], tools: Sequence[Tool[Any]]
    ) -> AsyncIterator[StreamItem]:
        attempt = 0
        cut_offs = 0
        while True:
            attempt += 1
            try:
                request = self.request(system, messages, tools)
                sent = {k: v for k, v in request.items() if v is not anthropic.omit}
                self.last_request = without_image_data(sent)
                async with self._client.beta.messages.stream(**request) as stream:
                    said = False  # some text has been streamed in this reply
                    new_block = False  # a text block began after it
                    async for event in stream:
                        if event.type == "content_block_start":
                            new_block = said and event.content_block.type == "text"
                        elif event.type == "text" and event.text:
                            # Separate text blocks (as around a web search) are paragraphs.
                            yield TextDelta(text=f"\n\n{event.text}" if new_block else event.text)
                            said, new_block = True, False
                        elif event.type == "thinking" and event.thinking:
                            yield ThinkingDelta(text=event.thinking)
                        elif event.type == "content_block_stop":
                            # A web search or its results, complete: pass it on now, so it
                            # shows before the text that follows it.
                            block = event.content_block
                            if block.type in SERVER_TYPES:
                                data = block.to_dict(mode="json")
                                yield ServerBlock(block=RawBlock(type=block.type, data=data))
                    message = await stream.get_final_message()
            except ValueError as exc:
                # With eager input streaming the SDK raises this for tool input it can't
                # parse at all. The tool call never completed, so ask again.
                if attempt < JSON_ATTEMPTS:
                    continue
                raise ProviderError("The model kept sending tool input that isn't JSON.") from exc
            except anthropic.AuthenticationError as exc:
                variable = "CLAUDE_CODE_OAUTH_TOKEN" if self.plan_token else "ANTHROPIC_API_KEY"
                raise ProviderError(f"Claude rejected {variable}. Check its value.") from exc
            except anthropic.APIStatusError as exc:
                plan_token = OAUTH_BETA in self.betas
                raise ProviderError(describe_api_error(exc, plan_token)) from exc
            except anthropic.APIConnectionError as exc:
                raise ProviderError("Couldn't reach the Claude API.") from exc
            except httpx2.TransportError as exc:
                # Nothing from the cut-off reply was added to the conversation, so it's
                # safe to ask again; the user may see its first words twice.
                cut_offs += 1
                if cut_offs < CUT_OFF_ATTEMPTS:
                    await asyncio.sleep(2 ** (cut_offs - 1))
                    continue
                raise ProviderError(
                    f"The connection to the Claude API kept dropping mid-reply ({exc!r})."
                ) from exc
            response = to_response(message)
            note = sources_note([block.to_dict(mode="json") for block in message.content])
            if note:
                yield TextDelta(text=note)
            yield response
            return

    def request(
        self, system: str, messages: Sequence[Message], tools: Sequence[Tool[Any]]
    ) -> dict[str, Any]:
        _, deferred, _ = split(tools, messages)
        loads = _loads(messages, deferred)
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            # A cache breakpoint after the system prompt covers the tools too, since the API
            # puts tools first. It survives whatever happens later in the conversation.
            "system": [{"type": "text", "text": system, **self._cache("system")}]
            if system
            else anthropic.omit,
            "messages": [message_param(m, loads) for m in messages],
            "tools": self._tools(tools, deferred) or anthropic.omit,
            # Automatic caching: a breakpoint on the conversation's last block, moving forward
            # each request, so every call re-reads everything before it from the cache.
            **self._cache("conversation"),
            "thinking": self._thinking(),
            "output_config": {"effort": self.effort} if self.traits.effort else anthropic.omit,
            "fallbacks": "default" if self.traits.fallbacks else anthropic.omit,
            "betas": self.betas,
        }

    def _tools(self, tools: Sequence[Tool[Any]], deferred: set[str]) -> list[dict[str, Any]]:
        # Every tool, every time, so the request's front stays the same: the deferred ones
        # only load once a ToolSearch result names them (tools/on_demand.py).
        params = [
            {**tool_param(t), "defer_loading": True} if t.name in deferred else tool_param(t)
            for t in tools
        ]
        if self.web:
            params += web_tool_params(self.traits.web_filtering)
        return params

    def _cache(self, breakpoint: PromptCache) -> dict[str, Any]:
        """A cache_control field for this breakpoint, if prompt_cache covers it."""
        covered = {"conversation": ("system", "conversation"), "system": ("system",), "off": ()}
        return {"cache_control": EPHEMERAL} if breakpoint in covered[self.prompt_cache] else {}

    def _thinking(self) -> dict[str, Any]:
        if not self.traits.adaptive_thinking:
            budget = min(THINKING_BUDGETS[self.effort], self.max_tokens - 1)
            return {"type": "enabled", "budget_tokens": max(budget, MIN_THINKING_BUDGET)}
        thinking: dict[str, Any] = {"type": "adaptive"}
        if self.traits.progress_notes:
            thinking["display"] = "updates"
        if self.traits.block_binding:
            # If an earlier thinking block no longer matches its conversation (after a
            # compaction, or when Zwans's tools changed between resumes), drop it instead
            # of failing the request.
            thinking["block_binding"] = {"prefix_mismatch_behavior": "drop_block"}
        return thinking

    async def aclose(self) -> None:
        await self._client.close()


def _betas(traits: Traits) -> list[str]:
    betas = []
    if traits.fallbacks:
        betas.append(FALLBACK_BETA)
    if traits.progress_notes:
        betas.append(PROGRESS_NOTES_BETA)
    if traits.block_binding:
        betas.append(BINDING_BETA)
    if not traits.adaptive_thinking:
        betas.append(INTERLEAVED_BETA)
    return betas


def without_image_data(value: Any) -> Any:
    """A copy of a request with each image's base64 data replaced by a note of its length,
    so the inspector shows what was sent without carrying megabytes to the browser."""
    if isinstance(value, dict):
        if value.get("type") == "base64" and isinstance(value.get("data"), str):
            return {**value, "data": f"<{len(value['data']):,} characters of base64>"}
        return {k: without_image_data(v) for k, v in value.items()}
    if isinstance(value, list):
        return [without_image_data(v) for v in value]
    return value


def describe_api_error(exc: anthropic.APIStatusError, plan_token: bool) -> str:
    error = exc.body.get("error", {}) if isinstance(exc.body, dict) else {}
    kind = error.get("type", "error")
    detail = error.get("message", exc.message)
    text = f"Claude API error {exc.status_code} ({kind}): {detail} [request {exc.request_id}]"
    if plan_token and exc.status_code in (400, 403, 429):
        text += (
            "\nPlan tokens are meant for Claude Code, and Claude may refuse them from other "
            "tools. Use an API key instead: set ZWANS_AUTH=api_key and ANTHROPIC_API_KEY."
        )
    return text


def to_response(message: BetaMessage) -> ModelResponse:
    usage = message.usage
    details = message.stop_details
    return ModelResponse(
        content=convert_content([block.to_dict(mode="json") for block in message.content]),
        stop_reason=message.stop_reason or "end_turn",
        stop_detail=(details.category or "") if details else "",
        model=message.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        cache_write_tokens=usage.cache_creation_input_tokens or 0,
        web_searches=usage.server_tool_use.web_search_requests if usage.server_tool_use else 0,
    )


def sources_note(blocks: list[dict[str, Any]]) -> str:
    """The web pages the reply's text cites, as a list to show after it. It's only shown,
    never added to the conversation, which keeps just the reply's text."""
    sources: dict[str, str] = {}  # address: title, in the order first cited
    for block in blocks:
        if block.get("type") != "text":
            continue
        for citation in block.get("citations") or []:
            url = citation.get("url")
            if isinstance(url, str) and url and url not in sources:
                sources[url] = str(citation.get("title") or url)
    if not sources:
        return ""
    lines = [f"- {title}: {url}" if title != url else f"- {url}" for url, title in sources.items()]
    return "\n\nSources:\n" + "\n".join(lines)


def convert_content(blocks: list[dict[str, Any]]) -> list[TextBlock | ToolUseBlock | RawBlock]:
    """Turn API content blocks into ours, keeping every block the loop doesn't read verbatim.

    When a safety classifier declines partway through and a fallback model takes over, the
    blocks before the last "fallback" marker came from the declined attempt: keep their
    text, but drop their thinking and tool calls, which must not be sent back or run.
    """
    boundary = max((i for i, b in enumerate(blocks) if b.get("type") == "fallback"), default=-1)
    converted: list[TextBlock | ToolUseBlock | RawBlock] = []
    for index, block in enumerate(blocks):
        kind = str(block.get("type"))
        if index < boundary and kind not in ("text", "fallback"):
            continue
        if kind == "text":
            converted.append(TextBlock(text=block["text"]))
        elif kind == "tool_use":
            converted.append(ToolUseBlock(id=block["id"], name=block["name"], input=block["input"]))
        else:
            converted.append(RawBlock(type=kind, data=block))
    return converted


def message_param(message: Message, loads: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """`message` as the API takes it. `loads` gives the tools each ToolSearch call loaded, by
    its ID: its result goes as references to them, which loads their definitions."""
    content = []
    for block in message.content:
        names = (
            loads.get(block.tool_use_id) if loads and isinstance(block, ToolResultBlock) else None
        )
        if isinstance(block, ToolResultBlock) and names:
            refs = [{"type": "tool_reference", "tool_name": name} for name in names]
            content.append(
                {"type": "tool_result", "tool_use_id": block.tool_use_id, "content": refs}
            )
        else:
            content.append(block_param(block))
    return {"role": message.role, "content": content}


def _loads(messages: Sequence[Message], deferred: set[str]) -> dict[str, list[str]]:
    """The deferred tools each ToolSearch call that worked loaded, by the call's ID."""
    if not deferred:
        return {}
    calls = {
        block.id: sorted(searched(block) & deferred)
        for message in messages
        for block in message.content
        if isinstance(block, ToolUseBlock) and block.name == SEARCH
    }
    return {
        block.tool_use_id: calls[block.tool_use_id]
        for message in messages
        for block in message.content
        if isinstance(block, ToolResultBlock)
        and not block.is_error
        and calls.get(block.tool_use_id)
    }


def block_param(block: ContentBlock) -> dict[str, Any]:
    if isinstance(block, RawBlock):
        return block.data  # exactly what the API sent
    return block.model_dump(mode="json")


def tool_param(tool: Tool[Any]) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": input_schema(tool),
        "eager_input_streaming": True,  # stream big inputs, like file contents, as they're written
    }
