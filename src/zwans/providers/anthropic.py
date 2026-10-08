"""Calls Claude through the Messages API and streams the reply."""

from collections.abc import AsyncIterator, Sequence
from typing import Any

import anthropic
from anthropic.types.beta import BetaMessage

from zwans.config import Credential, Effort
from zwans.events import TextDelta, ThinkingDelta
from zwans.messages import ContentBlock, Message, RawBlock, TextBlock, ToolUseBlock
from zwans.providers.base import ModelResponse, ProviderError
from zwans.tools.base import Tool

BETAS = [
    "server-side-fallback-2026-07-01",  # if a safety classifier declines, retry on another model
    "thinking-display-updates-2026-08-18",  # short progress notes between tool calls
    "thinking-binding-controls-2026-08-01",  # lets us choose drop_block, below
]
EPHEMERAL: dict[str, Any] = {"type": "ephemeral"}  # a 5-minute prompt-cache entry
OAUTH_BETA = "oauth-2025-04-20"  # required when signing in with a Claude plan token
JSON_ATTEMPTS = 3


class AnthropicProvider:
    def __init__(self, credential: Credential, model: str, effort: Effort, max_tokens: int) -> None:
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.betas = list(BETAS)
        # The SDK retries rate limits, overloads, and connection errors with backoff.
        if credential.mode == "api_key":
            self._client = anthropic.AsyncAnthropic(api_key=credential.token, max_retries=4)
        else:
            self._client = anthropic.AsyncAnthropic(auth_token=credential.token, max_retries=4)
            self.betas.append(OAUTH_BETA)

    async def stream(
        self, system: str, messages: Sequence[Message], tools: Sequence[Tool[Any]]
    ) -> AsyncIterator[TextDelta | ThinkingDelta | ModelResponse]:
        attempt = 0
        while True:
            attempt += 1
            try:
                request = self.request(system, messages, tools)
                async with self._client.beta.messages.stream(**request) as stream:
                    async for event in stream:
                        if event.type == "text":
                            yield TextDelta(text=event.text)
                        elif event.type == "thinking" and event.thinking:
                            yield ThinkingDelta(text=event.thinking)
                    message = await stream.get_final_message()
            except ValueError as exc:
                # With eager input streaming the SDK raises this for tool input it can't
                # parse at all. The tool call never completed, so ask again.
                if attempt < JSON_ATTEMPTS:
                    continue
                raise ProviderError("The model kept sending tool input that isn't JSON.") from exc
            except anthropic.AuthenticationError as exc:
                raise ProviderError(
                    "Claude rejected the credential. Check ANTHROPIC_API_KEY, or "
                    "CLAUDE_CODE_OAUTH_TOKEN when auth is 'subscription'."
                ) from exc
            except anthropic.APIStatusError as exc:
                plan_token = OAUTH_BETA in self.betas
                raise ProviderError(describe_api_error(exc, plan_token)) from exc
            except anthropic.APIConnectionError as exc:
                raise ProviderError("Couldn't reach the Claude API.") from exc
            yield to_response(message)
            return

    def request(
        self, system: str, messages: Sequence[Message], tools: Sequence[Tool[Any]]
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            # A cache breakpoint after the system prompt covers the tools too, since the API
            # puts tools first. It survives whatever happens later in the conversation.
            "system": [{"type": "text", "text": system, "cache_control": EPHEMERAL}]
            if system
            else anthropic.omit,
            "messages": [message_param(m) for m in messages],
            "tools": [tool_param(t) for t in tools] if tools else anthropic.omit,
            # Automatic caching: a breakpoint on the conversation's last block, moving forward
            # each request, so every call re-reads everything before it from the cache.
            "cache_control": EPHEMERAL,
            "thinking": {
                "type": "adaptive",
                "display": "updates",
                # If an earlier thinking block no longer matches its conversation (after a
                # compaction, or when Zwans's tools changed between resumes), drop it
                # instead of failing the request.
                "block_binding": {"prefix_mismatch_behavior": "drop_block"},
            },
            "output_config": {"effort": self.effort},
            "fallbacks": "default",
            "betas": self.betas,
        }

    async def aclose(self) -> None:
        await self._client.close()


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
    )


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


def message_param(message: Message) -> dict[str, Any]:
    return {"role": message.role, "content": [block_param(b) for b in message.content]}


def block_param(block: ContentBlock) -> dict[str, Any]:
    if isinstance(block, RawBlock):
        return block.data  # exactly what the API sent
    return block.model_dump(mode="json")


def tool_param(tool: Tool[Any]) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_model.model_json_schema(),
        "eager_input_streaming": True,  # stream big inputs, like file contents, as they're written
    }
