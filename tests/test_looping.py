import asyncio
from pathlib import Path

import pytest
from helpers import needs_bash

from zwans.budget import Budget, parse_dollars
from zwans.events import Event, LoopChecked, LoopEnded, TurnEnded, UsageUpdated
from zwans.looping import DEFAULT_ROUNDS, LoopSpec, parse_loop, run_loop
from zwans.messages import TextBlock, ToolUseBlock
from zwans.pricing import CostMeter
from zwans.providers.base import ModelResponse
from zwans.providers.fake import FakeProvider
from zwans.session import Session
from zwans.tools.base import ToolContext
from zwans.tools.write import WriteTool


def say(text: str, output_tokens: int = 0) -> ModelResponse:
    return ModelResponse(
        content=[TextBlock(text=text)],
        stop_reason="end_turn",
        output_tokens=output_tokens,
        model="claude-opus-5-5",
    )


def write(path: str, content: str) -> ModelResponse:
    call = ToolUseBlock(id=f"w-{path}", name="Write", input={"path": path, "content": content})
    return ModelResponse(content=[call], stop_reason="tool_use")


def test_loop_arguments_are_read_with_or_without_quotes_and_rounds() -> None:
    assert parse_loop("until pytest -q") == LoopSpec("pytest -q", "", DEFAULT_ROUNDS)
    assert parse_loop('8 until "npm test -- --run" fix the dates') == LoopSpec(
        "npm test -- --run", "fix the dates", 8
    )
    for wrong in ("", "pytest -q", "until", "0 until x", '"until x'):
        with pytest.raises(ValueError):
            parse_loop(wrong)


@needs_bash
def test_a_loop_sends_the_failure_back_until_the_check_passes(
    ctx: ToolContext, tmp_path: Path
) -> None:
    script = [
        say("Tried something."),  # turn 1 leaves the check failing
        write("done.txt", "yes"),
        say("Fixed."),  # turn 2 makes it pass
    ]
    provider = FakeProvider(script)
    seen: list[Event] = []
    session = Session(provider, [WriteTool()], ctx, "S", listeners=[seen.append])
    spec = LoopSpec(check="test -f done.txt || (echo missing done.txt; exit 3)", rounds=4)

    reason = asyncio.run(run_loop(session, ctx.executor, spec))

    assert reason == "passed" and (tmp_path / "done.txt").exists()
    checks = [e for e in seen if isinstance(e, LoopChecked)]
    assert [(c.round, c.passed, c.exit_code) for c in checks] == [
        (0, False, 3),
        (1, False, 3),
        (2, True, 0),
    ]
    first = provider.requests[0][-1].content[-1]
    again = provider.requests[1][-1].content[-1]
    assert isinstance(first, TextBlock) and "missing done.txt" in first.text
    assert isinstance(again, TextBlock) and "still fails (exit code 3), after turn 1" in again.text
    ended = [e for e in seen if isinstance(e, LoopEnded)]
    assert [e.reason for e in ended] == ["passed"] and "after 2 turns" in ended[0].detail


@needs_bash
def test_a_loop_gives_up_after_its_rounds_and_sends_nothing_when_already_passing(
    ctx: ToolContext,
) -> None:
    provider = FakeProvider([say("No."), say("Still no.")])
    session = Session(provider, [], ctx, "S", listeners=[])

    assert asyncio.run(run_loop(session, ctx.executor, LoopSpec("exit 1", rounds=2))) == "rounds"
    assert asyncio.run(run_loop(session, ctx.executor, LoopSpec("true"))) == "passed"
    assert len(provider.requests) == 2


@needs_bash
def test_a_spent_budget_stops_the_turn_and_the_loop_before_the_next_call(
    ctx: ToolContext,
) -> None:
    meter = CostMeter()
    seen: list[Event] = []
    provider = FakeProvider([say("Expensive.", output_tokens=200_000), say("Never sent.")])
    session = Session(provider, [], ctx, "S", listeners=[meter.on_event, seen.append])
    budget = Budget(meter, dollars=0.01)
    session.limit = budget.exceeded

    reason = asyncio.run(run_loop(session, ctx.executor, LoopSpec("exit 1", rounds=3)))

    assert reason == "budget"
    assert len(provider.requests) == 1
    ends = [e for e in seen if isinstance(e, TurnEnded)]
    assert ends[-1].stop_reason == "budget" and "budget spent" in ends[-1].detail
    assert any(isinstance(e, UsageUpdated) for e in seen)
    budget.dollars = None
    assert budget.exceeded() is None and "No budget" in budget.describe()


def test_dollars_are_read_as_people_type_them() -> None:
    assert parse_dollars("$2") == 2.0 and parse_dollars("0.50") == 0.5
    assert parse_dollars("off") is None and parse_dollars("") is None
    for wrong in ("two", "-1"):
        with pytest.raises(ValueError):
            parse_dollars(wrong)
