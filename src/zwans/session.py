"""A conversation with the agent: the history, plus everyone listening to its events."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from zwans import planning
from zwans.context.calls import context_split
from zwans.context.compaction import Compactor
from zwans.context.tokens import CHARS_PER_TOKEN
from zwans.events import (
    Event,
    PlanModeChanged,
    TextDelta,
    ThinkingDelta,
    TurnEnded,
    UsageUpdated,
)
from zwans.ext.hooks import Hooks
from zwans.loop import run_turn, user_text
from zwans.messages import ContentBlock, ImageBlock, Message, TextBlock
from zwans.policy.engine import Permissions
from zwans.providers.base import Provider
from zwans.tools.base import Tool, ToolContext
from zwans.tools.on_demand import split
from zwans.tools.task import TaskTool
from zwans.tools.web_local import WebFetchTool

type Listener = Callable[[Event], None]


class Session:
    def __init__(
        self,
        provider: Provider,
        tools: Sequence[Tool[Any]],
        ctx: ToolContext,
        system: str,
        listeners: Sequence[Listener],
        max_steps: int = 50,
        compactor: Compactor | None = None,
        permissions: Permissions | None = None,
        hooks: Hooks | None = None,
        follow_through: Callable[[], int] | None = None,
        subagent_provider: Provider | None = None,
        repeat_limit: int = 0,
    ) -> None:
        self.provider = provider
        self.subagent_provider = subagent_provider or provider  # subagent_model, if set
        self.tools = list(tools)
        self.ctx = ctx
        self.system = system  # fixed for the whole session, so earlier turns stay valid
        self.listeners = list(listeners)
        self.max_steps = max_steps
        self.repeat_limit = repeat_limit  # see repeats.py
        self.compactor = compactor
        self.permissions = permissions  # None runs every call without checking
        self.hooks = hooks
        # Asked each turn for how often it may send the model back to finish what its final
        # reply only announced (see followthrough.py): /model can change the answer.
        self.follow_through = follow_through
        self.messages: list[Message] = []
        self.turn = 0  # how many user turns the session has had
        # What the user has sent during the running turn, for the model's next step.
        self.steering: list[str] = []
        # Asked before each model call for a reason not to make it, such as a spent budget.
        self.limit: Callable[[], str | None] | None = None
        # Awaited with the turn's number before it starts, as checkpoints.py snapshots files.
        self.before_turn: Callable[[int], Awaitable[None]] | None = None
        self.planning = False  # plan mode (planning.py)
        self._note: str | None = None  # a note for the next prompt, as plan mode ending
        for tool in self.tools:
            if isinstance(tool, TaskTool | WebFetchTool):
                tool.parent = self
        self._measure_overhead()

    def set_planning(self, on: bool, approved: bool = False) -> bool:
        """Turn plan mode on or off; False when it already was. Turning it off tells the
        model so with the next prompt: that the plan was `approved`, or only that it may
        change things again."""
        if on == self.planning:
            return False
        if on and self.permissions is None:
            raise ValueError("Plan mode needs a session whose tool calls are checked.")
        self.planning = on
        if self.permissions is not None:
            self.permissions.planning = on
        self._note = None if on else planning.GO_NOTE if approved else planning.ENDED
        self.emit(PlanModeChanged(on=on, approved=approved))
        return True

    def _take_steering(self) -> list[str]:
        taken, self.steering = self.steering, []
        return taken

    def context_tokens(self) -> int:
        """About how many tokens the next request will send."""
        return self.compactor.estimate(self.messages) if self.compactor else 0

    def compact_at(self, configured: int) -> int:
        """Where compaction starts: `configured` (compact_at), or less for a smaller model."""
        return self.compactor.threshold if self.compactor else configured

    def _measure_overhead(self) -> None:
        """Tell the compactor what the system prompt and tool definitions add to each request,
        for its estimates before the API has counted one, as in a session just resumed."""
        if self.compactor is not None:
            offered = split(self.tools, self.messages)[0]  # not the tools still to load
            parts = context_split(self.system, offered, [])
            self.compactor.overhead = parts.system + parts.tools

    def prompt_of(self, turn: int) -> str:
        """The text the user sent to start `turn`, or "" when it's no longer in the
        conversation (a compaction may have summarized it)."""
        for message in self.messages:
            if message.role == "user" and message.turn == turn:
                return user_text(message)
        return ""

    def earliest_turn(self) -> int:
        """The first turn still in the conversation as it was; those before it were
        summarized, so going back to before them isn't possible."""
        return min((m.turn for m in self.messages if m.turn is not None), default=1)

    async def send(self, prompt: str, images: Sequence[ImageBlock] = ()) -> str:
        """Run one turn and return why it ended: "end_turn", "interrupted", "error", ...
        `images` go before the prompt, as the API recommends. A turn that fails before the
        model answers is taken back: its prompt leaves the conversation and `turn` goes back."""
        self.turn += 1
        self._measure_overhead()  # MCP tools may have joined since
        if self.before_turn is not None:
            await self.before_turn(self.turn)
        content: list[ContentBlock] = [*images, TextBlock(text=prompt)]
        note = planning.PLANNING if self.planning else self._note
        self._note = None
        if note:
            content.append(TextBlock(text=note))
        asked = Message(role="user", content=content, turn=self.turn)
        self.messages.append(asked)
        stop_reason: str | None = None
        streamed = 0  # characters streamed since the last model call's usage came in
        model = str(getattr(self.provider, "model", "") or "")
        turn = run_turn(
            self.provider,
            self.tools,
            self.messages,
            self.ctx,
            system=self.system,
            max_steps=self.max_steps,
            compactor=self.compactor,
            permissions=self.permissions,
            hooks=self.hooks,
            follow_through=self.follow_through() if self.follow_through else 0,
            steer=self._take_steering,
            limit=self.limit,
            repeat_limit=self.repeat_limit,
        )
        try:
            async for event in turn:
                self.emit(event)
                if isinstance(event, TextDelta | ThinkingDelta):
                    streamed += len(event.text)
                elif isinstance(event, UsageUpdated):
                    streamed, model = 0, event.model or model
                elif isinstance(event, TurnEnded):
                    stop_reason = event.stop_reason
        except asyncio.CancelledError:  # Ctrl+C
            if streamed and model:  # without a model, its price is unknown anyway
                # The API reports usage only once a reply is complete, so count what the
                # cut-off reply streamed. Its input isn't counted: how much of it came from
                # the cache is unknown, and guessing could overstate the cost many times over.
                tokens = max(1, streamed // CHARS_PER_TOKEN)
                self.emit(UsageUpdated(input_tokens=0, output_tokens=tokens, model=model))
            self.emit(TurnEnded(stop_reason="interrupted"))
            raise
        if stop_reason is None:  # the loop stopped on an error, which it has reported
            if self.messages and self.messages[-1] is asked:
                # The model never answered, so the prompt isn't kept: sending it again with
                # the next one would ask for both at once.
                self.messages.pop()
                self.turn -= 1
                if note and not self.planning and self._note is None:
                    self._note = note  # plan mode's end still needs telling
            stop_reason = "error"
            self.emit(TurnEnded(stop_reason=stop_reason))
        return stop_reason

    def emit(self, event: Event) -> None:
        for listener in self.listeners:
            listener(event)
