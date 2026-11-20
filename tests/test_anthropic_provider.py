import asyncio
from collections.abc import Mapping
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaMessage
from pydantic import BaseModel, Field

from zwans.config import Credential, PromptCache
from zwans.events import TextDelta
from zwans.messages import Message, RawBlock, TextBlock, ToolResultBlock, ToolUseBlock
from zwans.providers.anthropic import (
    CUT_OFF_ATTEMPTS,
    AnthropicProvider,
    convert_content,
    describe_api_error,
    message_param,
    sources_note,
    tool_param,
)
from zwans.providers.base import ModelResponse, ProviderError, ServerBlock
from zwans.tools.base import ToolContext, ToolOutput

THINKING = {"type": "thinking", "thinking": "", "signature": "sig-abc"}


def test_thinking_blocks_are_kept_verbatim_and_sent_back_unchanged() -> None:
    content = convert_content(
        [
            THINKING,
            {"type": "text", "text": "Running the tests."},
            {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "pytest"}},
        ]
    )

    assert content == [
        RawBlock(type="thinking", data=THINKING),
        TextBlock(text="Running the tests."),
        ToolUseBlock(id="toolu_1", name="Bash", input={"command": "pytest"}),
    ]
    sent = message_param(Message(role="assistant", content=list(content)))
    assert sent["content"][0] == THINKING


def test_blocks_from_a_declined_attempt_keep_only_their_text() -> None:
    fallback = {"type": "fallback", "from": {"model": "a"}, "to": {"model": "b"}}
    content = convert_content(
        [
            THINKING,
            {"type": "text", "text": "Partial answer"},
            {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {}},
            fallback,
            {"type": "text", "text": "Answer from the fallback model"},
        ]
    )

    assert content == [
        TextBlock(text="Partial answer"),
        RawBlock(type="fallback", data=fallback),
        TextBlock(text="Answer from the fallback model"),
    ]


def test_tool_results_use_the_api_shape() -> None:
    message = Message(
        role="user", content=[ToolResultBlock(tool_use_id="toolu_1", content="ok", is_error=True)]
    )

    assert message_param(message) == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok", "is_error": True}
        ],
    }


class NoteInput(BaseModel):
    text: str = Field(description="What to note.")


class NoteTool:
    name = "Note"
    description = "Take a note."
    input_model = NoteInput
    read_only = True

    async def run(self, args: NoteInput, ctx: ToolContext) -> ToolOutput:
        return ToolOutput(content=args.text)


def test_tool_definitions_carry_the_schema_and_stream_their_input() -> None:
    param = tool_param(NoteTool())

    assert param["name"] == "Note"
    assert param["input_schema"]["properties"]["text"]["description"] == "What to note."
    assert param["eager_input_streaming"] is True


def _rate_limit_error() -> anthropic.RateLimitError:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(429, request=request, headers={"request-id": "req_123"})
    body = {"type": "error", "error": {"type": "rate_limit_error", "message": "Error"}}
    return anthropic.RateLimitError("Error code: 429", response=response, body=body)


def test_api_errors_are_short_and_name_the_request() -> None:
    text = describe_api_error(_rate_limit_error(), plan_token=False)

    assert text == "Claude API error 429 (rate_limit_error): Error [request req_123]"


def test_errors_with_a_plan_token_suggest_an_api_key() -> None:
    text = describe_api_error(_rate_limit_error(), plan_token=True)

    assert "set ZWANS_AUTH=api_key" in text


def test_requests_cache_the_prefix_and_drop_stale_thinking() -> None:
    credential = Credential(mode="api_key", token="sk-test")
    provider = AnthropicProvider(credential, "claude-opus-5-5", "medium", 64_000)

    request = provider.request("You are Zwans.", [user_message("Hi")], [NoteTool()])

    assert request["system"] == [
        {"type": "text", "text": "You are Zwans.", "cache_control": {"type": "ephemeral"}}
    ]
    assert request["cache_control"] == {"type": "ephemeral"}  # moving breakpoint on the tail
    assert request["thinking"]["block_binding"] == {"prefix_mismatch_behavior": "drop_block"}
    assert "thinking-binding-controls-2026-08-01" in request["betas"]


@pytest.mark.parametrize(
    ("prompt_cache", "system_cached", "conversation_cached"),
    [("conversation", True, True), ("system", True, False), ("off", False, False)],
)
def test_prompt_cache_chooses_the_breakpoints(
    prompt_cache: PromptCache, system_cached: bool, conversation_cached: bool
) -> None:
    credential = Credential(mode="api_key", token="sk-test")
    provider = AnthropicProvider(credential, "claude-opus-5-5", "medium", 64_000, prompt_cache)

    request = provider.request("You are Zwans.", [user_message("Hi")], [NoteTool()])

    assert ("cache_control" in request["system"][0]) == system_cached
    assert ("cache_control" in request) == conversation_cached


def test_haiku_5_5_gets_no_fallbacks_or_progress_notes() -> None:
    credential = Credential(mode="api_key", token="sk-test")
    provider = AnthropicProvider(credential, "claude-haiku-5-5", "low", 64_000)

    request = provider.request("You are Zwans.", [user_message("Hi")], [NoteTool()])

    assert request["thinking"] == {
        "type": "adaptive",
        "block_binding": {"prefix_mismatch_behavior": "drop_block"},
    }
    assert request["output_config"] == {"effort": "low"}
    assert request["fallbacks"] is anthropic.omit
    assert request["betas"] == ["thinking-binding-controls-2026-08-01"]


def test_haiku_4_5_thinks_on_a_budget_instead_of_an_effort_level() -> None:
    credential = Credential(mode="api_key", token="sk-test")
    provider = AnthropicProvider(credential, "claude-haiku-4-5", "medium", 64_000)

    request = provider.request("You are Zwans.", [user_message("Hi")], [NoteTool()])

    assert request["thinking"] == {"type": "enabled", "budget_tokens": 8_000}
    assert request["output_config"] is anthropic.omit
    assert request["fallbacks"] is anthropic.omit
    assert request["betas"] == ["interleaved-thinking-2025-05-14"]


def test_a_thinking_budget_stays_below_max_tokens() -> None:
    credential = Credential(mode="api_key", token="sk-test")
    provider = AnthropicProvider(credential, "claude-haiku-4-5", "max", 16_000)

    budget = provider.request("", [user_message("Hi")], [])["thinking"]["budget_tokens"]

    assert budget == 15_999


def user_message(text: str) -> Message:
    return Message(role="user", content=[TextBlock(text=text)])


class _CutOffStream:
    """Stands in for the SDK's message stream; the first `drops` streams break mid-reply."""

    def __init__(self, owner: "_FakeMessages") -> None:
        self.owner = owner

    async def __aenter__(self) -> "_CutOffStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> "_CutOffStream":
        return self

    async def __anext__(self) -> object:
        self.owner.calls += 1
        if self.owner.calls <= self.owner.drops:
            raise httpx2.ReadError("connection reset")
        raise StopAsyncIteration

    async def get_final_message(self) -> BetaMessage:
        return BetaMessage.model_validate(
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [{"type": "text", "text": "Done."}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        )


class _FakeMessages:
    def __init__(self, drops: int) -> None:
        self.drops = drops
        self.calls = 0

    def stream(self, **request: object) -> _CutOffStream:
        return _CutOffStream(self)


def _provider_with_drops(drops: int, monkeypatch: pytest.MonkeyPatch) -> AnthropicProvider:
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    provider = AnthropicProvider(Credential("api_key", "key"), "claude-opus-5-5", "low", 1000)
    fake = SimpleNamespace(beta=SimpleNamespace(messages=_FakeMessages(drops)))
    provider._client = fake  # type: ignore[assignment]
    return provider


async def _no_sleep(seconds: float) -> None:
    pass


async def _collect(provider: AnthropicProvider) -> list[object]:
    return [item async for item in provider.stream("", [], [])]


def test_a_stream_cut_off_mid_reply_is_asked_for_again(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_with_drops(2, monkeypatch)

    items = asyncio.run(_collect(provider))

    assert isinstance(items[-1], ModelResponse)
    assert items[-1].stop_reason == "end_turn"


def test_a_connection_that_keeps_dropping_becomes_a_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_with_drops(CUT_OFF_ATTEMPTS, monkeypatch)

    with pytest.raises(ProviderError, match="kept dropping"):
        asyncio.run(_collect(provider))


class _ScriptedStream:
    """Stands in for the SDK's message stream: plays the given events, then the message, or
    raises `error` when entered."""

    def __init__(
        self, events: list[object], content: list[dict[str, object]], error: Exception | None
    ) -> None:
        self.events = iter(events)
        self.content = content
        self.error = error

    async def __aenter__(self) -> "_ScriptedStream":
        if self.error is not None:
            raise self.error
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> "_ScriptedStream":
        return self

    async def __anext__(self) -> object:
        try:
            return next(self.events)
        except StopIteration:
            raise StopAsyncIteration from None

    async def get_final_message(self) -> BetaMessage:
        return BetaMessage.model_validate(
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": self.content,
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        )


def _scripted_provider(
    events: list[object],
    content: list[dict[str, object]],
    error: Exception | None = None,
    mode: str = "api_key",
) -> AnthropicProvider:
    credential = Credential(mode, "key")  # type: ignore[arg-type]
    provider = AnthropicProvider(credential, "claude-opus-5-5", "low", 1000)
    messages = SimpleNamespace(stream=lambda **request: _ScriptedStream(events, content, error))
    provider._client = SimpleNamespace(beta=SimpleNamespace(messages=messages))  # type: ignore[assignment]
    return provider


def _block_start(kind: str) -> object:
    return SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type=kind))


def _text(text: str) -> object:
    return SimpleNamespace(type="text", text=text)


def test_separate_text_blocks_stream_as_paragraphs() -> None:
    events = [
        _block_start("text"),
        _text("Looking it up."),
        _block_start("server_tool_use"),
        _block_start("web_search_tool_result"),
        _block_start("text"),
        _text("Found it"),
        _text(" here."),
    ]
    provider = _scripted_provider(events, [{"type": "text", "text": "Looking it up."}])

    items = asyncio.run(_collect(provider))

    texts = [item.text for item in items if isinstance(item, TextDelta)]
    assert texts == ["Looking it up.", "\n\nFound it", " here."]


def _block_stop(block: Mapping[str, object]) -> object:
    content_block = SimpleNamespace(type=block["type"], to_dict=lambda mode: block)
    return SimpleNamespace(type="content_block_stop", content_block=content_block)


def test_web_calls_are_passed_on_as_they_stream_before_the_sources() -> None:
    search: dict[str, object] = {
        "type": "server_tool_use",
        "id": "s1",
        "name": "web_search",
        "input": {"q": "x"},
    }
    result: dict[str, object] = {
        "type": "web_search_tool_result",
        "tool_use_id": "s1",
        "content": [],
    }
    citation = {
        "type": "web_search_result_location",
        "url": "https://a.example",
        "title": "A",
        "cited_text": "a",
        "encrypted_index": "abc",
    }
    events = [
        _block_start("text"),
        _text("Looking."),
        _block_stop({"type": "text", "text": "Looking."}),
        _block_start("server_tool_use"),
        _block_stop(search),
        _block_start("web_search_tool_result"),
        _block_stop(result),
        _block_start("text"),
        _text("Found."),
    ]
    content: list[dict[str, object]] = [
        {"type": "text", "text": "Looking."},
        search,
        result,
        {"type": "text", "text": "Found.", "citations": [citation]},
    ]

    items = asyncio.run(_collect(_scripted_provider(events, content)))

    order = [
        item.text if isinstance(item, TextDelta) else item.block.type
        for item in items
        if isinstance(item, TextDelta | ServerBlock)
    ]
    assert order == [
        "Looking.",
        "server_tool_use",
        "web_search_tool_result",
        "\n\nFound.",
        "\n\nSources:\n- A: https://a.example",
    ]


def test_cited_pages_are_listed_after_the_reply() -> None:
    citation = {
        "type": "web_search_result_location",
        "url": "https://pypi.org/project/httpx/",
        "title": "httpx · PyPI",
        "cited_text": "httpx 0.28.1",
        "encrypted_index": "abc",
    }
    content: list[dict[str, object]] = [
        {"type": "text", "text": "The latest is 0.28.1.", "citations": [citation, citation]},
        {"type": "text", "text": "No citation here."},
    ]
    provider = _scripted_provider([_block_start("text"), _text("The latest is 0.28.1.")], content)

    items = asyncio.run(_collect(provider))

    texts = [item.text for item in items if isinstance(item, TextDelta)]
    assert texts[-1] == "\n\nSources:\n- httpx · PyPI: https://pypi.org/project/httpx/"
    assert isinstance(items[-1], ModelResponse)
    assert items[-1].content == [
        TextBlock(text="The latest is 0.28.1."),
        TextBlock(text="No citation here."),
    ]


def test_a_reply_without_citations_lists_no_sources() -> None:
    assert sources_note([{"type": "text", "text": "Hi.", "citations": None}]) == ""


def _authentication_error() -> anthropic.AuthenticationError:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(401, request=request)
    body = {"type": "error", "error": {"type": "authentication_error", "message": "invalid"}}
    return anthropic.AuthenticationError("Error code: 401", response=response, body=body)


@pytest.mark.parametrize(
    ("mode", "variable"),
    [("api_key", "ANTHROPIC_API_KEY"), ("subscription", "CLAUDE_CODE_OAUTH_TOKEN")],
)
def test_a_rejected_credential_names_the_variable_in_use(mode: str, variable: str) -> None:
    provider = _scripted_provider([], [], error=_authentication_error(), mode=mode)

    with pytest.raises(ProviderError) as raised:
        asyncio.run(_collect(provider))

    assert str(raised.value) == f"Claude rejected {variable}. Check its value."
