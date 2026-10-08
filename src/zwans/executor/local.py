"""Runs tool operations directly on this machine, confined to one workspace folder."""

import asyncio
import errno
from pathlib import Path


class OutsideWorkspaceError(PermissionError):
    def __init__(self, path: str) -> None:
        super().__init__(errno.EACCES, "Path is outside the workspace", path)


class LocalExecutor:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def resolve(self, path: str) -> Path:
        """Turn a path from the model into an absolute path, refusing anything outside the root."""
        resolved = (self.root / path).resolve()
        if not resolved.is_relative_to(self.root):
            raise OutsideWorkspaceError(path)
        return resolved

    async def read_bytes(self, path: str) -> bytes:
        return await asyncio.to_thread(self.resolve(path).read_bytes)

    async def write_bytes(self, path: str, data: bytes) -> None:
        await asyncio.to_thread(_write, self.resolve(path), data)


def _write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
