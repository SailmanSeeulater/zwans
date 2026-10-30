"""The Task tool: hand a piece of work to a subagent, which reports back when it's done.

A subagent is the same loop with a fresh conversation: it starts from the prompt it's given,
works with its own tools until it finishes or runs out of steps, and only its final message
comes back. Everything it read stays out of the parent's context, which is the point.

It shares the parent's model, permissions and hooks (except stop hooks, which are about the
user's task as a whole), so every call it makes is checked like the parent's would be.
"""

from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import BaseModel, Field

from zwans.events import Error, Event, SubagentEvent, TurnEnded, UsageUpdated
from zwans.ext.hooks import Hooks
from zwans.loop import run_turn
from zwans.messages import Message, TextBlock
from zwans.policy.engine import Permissions
from zwans.providers.base import Provider
from zwans.tools.base import Tool, ToolContext, ToolError, ToolOutput

SUBAGENT_NOTE = """

You are working as a subagent. Another agent gave you the task below and will see only your \
final message, not your tool calls or what they returned. You can't ask it questions, so \
make reasonable choices and say what you assumed. Finish with a complete report: what you \
found or did, with the file paths, names and details the task asks for."""


class TaskInput(BaseModel):
    description: str = Field(description="A few words on what the subagent is for.")
    prompt: str = Field(
        description="The whole task. The subagent sees nothing of this conversation, so "
        "include what it needs: the goal, file paths, what you already know, and what its "
        "report should contain."
    )
    tools: list[str] | None = Field(
        default=None,
        description="The tools it may use. Leave this out for all of yours except Task. For a "
        "search that mustn't change anything, give only Read, Glob and Grep.",
    )


class Parent(Protocol):
    """The session a Task tool belongs to."""

    provider: Provider
    tools: list[Tool[Any]]
    system: str
    permissions: Permissions | None
    hooks: Hooks | None

    def emit(self, event: Event) -> None: ...


class TaskTool:
    name = "Task"
    description = (
        "Start a subagent: a separate agent with a fresh context that does one task and "
        "returns only its final report. Use it for searches and investigations that would "
        "read many files, so only the conclusion comes back to you, and for independent "
        "pieces of work: several Task calls in one response run at the same time. It can't "
        "see this conversation or ask you anything, so write the prompt as a complete brief. "
        "Don't use it for a quick lookup of a known file; Read that yourself."
    )
    input_model = TaskInput
    # The call itself changes nothing, and each call the subagent makes is checked on its
    # own. Being read-only also lets several subagents run at once.
    read_only = True

    def __init__(self, max_steps: int = 30) -> None:
        self.max_steps = max_steps
        self.parent: Parent | None = None  # set by the Session it's given to

    async def run(self, args: TaskInput, ctx: ToolContext) -> ToolOutput:
        parent = self.parent
        if parent is None:
            raise ToolError("Subagents aren't available here.")
        tools = self._tools(parent.tools, args.tools)
        messages = [Message(role="user", content=[TextBlock(text=args.prompt)])]
        hooks = parent.hooks.without("stop") if parent.hooks is not None else None
        stop_reason, problems = "error", []
        turn = run_turn(
            parent.provider,
            tools,
            messages,
            ctx,
            system=parent.system + SUBAGENT_NOTE,
            max_steps=self.max_steps,
            permissions=parent.permissions,
            hooks=hooks,
        )
        async for event in turn:
            if isinstance(event, UsageUpdated):
                parent.emit(event)  # so the cost counts wherever cost is counted
            else:
                parent.emit(SubagentEvent(task=args.description, event=event.model_dump()))
            if isinstance(event, TurnEnded):
                stop_reason = event.stop_reason
            elif isinstance(event, Error):
                problems.append(event.message)
        return _report(messages, stop_reason, problems)

    def _tools(self, available: Sequence[Tool[Any]], wanted: list[str] | None) -> list[Tool[Any]]:
        tools = [tool for tool in available if tool.name != self.name]  # no subagents of its own
        if wanted is None:
            return tools
        names = {tool.name for tool in tools}
        unknown = sorted(set(wanted) - names)
        if unknown:
            raise ToolError(f"Unknown tools: {', '.join(unknown)}. Available: {sorted(names)}")
        return [tool for tool in tools if tool.name in wanted]


def _report(messages: list[Message], stop_reason: str, problems: list[str]) -> ToolOutput:
    last = messages[-1] if messages[-1].role == "assistant" else None
    text = "".join(b.text for b in last.content if isinstance(b, TextBlock)) if last else ""
    text = text.strip()
    if stop_reason == "end_turn" and text:
        return ToolOutput(content=text)
    why = "; ".join(problems) or stop_reason
    note = f"The subagent stopped before finishing ({why})."
    if text:
        return ToolOutput(content=f"{note} Its last message:\n\n{text}", is_error=True)
    return ToolOutput(content=note, is_error=True)
