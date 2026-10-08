import asyncio
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from zwans.executor.local import find_bash, find_program
from zwans.tools.base import ToolContext
from zwans.tools.bash import BashInput, BashTool
from zwans.tools.glob import GlobInput, GlobTool
from zwans.tools.grep import GrepInput, GrepTool


def _available(find: Callable[[], str]) -> bool:
    try:
        find()
    except FileNotFoundError:
        return False
    return True


needs_rg = pytest.mark.skipif(
    not _available(lambda: find_program("rg")), reason="ripgrep is not installed"
)
needs_bash = pytest.mark.skipif(not _available(find_bash), reason="bash is not installed")


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
def test_bash_shortens_long_output_in_the_middle(ctx: ToolContext) -> None:
    output = asyncio.run(BashTool().run(BashInput(command="seq 1 100000"), ctx))

    assert output.content.startswith("1\n2\n3\n")
    assert "bytes not shown" in output.content
    assert output.content.endswith("100000\n(exit code 0)")
