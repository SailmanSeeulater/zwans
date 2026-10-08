"""The interface between the loop and a model."""

from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol

from pydantic import BaseModel

from zwans.events import TextDelta, ThinkingDelta
from zwans.messages import Message, RawBlock, TextBlock, ToolUseBlock
from zwans.tools.base import Tool


class ModelResponse(BaseModel):
    content: list[TextBlock | ToolUseBlock | RawBlock]
    stop_reason: str  # "end_turn", "tool_use", "max_tokens", "refusal", ...
    stop_detail: str = ""  # for a refusal, its category
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class ProviderError(Exception):
    """The model couldn't be reached, or rejected the request, after any retries."""


class Provider(Protocol):
    def stream(
        self, system: str, messages: Sequence[Message], tools: Sequence[Tool[Any]]
    ) -> AsyncIterator[TextDelta | ThinkingDelta | ModelResponse]:
        """Yield text and progress notes as they arrive, then the complete response last."""
        ...

    async def aclose(self) -> None:
        """Release network connections at the end of a session."""
        ...
