"""How tools touch files and run commands. Swapping the executor swaps the sandbox."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CommandResult:
    output: str  # stdout and stderr together, shortened in the middle when very long
    exit_code: int | None  # None when the command was stopped before it finished
    timed_out: bool = False


class Executor(Protocol):
    """Paths are relative to the workspace root, or absolute paths inside it."""

    def relative(self, path: str) -> str:
        """Check that a path is inside the workspace and return it relative to the root."""
        ...

    async def read_bytes(self, path: str) -> bytes: ...

    async def write_bytes(self, path: str, data: bytes) -> None: ...

    async def run(self, argv: Sequence[str], timeout: float) -> CommandResult:
        """Run a program in the workspace root. Cancelling the call stops the program."""
        ...

    async def run_shell(self, command: str, timeout: float) -> CommandResult: ...
