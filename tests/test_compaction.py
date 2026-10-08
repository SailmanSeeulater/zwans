import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from helpers import user
from pydantic import BaseModel

from zwans.context.compaction import SUMMARY_HEADER, Compactor
from zwans.context.tokens import approx_tokens
from zwans.events import ContextCompacted, Event, TextDelta, ThinkingDelta, TurnEnded, UsageUpdated
from zwans.messages import Message, RawBlock, TextBlock, ToolResultBlock, ToolUseBlock
from zwans.providers.base import ModelResponse
from zwans.session import Session
from zwans.tools.base import Tool, ToolContext, ToolOutput

THINKING = RawBlock(type="thinking", data={"type": "thinking", "thinking": "", "signature": "s"})


class Summarizer:
    """Answers every summary request with the same notes."""

    def __init__(self) -> None:
        self.requests = 0

    async def stream(
        self, system: str, messages: Sequence[Message], tools: Sequence[Tool[Any]]
    ) -> AsyncIterator[TextDelta | ThinkingDelta | ModelResponse]:
        self.requests += 1
        yield ModelResponse(
            content=[TextBlock(text="Notes: lines were being appended to log.txt.")],
            stop_reason="end_turn",
            input_tokens=1_000,
            output_tokens=50,
        )

    async def aclose(self) -> None:
        pass


def tool_round(n: int) -> list[Message]:
    """One step of a tool loop: the model thinks and calls a tool, then the result comes back."""
    call = ToolUseBlock(id=f"call_{n}", name="Append", input={"line": f"line {n}"})
    return [
        Message(role="assistant", content=[THINKING, call]),
        Message(role="user", content=[ToolResultBlock(tool_use_id=f"call_{n}", content="ok")]),
    ]


def test_the_estimate_is_the_api_count_plus_a_guess_for_newer_messages() -> None:
    compactor = Compactor(Summarizer(), threshold=10_000)
    messages = [user("Go"), *tool_round(1)]
    response = ModelResponse(content=[], stop_reason="tool_use", input_tokens=900, output_tokens=40)

    compactor.observe(response, message_count=2)

    assert compactor.estimate(messages) == 940 + approx_tokens(messages[2:])


def test_nothing_happens_below_the_threshold() -> None:
    compactor = Compactor(Summarizer(), threshold=10_000)
    messages = [user("Go"), *tool_round(1), *tool_round(2)]

    assert asyncio.run(compactor.maybe_compact(messages)) == []
    assert len(messages) == 5


def test_compaction_summarizes_old_messages_and_keeps_recent_ones_without_thinking() -> None:
    summarizer = Summarizer()
    compactor = Compactor(summarizer, threshold=0, keep_messages=4)
    messages = [user("Append lines")]
    for n in range(1, 6):
        messages += tool_round(n)

    events = asyncio.run(compactor.maybe_compact(messages))

    assert [type(event) for event in events] == [ContextCompacted, UsageUpdated]
    first = messages[0].content[0]
    assert isinstance(first, TextBlock)
    assert first.text.startswith(SUMMARY_HEADER)
    assert messages[1].role == "assistant"  # kept part starts with the call, not its result
    assert len(messages) == 1 + 4
    assert not any(isinstance(block, RawBlock) for m in messages for block in m.content)


class AppendInput(BaseModel):
    line: str


class AppendTool:
    name = "Append"
    description = "Append a line to log.txt."
    input_model = AppendInput
    read_only = False

    async def run(self, args: AppendInput, ctx: ToolContext) -> ToolOutput:
        try:
            old = await ctx.executor.read_bytes("log.txt")
        except FileNotFoundError:
            old = b""
        await ctx.executor.write_bytes("log.txt", old + f"{args.line}\n".encode())
        return ToolOutput(content="ok")


class Worker:
    """Each turn: think, append the line the user asked for, then say it's done.

    It reports input tokens from the real size of what it was sent, as the API would, so
    the conversation keeps growing until compaction shrinks it.
    """

    async def stream(
        self, system: str, messages: Sequence[Message], tools: Sequence[Tool[Any]]
    ) -> AsyncIterator[TextDelta | ThinkingDelta | ModelResponse]:
        tokens = 2_000 + approx_tokens(messages)  # 2,000 stands in for system prompt and tools
        last = messages[-1].content[-1]
        if isinstance(last, TextBlock) and last.text.startswith("Add line"):
            number = last.text.removeprefix("Add line ")
            call = ToolUseBlock(id=f"call_{number}", name="Append", input={"line": number})
            yield ModelResponse(
                content=[THINKING, call], stop_reason="tool_use", input_tokens=tokens
            )
        else:
            yield ModelResponse(
                content=[TextBlock(text="Added.")], stop_reason="end_turn", input_tokens=tokens
            )

    async def aclose(self) -> None:
        pass


def assert_valid(messages: list[Message]) -> None:
    """The rules the API enforces: start with the user, and answer every tool call next."""
    assert messages[0].role == "user"
    for index, message in enumerate(messages):
        calls = {b.id for b in message.content if isinstance(b, ToolUseBlock)}
        if calls:
            answers = messages[index + 1].content
            assert {b.tool_use_id for b in answers if isinstance(b, ToolResultBlock)} == calls
        for block in message.content:
            if isinstance(block, ToolResultBlock):
                previous = messages[index - 1].content
                assert any(
                    isinstance(b, ToolUseBlock) and b.id == block.tool_use_id for b in previous
                )


def test_a_200_turn_session_survives_compactions_and_finishes(
    tmp_path: Path, ctx: ToolContext
) -> None:
    """Phase 2's "Done when": a 200-turn session compacts at least twice and still works."""
    events: list[Event] = []
    summarizer = Summarizer()
    session = Session(
        provider=Worker(),
        tools=[AppendTool()],
        ctx=ctx,
        system="",
        listeners=[events.append],
        compactor=Compactor(summarizer, threshold=6_000, keep_messages=8),
    )

    async def two_hundred_turns() -> list[str]:
        return [await session.send(f"Add line {n}") for n in range(1, 201)]

    stop_reasons = asyncio.run(two_hundred_turns())

    compactions = [event for event in events if isinstance(event, ContextCompacted)]
    assert len(compactions) >= 2
    assert summarizer.requests == len(compactions)
    assert stop_reasons == ["end_turn"] * 200
    assert_valid(session.messages)
    assert len(session.messages) < 200  # it stayed bounded instead of growing to 800
    lines = (tmp_path / "log.txt").read_text(encoding="utf-8").splitlines()
    assert lines == [str(n) for n in range(1, 201)]
    assert sum(isinstance(event, TurnEnded) for event in events) == 200
