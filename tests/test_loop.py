import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import BaseModel

from zwans.events import (
    Event,
    TextDelta,
    ToolCallRequested,
    ToolResult,
    TurnEnded,
    TurnStarted,
    UsageUpdated,
)
from zwans.loop import run_turn
from zwans.messages import Message, TextBlock, ToolResultBlock, ToolUseBlock
from zwans.providers.base import ModelResponse
from zwans.providers.fake import FakeProvider
from zwans.tools.base import ToolContext, ToolOutput


class EchoInput(BaseModel):
    text: str


class EchoTool:
    name = "echo"
    description = "Return the given text unchanged."
    input_model = EchoInput
    read_only = True

    async def run(self, args: EchoInput, ctx: ToolContext) -> ToolOutput:
        return ToolOutput(content=args.text)


async def collect(events: AsyncIterator[Event]) -> list[Event]:
    return [event async for event in events]


def test_one_full_turn(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            ModelResponse(
                content=[
                    TextBlock(text="Let me echo that."),
                    ToolUseBlock(id="call_1", name="echo", input={"text": "hi"}),
                ],
                stop_reason="tool_use",
            ),
            ModelResponse(content=[TextBlock(text="The tool said hi.")], stop_reason="end_turn"),
        ]
    )
    messages = [Message(role="user", content=[TextBlock(text="Echo hi")])]

    events = asyncio.run(
        collect(run_turn(provider, [EchoTool()], messages, ToolContext(cwd=tmp_path)))
    )

    assert events == [
        TurnStarted(),
        UsageUpdated(input_tokens=0, output_tokens=0),
        TextDelta(text="Let me echo that."),
        ToolCallRequested(call_id="call_1", name="echo", args={"text": "hi"}),
        ToolResult(call_id="call_1", content="hi"),
        UsageUpdated(input_tokens=0, output_tokens=0),
        TextDelta(text="The tool said hi."),
        TurnEnded(stop_reason="end_turn"),
    ]
    # The second model call received the tool's result.
    assert provider.requests[1][-1] == Message(
        role="user", content=[ToolResultBlock(tool_use_id="call_1", content="hi")]
    )


def test_unknown_tool_goes_back_to_the_model_as_an_error(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            ModelResponse(
                content=[ToolUseBlock(id="call_1", name="missing", input={})],
                stop_reason="tool_use",
            ),
            ModelResponse(content=[TextBlock(text="Sorry.")], stop_reason="end_turn"),
        ]
    )
    messages = [Message(role="user", content=[TextBlock(text="Use a tool")])]

    events = asyncio.run(collect(run_turn(provider, [], messages, ToolContext(cwd=tmp_path))))

    assert ToolResult(call_id="call_1", content="Unknown tool: missing", is_error=True) in events
