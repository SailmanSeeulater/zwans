"""The Task tool: hand a piece of work to a subagent, which reports back when it's done.

A subagent is the same loop with a fresh conversation: it starts from the prompt it's given,
works with its own tools until it finishes or runs out of steps, and only its final message
comes back. Everything it read stays out of the parent's context, which is the point.

It runs on the parent's subagent_provider: the session's model, or subagent_model when the
config names a cheaper one for this kind of legwork. It shares the parent's permissions and
hooks (except stop hooks, which are about the user's task as a whole), so every call it
makes is checked like the parent's would be.

A call can name an agent type (ext/agents.py): a subagent defined once, with its own
instructions, model, tools and number of steps, so the same reviewer or searcher runs each
time it's asked for.
"""

from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import BaseModel, Field

from zwans.config import ConfigError
from zwans.events import Error, Event, SubagentEvent, TurnEnded, UsageUpdated
from zwans.ext.agents import AgentType
from zwans.ext.hooks import Hooks
from zwans.loop import run_turn
from zwans.messages import Message, TextBlock
from zwans.policy.engine import Permissions
from zwans.providers.base import Provider
from zwans.providers.router import helper
from zwans.tools.base import Tool, ToolContext, ToolError, ToolOutput

SUBAGENT_NOTE = """

You are working as a subagent. Another agent gave you the task below and will see only your \
final message, not your tool calls or what they returned. You can't ask it questions, so \
make reasonable choices and say what you assumed. Finish with a complete report: what you \
found or did, with the file paths, names and details the task asks for."""


class TaskInput(BaseModel):
    description: str = Field(description="A few words on what the subagent is for.")
    agent: str | None = Field(
        default=None,
        description="An agent type to start, from the list in this tool's description: it "
        "brings its own instructions, model and tools. Leave it out for a general subagent.",
    )
    prompt: str = Field(
        description="The whole task. The subagent sees nothing of this conversation, so "
        "include what it needs: the goal, file paths, what you already know, and what its "
        "report should contain."
    )
    tools: list[str] | None = Field(
        default=None,
        description="The tools it may use. Leave this out for all of yours except Task, or "
        "for an agent type's own. For a search that mustn't change anything, give only Read, "
        "Glob and Grep.",
    )


class Parent(Protocol):
    """The session a Task tool belongs to."""

    provider: Provider
    subagent_provider: Provider
    tools: list[Tool[Any]]
    system: str
    permissions: Permissions | None
    hooks: Hooks | None
    repeat_limit: int

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

    def __init__(self, max_steps: int = 30, agents: Sequence[AgentType] = ()) -> None:
        self.max_steps = max_steps
        self.agents = {agent.name: agent for agent in agents}
        self.parent: Parent | None = None  # set by the Session it's given to
        if self.agents:
            listed = "\n".join(f"- {a.name}: {a.description}" for a in self.agents.values())
            self.description = (
                f"{TaskTool.description}\n\nAgent types, started with agent=<name>; prefer "
                f"one whose description fits the task:\n{listed}"
            )

    async def run(self, args: TaskInput, ctx: ToolContext) -> ToolOutput:
        parent = self.parent
        if parent is None:
            raise ToolError("Subagents aren't available here.")
        agent = self._agent(args.agent)
        provider = parent.subagent_provider
        system = parent.system + SUBAGENT_NOTE
        max_steps = self.max_steps
        task = args.description
        if agent is not None:
            provider = self._provider(parent, agent)
            if agent.instructions:
                system += f"\n\nYou are the {agent.name} agent. {agent.instructions}"
            max_steps = agent.max_steps or max_steps
            task = f"{agent.name}: {args.description}"
        tools = self._tools(parent.tools, args.tools, agent)
        messages = [Message(role="user", content=[TextBlock(text=args.prompt)])]
        hooks = parent.hooks.without("stop") if parent.hooks is not None else None
        stop_reason, problems = "error", []
        turn = run_turn(
            provider,
            tools,
            messages,
            ctx,
            system=system,
            max_steps=max_steps,
            permissions=parent.permissions,
            hooks=hooks,
            repeat_limit=parent.repeat_limit,
        )
        async for event in turn:
            if isinstance(event, UsageUpdated):
                parent.emit(event)  # so the cost counts wherever cost is counted
            else:
                parent.emit(SubagentEvent(task=task, event=event.model_dump()))
            if isinstance(event, TurnEnded):
                stop_reason = event.stop_reason
            elif isinstance(event, Error):
                problems.append(event.message)
        return _report(messages, stop_reason, problems)

    def _agent(self, name: str | None) -> AgentType | None:
        if not name:
            return None
        agent = self.agents.get(name.strip())
        if agent is None:
            known = ", ".join(self.agents) or "none"
            raise ToolError(f"There's no agent type named {name!r}. The ones there are: {known}.")
        return agent

    def _provider(self, parent: Parent, agent: AgentType) -> Provider:
        """The model an agent type runs on: its own, else the session's subagent model."""
        if agent.model is None:
            return parent.subagent_provider
        try:
            return helper(parent.provider, agent.model)
        except ConfigError as exc:  # ModelError among them: no such provider, or no key
            raise ToolError(
                f"The {agent.name} agent ({agent.path}) runs on {agent.model}, which can't be "
                f"used: {exc}"
            ) from exc

    def _tools(
        self,
        available: Sequence[Tool[Any]],
        wanted: list[str] | None,
        agent: AgentType | None = None,
    ) -> list[Tool[Any]]:
        # No subagents of its own, and no to-do list: the one people see is the parent's.
        # Nor may it question the user or leave notes: those are the parent's to do.
        apart = (self.name, "TodoWrite", "AskUser", "Memory")
        tools = [tool for tool in available if tool.name not in apart]
        if agent is not None and agent.tools is not None:
            # Of the ones its file names, those this session has: a tool turned off here, or
            # one only Claude Code has, is left out rather than failing every call.
            tools = [tool for tool in tools if tool.name in agent.tools]
            if not tools:
                raise ToolError(
                    f"The {agent.name} agent may use {', '.join(agent.tools)}, and this "
                    "session has none of them."
                )
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
