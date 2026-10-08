import asyncio
from pathlib import Path

import pytest

from zwans.tools.base import ToolContext, ToolError
from zwans.tools.read import ReadInput, ReadTool
from zwans.tools.write import WriteInput, WriteTool


def test_read_numbers_lines_and_honors_offset_and_limit(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "a.txt").write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    output = asyncio.run(ReadTool().run(ReadInput(path="a.txt", offset=2, limit=2), ctx))

    assert output.content == (
        "     2\ttwo\n     3\tthree\n(Showing lines 2-3 of 4. Use offset to see more.)"
    )


def test_read_refuses_binary_files(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "image.png").write_bytes(b"\x89PNG\x00\x00")

    with pytest.raises(ToolError, match="binary"):
        asyncio.run(ReadTool().run(ReadInput(path="image.png"), ctx))


def test_write_creates_missing_folders(tmp_path: Path, ctx: ToolContext) -> None:
    asyncio.run(WriteTool().run(WriteInput(path="src/new.py", content="x = 1\n"), ctx))

    assert (tmp_path / "src" / "new.py").read_bytes() == b"x = 1\n"


def test_write_keeps_crlf_line_endings(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "win.txt").write_bytes(b"old\r\n")

    asyncio.run(WriteTool().run(WriteInput(path="win.txt", content="new\nlines\n"), ctx))

    assert (tmp_path / "win.txt").read_bytes() == b"new\r\nlines\r\n"
