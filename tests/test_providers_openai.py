"""The OpenAI-compatible provider, the provider catalog, and switching models mid-session,
against an in-memory server that speaks the Chat Completions API."""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from helpers import collect, user

from zwans import pricing
from zwans.config import Config, ProviderConfig
from zwans.context.compaction import Compactor
from zwans.events import TextDelta, ThinkingDelta, ToolResult, TurnEnded
from zwans.loop import run_turn
from zwans.messages import (
    ImageBlock,
    ImageSource,
    Message,
    RawBlock,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from zwans.providers.base import ModelResponse, ProviderError
from zwans.providers.catalog import (
    ModelError,
    Resolved,
    canonical,
    is_known,
    list_all,
    providers,
    register_prices,
    resolve,
    split,
)
from zwans.providers.fake import FakeProvider
from zwans.providers.openai_compat import Endpoint, OpenAICompatProvider, chat_messages
from zwans.providers.router import ModelRouter
from zwans.tools.base import ToolContext
from zwans.tools.write import WriteTool

KEY = {"ANTHROPIC_API_KEY": "sk-test"}


def sse(*chunks: dict[str, Any]) -> bytes:
    lines = [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks]
    return ("".join(lines) + "data: [DONE]\n\n").encode()


def delta(**fields: Any) -> dict[str, Any]:
    return {"model": "qwen3:8b", "choices": [{"index": 0, "delta": fields}]}


def finish(reason: str) -> dict[str, Any]:
    return {"model": "qwen3:8b", "choices": [{"index": 0, "delta": {}, "finish_reason": reason}]}


def usage(prompt: int, completion: int, cached: int = 0) -> dict[str, Any]:
    details = {"cached_tokens": cached}
    return {
        "choices": [],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "prompt_tokens_details": details,
        },
    }


class Server:
    """Answers each POST /chat/completions with the next scripted reply."""

    def __init__(self, *replies: httpx.Response | bytes) -> None:
        self.replies = list(replies)
        self.bodies: list[dict[str, Any]] = []
        self.headers: list[httpx.Headers] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen3:8b"}, {"id": "gemma3:4b"}]})
        self.bodies.append(json.loads(request.content))
        self.headers.append(request.headers)
        reply = self.replies.pop(0)
        if isinstance(reply, httpx.Response):
            return reply
        return httpx.Response(200, content=reply, headers={"content-type": "text/event-stream"})

    def provider(self, model: str = "qwen3:8b", **endpoint: Any) -> OpenAICompatProvider:
        settings = {"name": "ollama", "base_url": "http://localhost:11434/v1", **endpoint}
        return OpenAICompatProvider(
            Endpoint(**settings), model, transport=httpx.MockTransport(self.handle)
        )


def stream_all(provider: OpenAICompatProvider, messages: list[Message]) -> list[Any]:
    async def go() -> list[Any]:
        items = [item async for item in provider.stream("Be brief.", messages, [WriteTool()])]
        await provider.aclose()
        return items

    return asyncio.run(go())


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr("zwans.providers.openai_compat.asyncio.sleep", instant)


def test_text_tool_calls_and_usage_stream_into_one_response() -> None:
    server = Server(
        sse(
            delta(reasoning_content="The user wants a file."),
            delta(content="Writing "),
            delta(content="it."),
            delta(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_abc",
                        "type": "function",
                        "function": {"name": "Write", "arguments": '{"path": "a.txt", '},
                    }
                ]
            ),
            delta(tool_calls=[{"index": 0, "function": {"arguments": '"content": "hi"}'}}]),
            finish("tool_calls"),
            usage(prompt=1200, completion=40, cached=1000),
        )
    )
    items = stream_all(server.provider(), [user("Make a.txt")])

    assert items[:3] == [
        ThinkingDelta(text="The user wants a file."),
        TextDelta(text="Writing "),
        TextDelta(text="it."),
    ]
    response = items[-1]
    assert isinstance(response, ModelResponse)
    assert response.content == [
        TextBlock(text="Writing it."),
        ToolUseBlock(id="call_abc", name="Write", input={"path": "a.txt", "content": "hi"}),
    ]
    assert response.stop_reason == "tool_use"
    assert response.model == "ollama/qwen3:8b"  # the name Zwans knows it by, for prices
    assert (response.input_tokens, response.cache_read_tokens, response.output_tokens) == (
        200,
        1000,
        40,
    )
    body = server.bodies[0]
    assert body["model"] == "qwen3:8b" and body["stream"] is True
    assert body["messages"][0] == {"role": "system", "content": "Be brief."}
    assert body["tools"][0]["function"]["name"] == "Write"
    assert "parameters" in body["tools"][0]["function"]
    assert "max_tokens" not in body and "reasoning_effort" not in body


def test_the_key_and_effort_go_only_where_configured() -> None:
    server = Server(sse(delta(content="ok"), finish("stop")))
    provider = server.provider(api_key="sk-or", max_tokens=4096, reasoning_effort=True)
    provider.effort = "max"
    stream_all(provider, [user("hi")])
    assert server.headers[0]["authorization"] == "Bearer sk-or"
    assert server.bodies[0]["max_tokens"] == 4096
    assert server.bodies[0]["reasoning_effort"] == "high"  # the most these APIs take


def test_missing_or_odd_tool_call_ids_are_made_valid_for_claude() -> None:
    server = Server(
        sse(
            delta(tool_calls=[{"index": 0, "function": {"name": "Write", "arguments": "{}"}}]),
            delta(
                tool_calls=[
                    {"index": 1, "id": "fc.1:2", "function": {"name": "Write", "arguments": "{}"}}
                ]
            ),
            finish("stop"),  # some servers say "stop" even when they called tools
        )
    )
    response = stream_all(server.provider(), [user("hi")])[-1]
    first, second = response.content
    assert first.id.startswith("call_") and second.id == "fc_1_2"
    assert response.stop_reason == "tool_use"


def test_tool_input_that_isnt_json_is_asked_for_again_then_reported() -> None:
    bad = sse(
        delta(
            tool_calls=[{"index": 0, "id": "c1", "function": {"name": "Write", "arguments": "{"}}]
        ),
        finish("tool_calls"),
    )
    good = sse(delta(content="fine"), finish("stop"))
    # Each bad reply is first repaired (tests/test_tool_repair.py), which this server can't do.
    no_schemas = httpx.Response(400, json={"error": {"message": "no structured output"}})
    server = Server(bad, no_schemas, good)
    assert stream_all(server.provider(), [user("hi")])[-1].content == [TextBlock(text="fine")]

    server = Server(bad, no_schemas, bad, no_schemas, bad, no_schemas)
    with pytest.raises(ProviderError, match="isn't a JSON object"):
        stream_all(server.provider(), [user("hi")])


def test_busy_servers_are_retried_and_errors_explained() -> None:
    server = Server(
        httpx.Response(429, json={"error": {"message": "slow down"}}),
        sse(delta(content="ok"), finish("stop")),
    )
    assert stream_all(server.provider(), [user("hi")])[-1].content == [TextBlock(text="ok")]

    server = Server(httpx.Response(404, json={"error": {"message": "model 'qwen9' not found"}}))
    with pytest.raises(ProviderError, match="zwans models ollama"):
        stream_all(server.provider("qwen9"), [user("hi")])

    server = Server(httpx.Response(401, text="no"))
    with pytest.raises(ProviderError, match="API key"):
        stream_all(server.provider(), [user("hi")])


def test_a_server_that_isnt_running_says_what_to_check() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    provider = OpenAICompatProvider(
        Endpoint(name="ollama", base_url="http://localhost:11434/v1", hint="Is Ollama running?"),
        "qwen3:8b",
        transport=httpx.MockTransport(refuse),
    )
    with pytest.raises(ProviderError, match=r"Couldn't reach ollama.*Is Ollama running"):
        stream_all(provider, [user("hi")])


def test_the_conversation_is_translated_and_claudes_own_blocks_left_out() -> None:
    image = ImageBlock(source=ImageSource(media_type="image/png", data="iVBOR"))
    messages = [
        Message(role="user", content=[TextBlock(text="What's this?"), image]),
        Message(
            role="assistant",
            content=[
                RawBlock(type="thinking", data={"type": "thinking", "thinking": "hm"}),
                TextBlock(text="Let me look."),
                ToolUseBlock(id="t1", name="Read", input={"path": "shot.png"}),
                ToolUseBlock(id="t2", name="Bash", input={"command": "false"}),
            ],
        ),
        Message(
            role="user",
            content=[
                ToolResultBlock(tool_use_id="t1", content=[TextBlock(text="An image:"), image]),
                ToolResultBlock(tool_use_id="t2", content="exit 1", is_error=True),
            ],
        ),
        Message(role="assistant", content=[RawBlock(type="thinking", data={})]),  # nothing to send
        Message(role="user", content=[TextBlock(text="Thanks")]),
    ]
    out = chat_messages("S", messages)
    data_url = "data:image/png;base64,iVBOR"
    assert out == [
        {"role": "system", "content": "S"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What's this?"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
        {
            "role": "assistant",
            "content": "Let me look.",
            "tool_calls": [
                {
                    "id": "t1",
                    "type": "function",
                    "function": {"name": "Read", "arguments": '{"path": "shot.png"}'},
                },
                {
                    "id": "t2",
                    "type": "function",
                    "function": {"name": "Bash", "arguments": '{"command": "false"}'},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "t1", "content": "An image:\n[image]"},
        {"role": "tool", "tool_call_id": "t2", "content": "Error: exit 1"},
        # Tool messages hold only text, so a result's images follow them.
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": data_url}}]},
        {"role": "user", "content": "Thanks"},
    ]


def test_model_names_say_where_they_run() -> None:
    assert split("claude-opus-5-5") == ("anthropic", "claude-opus-5-5")
    assert split("anthropic/claude-opus-5-5") == ("anthropic", "claude-opus-5-5")
    assert split("openrouter/qwen/qwen3-coder") == ("openrouter", "qwen/qwen3-coder")
    assert split("ollama/qwen3-coder:30b") == ("ollama", "qwen3-coder:30b")
    assert split("qwen3") == (None, "qwen3")
    assert canonical("anthropic/claude-haiku-5-5") == "claude-haiku-5-5"
    assert is_known("claude-opus-5-5") and is_known("ollama/anything")
    assert not is_known("claude-opus-9") and not is_known("qwen3")


def test_resolving_checks_the_provider_and_its_key() -> None:
    config = Config()
    assert resolve("claude-opus-5-5", config, KEY).provider == "anthropic"
    with pytest.raises(ModelError, match="ANTHROPIC_API_KEY"):
        resolve("claude-opus-5-5", config, {})
    local = resolve("ollama/qwen3:8b", config, {})  # no key needed
    assert (local.provider, local.model_id, local.name) == ("ollama", "qwen3:8b", "ollama/qwen3:8b")
    with pytest.raises(ModelError, match="OPENROUTER_API_KEY"):
        resolve("openrouter/qwen/qwen3-coder", config, {})
    assert resolve("openrouter/x/y", config, {"OPENROUTER_API_KEY": "k"}).model_id == "x/y"
    with pytest.raises(ModelError, match="no provider called 'nope'"):
        resolve("nope/model", config, {})
    with pytest.raises(ModelError, match=r"doesn't say where it runs.*ollama/qwen3"):
        resolve("qwen3", config, {})


def test_the_config_adds_providers_and_changes_built_in_ones() -> None:
    config = Config(
        providers={
            "runpod": ProviderConfig(
                base_url="https://abc-8000.proxy.runpod.net/v1",
                api_key_env="RUNPOD_KEY",
                models=["Qwen/Qwen3-Coder-30B"],
                context_window=65_536,
                prices={"Qwen/Qwen3-Coder-30B": (0.2, 0.8)},
            ),
            "ollama": ProviderConfig(context_window=32_768),
            "broken": ProviderConfig(models=["x"]),
        }
    )
    found = providers(config)
    assert found["runpod"].local is False and found["ollama"].local is True
    assert found["ollama"].context_window == 32_768
    assert found["ollama"].hint  # the preset's hint stays, since base_url is the preset's
    with pytest.raises(ModelError, match="RUNPOD_KEY"):
        resolve("runpod/Qwen/Qwen3-Coder-30B", config, {})
    assert resolve("runpod/m", config, {"RUNPOD_KEY": "k"}).context_window == 65_536
    with pytest.raises(ModelError, match=r"\[providers.broken\] in the config needs a base_url"):
        resolve("broken/x", config, {})

    register_prices(config)
    assert pricing.price_of("ollama/anything") == pricing.FREE  # runs on this machine
    price = pricing.price_of("runpod/Qwen/Qwen3-Coder-30B")
    assert price is not None and (price.input, price.output) == (0.2, 0.8)
    assert pricing.price_of("openrouter/unpriced") is None


def test_listing_asks_local_servers_and_skips_remote_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_list(endpoint: Endpoint, timeout: float = 3.0) -> list[str]:
        if endpoint.name == "ollama":
            return ["nomic-embed-text:latest", "qwen3:8b"]
        raise ProviderError("refused")

    monkeypatch.setattr("zwans.providers.catalog.list_models", fake_list)
    listings = {item.provider: item for item in asyncio.run(list_all(Config(), KEY))}
    assert listings["anthropic"].ready and "claude-opus-5-5" in listings["anthropic"].models
    assert listings["ollama"].models == ["ollama/qwen3:8b"] and listings["ollama"].ready
    assert listings["lmstudio"].note == "not running"
    assert listings["openrouter"].note == "set OPENROUTER_API_KEY"
    with pytest.raises(ModelError):
        asyncio.run(list_all(Config(), KEY, only="nope"))


def fakes() -> tuple[Callable[[Resolved], Any], dict[str, Any]]:
    made: dict[str, Any] = {}

    def make(resolved: Resolved) -> Any:
        backend = FakeProvider(
            [ModelResponse(content=[TextBlock(text=resolved.provider)], stop_reason="end_turn")]
        )
        made[resolved.provider] = backend
        return backend

    return make, made


def test_the_router_switches_between_claude_and_other_providers() -> None:
    config = Config(providers={"ollama": ProviderConfig(context_window=10_000)})
    make, made = fakes()
    router = ModelRouter(config, KEY, "claude-sonnet-5-5", make_backend=make)
    assert router.model == "claude-sonnet-5-5" and router.context_window is None
    compactor = Compactor(router, threshold=200_000)
    assert compactor.threshold == 200_000

    router.set_model("ollama/qwen3:8b")
    assert router.model == "ollama/qwen3:8b" and made["ollama"].model == "qwen3:8b"
    assert compactor.threshold == 8_000  # 80% of the smaller model's context

    with pytest.raises(ModelError):
        router.set_model("openrouter/x")  # no key: the current model stays
    assert router.model == "ollama/qwen3:8b"

    router.set_model("anthropic/claude-haiku-5-5")
    assert router.model == "claude-haiku-5-5" and set(made) == {"anthropic", "ollama"}


def test_a_whole_turn_with_a_tool_call_runs_on_an_openai_compatible_model(
    ctx: ToolContext, tmp_path: Path
) -> None:
    server = Server(
        sse(
            delta(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_1",
                        "function": {
                            "name": "Write",
                            "arguments": json.dumps({"path": "hello.txt", "content": "hello\n"}),
                        },
                    }
                ]
            ),
            finish("tool_calls"),
        ),
        sse(delta(content="Wrote hello.txt."), finish("stop"), usage(50, 5)),
    )
    router = ModelRouter(
        Config(), {}, "ollama/qwen3:8b", make_backend=lambda resolved: server.provider()
    )
    messages = [user("Write hello.txt")]

    events = asyncio.run(collect(run_turn(router, [WriteTool()], messages, ctx)))

    assert (tmp_path / "hello.txt").read_text() == "hello\n"
    assert any(isinstance(e, ToolResult) and not e.is_error for e in events)
    assert isinstance(events[-1], TurnEnded) and events[-1].stop_reason == "end_turn"
    second = server.bodies[1]["messages"]
    assert second[-2]["tool_calls"][0]["id"] == "call_1"
    assert second[-1]["role"] == "tool" and second[-1]["tool_call_id"] == "call_1"
