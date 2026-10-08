"""Runs tool operations directly on this machine, confined to one workspace folder."""

import asyncio
import contextlib
import errno
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from zwans.executor.base import CommandResult

MAX_OUTPUT_BYTES = 30_000


class OutsideWorkspaceError(PermissionError):
    def __init__(self, path: str) -> None:
        super().__init__(errno.EACCES, "Path is outside the workspace", path)


class LocalExecutor:
    def __init__(self, root: Path, shell: str | None = None) -> None:
        self.root = root.resolve()
        self._shell = shell

    def resolve(self, path: str) -> Path:
        """Turn a path from the model into an absolute path, refusing anything outside the root."""
        resolved = (self.root / path).resolve()
        if not resolved.is_relative_to(self.root):
            raise OutsideWorkspaceError(path)
        return resolved

    def relative(self, path: str) -> str:
        return self.resolve(path).relative_to(self.root).as_posix()

    async def read_bytes(self, path: str) -> bytes:
        return await asyncio.to_thread(self.resolve(path).read_bytes)

    async def write_bytes(self, path: str, data: bytes) -> None:
        await asyncio.to_thread(_write, self.resolve(path), data)

    async def run(self, argv: Sequence[str], timeout: float) -> CommandResult:
        process = await asyncio.create_subprocess_exec(
            find_program(argv[0]),
            *argv[1:],
            cwd=self.root,
            env={**os.environ, "PYTHONUTF8": "1"},  # Python programs print UTF-8, which we decode
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **_own_process_group(),
        )
        assert process.stdout is not None
        output = _Output(MAX_OUTPUT_BYTES)
        pump = asyncio.create_task(_pump(process.stdout, output))
        timed_out = False
        try:
            await asyncio.wait_for(process.wait(), timeout)
        except TimeoutError:
            timed_out = True
        finally:
            # Runs after a timeout and after a cancel (Ctrl+C): stop the command and its children.
            await _kill_tree(process)
            # A leftover background process can hold the pipe open, so don't wait on it forever.
            await asyncio.wait([pump], timeout=2)
            pump.cancel()
        exit_code = None if timed_out else process.returncode
        return CommandResult(output=output.text(), exit_code=exit_code, timed_out=timed_out)

    async def run_shell(self, command: str, timeout: float) -> CommandResult:
        return await self.run([self._shell or find_bash(), "-c", command], timeout)


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


def _own_process_group() -> dict[str, Any]:
    """Start a command in its own process group, so it can be stopped with everything it started."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


async def _kill_tree(process: asyncio.subprocess.Process) -> None:
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
