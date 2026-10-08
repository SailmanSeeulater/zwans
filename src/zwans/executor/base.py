"""How tools touch files and run commands. Swapping the executor swaps the sandbox."""

from typing import Protocol


class Executor(Protocol):
    """Paths are relative to the workspace root, or absolute paths inside it."""

    async def read_bytes(self, path: str) -> bytes: ...

    async def write_bytes(self, path: str, data: bytes) -> None: ...
