"""The interface every tool implements."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class ToolContext:
    # What a tool can use while it runs. The executor and policy decision join it later.
    cwd: Path


@dataclass(frozen=True)
class ToolOutput:
    content: str
    is_error: bool = False


class Tool[InputT: BaseModel](Protocol):
    name: str
    # The model reads this. It will treat it as product copy
    description: str
    input_model: type[InputT]
    # Read-only tools may run in parallel and skip "ask"
    read_only: bool

    async def run(self, args: InputT, ctx: ToolContext) -> ToolOutput: ...
