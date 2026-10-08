import asyncio
from pathlib import Path

import pytest

from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.edit import EditInput, EditTool
from zwans.tools.read import ReadInput, ReadTool
from zwans.tools.write import WriteInput, WriteTool


def edit(ctx: ToolContext, path: str, old: str, new: str, replace_all: bool = False) -> ToolOutput:
    args = EditInput(path=path, old_string=old, new_string=new, replace_all=replace_all)
    return asyncio.run(EditTool().run(args, ctx))


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


def test_edit_replaces_a_unique_match(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "a.py").write_bytes(b"x = 1\ny = 2\n")

    output = edit(ctx, "a.py", "y = 2", "y = 3")

    assert output.content == "Replaced 1 occurrence in a.py."
    assert (tmp_path / "a.py").read_bytes() == b"x = 1\ny = 3\n"


def test_edit_fails_when_there_is_no_match(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "a.py").write_bytes(b"x = 1\n")

    with pytest.raises(ToolError, match="not found"):
        edit(ctx, "a.py", "x = 2", "x = 3")
    assert (tmp_path / "a.py").read_bytes() == b"x = 1\n"


def test_edit_needs_replace_all_for_multiple_matches(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "a.py").write_bytes(b"x = 1\nx = 1\n")

    with pytest.raises(ToolError, match="appears 2 times"):
        edit(ctx, "a.py", "x = 1", "x = 2")
    assert (tmp_path / "a.py").read_bytes() == b"x = 1\nx = 1\n"

    edit(ctx, "a.py", "x = 1", "x = 2", replace_all=True)
    assert (tmp_path / "a.py").read_bytes() == b"x = 2\nx = 2\n"


def test_edit_keeps_crlf_line_endings(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "win.py").write_bytes(b"def f():\r\n    return 1\r\n")

    # The model writes "\n" because Read shows the file without "\r".
    edit(ctx, "win.py", "def f():\n    return 1", "def f():\n    return 2")

    assert (tmp_path / "win.py").read_bytes() == b"def f():\r\n    return 2\r\n"


def test_edit_keeps_bytes_of_a_non_utf8_file(tmp_path: Path, ctx: ToolContext) -> None:
    # "café" in Latin-1 is not valid UTF-8; the bytes we don't touch must survive unchanged.
    (tmp_path / "legacy.txt").write_bytes(b"caf\xe9 = 1\nother = 2\n")

    edit(ctx, "legacy.txt", "other = 2", "other = 3")

    assert (tmp_path / "legacy.txt").read_bytes() == b"caf\xe9 = 1\nother = 3\n"


def test_edit_refuses_text_the_file_encoding_cannot_store(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "legacy.txt").write_bytes(b"caf\xe9 = 1\n")

    with pytest.raises(ToolError, match="can't be saved"):
        edit(ctx, "legacy.txt", "= 1", "= '☃'")
