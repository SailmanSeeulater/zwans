"""A conversation with the agent: the history, plus everyone listening to its events."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from zwans.context.compaction import Compactor
from zwans.context.tokens import CHARS_PER_TOKEN
from zwans.events import Event, TextDelta, ThinkingDelta, TurnEnded, UsageUpdated
from zwans.ext.hooks import Hooks
from zwans.loop import run_turn
from zwans.messages import ContentBlock, ImageBlock, Message, TextBlock
from zwans.policy.engine import Permissions
from zwans.providers.base import Provider
from zwans.tools.base import Tool, ToolContext
from zwans.tools.task import TaskTool

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
    ) -> None:
        self.provider = provider
        self.tools = list(tools)
        self.ctx = ctx
        self.system = system  # fixed for the whole session, so earlier turns stay valid
        self.listeners = list(listeners)
        self.max_steps = max_steps
        self.compactor = compactor
        self.permissions = permissions  # None runs every call without checking
        self.hooks = hooks
        self.messages: list[Message] = []
        self.turn = 0  # how many user turns the session has had
        # Awaited with the turn's number before it starts, as checkpoints.py snapshots files.
        self.before_turn: Callable[[int], Awaitable[None]] | None = None
        for tool in self.tools:
            if isinstance(tool, TaskTool):
                tool.parent = self

    def context_tokens(self) -> int:
        """About how many tokens the next request will send."""
        return self.compactor.estimate(self.messages) if self.compactor else 0

    async def send(self, prompt: str, images: Sequence[ImageBlock] = ()) -> str:
        """Run one turn and return why it ended: "end_turn", "interrupted", "error", ...
        `images` go before the prompt, as the API recommends. A turn that fails before the
        model answers is taken back: its prompt leaves the conversation and `turn` goes back."""
        self.turn += 1
        if self.before_turn is not None:
            await self.before_turn(self.turn)
        content: list[ContentBlock] = [*images, TextBlock(text=prompt)]
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
            stop_reason = "error"
            self.emit(TurnEnded(stop_reason=stop_reason))
        return stop_reason

    def emit(self, event: Event) -> None:
        for listener in self.listeners:
            listener(event)
