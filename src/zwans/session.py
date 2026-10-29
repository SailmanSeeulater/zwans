"""A conversation with the agent: the history, plus everyone listening to its events."""

import asyncio
from collections.abc import Callable, Sequence
from typing import Any

from zwans.context.compaction import Compactor
from zwans.events import Event, TurnEnded
from zwans.loop import run_turn
from zwans.messages import Message, TextBlock
from zwans.policy.engine import Permissions
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
        compactor: Compactor | None = None,
        permissions: Permissions | None = None,
    ) -> None:
        self.provider = provider
        self.tools = list(tools)
        self.ctx = ctx
        self.system = system  # fixed for the whole session, so earlier turns stay valid
        self.listeners = list(listeners)
        self.max_steps = max_steps
        self.compactor = compactor
        self.permissions = permissions  # None runs every call without checking
        self.messages: list[Message] = []
        self.turn = 0  # how many user turns the session has had

    def context_tokens(self) -> int:
        """About how many tokens the next request will send."""
        return self.compactor.estimate(self.messages) if self.compactor else 0

    async def send(self, prompt: str) -> str:
        """Run one turn and return why it ended: "end_turn", "interrupted", "error", ..."""
        self.turn += 1
        self.messages.append(Message(role="user", content=[TextBlock(text=prompt)], turn=self.turn))
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
