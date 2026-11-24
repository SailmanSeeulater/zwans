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
    turn: int = 0  # the session's turn number; 0 in transcripts from before it was recorded
    images: int = 0  # images sent with the prompt


class Rewound(_Event):
    """Written to a session's transcript when it's reopened rewound: the conversation now
    ends after `turn`, and the turns after it are gone (0 means all of them)."""

    type: Literal["rewound"] = "rewound"
    turn: int


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
    preview: str | None = None  # what an Edit or Write would change, as a unified diff


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
    diff: str | None = None  # what an Edit or Write changed, as a unified diff


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
        return parse_event(self.event)


class ContextCompacted(_Event):
    type: Literal["context_compacted"] = "context_compacted"
    tokens_before: int
    tokens_after: int
    summary: str = ""  # what the model wrote to stand in for the older messages


class ContextSplit(BaseModel):
    """What one request held, in tokens, by part. The parts are character estimates scaled
    so they add up to what the API counted; only the total is exact."""

    model_config = ConfigDict(frozen=True)
    system: int = 0
    tools: int = 0  # the tool definitions: names, descriptions, input schemas
    messages: int = 0  # the conversation, except tool results
    tool_results: int = 0


class ModelCalled(_Event):
    """One request to the model, finished: what it cost, how long it took, what it held.
    It follows that call's usage_updated, which stays the event cost is counted from."""

    type: Literal["model_call"] = "model_call"
    purpose: Literal["turn", "summary"] = "turn"  # a summary call is part of compaction
    model: str = ""
    stop_reason: str = ""
    seconds: float = 0.0
    first_token_seconds: float | None = None  # until the first streamed text, if any
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    web_searches: int = 0
    dollars: float | None = None  # None when the model's price isn't known
    # The model's prices in dollars per million tokens: input, output, cache_write and
    # cache_read. With them the UI can split the cost and price the call without the cache.
    prices: dict[str, float] | None = None
    tools: list[str] = Field(default_factory=list)  # the tool calls it asked for, by name
    context: ContextSplit = Field(default_factory=ContextSplit)


class UsageUpdated(_Event):
    type: Literal["usage_updated"] = "usage_updated"
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    model: str = ""
    web_searches: int = 0  # charged per search, apart from tokens
    # "title" for the small call that names a session (titles.py): counted in what it cost,
    # but not one of a turn's model calls.
    purpose: Literal["turn", "title"] = "turn"


class TurnEnded(_Event):
    type: Literal["turn_ended"] = "turn_ended"
    stop_reason: str  # "end_turn", "max_tokens", "refusal", "interrupted", ...
    detail: str = ""


class Steered(_Event):
    """Something the user sent while the turn was running, passed to the model at its next
    step so it can change course without being stopped."""

    type: Literal["steered"] = "steered"
    text: str


class LoopChecked(_Event):
    """/loop ran its check: before the first turn (round 0) and after each one."""

    type: Literal["loop_checked"] = "loop_checked"
    check: str
    round: int
    rounds: int
    passed: bool
    exit_code: int | None
    output: str  # its end, as the model is sent it


class LoopEnded(_Event):
    """/loop stopped: the check passed, the rounds ran out, or a turn ended early."""

    type: Literal["loop_ended"] = "loop_ended"
    reason: str  # "passed", "rounds", "stopped", "budget" or "error"
    detail: str
    check: str = ""


class PlanModeChanged(_Event):
    """Plan mode went on or off: off with `approved` when the user approved the plan."""

    type: Literal["plan_mode"] = "plan_mode"
    on: bool
    approved: bool = False


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
    | ModelCalled
    | TurnEnded
    | Steered
    | LoopChecked
    | LoopEnded
    | Rewound
    | PlanModeChanged
    | Error
)


@cache
def _event_adapter() -> TypeAdapter[Event]:
    return TypeAdapter(Annotated[Event, Field(discriminator="type")])


def parse_event(data: dict[str, Any]) -> Event:
    """An event from its JSON form, as transcripts and the server send it. Raises
    pydantic.ValidationError for anything that isn't one."""
    return _event_adapter().validate_python(data)


def unwrap(event: Event) -> Event:
    """The event itself, or for a subagent's, the event inside: for listeners that count tool
    calls the same wherever they happen."""
    while isinstance(event, SubagentEvent):
        event = event.inner()
    return event
