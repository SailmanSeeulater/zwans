"""A provider that replays scripted responses, so loop tests are deterministic and free."""

from collections.abc import Sequence
from typing import Any

from zwans.messages import Message
from zwans.providers.base import ModelResponse
from zwans.tools.base import Tool


class FakeProvider:
    def __init__(self, script: Sequence[ModelResponse]) -> None:
        self._script = list(script)
        self.requests: list[list[Message]] = []  # what the loop sent on each call

    async def complete(
        self, messages: Sequence[Message], tools: Sequence[Tool[Any]]
    ) -> ModelResponse:
        self.requests.append(list(messages))
        if not self._script:
            raise RuntimeError("FakeProvider ran out of scripted responses")
        return self._script.pop(0)
