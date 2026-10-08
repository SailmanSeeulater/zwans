"""Events the agent core emits.

The CLI, web UI, eval runner, and transcript writer all consume this stream.
None of them reach into the loop itself.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class _Event(BaseModel):
    model_config = ConfigDict(frozen=True)


class TurnStarted(_Event):
    type: Literal["turn_started"] = "turn_started"
    prompt: str = ""


class TextDelta(_Event):
    type: Literal["text_delta"] = "text_delta"
    text: str


class ThinkingDelta(_Event):
    """A short progress note the model writes between tool calls."""

    type: Literal["thinking_delta"] = "thinking_delta"
    text: str


class ToolCallRequested(_Event):
    type: Literal["tool_call_requested"] = "tool_call_requested"
    call_id: str
    name: str
    args: dict[str, Any]


class PermissionRequested(_Event):
    type: Literal["permission_requested"] = "permission_requested"
    call_id: str
    reason: str


class PermissionResolved(_Event):
    type: Literal["permission_resolved"] = "permission_resolved"
    call_id: str
    allowed: bool


class ToolResult(_Event):
    type: Literal["tool_result"] = "tool_result"
    call_id: str
    content: str
    is_error: bool = False


class ContextCompacted(_Event):
    type: Literal["context_compacted"] = "context_compacted"
    tokens_before: int
    tokens_after: int


class UsageUpdated(_Event):
    type: Literal["usage_updated"] = "usage_updated"
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    model: str = ""


class TurnEnded(_Event):
    type: Literal["turn_ended"] = "turn_ended"
    stop_reason: str  # "end_turn", "max_tokens", "refusal", "interrupted", ...
    detail: str = ""


class Error(_Event):
    type: Literal["error"] = "error"
    message: str


type Event = (
    TurnStarted
    | TextDelta
    | ThinkingDelta
    | ToolCallRequested
    | PermissionRequested
    | PermissionResolved
    | ToolResult
    | ContextCompacted
    | UsageUpdated
    | TurnEnded
    | Error
)
