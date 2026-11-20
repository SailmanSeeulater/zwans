"""The web UI's demo: a recorded session replayed with no API key and no API calls.

The model's side is scripted; everything else is real. The tools run in a fresh copy of a
small project (calc/, a calculator with one failing test), the policy decides what may run,
and the events, costs and transcript come out exactly as they would with Claude.

Turn 1 finds and fixes the bug. Turn 2 adds a test, and starts with a compaction, because
the demo compacts at a few thousand tokens instead of 200,000 so you can watch one happen.
The token counts are made up, but in proportion to what Claude Haiku 5.5 reports for this
work, and priced as that model.
"""

import shutil
import tempfile
from pathlib import Path
from typing import Any

from zwans.config import Config
from zwans.messages import RawBlock, TextBlock, ToolUseBlock
from zwans.providers.base import ModelResponse
from zwans.providers.fake import FakeProvider

PROJECT = Path(__file__).parent / "calc"
MODEL = "claude-haiku-5-5"
COMPACT_AT = 6_400
KEEP_MESSAGES = 4
PACE = 0.045  # seconds between streamed pieces of text

PROMPTS = (
    "One of the tests fails. Find out why and fix it.",
    "Add a test that dividing by zero raises an error.",
)
NOTE = (
    "Demo: the model's replies are a script, so nothing is sent to Claude and nothing is "
    f"charged. The tools really run, in a copy of a small project. It compacts at "
    f"{COMPACT_AT:,} tokens so you can see a compaction; the default is 200,000."
)

TEST = "python3 -m unittest -q"
BUG = "        right, tokens = _expression(tokens)\n        value = value + right"
FIX = "        right, tokens = _term(tokens)\n        value = value + right"
LAST_TEST = """    def test_negative_numbers(self) -> None:
        self.assertEqual(evaluate("-2 * 3"), -6)
"""
NEW_TEST = (
    LAST_TEST
    + """
    def test_dividing_by_zero_raises(self) -> None:
        with self.assertRaises(ZeroDivisionError):
            evaluate("1 / 0")
"""
)


def copy_project() -> Path:
    """A fresh copy of the demo project, in a temporary folder."""
    folder = Path(tempfile.mkdtemp(prefix="zwans-demo-")) / "calc"
    shutil.copytree(PROJECT, folder, ignore=shutil.ignore_patterns("__pycache__"))
    return folder


def config(base: Config) -> Config:
    """The server's config, with what the demo needs: commands run here, not in a
    container, and compaction comes early."""
    return base.model_copy(
        update={
            "executor": "local",
            "model": MODEL,
            "compact_at": COMPACT_AT,
            "keep_messages": KEEP_MESSAGES,
            "mcp_servers": {},
        }
    )


def provider(pace: float = PACE) -> FakeProvider:
    return FakeProvider(script(), pace=pace)


def script() -> list[ModelResponse]:
    return _numbered(
        [
            # Turn 1: find and fix the bug.
            _reply(
                "I'll start by running the tests to see what fails.",
                [_todos(0), _call("Bash", command=TEST)],
                usage=(310, 0, 4_180, 96),
            ),
            _reply(
                "One failure: `10 - 4 - 3` comes out as 9 instead of 3. "
                "Let me look at the files and the parser.",
                [_call("Glob", pattern="*.py"), _call("Read", path="calc.py")],
                usage=(14, 4_480, 342, 120),
            ),
            _reply(
                "Found it. `_expression` reads the right-hand side of `+` and `-` by calling "
                "itself, so `10 - 4 - 3` groups as `10 - (4 - 3)`. It should read one term at "
                "a time and let the loop carry on, the way `_term` already does for `*` and `/`.",
                [_todos(2), _call("Edit", path="calc.py", old_string=BUG, new_string=FIX)],
                usage=(12, 4_822, 772, 210),
            ),
            _reply(
                "Now the tests again.",
                [_todos(3), _call("Bash", command=TEST)],
                usage=(10, 5_594, 242, 70),
            ),
            _reply(
                "All six tests pass.\n\n"
                "**The bug:** in `calc.py`, `_expression` parsed the right side of `+` and `-` "
                "with a recursive call, which made subtraction group from the right.\n\n"
                "**The fix:** it now reads a single term with `_term`, so `10 - 4 - 3` is "
                "`(10 - 4) - 3 = 3`, while `2 + 3 * 4` still respects precedence.",
                [],
                usage=(10, 5_836, 120, 640),
            ),
            # Turn 2 starts with the compaction's summary call: no tools, its own prompt.
            _reply(
                "## Handoff notes\n\n"
                "- **Asked:** find and fix the failing test in the calc project.\n"
                "- **Cause:** `_expression` in `calc.py` called itself for the right side of "
                "`+`/`-`, so `10 - 4 - 3` evaluated to 9.\n"
                "- **Changed:** `calc.py`: the recursive call is now `_term(tokens)`.\n"
                f"- **Checked:** `{TEST}`: 6 tests, all passing.\n"
                "- **Left:** nothing from the first request.",
                [],
                usage=(1_880, 0, 0, 160),
            ),
            _reply(
                "I'll add the test next to the others in `test_calc.py`.",
                [_call("Edit", path="test_calc.py", old_string=LAST_TEST, new_string=NEW_TEST)],
                usage=(12, 4_180, 808, 160),
            ),
            _reply(
                "And run them.",
                [_call("Bash", command=TEST)],
                usage=(10, 5_000, 190, 60),
            ),
            _reply(
                'Added `test_dividing_by_zero_raises`: `evaluate("1 / 0")` raises '
                "`ZeroDivisionError`. All seven tests pass.",
                [],
                usage=(10, 5_200, 90, 140),
            ),
        ]
    )


def _numbered(replies: list[ModelResponse]) -> list[ModelResponse]:
    """Give each tool call its own id, as the API would."""
    count = 0
    numbered = []
    for reply in replies:
        content: list[TextBlock | ToolUseBlock | RawBlock] = []
        for block in reply.content:
            if isinstance(block, ToolUseBlock):
                count += 1
                block = block.model_copy(update={"id": f"toolu_demo_{count:02d}"})
            content.append(block)
        numbered.append(reply.model_copy(update={"content": content}))
    return numbered


PLAN = ["Run the tests", "Find the cause", "Fix it", "Run the tests again"]


def _todos(step: int) -> ToolUseBlock:
    """The plan for the first task, with steps before `step` done and that one in progress."""
    statuses = ["completed"] * step + ["in_progress"] + ["pending"] * (len(PLAN) - step - 1)
    return _call(
        "TodoWrite",
        todos=[{"content": c, "status": s} for c, s in zip(PLAN, statuses, strict=True)],
    )


def _call(name: str, **args: Any) -> ToolUseBlock:
    return ToolUseBlock(id="", name=name, input=args)  # numbered in _numbered


def _reply(text: str, calls: list[ToolUseBlock], usage: tuple[int, int, int, int]) -> ModelResponse:
    fresh, cache_read, cache_write, output = usage
    return ModelResponse(
        content=[TextBlock(text=text), *calls],
        stop_reason="tool_use" if calls else "end_turn",
        model=MODEL,
        input_tokens=fresh,
        output_tokens=output,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )
