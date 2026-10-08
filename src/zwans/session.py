"""A conversation with the agent: the history, plus everyone listening to its events."""

import asyncio
from collections.abc import Callable, Sequence
from typing import Any

from zwans.events import Event, TurnEnded
from zwans.loop import run_turn
from zwans.messages import Message, TextBlock
from zwans.providers.base import Provider
from zwans.tools.base import Tool, ToolContext

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
    ) -> None:
        self.provider = provider
        self.tools = list(tools)
        self.ctx = ctx
        self.system = system  # fixed for the whole session, so earlier turns stay valid
        self.listeners = list(listeners)
        self.max_steps = max_steps
        self.messages: list[Message] = []

    async def send(self, prompt: str) -> str:
        """Run one turn and return why it ended: "end_turn", "interrupted", "error", ..."""
        self.messages.append(Message(role="user", content=[TextBlock(text=prompt)]))
        stop_reason = "error"
        turn = run_turn(
            self.provider,
            self.tools,
            self.messages,
            self.ctx,
            system=self.system,
            max_steps=self.max_steps,
        )
        try:
            async for event in turn:
                self._emit(event)
                if isinstance(event, TurnEnded):
                    stop_reason = event.stop_reason
        except asyncio.CancelledError:  # Ctrl+C
            self._emit(TurnEnded(stop_reason="interrupted"))
            raise
        return stop_reason

    def _emit(self, event: Event) -> None:
        for listener in self.listeners:
            listener(event)
