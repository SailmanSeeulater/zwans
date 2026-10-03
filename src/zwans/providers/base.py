"""The interface between the loop and a model."""

from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import BaseModel

from zwans.messages import Message, TextBlock, ToolUseBlock
from zwans.tools.base import Tool


class ModelResponse(BaseModel):
    content: list[TextBlock | ToolUseBlock]
    stop_reason: str  # "end_turn", "tool_use", "max_tokens", ...
    input_tokens: int = 0
    output_tokens: int = 0


class Provider(Protocol):
    async def complete(
        self, messages: Sequence[Message], tools: Sequence[Tool[Any]]
    ) -> ModelResponse: ...
