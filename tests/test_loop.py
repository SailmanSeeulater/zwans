import asyncio
import time

import pytest
from helpers import collect, needs_bash, user
from pydantic import BaseModel

from zwans.events import (
    Error,
    TextDelta,
    ToolCallRequested,
    ToolResult,
    TurnEnded,
    TurnStarted,
    UsageUpdated,
)
from zwans.loop import INTERRUPTED, run_turn
from zwans.messages import Message, TextBlock, ToolResultBlock, ToolUseBlock
from zwans.providers.base import ModelResponse
from zwans.providers.fake import FakeProvider
from zwans.tools.base import ToolContext, ToolOutput
from zwans.tools.bash import BashTool
from zwans.tools.read import ReadTool


class EchoInput(BaseModel):
    text: str


class EchoTool:
    name = "echo"
    description = "Return the given text unchanged."
    input_model = EchoInput
    read_only = True

    async def run(self, args: EchoInput, ctx: ToolContext) -> ToolOutput:
        return ToolOutput(content=args.text)


class ProbeInput(BaseModel):
    pass


class ProbeTool:
    """Records how many of its calls were running at the same moment."""

    description = "A test tool."
    input_model = ProbeInput

    def __init__(self, name: str, read_only: bool) -> None:
        self.name = name
        self.read_only = read_only
        self.running = 0
        self.most_at_once = 0

    async def run(self, args: ProbeInput, ctx: ToolContext) -> ToolOutput:
        self.running += 1
        self.most_at_once = max(self.most_at_once, self.running)
        await asyncio.sleep(0.05)
        self.running -= 1
        return ToolOutput(content="done")


def test_one_full_turn(ctx: ToolContext) -> None:
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
    messages = [user("Echo hi")]

    events = asyncio.run(collect(run_turn(provider, [EchoTool()], messages, ctx)))

    assert events == [
        TurnStarted(prompt="Echo hi"),
        TextDelta(text="Let me echo that."),
        UsageUpdated(input_tokens=0, output_tokens=0),
        ToolCallRequested(call_id="call_1", name="echo", args={"text": "hi"}),
        ToolResult(call_id="call_1", content="hi"),
        TextDelta(text="The tool said hi."),
        UsageUpdated(input_tokens=0, output_tokens=0),
        TurnEnded(stop_reason="end_turn"),
    ]
    # The second model call received the tool's result.
    assert provider.requests[1][-1] == Message(
        role="user", content=[ToolResultBlock(tool_use_id="call_1", content="hi")]
    )


def test_unknown_tool_goes_back_to_the_model_as_an_error(ctx: ToolContext) -> None:
    provider = FakeProvider(
        [
            ModelResponse(
                content=[ToolUseBlock(id="call_1", name="missing", input={})],
                stop_reason="tool_use",
            ),
            ModelResponse(content=[TextBlock(text="Sorry.")], stop_reason="end_turn"),
        ]
    )

    events = asyncio.run(collect(run_turn(provider, [], [user("Use a tool")], ctx)))

    assert ToolResult(call_id="call_1", content="Unknown tool: missing", is_error=True) in events


def test_tool_failures_go_back_to_the_model_as_errors(ctx: ToolContext) -> None:
    provider = FakeProvider(
        [
            ModelResponse(
                content=[ToolUseBlock(id="call_1", name="Read", input={"path": "missing.txt"})],
                stop_reason="tool_use",
            ),
            ModelResponse(
                content=[TextBlock(text="That file doesn't exist.")], stop_reason="end_turn"
            ),
        ]
    )

    events = asyncio.run(collect(run_turn(provider, [ReadTool()], [user("Read it")], ctx)))

    result = next(event for event in events if isinstance(event, ToolResult))
    assert result.is_error
    assert "missing.txt" in result.content


def test_read_only_calls_run_together_and_writes_one_at_a_time(ctx: ToolContext) -> None:
    look = ProbeTool("look", read_only=True)
    change = ProbeTool("change", read_only=False)
    calls = [ToolUseBlock(id=f"look_{i}", name="look", input={}) for i in range(3)]
    calls += [ToolUseBlock(id=f"change_{i}", name="change", input={}) for i in range(2)]
    provider = FakeProvider(
        [
            ModelResponse(content=calls, stop_reason="tool_use"),
            ModelResponse(content=[TextBlock(text="Done.")], stop_reason="end_turn"),
        ]
    )

    asyncio.run(collect(run_turn(provider, [look, change], [user("Go")], ctx)))

    assert look.most_at_once == 3
    assert change.most_at_once == 1


def test_a_cut_off_response_still_answers_every_tool_call(ctx: ToolContext) -> None:
    provider = FakeProvider(
        [
            ModelResponse(
                content=[ToolUseBlock(id="call_1", name="echo", input={"text": "hal"})],
                stop_reason="max_tokens",
            )
        ]
    )
    messages = [user("Echo a lot")]

    events = asyncio.run(collect(run_turn(provider, [EchoTool()], messages, ctx)))

    assert events[-1] == TurnEnded(stop_reason="max_tokens")
    result = messages[-1].content[0]
    assert isinstance(result, ToolResultBlock)
    assert result.tool_use_id == "call_1"
    assert result.is_error


def test_a_provider_failure_ends_the_turn_with_an_error(ctx: ToolContext) -> None:
    events = asyncio.run(collect(run_turn(FakeProvider([]), [], [user("Hi")], ctx)))

    assert isinstance(events[-1], Error)


@needs_bash
def test_ctrl_c_stops_the_command_and_the_session_carries_on(ctx: ToolContext) -> None:
    provider = FakeProvider(
        [
            ModelResponse(
                content=[ToolUseBlock(id="call_1", name="Bash", input={"command": "sleep 30"})],
                stop_reason="tool_use",
            ),
            ModelResponse(content=[TextBlock(text="Okay.")], stop_reason="end_turn"),
        ]
    )
    messages = [user("Wait a while")]

    async def press_ctrl_c_after_a_second() -> None:
        turn = asyncio.create_task(collect(run_turn(provider, [BashTool()], messages, ctx)))
        await asyncio.sleep(1)
        turn.cancel()  # what Ctrl+C does in the CLI
        with pytest.raises(asyncio.CancelledError):
            await turn

    started = time.monotonic()
    asyncio.run(press_ctrl_c_after_a_second())

    assert time.monotonic() - started < 10  # the 30-second sleep was stopped
    assert messages[-1] == Message(
        role="user",
        content=[ToolResultBlock(tool_use_id="call_1", content=INTERRUPTED, is_error=True)],
    )
    messages.append(user("Never mind"))
    events = asyncio.run(collect(run_turn(provider, [BashTool()], messages, ctx)))
    assert events[-1] == TurnEnded(stop_reason="end_turn")
