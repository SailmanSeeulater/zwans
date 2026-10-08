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
