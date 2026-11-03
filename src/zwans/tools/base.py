"""The interface every tool implements."""

from dataclasses import dataclass
from typing import Any, Protocol

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
    # A unified diff of the file the call changed, for people watching. The model doesn't
    # see it; it already knows what it asked for.
    diff: str | None = None


class Tool[InputT: BaseModel](Protocol):
    name: str
    # The model reads this to decide when and how to call the tool, so write it like product copy
    description: str
    input_model: type[InputT]
    # Read-only tools may run in parallel and skip "ask"
    read_only: bool

    async def run(self, args: InputT, ctx: ToolContext) -> ToolOutput: ...


def input_schema(tool: Tool[Any]) -> dict[str, Any]:
    """The JSON schema the model sees. Tools from MCP servers bring their own; Zwans's tools
    derive it from their input model."""
    schema = getattr(tool, "input_schema", None)
    return schema if isinstance(schema, dict) else tool.input_model.model_json_schema()
