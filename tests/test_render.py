import asyncio
import sys

import click
import pytest

from zwans.cli.render import CLEAR_LINE, Renderer, _block_end
from zwans.events import (
    Event,
    HookReported,
    PermissionRequested,
    PermissionResolved,
    TextDelta,
    ToolCallRequested,
    ToolResult,
    TurnEnded,
    TurnStarted,
)
from zwans.web import describe


def shown(capsys: pytest.CaptureFixture[str], *events: Event, markdown: bool = False) -> str:
    renderer = Renderer(markdown=markdown)
    for event in events:
        renderer.on_event(event)
    return capsys.readouterr().out


def call(call_id: str, name: str, **args: object) -> ToolCallRequested:
    return ToolCallRequested(call_id=call_id, name=name, args=args)


def test_a_grep_shows_its_pattern_and_where_it_looks(capsys: pytest.CaptureFixture[str]) -> None:
    out = shown(capsys, call("1", "Grep", pattern="before_turn", path="src"))

    assert out == "> Grep before_turn in src\n"


def test_call_lines_note_background_runs_extra_lines_and_offsets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = shown(
        capsys,
        call("1", "Bash", command="npm run dev", run_in_background=True),
        call("2", "Bash", command="python - <<'EOF'\nprint(1)\nEOF", timeout=600),
        call("3", "Read", path="pkg/stats.py", offset=200),
        call("4", "Read", path="a/" * 60 + "stats.py"),
    )

    lines = out.splitlines()
    assert lines[0] == "> Bash npm run dev (in the background)"
    assert lines[1] == "> Bash python - <<'EOF' (+2 lines) (timeout 600s)"
    assert lines[2] == "> Read pkg/stats.py (from line 200)"
    assert lines[3].startswith("> Read ...") and lines[3].endswith("a/stats.py")


def test_a_command_shows_the_end_of_its_output_and_its_exit_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = "\n".join(f"line {n}" for n in range(10))
    content = f"{output}\nFAILED test_x\n1 failed, 5 passed\n(exit code 0)"
    out = shown(
        capsys,
        call("1", "Bash", command="pytest -q | tail -5"),
        ToolResult(call_id="1", content=content),
    )

    assert out.splitlines()[1:] == [
        "  (9 earlier lines)",
        "  line 9",
        "  FAILED test_x",
        "  1 failed, 5 passed",
        "  (exit code 0)",
    ]


def test_a_command_with_no_output_shows_just_its_exit_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = shown(
        capsys,
        call("1", "Bash", command="false"),
        ToolResult(call_id="1", content="(no output)\n(exit code 1)"),
    )

    assert out.splitlines()[1:] == ["  (exit code 1)"]


def test_a_timed_out_command_says_why_it_stopped(capsys: pytest.CaptureFixture[str]) -> None:
    content = "starting server\nlistening\nStopped after 120s because it hadn't finished."
    out = shown(
        capsys,
        call("1", "Bash", command="npm start"),
        ToolResult(call_id="1", content=content, is_error=True),
    )

    assert out.splitlines()[1] == "  ! Stopped after 120s because it hadn't finished."


def test_results_of_calls_run_together_say_whose_they_are(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = shown(
        capsys,
        call("1", "Read", path="a.py"),
        call("2", "Read", path="b.py"),
        ToolResult(call_id="1", content="1\tx\n2\ty"),
        ToolResult(call_id="2", content="No such file: b.py", is_error=True),
        call("3", "Read", path="c.py"),
        ToolResult(call_id="3", content="1\tz\n2\tz\n3\tz"),
    )

    assert out.splitlines() == [
        "> Read a.py",
        "> Read b.py",
        "  Read a.py: (2 lines)",
        "  ! Read b.py: No such file: b.py",
        "> Read c.py",
        "  (3 lines)",
    ]


def test_web_results_say_what_was_found(capsys: pytest.CaptureFixture[str]) -> None:
    page = {
        "type": "web_fetch_result",
        "url": "https://pypi.org/project/httpx/",
        "content": {"title": "httpx", "source": {"type": "text", "data": "x" * 49_741}},
    }
    hits = [{"title": "httpx · PyPI", "url": "https://pypi.org"}, {"title": "httpx docs"}]
    out = shown(
        capsys,
        call("1", "web_fetch", url="https://pypi.org/project/httpx/"),
        ToolResult(call_id="1", content=describe(page)[0]),
        call("2", "web_search", query="httpx"),
        ToolResult(call_id="2", content=describe(hits)[0]),
    )

    lines = out.splitlines()
    assert lines[1] == "  httpx · https://pypi.org/project/httpx/ · 49,741 characters"
    assert lines[3] == "  2 results: httpx · PyPI, httpx docs"


def test_an_edit_shows_its_diff(capsys: pytest.CaptureFixture[str]) -> None:
    diff = "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def sub(a, b):\n-    return a + b\n"
    diff += "+    return a - b\n"
    out = shown(
        capsys,
        call("1", "Edit", path="calc.py"),
        ToolResult(call_id="1", content="Replaced 1 occurrence in calc.py.", diff=diff),
    )

    assert out.splitlines() == [
        "> Edit calc.py",
        "  Replaced 1 occurrence in calc.py.",
        "    @@ -1,2 +1,2 @@",
        "     def sub(a, b):",
        "    -    return a + b",
        "    +    return a - b",
    ]


def test_a_long_diff_is_cut(capsys: pytest.CaptureFixture[str]) -> None:
    diff = "--- /dev/null\n+++ b/big.txt\n" + "".join(f"+{n}\n" for n in range(100))
    out = shown(capsys, ToolResult(call_id="1", content="Wrote big.txt.", diff=diff))

    assert out.splitlines()[-1] == "    ... 60 more lines"


def test_a_blocking_hook_is_reported_once(capsys: pytest.CaptureFixture[str]) -> None:
    message = "rm -rf is blocked by the project hook."
    out = shown(
        capsys,
        call("1", "Bash", command="rm -rf build"),
        HookReported(event="pre_tool", command="no_rm", message=message, call_id="1"),
        ToolResult(call_id="1", content=f"A pre_tool hook blocked this: {message}", is_error=True),
    )

    assert out.count(message) == 1


def test_markdown_is_rendered_a_block_at_a_time(capsys: pytest.CaptureFixture[str]) -> None:
    renderer = Renderer(markdown=True)

    for piece in ["## Do", "ne\n\nSome **bold** text.\n", "\n- one\n", "- two"]:
        renderer.on_event(TextDelta(text=piece))
    partial = capsys.readouterr().out
    renderer.on_event(TurnEnded(stop_reason="end_turn"))
    rest = capsys.readouterr().out

    assert partial.strip() == "Done"
    assert "Some bold text." in rest and "**" not in rest
    assert "• one" in rest and "• two" in rest


def test_a_markdown_block_ends_only_where_nothing_carries_it_on() -> None:
    assert _block_end("Para one.\n\nPara") == len("Para one.\n\n")
    assert _block_end("Para one.\n\nPa") is None  # too little of the next line to judge
    assert _block_end("Intro:\n\n1. first\n\n2. second") is None  # one list
    assert _block_end("```\ncode\n\nmore\n```\n\nAfter") == len("```\ncode\n\nmore\n```\n\n")
    assert _block_end("```\ncode\n\nmore") is None  # inside a fence


def test_the_status_line_shows_while_the_turn_runs(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    async def turn() -> Renderer:
        renderer = Renderer(spinner=True, markdown=False)
        renderer.on_event(TurnStarted(prompt="hi"))
        await asyncio.sleep(0.25)
        renderer.on_event(call("1", "Edit", path="a.py"))
        renderer.on_event(PermissionRequested(call_id="1", reason="Edit a.py changes files"))
        asking = click.unstyle(capsys.readouterr().out)
        await asyncio.sleep(0.25)
        assert capsys.readouterr().out == ""  # quiet while the user answers
        renderer.on_event(PermissionResolved(call_id="1", allowed=True))
        assert asking.endswith("> Edit a.py\n")
        await asyncio.sleep(0.15)
        renderer.on_event(ToolResult(call_id="1", content="Replaced 1 occurrence in a.py."))
        renderer.on_event(TextDelta(text="Done."))
        renderer.on_event(TurnEnded(stop_reason="end_turn"))
        await asyncio.sleep(0.15)
        return renderer

    renderer = asyncio.run(turn())
    out = click.unstyle(capsys.readouterr().out)

    assert renderer._status_task is None
    assert "Running Edit… 0s" in out
    assert out.endswith("\r  Replaced 1 occurrence in a.py.\nDone.\n")


def test_the_status_line_stays_off_without_a_terminal(capsys: pytest.CaptureFixture[str]) -> None:
    async def turn() -> None:
        renderer = Renderer(spinner=True)
        renderer.on_event(TurnStarted(prompt="hi"))
        await asyncio.sleep(0.15)
        renderer.on_event(TurnEnded(stop_reason="end_turn"))

    asyncio.run(turn())

    assert capsys.readouterr().out == ""


def test_an_interruption_wipes_the_echoed_ctrl_c(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    out = shown(capsys, TurnEnded(stop_reason="interrupted"))

    assert out.startswith(CLEAR_LINE)
    assert click.unstyle(out) == "\r[stopped: interrupted]\n"
