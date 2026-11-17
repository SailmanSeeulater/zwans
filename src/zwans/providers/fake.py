"""A provider that replays scripted responses, so loop tests are deterministic and free.

It also drives the web UI's demo, which replays a recorded session without an API key; for
that, `pace` slows the replay down to something a person can follow.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, Self

from pydantic import TypeAdapter

from zwans.events import TextDelta, ThinkingDelta
from zwans.messages import Message, TextBlock
from zwans.providers.anthropic import EPHEMERAL, message_param, tool_param
from zwans.providers.base import ModelResponse, ProviderError
from zwans.tools.base import Tool

WORDS_PER_DELTA = 3


class FakeProvider:
    def __init__(self, script: Sequence[ModelResponse], pace: float = 0.0) -> None:
        self._script = list(script)
        self.pace = pace  # seconds between streamed pieces of text; 0 streams it all at once
        self.requests: list[list[Message]] = []  # what the loop sent on each call
        self.last_request: dict[str, Any] | None = None  # shaped like the real API's

    @classmethod
    def from_file(cls, path: Path, pace: float = 0.0) -> Self:
        """Load a script: a JSON list of responses, each shaped like ModelResponse."""
        return cls(TypeAdapter(list[ModelResponse]).validate_json(path.read_bytes()), pace)

    async def stream(
        self, system: str, messages: Sequence[Message], tools: Sequence[Tool[Any]]
    ) -> AsyncIterator[TextDelta | ThinkingDelta | ModelResponse]:
        self.requests.append(list(messages))
        if not self._script:
            raise ProviderError("FakeProvider ran out of scripted responses")
        response = self._script.pop(0)
        # Shaped like AnthropicProvider's with its default prompt cache: a breakpoint after the
        # system prompt, and automatic caching for the conversation.
        self.last_request = {
            "model": response.model or "fake",
            "system": [{"type": "text", "text": system, "cache_control": EPHEMERAL}]
            if system
            else [],
            "messages": [message_param(m) for m in messages],
            "tools": [tool_param(t) for t in tools],
            "cache_control": EPHEMERAL,
        }
        if self.pace:
            await asyncio.sleep(self.pace * 15)  # the wait for the first token
        for block in response.content:
            if isinstance(block, TextBlock):
                if not self.pace:
                    yield TextDelta(text=block.text)
                    continue
                words = block.text.split(" ")
                for start in range(0, len(words), WORDS_PER_DELTA):
                    piece = " ".join(words[start : start + WORDS_PER_DELTA])
                    yield TextDelta(text=piece if start == 0 else " " + piece)
                    await asyncio.sleep(self.pace)
        yield response

    async def aclose(self) -> None:
        pass
