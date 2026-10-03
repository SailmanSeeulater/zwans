"""Conversation types shared by the loop and providers. They mirror the Messages API shape."""

from typing import Any, Literal

from pydantic import BaseModel


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str

class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any]

class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False

type ContentBlock = TextBlock | ToolUseBlock|ToolResultBlock

class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: list[ContentBlock]
