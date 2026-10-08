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


class RawBlock(BaseModel):
    """A block the loop doesn't read, such as thinking, kept exactly as the API sent it.

    Thinking blocks must go back to the API unchanged, or later requests are rejected.
    """

    type: str
    data: dict[str, Any]


type ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock | RawBlock


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: list[ContentBlock]
