"""The interface every tool implements."""

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from zwans.executor.base import Executor


class ToolError(Exception):
    """A problem the model should hear about and can fix, such as an Edit with no match."""


@dataclass(frozen=True)
class ToolContext:
    # What a tool can use while it runs. The policy decision joins it in Phase 4.
    executor: Executor


@dataclass(frozen=True)
class ToolOutput:
    content: str
    is_error: bool = False


class Tool[InputT: BaseModel](Protocol):
    name: str
    # The model reads this to decide when and how to call the tool, so write it like product copy
    description: str
    input_model: type[InputT]
    # Read-only tools may run in parallel and skip "ask"
    read_only: bool

    async def run(self, args: InputT, ctx: ToolContext) -> ToolOutput: ...
