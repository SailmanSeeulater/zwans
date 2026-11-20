import asyncio
from pathlib import Path
from typing import Any

from anthropic.types.beta import BetaMessage
from helpers import collect, user

from zwans.config import Credential
from zwans.context.compaction import render_transcript
from zwans.events import ModelCalled, ToolCallRequested, ToolResult, TurnEnded, UsageUpdated
from zwans.executor.local import LocalExecutor
from zwans.loop import run_turn
from zwans.messages import Message, RawBlock, TextBlock
from zwans.policy.engine import Permissions
from zwans.policy.rules import Policy
from zwans.pricing import cost
from zwans.prompt import system_prompt
from zwans.providers.anthropic import AnthropicProvider, convert_content, to_response
from zwans.providers.base import ModelResponse
from zwans.providers.fake import FakeProvider
from zwans.tools.base import ToolContext
from zwans.web import describe

KEY = Credential(mode="api_key", token="sk-test")

SEARCH_CALL = {
    "type": "server_tool_use",
    "id": "srvtoolu_1",
    "name": "web_search",
    "input": {"query": "httpx2 timeout"},
}
SEARCH_RESULT = {
    "type": "web_search_tool_result",
    "tool_use_id": "srvtoolu_1",
    "content": [
        {
            "type": "web_search_result",
            "url": "https://example.com/timeouts",
            "title": "Timeouts",
            "encrypted_content": "abc",
            "page_age": None,
        }
    ],
}
FETCH_CALL = {
    "type": "server_tool_use",
    "id": "srvtoolu_2",
    "name": "web_fetch",
    "input": {"url": "https://example.com/timeouts"},
}
FETCH_RESULT = {
    "type": "web_fetch_tool_result",
    "tool_use_id": "srvtoolu_2",
    "content": {
        "type": "web_fetch_result",
        "url": "https://example.com/timeouts",
        "content": {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain", "data": "Set read=5."},
            "title": "Timeouts",
        },
        "retrieved_at": "2026-11-19T10:00:00Z",
    },
}


def raw(*blocks: dict[str, Any]) -> list[TextBlock | RawBlock]:
    return [RawBlock(type=block["type"], data=block) for block in blocks]


def test_web_tools_are_offered_in_the_version_each_model_takes() -> None:
    def web_types(model: str, web: bool) -> list[str]:
        provider = AnthropicProvider(KEY, model, "low", 16_000, web=web)
        tools = provider.request("", [user("Hi")], [])["tools"]
        return [] if not isinstance(tools, list) else [tool["type"] for tool in tools]

    assert web_types("claude-opus-5-5", True) == ["web_search_20260209", "web_fetch_20260209"]
    assert web_types("claude-haiku-5-5", True) == ["web_search_20250305", "web_fetch_20250910"]
    assert web_types("claude-opus-5-5", False) == []


def test_server_tool_blocks_round_trip_and_searches_are_counted() -> None:
    message = BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": [SEARCH_CALL, SEARCH_RESULT, {"type": "text", "text": "Found it."}],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 1_000_000,
                "output_tokens": 0,
                "server_tool_use": {"web_search_requests": 2, "web_fetch_requests": 0},
            },
        }
    )

    response = to_response(message)

    assert response.web_searches == 2
    assert [block.type for block in response.content] == [
        "server_tool_use",
        "web_search_tool_result",
        "text",
    ]
    assert cost(response.usage_event()) == 4 + 2 * 0.01  # $4 of input, two searches


def test_results_are_described_in_a_few_lines() -> None:
    assert describe(SEARCH_RESULT["content"]) == (
        "Timeouts\n  https://example.com/timeouts",
        False,
    )
    assert describe(FETCH_RESULT["content"]) == (
        "Timeouts\n  https://example.com/timeouts\n  11 characters",
        False,
    )
    error = {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}
    assert describe(error) == ("The API couldn't do this: max_uses_exceeded", True)


def test_a_paused_turn_is_sent_back_and_web_calls_show_as_tool_calls(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            # The API pauses after the search, before it fetches the page.
            ModelResponse(content=raw(SEARCH_CALL, SEARCH_RESULT), stop_reason="pause_turn"),
            ModelResponse(
                content=[*raw(FETCH_CALL, FETCH_RESULT), TextBlock(text="Set read=5.")],
                stop_reason="end_turn",
            ),
        ]
    )
    executor = LocalExecutor(tmp_path)
    permissions = Permissions(Policy.default(), executor.contains, executor.relative)
    messages = [user("How do I set a read timeout?")]

    events = asyncio.run(
        collect(
            run_turn(
                provider, [], messages, ToolContext(executor=executor), permissions=permissions
            )
        )
    )

    # The second request carries on from the paused reply, with nothing added after it.
    assert provider.requests[1][-1].role == "assistant"
    assert [m.role for m in messages] == ["user", "assistant", "assistant"]
    shown = [e for e in events if isinstance(e, ToolCallRequested | ToolResult)]
    assert [type(e).__name__ for e in shown] == [
        "ToolCallRequested",
        "ToolResult",
        "ToolCallRequested",
        "ToolResult",
    ]
    assert shown[0] == ToolCallRequested(
        call_id="srvtoolu_1", name="web_search", args={"query": "httpx2 timeout"}
    )
    assert all(e.untrusted for e in shown if isinstance(e, ToolResult))
    assert permissions.tainted  # later writes are checked as after untrusted content
    assert [e.tools for e in events if isinstance(e, ModelCalled)] == [
        ["web_search"],
        ["web_fetch"],
    ]
    assert sum(isinstance(e, UsageUpdated) for e in events) == 2
    assert events[-1] == TurnEnded(stop_reason="end_turn")


def test_the_summarizer_sees_web_calls() -> None:
    message = Message(role="assistant", content=convert_content([SEARCH_CALL, SEARCH_RESULT]))

    text = render_transcript([message])

    assert 'TOOL CALL web_search: {"query": "httpx2 timeout"}' in text
    assert "TOOL RESULT: Timeouts\n  https://example.com/timeouts" in text


def test_the_prompt_mentions_the_web_tools_only_when_offered(tmp_path: Path) -> None:
    assert "web_search" in system_prompt(tmp_path, "bash", [], web=True)
    assert "web_search" not in system_prompt(tmp_path, "bash", [])
