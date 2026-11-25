"""A model that repeats itself: the same call, coming back the same, with nothing changed
between, is told so, and a turn that keeps it up stops."""

import asyncio
from itertools import count
from pathlib import Path
from typing import Any

from helpers import collect, user

from zwans.config import Config
from zwans.events import ToolResult, TurnEnded
from zwans.loop import run_turn
from zwans.messages import TextBlock, ToolUseBlock
from zwans.providers.base import ModelResponse
from zwans.providers.fake import FakeProvider
from zwans.repeats import NOTE, Repeats
from zwans.tools.base import ToolContext
from zwans.tools.read import ReadTool
from zwans.tools.write import WriteTool

ids = count()


def calls(name: str, **args: Any) -> ModelResponse:
    call = ToolUseBlock(id=f"call_{next(ids)}", name=name, input=args)
    return ModelResponse(content=[TextBlock(text="Checking."), call], stop_reason="tool_use")


def says(text: str) -> ModelResponse:
    return ModelResponse(content=[TextBlock(text=text)], stop_reason="end_turn")


def call(name: str, **args: Any) -> ToolUseBlock:
    return ToolUseBlock(id="c", name=name, input=args)


def test_the_same_call_with_the_same_result_is_a_repeat_whatever_the_numbers_say() -> None:
    repeats = Repeats()
    tests = call("RunTests", path=".")

    assert not repeats.observe(tests, "1 passed in 0.01s", False, read_only=True)
    assert repeats.observe(tests, "1 passed in 0.03s", False, read_only=True)
    assert not repeats.observe(tests, "1 failed in 0.03s", False, read_only=True)
    assert not repeats.observe(call("RunTests", path="tests"), "1 failed", False, read_only=True)
    assert repeats.count == 1


def test_a_change_means_calls_after_it_can_find_something_new() -> None:
    repeats = Repeats()
    read = call("Read", path="a.py")
    repeats.observe(read, "x = 1", False, read_only=True)

    assert not repeats.observe(call("Edit", path="a.py"), "Replaced 1.", False, read_only=False)
    assert not repeats.observe(read, "x = 1", False, read_only=True)  # the edit came between
    assert repeats.observe(read, "x = 1", False, read_only=True)


def test_a_turn_that_keeps_repeating_is_told_then_stopped(ctx: ToolContext, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hi\n")
    script = [calls("Read", path="a.txt") for _ in range(5)] + [says("Done.")]
    provider = FakeProvider(script)

    events = asyncio.run(
        collect(run_turn(provider, [ReadTool()], [user("Check a.txt")], ctx, repeat_limit=3))
    )

    results = [e.content for e in events if isinstance(e, ToolResult)]
    assert len(results) == 4 and not results[0].endswith(NOTE)
    assert all(result.endswith(NOTE) for result in results[1:])
    ended = events[-1]
    assert isinstance(ended, TurnEnded) and ended.stop_reason == "repeating"
    assert ended.detail == "3 tool calls repeated earlier ones with the same results"
    assert len(provider.requests) == 4  # the fifth call was never asked for


def test_repeats_after_a_change_dont_count_and_0_never_checks(
    ctx: ToolContext, tmp_path: Path
) -> None:
    (tmp_path / "a.txt").write_text("hi\n")
    rewrite = calls("Write", path="a.txt", content="hi\n")
    script = [calls("Read", path="a.txt"), rewrite, calls("Read", path="a.txt"), says("Done.")]

    events = asyncio.run(
        collect(
            run_turn(
                FakeProvider(script),
                [ReadTool(), WriteTool()],
                [user("Check a.txt")],
                ctx,
                repeat_limit=1,
            )
        )
    )

    assert not any(e.content.endswith(NOTE) for e in events if isinstance(e, ToolResult))
    assert [e.stop_reason for e in events if isinstance(e, TurnEnded)] == ["end_turn"]

    again = [calls("Read", path="a.txt") for _ in range(3)] + [says("Done.")]
    unchecked = asyncio.run(
        collect(run_turn(FakeProvider(again), [ReadTool()], [user("Check")], ctx))
    )
    assert [e.stop_reason for e in unchecked if isinstance(e, TurnEnded)] == ["end_turn"]


def test_sessions_stop_at_three_repeats_unless_configured() -> None:
    assert Config().repeat_limit == 3
    assert Config(repeat_limit=0).repeat_limit == 0
