"""Help for models that make small mistakes: a turn sent back when its reply left the work
undone, tool errors that say what the tool takes, and where a missing file may be."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from helpers import collect, needs_rg, user

from zwans.config import Config
from zwans.events import HookReported, ToolResult, TurnEnded
from zwans.followthrough import (
    ANNOUNCED,
    LOCAL_FOLLOW_THROUGH,
    ONLY_SHOWN,
    announces_a_step,
    follow_through_for,
    unfinished,
)
from zwans.loop import run_turn
from zwans.messages import TextBlock, ToolUseBlock
from zwans.providers.base import ModelResponse
from zwans.providers.fake import FakeProvider
from zwans.tools.base import ToolContext
from zwans.tools.bash import BashTool
from zwans.tools.edit import EditTool
from zwans.tools.glob import GlobTool
from zwans.tools.grep import GrepTool
from zwans.tools.hints import missing_path
from zwans.tools.read import ReadTool
from zwans.tools.write import WriteTool


def says(text: str) -> ModelResponse:
    return ModelResponse(content=[TextBlock(text=text)], stop_reason="end_turn")


def calls(name: str, **args: Any) -> ModelResponse:
    return ModelResponse(
        content=[ToolUseBlock(id=f"call_{name}", name=name, input=args)], stop_reason="tool_use"
    )


def result_of(events: list[Any]) -> ToolResult:
    return next(event for event in events if isinstance(event, ToolResult))


# -- what counts as leaving the work undone


@pytest.mark.parametrize(
    "reply",
    [
        "I have read the file and confirmed it is a stub. I will now implement parse_duration.",
        "The import is circular. Let's fix this by moving the helper into util.py.",
        "Based on the code in search.py, it imports Store. Now, I'll update the import.",
        "It seems users.py is not available. Let me proceed by focusing on the utils module.",
        "I'm going to rename the function next:",
    ],
)
def test_a_reply_that_ends_by_saying_what_comes_next_announces_a_step(reply: str) -> None:
    assert announces_a_step(reply)


@pytest.mark.parametrize(
    "reply",
    [
        "Done. The test passes now.",
        "I fixed average() to divide by the number of values. Let me know if you want more.",
        "The tests pass. If you'd like, I'll also add a test for negative numbers.",
        "Which of the two files should I change?",
        "I will need the API key before I can go on. Where is it kept?",
        "",
    ],
)
def test_a_finished_reply_an_offer_or_a_question_doesnt(reply: str) -> None:
    assert not announces_a_step(reply)


def test_code_shown_without_a_change_is_unfinished_only_when_nothing_was_changed() -> None:
    code = "def average(xs):\n    total = sum(xs)\n    return total / len(xs)"
    shown = f"Here is the fix:\n```python\n{code}\n```"

    assert unfinished(shown, changed=False) == ONLY_SHOWN
    assert unfinished(shown, changed=True) is None
    assert unfinished("Run it with:\n```\npytest -q\n```", changed=False) is None


# -- the loop sends the model back


def test_a_turn_that_only_announces_its_next_step_is_sent_back_to_take_it(
    ctx: ToolContext, tmp_path: Path
) -> None:
    provider = FakeProvider(
        [
            says("I will now write the file."),
            calls("Write", path="out.txt", content="hi\n"),
            says("Done."),
        ]
    )
    messages = [user("Write hi to out.txt")]

    events = asyncio.run(
        collect(run_turn(provider, [WriteTool()], messages, ctx, follow_through=2))
    )

    assert (tmp_path / "out.txt").read_text() == "hi\n"
    assert HookReported(event="follow_through", command="", message=ANNOUNCED) in events
    assert [e.stop_reason for e in events if isinstance(e, TurnEnded)] == ["end_turn"]
    # The note went to the model as the user's next message.
    assert provider.requests[1][-1].content == [TextBlock(text=ANNOUNCED)]


def test_it_is_sent_back_no_more_often_than_the_setting_allows(ctx: ToolContext) -> None:
    provider = FakeProvider([says("I will now do it."), says("Let me do it."), says("I'll do it.")])

    events = asyncio.run(
        collect(run_turn(provider, [WriteTool()], [user("Do it")], ctx, follow_through=2))
    )

    assert sum(isinstance(e, HookReported) for e in events) == 2
    assert isinstance(events[-1], TurnEnded)


def test_by_default_and_without_tools_nobody_is_sent_back(ctx: ToolContext) -> None:
    default = FakeProvider([says("I will now do it.")])
    chat = FakeProvider([says("I will now explain.")])

    by_default = asyncio.run(collect(run_turn(default, [WriteTool()], [user("Do it")], ctx)))
    in_a_chat = asyncio.run(collect(run_turn(chat, [], [user("Hi")], ctx, follow_through=2)))

    assert not any(isinstance(e, HookReported) for e in by_default + in_a_chat)


def test_local_models_are_sent_back_unless_the_setting_says_otherwise() -> None:
    class Info:
        local = True

    class Resolved:
        info: Any = Info()

    class Router(FakeProvider):
        resolved = Resolved()

    local, claude = Router([]), FakeProvider([])

    assert follow_through_for(Config(), local)() == LOCAL_FOLLOW_THROUGH
    assert follow_through_for(Config(), claude)() == 0
    assert follow_through_for(Config(follow_through=0), local)() == 0
    assert follow_through_for(Config(follow_through=1), claude)() == 1


# -- errors that help the next try


def test_read_takes_an_offset_of_0_as_the_first_line(ctx: ToolContext, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    provider = FakeProvider([calls("Read", path="a.txt", offset=0, limit=1), says("Read.")])

    events = asyncio.run(collect(run_turn(provider, [ReadTool()], [user("Read it")], ctx)))

    result = result_of(events)
    assert not result.is_error
    assert result.content.startswith("     1\tone")
    assert "Showing lines 1-1 of 2" in result.content


def test_input_that_fits_another_tool_says_which_and_what_this_one_takes(
    ctx: ToolContext,
) -> None:
    provider = FakeProvider([calls("Write", command="pytest -q"), says("Oh.")])

    events = asyncio.run(
        collect(run_turn(provider, [WriteTool(), BashTool()], [user("Run the tests")], ctx))
    )

    result = result_of(events)
    assert result.is_error
    assert result.content.startswith(
        "Invalid input for Write: path is required; content is required; command isn't a "
        "parameter. Write takes path, content."
    )
    assert "That input fits Bash: call Bash instead." in result.content
    assert "pydantic" not in result.content


def test_an_edit_with_nothing_to_replace_points_to_write(ctx: ToolContext, tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    provider = FakeProvider(
        [calls("Edit", path="a.py", old_string="", new_string="y = 2\n"), says("Oh.")]
    )

    events = asyncio.run(collect(run_turn(provider, [EditTool()], [user("Add y")], ctx)))

    result = result_of(events)
    assert result.is_error
    assert "old_string is empty" in result.content and "use Write" in result.content
    assert (tmp_path / "a.py").read_text() == "x = 1\n"


def test_reading_a_missing_file_reads_the_only_one_of_that_name(
    ctx: ToolContext, tmp_path: Path
) -> None:
    (tmp_path / "timer").mkdir()
    (tmp_path / "timer" / "durations.py").write_text("UNITS = {}\n")
    provider = FakeProvider([calls("Read", path="durations.py"), says("Ah.")])

    events = asyncio.run(collect(run_turn(provider, [ReadTool()], [user("Read it")], ctx)))

    result = result_of(events)
    assert not result.is_error
    assert result.content == (
        "(There is no durations.py. This is timer/durations.py, the only file of that name: "
        "use that path from now on.)\n     1\tUNITS = {}"
    )


def test_a_missing_file_says_where_files_of_that_name_are(ctx: ToolContext, tmp_path: Path) -> None:
    for folder in ("timer", "clock"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "durations.py").write_text("")
    provider = FakeProvider(
        [
            calls("Read", path="durations.py"),
            calls("Edit", path="x/durations.py", old_string="a", new_string="b"),
            says("Ah."),
        ]
    )

    events = asyncio.run(
        collect(run_turn(provider, [ReadTool(), EditTool()], [user("Read it")], ctx))
    )

    results = [event for event in events if isinstance(event, ToolResult)]
    hint = "A file called durations.py is at clock/durations.py or timer/durations.py."
    assert [r.content for r in results] == [
        f"No such file or folder: durations.py. {hint}",
        f"No such file or folder: x/durations.py. {hint}",
    ]


def test_a_missing_file_suggests_a_close_name_or_lists_the_folder(tmp_path: Path) -> None:
    (tmp_path / "calc.py").write_text("")
    (tmp_path / "test_calc.py").write_text("")
    (tmp_path / ".git").mkdir()
    (tmp_path / "docs").mkdir()

    assert missing_path(tmp_path, tmp_path / "test_calcs.py") == (
        "Did you mean test_calc.py or calc.py?"
    )
    assert missing_path(tmp_path, tmp_path / "tests" / "zzz.toml") == (
        "The workspace root holds: calc.py, docs/, test_calc.py."
    )
    assert missing_path(tmp_path, tmp_path / "docs" / "zzz.toml") == "docs/ is empty."
    assert missing_path(tmp_path, tmp_path.parent / "elsewhere.py") == ""


@needs_rg
def test_searching_a_folder_that_isnt_there_says_what_is(ctx: ToolContext, tmp_path: Path) -> None:
    (tmp_path / "test_calc.py").write_text("assert True\n")
    provider = FakeProvider(
        [
            calls("Grep", pattern="assert", path="tests"),
            ModelResponse(
                content=[
                    ToolUseBlock(id="g2", name="Glob", input={"pattern": "*.py", "path": "tests"})
                ],
                stop_reason="tool_use",
            ),
            says("Ah."),
        ]
    )

    events = asyncio.run(
        collect(run_turn(provider, [GrepTool(), GlobTool()], [user("Find the tests")], ctx))
    )

    results = [event for event in events if isinstance(event, ToolResult)]
    expected = "No such file or folder: tests. The workspace root holds: test_calc.py."
    assert [r.content for r in results] == [expected, expected]
