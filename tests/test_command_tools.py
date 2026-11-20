import asyncio
import sys
import time
from pathlib import Path

import pytest
from helpers import needs_bash, needs_rg, process_gone

from zwans.executor.local import LocalExecutor
from zwans.tools.base import ToolContext
from zwans.tools.bash import BashInput, BashTool
from zwans.tools.glob import GlobInput, GlobTool
from zwans.tools.grep import GrepInput, GrepTool


@needs_rg
def test_glob_finds_files_and_skips_ignored_ones(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("", encoding="utf-8")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "copy.py").write_text("", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("build/\n", encoding="utf-8")

    output = asyncio.run(GlobTool().run(GlobInput(pattern="**/*.py"), ctx))

    assert output.content == "src/app.py"


@needs_rg
def test_glob_and_grep_skip_installed_packages_without_a_gitignore(
    tmp_path: Path, ctx: ToolContext
) -> None:
    for folder in ("src", "node_modules/pkg", ".venv/lib"):
        (tmp_path / folder).mkdir(parents=True)
        (tmp_path / folder / "a.js").write_text("function greet() {}\n", encoding="utf-8")

    found = asyncio.run(GlobTool().run(GlobInput(pattern="**/*.js"), ctx))
    matched = asyncio.run(GrepTool().run(GrepInput(pattern="greet"), ctx))
    inside = asyncio.run(GrepTool().run(GrepInput(pattern="greet", path="node_modules"), ctx))
    named = asyncio.run(GlobTool().run(GlobInput(pattern="node_modules/**/*.js"), ctx))
    globbed = asyncio.run(GrepTool().run(GrepInput(pattern="greet", glob="node_modules/**"), ctx))

    assert found.content == "src/a.js"
    assert matched.content == "src/a.js:1:function greet() {}"
    assert inside.content == "node_modules/pkg/a.js:1:function greet() {}"
    assert named.content == "node_modules/pkg/a.js"
    assert globbed.content == "node_modules/pkg/a.js:1:function greet() {}"


@needs_rg
def test_grep_searches_saved_tool_output_but_nothing_else_outside(
    tmp_path: Path, ctx: ToolContext
) -> None:
    saved = asyncio.run(ctx.executor.spill("toolu_1.txt", "one\nline 500000 here\nthree\n"))
    (tmp_path.parent / "secret.txt").write_text("line 500000\n", encoding="utf-8")

    output = asyncio.run(GrepTool().run(GrepInput(pattern="500000", path=saved), ctx))

    assert output.content.endswith("toolu_1.txt:2:line 500000 here")
    with pytest.raises(PermissionError):
        asyncio.run(GrepTool().run(GrepInput(pattern="500000", path="../secret.txt"), ctx))


@needs_rg
def test_grep_returns_matching_lines_with_numbers(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "a.py").write_text("x = 1\ndef total():\n    pass\n", encoding="utf-8")

    output = asyncio.run(GrepTool().run(GrepInput(pattern=r"def \w+"), ctx))

    assert output.content == "a.py:2:def total():"


@needs_rg
def test_grep_says_when_nothing_matches(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")

    output = asyncio.run(GrepTool().run(GrepInput(pattern="missing"), ctx))

    assert output.content == "No matches."


@needs_bash
def test_bash_returns_output_and_exit_code(ctx: ToolContext) -> None:
    output = asyncio.run(BashTool().run(BashInput(command="echo hello; exit 3"), ctx))

    assert output.content == "hello\n(exit code 3)"
    assert not output.is_error


@needs_bash
def test_bash_stops_a_command_that_runs_too_long(ctx: ToolContext) -> None:
    started = time.monotonic()

    output = asyncio.run(BashTool().run(BashInput(command="sleep 30", timeout=1), ctx))

    assert output.is_error
    assert "Stopped after 1s" in output.content
    assert time.monotonic() - started < 10


@needs_bash
@pytest.mark.skipif(sys.platform == "win32", reason="process groups are a POSIX idea")
def test_bash_returns_when_the_command_exits_and_stops_what_it_left_running(
    ctx: ToolContext,
) -> None:
    started = time.monotonic()

    output = asyncio.run(BashTool().run(BashInput(command="sleep 300 & echo $!", timeout=5), ctx))

    assert time.monotonic() - started < 3  # not held open until the timeout by the sleep
    pid, code = output.content.splitlines()
    assert code == "(exit code 0)"
    assert process_gone(int(pid))


@needs_bash
@pytest.mark.skipif(sys.platform == "win32", reason="process groups are a POSIX idea")
def test_bash_stops_leftovers_that_let_go_of_the_output(ctx: ToolContext) -> None:
    command = "sh -c 'sleep 301 >/dev/null 2>&1 & echo $!'"

    output = asyncio.run(BashTool().run(BashInput(command=command), ctx))

    assert process_gone(int(output.content.splitlines()[0]))


@needs_bash
def test_bash_keeps_the_start_and_end_of_runaway_output(tmp_path: Path) -> None:
    ctx = ToolContext(executor=LocalExecutor(tmp_path, max_output_bytes=10_000))

    output = asyncio.run(BashTool().run(BashInput(command="seq 1 100000"), ctx))

    assert output.content.startswith("1\n2\n3\n")
    assert "bytes dropped while the command ran" in output.content
    assert output.content.endswith("100000\n(exit code 0)")


@needs_bash
def test_commands_cannot_see_zwans_credentials(
    ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")

    output = asyncio.run(
        BashTool().run(BashInput(command='echo "${ANTHROPIC_API_KEY:-hidden}"'), ctx)
    )

    assert output.content == "hidden\n(exit code 0)"
