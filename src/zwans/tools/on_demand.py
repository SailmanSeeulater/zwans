"""Tools on demand: the everyday tools go with every request, and the rest are loaded when the
model asks for them.

Every tool's definition goes with every request, and with every tool Zwans has that is about
11,000 tokens, most of it for tools a given task never calls. On a local model, that is time
before each reply, and more tools to pick the wrong one from. So only the core tools, plus
ToolSearch, are offered from the start. ToolSearch's description lists the others by name and
first sentence, and calling it with some of those names loads them.

How a tool is loaded depends on the model, and is the provider's job (`split` below is what
they share):

- Claude gets every definition in every request, the deferred ones marked `defer_loading`, so
  the request's front, and the prompt cache with it, never changes. ToolSearch's result is
  sent as `tool_reference` blocks, which make the API load those definitions from then on.
- Other models get only the tools offered so far. A loaded tool joins them from the next
  request, which on a local server means reading the conversation again once.

What has been loaded is read from the conversation, so it holds after a resume or a rewind.
A compaction summarizes the calls that loaded tools, so after one they are loaded again.
"""

from collections.abc import Collection, Iterable, Sequence
from typing import Any

from pydantic import BaseModel, Field

from zwans.messages import Message, ToolResultBlock, ToolUseBlock
from zwans.tools.base import Tool, ToolContext, ToolError, ToolOutput

NAME = "ToolSearch"
# Fewer tools than this to defer don't save enough to be worth a call to load one.
MIN_DEFERRED = 4
# Offered from the start: what nearly every coding task needs. The web stand-ins are too,
# since for Claude the router leaves them out and ToolSearch mustn't list what isn't there.
CORE = frozenset(
    {
        "Read",
        "Write",
        "Edit",
        "MultiEdit",
        "Glob",
        "Grep",
        "Bash",
        "BashOutput",
        "KillBash",
        "RunTests",
        "TodoWrite",
        "Task",
        "Skill",
        "AskUser",
    }
)


class ToolSearchInput(BaseModel):
    names: list[str] = Field(
        min_length=1, description="Tools to load, by their names as listed, such as Data."
    )


class ToolSearchTool:
    name = NAME
    input_model = ToolSearchInput
    read_only = True

    def __init__(self, deferred: Sequence[Tool[Any]]) -> None:
        self.catalog = {tool.name: tool for tool in deferred}
        listed = "\n".join(
            f"- {tool.name}: {_first_sentence(tool.description)}" for tool in deferred
        )
        # Fixed for the session: a description that changed would change the request's front.
        self.description = (
            "Load tools that aren't offered yet, so you can call them. These are the tools you "
            "can load, by name and what they do:\n"
            f"{listed}\n"
            "Load one when the task calls for it, then call it as usual. Loaded tools stay "
            "loaded for the rest of the conversation."
        )

    async def run(self, args: ToolSearchInput, ctx: ToolContext) -> ToolOutput:
        unknown = [name for name in args.names if name not in self.catalog and name not in CORE]
        if unknown:
            raise ToolError(
                f"No tool to load called {', '.join(unknown)}. "
                f"These can be loaded: {', '.join(self.catalog)}."
            )
        wanted = [name for name in args.names if name in self.catalog]
        if not wanted:
            return ToolOutput(content="Those are offered already; call them as usual.")
        return ToolOutput(content=f"Loaded {', '.join(wanted)}. Call them as usual.")


def with_search(tools: Sequence[Tool[Any]], always: Collection[str] = ()) -> list[Tool[Any]]:
    """`tools` with ToolSearch added, standing in for every tool outside the core and `always`
    until it's loaded; `tools` as they are when there's too little to defer."""
    deferred = [
        tool
        for tool in tools
        if tool.name not in CORE
        and tool.name not in always
        and not getattr(tool, "local_web", False)
    ]
    if len(deferred) < MIN_DEFERRED:
        return list(tools)
    return [*tools, ToolSearchTool(deferred)]


def split(
    tools: Sequence[Tool[Any]], messages: Iterable[Message]
) -> tuple[list[Tool[Any]], set[str], set[str]]:
    """What a request declares: the tools offered so far (the core and those loaded), the
    names of the deferred ones among `tools`, and of those, the ones loaded."""
    searcher = next((tool for tool in tools if isinstance(tool, ToolSearchTool)), None)
    if searcher is None:
        return list(tools), set(), set()
    deferred = {tool.name for tool in tools if tool.name in searcher.catalog}
    loaded = loaded_tools(messages, deferred)
    offered = [tool for tool in tools if tool.name not in deferred or tool.name in loaded]
    return offered, deferred, loaded


def loaded_tools(messages: Iterable[Message], deferred: Collection[str]) -> set[str]:
    """The deferred tools the conversation has loaded, by a ToolSearch call that worked or by
    calling one outright."""
    calls: dict[str, ToolUseBlock] = {}
    loaded: set[str] = set()
    for message in messages:
        for block in message.content:
            if isinstance(block, ToolUseBlock):
                calls[block.id] = block
                if block.name in deferred:
                    loaded.add(block.name)
            elif isinstance(block, ToolResultBlock) and not block.is_error:
                call = calls.get(block.tool_use_id)
                if call is not None and call.name == NAME:
                    loaded.update(searched(call) & set(deferred))
    return loaded


def searched(call: ToolUseBlock) -> set[str]:
    """The names a ToolSearch call asked for."""
    names = call.input.get("names")
    return {name for name in names if isinstance(name, str)} if isinstance(names, list) else set()


def _first_sentence(text: str) -> str:
    text = " ".join(text.split())
    end = text.find(". ")
    return text if end == -1 else text[: end + 1]
