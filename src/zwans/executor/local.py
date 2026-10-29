"""Runs tool operations directly on this machine, confined to one workspace folder."""

import asyncio
import contextlib
import errno
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from zwans.executor.base import CommandResult

# A memory guard for runaway commands. The loop decides how much output reaches the model.
MAX_OUTPUT_BYTES = 2_000_000

# Removed from every command's environment, so the model can't read Zwans's own credentials.
SECRET_VARS = frozenset({"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"})


class OutsideWorkspaceError(PermissionError):
    def __init__(self, path: str) -> None:
        super().__init__(errno.EACCES, "Path is outside the workspace", path)


class LocalExecutor:
    def __init__(
        self,
        root: Path,
        shell: str | None = None,
        spill_dir: Path | None = None,
        max_output_bytes: int = MAX_OUTPUT_BYTES,
    ) -> None:
        self.root = root.resolve()
        self._shell = shell
        # Where large tool output is saved. It's outside the workspace, so the user's project
        # stays clean, and the model can Read it but not write there.
        default_spill = Path(tempfile.gettempdir()) / "zwans-tool-output"
        self.spill_dir = (spill_dir or default_spill).resolve()
        self.max_output_bytes = max_output_bytes

    def resolve(self, path: str, *, reading: bool = False) -> Path:
        """Turn a path from the model into an absolute path, refusing anything outside the root."""
        resolved = (self.root / path).resolve()
        if resolved.is_relative_to(self.root):
            return resolved
        if reading and resolved.is_relative_to(self.spill_dir):
            return resolved
        raise OutsideWorkspaceError(path)

    def relative(self, path: str) -> str:
        return self.resolve(path).relative_to(self.root).as_posix()

    def contains(self, path: str) -> bool:
        """Whether a path (relative to the root, or absolute) is inside the workspace."""
        try:
            self.resolve(path)
        except OutsideWorkspaceError:
            return False
        return True

    async def read_bytes(self, path: str) -> bytes:
        return await asyncio.to_thread(self.resolve(path, reading=True).read_bytes)

    async def write_bytes(self, path: str, data: bytes) -> None:
        await asyncio.to_thread(_write, self.resolve(path), data)

    async def run(self, argv: Sequence[str], timeout: float) -> CommandResult:
        process = await asyncio.create_subprocess_exec(
            find_program(argv[0]),
            *argv[1:],
            cwd=self.root,
            env=_command_env(),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **own_process_group(),
        )
        assert process.stdout is not None
        output = _Output(self.max_output_bytes)
        pump = asyncio.create_task(_pump(process.stdout, output))
        timed_out = False
        try:
            await asyncio.wait_for(process.wait(), timeout)
        except TimeoutError:
            timed_out = True
        finally:
            # Runs after a timeout and after a cancel (Ctrl+C): stop the command and its children.
            await kill_tree(process)
            # A leftover background process can hold the pipe open, so don't wait on it forever.
            await asyncio.wait([pump], timeout=2)
            pump.cancel()
        exit_code = None if timed_out else process.returncode
        return CommandResult(output=output.text(), exit_code=exit_code, timed_out=timed_out)

    async def run_shell(self, command: str, timeout: float) -> CommandResult:
        return await self.run([self._shell or find_bash(), "-c", command], timeout)

    async def spill(self, name: str, text: str) -> str:
        target = self.spill_dir / re.sub(r"[^\w.-]", "_", name)
        await asyncio.to_thread(_write, target, text.encode("utf-8"))
        return str(target)


def find_program(name: str) -> str:
    """Find a program on PATH, or in this Python environment's folders, where conda puts tools."""
    prefix = Path(sys.prefix)
    env_dirs = os.pathsep.join(str(prefix / d) for d in ("bin", "Scripts", "Library/bin", "."))
    found = shutil.which(name) or shutil.which(name, path=env_dirs)
    if found is None:
        raise FileNotFoundError(errno.ENOENT, f"{name} is not installed or not on PATH", name)
    return found


def find_bash() -> str:
    """Find bash. On Windows that means Git Bash, not the WSL launcher in System32."""
    if sys.platform != "win32":
        return find_program("bash")
    candidates = []
    git = shutil.which("git")
    if git:
        candidates.append(Path(git).resolve().parents[1] / "bin" / "bash.exe")
    program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    candidates.append(program_files / "Git" / "bin" / "bash.exe")
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(
        errno.ENOENT, "Git Bash was not found. Install Git for Windows or set `shell`", "bash"
    )


def _write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _command_env() -> dict[str, str]:
    env = {name: value for name, value in os.environ.items() if name.upper() not in SECRET_VARS}
    env["PYTHONUTF8"] = "1"  # Python programs print UTF-8, which is how we decode output
    return env


def own_process_group() -> dict[str, Any]:
    """Start a command in its own process group, so it can be stopped with everything it started."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


async def kill_tree(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if sys.platform == "win32":
        # /T also stops child programs, such as the test runner a shell command started.
        killer = await asyncio.create_subprocess_exec(
            "taskkill",
            "/F",
            "/T",
            "/PID",
            str(process.pid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await killer.wait()
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    await process.wait()


class _Output:
    """Keeps the start and the end of a command's output and counts what was dropped between."""

    def __init__(self, limit: int) -> None:
        self.half = limit // 2
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0

    def feed(self, chunk: bytes) -> None:
        self.total += len(chunk)
        room = self.half - len(self.head)
        if room > 0:
            self.head += chunk[:room]
            chunk = chunk[room:]
        self.tail += chunk
        del self.tail[: max(0, len(self.tail) - self.half)]

    def text(self) -> str:
        data = bytes(self.head)
        dropped = self.total - len(self.head) - len(self.tail)
        if dropped:
            data += f"\n[... {dropped} bytes not shown ...]\n".encode()
        data += bytes(self.tail)
        return data.decode("utf-8", errors="replace").replace("\r\n", "\n")


async def _pump(stream: asyncio.StreamReader, output: _Output) -> None:
    while chunk := await stream.read(65536):
        output.feed(chunk)
