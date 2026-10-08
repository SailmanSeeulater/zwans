import asyncio
from pathlib import Path

import pytest

from zwans.executor.local import LocalExecutor, OutsideWorkspaceError


def test_write_then_read_inside_the_workspace(tmp_path: Path) -> None:
    executor = LocalExecutor(tmp_path)

    asyncio.run(executor.write_bytes("new/dir/file.txt", b"hello"))

    assert (tmp_path / "new" / "dir" / "file.txt").read_bytes() == b"hello"
    assert asyncio.run(executor.read_bytes("new/dir/file.txt")) == b"hello"


def test_paths_outside_the_workspace_are_refused(tmp_path: Path) -> None:
    executor = LocalExecutor(tmp_path / "workspace")

    for path in ["../outside.txt", "sub/../../outside.txt", str(tmp_path / "outside.txt")]:
        with pytest.raises(OutsideWorkspaceError):
            asyncio.run(executor.read_bytes(path))


def test_spilled_output_can_be_read_but_not_written(tmp_path: Path) -> None:
    executor = LocalExecutor(tmp_path / "workspace", spill_dir=tmp_path / "spill")

    path = asyncio.run(executor.spill("toolu_1.txt", "the full output"))

    assert not Path(path).is_relative_to(tmp_path / "workspace")
    assert asyncio.run(executor.read_bytes(path)) == b"the full output"
    with pytest.raises(OutsideWorkspaceError):
        asyncio.run(executor.write_bytes(path, b"changed"))
