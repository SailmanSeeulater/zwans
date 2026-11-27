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

An isolated subagent (isolation.py) works in a copy of the workspace, and its changes are
applied when it finishes, so subagents started together can edit at once.
"""

import copy as copying
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from zwans.config import ConfigError
from zwans.events import Error, Event, SubagentEvent, TurnEnded, UsageUpdated
from zwans.ext.agents import AgentType
from zwans.ext.hooks import Hooks
from zwans.isolation import Copy, Isolation, IsolationError
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

ISOLATED_NOTE = """

You work in a private copy of the workspace, at {folder}, so other subagents working at the \
same time can't get in your way, nor you in theirs. Use paths relative to it. When you \
finish, what you changed is applied to the real workspace. Change only what your task needs."""

# Tools that belong to the session's own workspace rather than to a copy of it: its changes
# so far, its Python session and its background commands.
NOT_ISOLATED = frozenset({"ShowChanges", "Python", "BashOutput", "KillBash"})


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
    isolated: bool = Field(
        default=False,
        description="Work in a private copy of the workspace, its changes applied when it "
        "finishes. Use it for subagents that edit files at the same time as others.",
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

    def __init__(
        self,
        max_steps: int = 30,
        agents: Sequence[AgentType] = (),
        isolation: Isolation | None = None,
    ) -> None:
        self.max_steps = max_steps
        self.isolation = isolation  # None: no copies here, as in a chat
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
        permissions = parent.permissions
        isolated: Copy | None = None
        if args.isolated or (agent is not None and agent.isolated):
            isolated, ctx, tools, permissions = await self._isolate(ctx, tools, permissions)
            system += ISOLATED_NOTE.format(folder=isolated.folder)
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
            permissions=permissions,
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
        if permissions is not None and parent.permissions is not None:
            # What the subagent read stays read: its report may carry it.
            parent.permissions.tainted |= permissions.tainted
        report = _report(messages, stop_reason, problems)
        if isolated is None:
            return report
        return await self._bring_back(isolated, report)

    async def _isolate(
        self, ctx: ToolContext, tools: list[Tool[Any]], permissions: Permissions | None
    ) -> tuple[Copy, ToolContext, list[Tool[Any]], Permissions | None]:
        """A copy of the workspace for a subagent, and its tools, context and permissions
        moved there."""
        isolation = self.isolation
        if isolation is None or isolation.problem:
            why = isolation.problem if isolation is not None else "this session has no workspace"
            raise ToolError(f"An isolated subagent can't run here: {why}")
        mover = getattr(ctx.executor, "at", None)
        if mover is None:
            raise ToolError("An isolated subagent can't run here: commands don't run locally.")
        try:
            executor = mover(isolation.workspace)  # checked before a copy is made
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        try:
            made = await isolation.open()
        except IsolationError as exc:
            raise ToolError(f"Couldn't copy the workspace for the subagent: {exc}") from exc
        executor = mover(made.folder)
        moved = [_moved(tool, made.folder) for tool in tools if tool.name not in NOT_ISOLATED]
        context = ToolContext(executor=executor, jobs=None, ask=ctx.ask)
        if permissions is not None:
            permissions = replace(
                permissions,
                inside=executor.contains,
                relative=executor.relative,
                root=executor.root,
            )
        return made, context, moved, permissions

    async def _bring_back(self, made: Copy, report: ToolOutput) -> ToolOutput:
        """The report, with what applying the subagent's changes to the workspace did."""
        assert self.isolation is not None
        if report.is_error:
            note = (
                f"Its changes weren't applied, since it didn't finish. They're in its copy of "
                f"the workspace, at {made.folder}."
            )
            return ToolOutput(content=f"{report.content}\n\n[{note}]", is_error=True)
        try:
            outcome = await self.isolation.bring_back(made)
        except IsolationError as exc:
            note = (
                f"Its changes couldn't be applied to the workspace ({exc}). They're in its copy "
                f"of the workspace, at {made.folder}."
            )
            return ToolOutput(content=f"{report.content}\n\n[{note}]", is_error=True)
        return ToolOutput(content=f"{report.content}\n\n[{outcome.describe()}]")

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


def _moved(tool: Tool[Any], folder: Path) -> Tool[Any]:
    """`tool` for a subagent in a copy of the workspace: one that keeps the workspace's
    folder of its own (as RunTests does, to find the project's runner) gets a copy of itself
    with the copy's folder. The others use the executor they're given."""
    if not isinstance(getattr(tool, "root", None), Path):
        return tool
    clone = copying.copy(tool)
    clone.root = folder  # type: ignore[attr-defined]
    return clone
