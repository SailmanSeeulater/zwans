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


class ImageSource(BaseModel):
    type: Literal["base64"] = "base64"
    media_type: str  # image/png, image/jpeg, image/gif or image/webp
    data: str  # the file, base64-encoded


class ImageBlock(BaseModel):
    type: Literal["image"] = "image"
    source: ImageSource


class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str | list[TextBlock | ImageBlock]  # a list when the result includes images
    is_error: bool = False

    def text(self) -> str:
        """The result's text, with "[image]" where an image is."""
        if isinstance(self.content, str):
            return self.content
        return "\n".join(b.text if isinstance(b, TextBlock) else "[image]" for b in self.content)


class RawBlock(BaseModel):
    """A block the loop doesn't read, such as thinking, kept exactly as the API sent it.

    Thinking blocks must go back to the API unchanged, or later requests are rejected.
    """

    type: str
    data: dict[str, Any]


type ContentBlock = TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock | RawBlock


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: list[ContentBlock]
    turn: int | None = None  # which user turn it belongs to; saved, never sent to the API
