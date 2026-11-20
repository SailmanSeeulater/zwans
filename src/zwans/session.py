"""A conversation with the agent: the history, plus everyone listening to its events."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from zwans.context.compaction import Compactor
from zwans.events import Event, TurnEnded
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
        `images` go before the prompt, as the API recommends."""
        self.turn += 1
        if self.before_turn is not None:
            await self.before_turn(self.turn)
        content: list[ContentBlock] = [*images, TextBlock(text=prompt)]
        self.messages.append(Message(role="user", content=content, turn=self.turn))
        stop_reason = "error"
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
                if isinstance(event, TurnEnded):
                    stop_reason = event.stop_reason
        except asyncio.CancelledError:  # Ctrl+C
            self.emit(TurnEnded(stop_reason="interrupted"))
            raise
        return stop_reason

    def emit(self, event: Event) -> None:
        for listener in self.listeners:
            listener(event)
