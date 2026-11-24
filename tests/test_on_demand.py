"""Tools on demand: the everyday tools are offered from the start, and the model loads the rest
with ToolSearch. Claude gets every definition with the unloaded ones deferred, so the request's
front never changes; other models get only the tools offered so far."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from helpers import user
from test_providers_openai import Server, delta, finish, sse

from zwans.config import Credential
from zwans.context.calls import context_split
from zwans.executor.local import LocalExecutor
from zwans.messages import Message, ToolResultBlock, ToolUseBlock
from zwans.providers.anthropic import AnthropicProvider
from zwans.tools.base import Tool, ToolContext, ToolError
from zwans.tools.bash import BashTool
from zwans.tools.bisect import BisectTool
from zwans.tools.data import DataTool
from zwans.tools.history import HistoryTool
from zwans.tools.logs import LogsTool
from zwans.tools.on_demand import (
    ToolSearchInput,
    ToolSearchTool,
    loaded_tools,
    split,
    with_search,
)
from zwans.tools.profile import ProfileTool
from zwans.tools.read import ReadTool
from zwans.tools.web_local import WebFetchTool


def every_tool() -> list[Tool[Any]]:
    return [
        ReadTool(),
        BashTool(),
        DataTool(),
        LogsTool(),
        HistoryTool(),
        BisectTool(),
        WebFetchTool(),
    ]


def search_of(tools: list[Tool[Any]]) -> ToolSearchTool:
    [searcher] = [tool for tool in tools if isinstance(tool, ToolSearchTool)]
    return searcher


def searched(names: list[str], error: bool = False, call_id: str = "s1") -> list[Message]:
    """A ToolSearch call for `names`, and its result."""
    call = ToolUseBlock(id=call_id, name="ToolSearch", input={"names": names})
    result = ToolResultBlock(tool_use_id=call_id, content="Loaded.", is_error=error)
    return [Message(role="assistant", content=[call]), Message(role="user", content=[result])]


def test_toolsearch_stands_in_for_all_but_the_everyday_tools_and_the_web_stand_ins() -> None:
    tools = with_search(every_tool())

    searcher = search_of(tools)
    assert list(searcher.catalog) == ["Data", "Logs", "History", "Bisect"]
    assert tools[-1] is searcher and len(tools) == 8
    assert "- Data: " in searcher.description and "- Read" not in searcher.description
    assert "WebFetch" not in searcher.description  # the router leaves it out for Claude


def test_always_tools_join_the_everyday_ones_and_too_few_to_defer_defers_none() -> None:
    more = [*every_tool(), ProfileTool()]
    catalog = search_of(with_search(more, ["Data"])).catalog
    assert list(catalog) == ["Logs", "History", "Bisect", "Profile"]
    few = with_search(every_tool(), always=["Data", "Logs"])
    assert not any(isinstance(tool, ToolSearchTool) for tool in few)  # two left: not worth it


def test_loading_names_the_tools_and_refuses_ones_it_doesnt_know(tmp_path: Path) -> None:
    searcher = search_of(with_search(every_tool()))
    ctx = ToolContext(executor=LocalExecutor(tmp_path))

    def run(*names: str) -> str:
        return asyncio.run(searcher.run(ToolSearchInput(names=list(names)), ctx)).content

    assert run("Data", "Bisect") == "Loaded Data, Bisect. Call them as usual."
    assert run("Read") == "Those are offered already; call them as usual."
    with pytest.raises(
        ToolError, match=r"No tool to load called Spreadsheet\. These can be loaded: Data, Logs"
    ):
        run("Data", "Spreadsheet")


def test_what_is_loaded_is_read_from_the_conversation() -> None:
    deferred = {"Data", "Logs", "History", "Bisect"}
    direct = Message(
        role="assistant", content=[ToolUseBlock(id="c1", name="Logs", input={"path": "a.log"})]
    )
    messages = [
        user("Look at the data"),
        *searched(["Data", "Read"]),
        *searched(["History"], error=True, call_id="s2"),
        direct,
    ]

    assert loaded_tools(messages, deferred) == {"Data", "Logs"}


def test_without_toolsearch_every_tool_is_offered() -> None:
    tools = every_tool()

    assert split(tools, [user("hi")]) == (tools, set(), set())


def test_a_local_model_is_offered_the_core_and_then_what_it_loads() -> None:
    tools = with_search(every_tool())
    reply = sse(delta(content="Done."), finish("stop"))
    server = Server(reply, reply)

    async def ask(messages: list[Message]) -> None:
        async for _ in server.provider().stream("Be brief.", messages, tools):
            pass

    async def both() -> None:
        await ask([user("Plot the data")])
        await ask([user("Plot the data"), *searched(["Data"]), user("go on")])

    asyncio.run(both())

    first, second = ([t["function"]["name"] for t in body["tools"]] for body in server.bodies)
    assert first == ["Read", "Bash", "WebFetch", "ToolSearch"]
    assert second == ["Read", "Bash", "Data", "WebFetch", "ToolSearch"]


def anthropic_request(messages: list[Message]) -> dict[str, Any]:
    provider = AnthropicProvider(
        Credential(mode="api_key", token="sk-test"), "claude-opus-5-5", "medium", 64_000
    )
    return provider.request("You are Zwans.", messages, with_search(every_tool()))


def test_claude_gets_every_definition_with_the_unloaded_ones_deferred() -> None:
    before = anthropic_request([user("Plot the data")])
    after = anthropic_request([user("Plot the data"), *searched(["Data", "Read"])])

    assert before["tools"] == after["tools"]  # the request's front, and its cache, holds
    deferred = {t["name"] for t in before["tools"] if t.get("defer_loading")}
    assert deferred == {"Data", "Logs", "History", "Bisect"}
    assert after["messages"][2]["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "s1",
            "content": [{"type": "tool_reference", "tool_name": "Data"}],
        }
    ]


def test_a_search_that_failed_or_loaded_nothing_goes_to_claude_as_text() -> None:
    request = anthropic_request(
        [
            user("hi"),
            *searched(["Data"], error=True),
            *searched(["Read"], call_id="s2"),
        ]
    )

    results = [m["content"][0] for m in request["messages"][2::2]]
    assert [r["content"] for r in results] == ["Loaded.", "Loaded."]


def test_the_context_shown_counts_only_the_offered_tools() -> None:
    tools = with_search(every_tool())
    offered = split(tools, [user("hi")])[0]

    assert context_split("", offered, []).tools < context_split("", tools, []).tools
    assert [tool.name for tool in offered] == ["Read", "Bash", "WebFetch", "ToolSearch"]
