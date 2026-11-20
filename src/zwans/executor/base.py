"""How tools touch files and run commands. Swapping the executor swaps the sandbox."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

# Marks where an executor dropped the middle of a runaway command's output. It isn't kept
# anywhere, so the note on a shortened result must not promise it.
DROPPED_NOTE = "[... {:,} bytes dropped while the command ran ...]"
DROPPED_PATTERN = re.compile(
    r"^\[\.\.\. ([\d,]+) bytes dropped while the command ran \.\.\.\]$", re.M
)


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

    def search_path(self, path: str) -> str:
        """Like `relative`, but also allows saved tool output (as an absolute path), for
        read-only searches such as Grep."""
        ...

    async def read_bytes(self, path: str) -> bytes: ...

    async def write_bytes(self, path: str, data: bytes) -> None: ...

    async def run(self, argv: Sequence[str], timeout: float) -> CommandResult:
        """Run a program in the workspace root. Cancelling the call stops the program."""
        ...

    async def run_shell(self, command: str, timeout: float) -> CommandResult: ...

    async def spill(self, name: str, text: str) -> str:
        """Save text that is too long for the conversation. Returns a path Read can open."""
        ...
