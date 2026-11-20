"""What the inspector shows about each model call: timing, cost, and what the request held.

The API counts a request's tokens only as a total. To show how that total divides between
the system prompt, the tool definitions, the conversation and the tool results, each part's
size in characters is measured and the total shared out in proportion.
"""

import dataclasses
import json
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from zwans.events import ContextSplit, ModelCalled, TextDelta, ThinkingDelta
from zwans.messages import Message, ToolResultBlock, ToolUseBlock
from zwans.pricing import cost, price_of
from zwans.providers.base import ModelResponse, Provider
from zwans.tools.base import Tool, input_schema
from zwans.web import web_calls


def context_split(
    system: str, tools: Sequence[Tool[Any]], messages: Sequence[Message], counted: int = 0
) -> ContextSplit:
    """The request's parts in tokens. With `counted`, the API's total for the request, the
    estimates are scaled to add up to it."""
    sizes = {
        "system": len(system),
        "tools": sum(len(_tool_text(tool)) for tool in tools),
        "messages": 0,
        "tool_results": 0,
    }
    for message in messages:
        for block in message.content:
            part = "tool_results" if isinstance(block, ToolResultBlock) else "messages"
            sizes[part] += len(block.model_dump_json())
    total = sum(sizes.values())
    if total == 0:
        return ContextSplit()
    scale = counted / total if counted > 0 else 1 / 4  # about four characters a token
    return ContextSplit(**{part: round(size * scale) for part, size in sizes.items()})


def _tool_text(tool: Tool[Any]) -> str:
    return json.dumps(
        {"name": tool.name, "description": tool.description, "input_schema": input_schema(tool)}
    )


@dataclass
class TimedCall:
    """One model call as it streams: the events to pass on, then the response and timing."""

    response: ModelResponse | None = None
    seconds: float = 0.0
    first_token_seconds: float | None = None
    _started: float = field(default_factory=time.monotonic)

    async def stream(
        self,
        provider: Provider,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[Tool[Any]],
    ) -> AsyncIterator[TextDelta | ThinkingDelta]:
        async for item in provider.stream(system, messages, tools):
            if isinstance(item, ModelResponse):
                self.response = item
            else:
                if self.first_token_seconds is None:
                    self.first_token_seconds = time.monotonic() - self._started
                yield item
        self.seconds = time.monotonic() - self._started

    def event(
        self, context: ContextSplit, purpose: Literal["turn", "summary"] = "turn"
    ) -> ModelCalled:
        response = self.response
        assert response is not None
        return ModelCalled(
            purpose=purpose,
            model=response.model,
            stop_reason=response.stop_reason,
            seconds=round(self.seconds, 3),
            first_token_seconds=None
            if self.first_token_seconds is None
            else round(self.first_token_seconds, 3),
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cache_read_tokens=response.cache_read_tokens,
            cache_write_tokens=response.cache_write_tokens,
            web_searches=response.web_searches,
            dollars=cost(response.usage_event()),
            prices=dataclasses.asdict(price) if (price := price_of(response.model)) else None,
            tools=[
                *(call.name for call in web_calls(response.content)),
                *(block.name for block in response.content if isinstance(block, ToolUseBlock)),
            ],
            context=context,
        )


def counted_input(response: ModelResponse) -> int:
    """Every input token the API counted for the request, cached or not."""
    return response.input_tokens + response.cache_read_tokens + response.cache_write_tokens
