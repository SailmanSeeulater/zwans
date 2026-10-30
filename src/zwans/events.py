"""Events the agent core emits.

The CLI, web UI, eval runner, and transcript writer all consume this stream.
None of them reach into the loop itself.
"""

from functools import cache
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


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
    rules: list[str] = []  # what "always allow" would add


class PermissionDenied(_Event):
    """The policy refused a call outright, without asking."""

    type: Literal["permission_denied"] = "permission_denied"
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
    # From outside the conversation (a file, a command, the web), so it may carry planted
    # instructions. Set when a policy is in use.
    untrusted: bool = False


class HookReported(_Event):
    """A hook exited non-zero: it blocked a call, added to its result, or kept the turn going."""

    type: Literal["hook_reported"] = "hook_reported"
    event: str  # pre_tool, post_tool or stop
    command: str
    message: str
    call_id: str = ""  # empty for stop hooks


class SubagentEvent(_Event):
    """Something a subagent did, passed up through the Task call that started it. Its usage
    events aren't wrapped, so whatever counts cost counts the subagent's too."""

    type: Literal["subagent"] = "subagent"
    task: str  # the Task call's description
    event: dict[str, Any]

    def inner(self) -> "Event":
        return _event_adapter().validate_python(self.event)


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
    | PermissionDenied
    | ToolResult
    | HookReported
    | SubagentEvent
    | ContextCompacted
    | UsageUpdated
    | TurnEnded
    | Error
)


@cache
def _event_adapter() -> TypeAdapter[Event]:
    return TypeAdapter(Annotated[Event, Field(discriminator="type")])


def unwrap(event: Event) -> Event:
    """The event itself, or for a subagent's, the event inside: for listeners that count tool
    calls the same wherever they happen."""
    while isinstance(event, SubagentEvent):
        event = event.inner()
    return event
