"""A provider that replays scripted responses, so loop tests are deterministic and free."""

from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, Self

from pydantic import TypeAdapter

from zwans.events import TextDelta, ThinkingDelta
from zwans.messages import Message, TextBlock
from zwans.providers.base import ModelResponse, ProviderError
from zwans.tools.base import Tool


class FakeProvider:
    def __init__(self, script: Sequence[ModelResponse]) -> None:
        self._script = list(script)
        self.requests: list[list[Message]] = []  # what the loop sent on each call

    @classmethod
    def from_file(cls, path: Path) -> Self:
        """Load a script: a JSON list of responses, each shaped like ModelResponse."""
        return cls(TypeAdapter(list[ModelResponse]).validate_json(path.read_bytes()))

    async def stream(
        self, system: str, messages: Sequence[Message], tools: Sequence[Tool[Any]]
    ) -> AsyncIterator[TextDelta | ThinkingDelta | ModelResponse]:
        self.requests.append(list(messages))
        if not self._script:
            raise ProviderError("FakeProvider ran out of scripted responses")
        response = self._script.pop(0)
        for block in response.content:
            if isinstance(block, TextBlock):
                yield TextDelta(text=block.text)
        yield response
