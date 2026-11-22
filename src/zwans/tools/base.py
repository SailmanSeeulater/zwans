"""The interface every tool implements."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel

from zwans.executor.base import Executor
from zwans.messages import ImageBlock

if TYPE_CHECKING:
    from zwans.executor.background import BackgroundJobs


class ToolError(Exception):
    """A problem the model should hear about and can fix, such as an Edit with no match."""


# Puts a question and its suggested answers to the person, and returns what they said, or
# None when they gave no answer.
type Asker = Callable[[str, Sequence[str]], Awaitable[str | None]]


@dataclass(frozen=True)
class ToolContext:
    # What a tool can use while it runs. The policy decision joins it in Phase 4.
    executor: Executor
    jobs: "BackgroundJobs | None" = None  # the session's background commands, if it has any
    ask: Asker | None = None  # how to ask the person something; None when nobody is there


@dataclass(frozen=True)
class ToolOutput:
    content: str
    is_error: bool = False
    # A unified diff of the file the call changed, for people watching. The model doesn't
    # see it; it already knows what it asked for.
    diff: str | None = None
    images: tuple[ImageBlock, ...] = ()  # sent to the model after the text, as with Read


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
