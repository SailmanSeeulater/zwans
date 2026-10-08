import anthropic
import httpx2
from pydantic import BaseModel, Field

from zwans.config import Credential
from zwans.messages import Message, RawBlock, TextBlock, ToolResultBlock, ToolUseBlock
from zwans.providers.anthropic import (
    AnthropicProvider,
    convert_content,
    describe_api_error,
    message_param,
    tool_param,
)
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


def user_message(text: str) -> Message:
    return Message(role="user", content=[TextBlock(text=text)])
