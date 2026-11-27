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

from zwans.executor.base import DROPPED_NOTE, CommandResult

# A memory guard for runaway commands. The loop decides how much output reaches the model.
MAX_OUTPUT_BYTES = 2_000_000

# Removed from every command's environment, so the model can't read Zwans's own credentials.
SECRET_VARS = frozenset({"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"})


class OutsideWorkspaceError(PermissionError):
    def __init__(self, path: str) -> None:
        super().__init__(errno.EACCES, "Path is outside the workspace", path)


class LocalExecutor:
    # Whether a program it starts can be written to while it runs, as a Python session is.
    interactive = True

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

    def at(self, root: Path) -> "LocalExecutor":
        """The same kind of executor, working in another folder: an isolated subagent's copy
        of the workspace (isolation.py)."""
        return LocalExecutor(root, self._shell, self.spill_dir, self.max_output_bytes)

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

    def search_path(self, path: str) -> str:
        """Where a read-only search may look: like `relative` in the workspace, and the
        absolute path in the folder of saved tool output, which Read can open too."""
        resolved = self.resolve(path, reading=True)
        if resolved.is_relative_to(self.root):
            return resolved.relative_to(self.root).as_posix()
        return str(resolved)

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
        process = await self._spawn(argv)
        assert process.stdout is not None
        output = _Output(self.max_output_bytes)
        pump = asyncio.create_task(_pump(process.stdout, output))
        timed_out = False
        try:
            # Wait for the command to exit, not for its output to close: a process it left
            # running in the background can hold the output open long after.
            timed_out = not await wait_exit(process, timeout)
        finally:
            # Runs after a timeout, after a cancel (Ctrl+C) and after a normal exit, since a
            # command can leave processes behind: stop the command and everything it started.
            await self._stop(process)
            # A process that left the group can still hold the pipe open; don't wait forever.
            done, _ = await asyncio.wait([pump], timeout=2)
            if not done:
                pump.cancel()
                close_pipes(process)
        exit_code = None if timed_out else process.returncode
        return CommandResult(output=output.text(), exit_code=exit_code, timed_out=timed_out)

    async def _spawn(
        self, argv: Sequence[str], background: bool = False, stdin: int = asyncio.subprocess.DEVNULL
    ) -> asyncio.subprocess.Process:
        """Start a program with its output piped, in its own process group. `background` says
        it's a background job, whose leftover processes may keep running after it exits."""
        return await asyncio.create_subprocess_exec(
            find_program(argv[0]),
            *argv[1:],
            cwd=self.root,
            env=command_env(),
            stdin=stdin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **own_process_group(),
        )

    async def _stop(self, process: asyncio.subprocess.Process) -> None:
        await kill_tree(process)

    async def run_shell(self, command: str, timeout: float) -> CommandResult:
        return await self.run(self.shell_argv(command), timeout)

    def shell_argv(self, command: str) -> list[str]:
        """How to run a command with the shell, wherever this executor runs commands."""
        return [self._shell or find_bash(), "-c", command]

    async def start_process(
        self, argv: Sequence[str], stdin: bool = False
    ) -> asyncio.subprocess.Process:
        """Start a program and leave it running, its output piped, for background jobs.
        `stdin` gives it a pipe to be written to as well, where the executor is
        `interactive`. Stop it with `stop_process`."""
        if not stdin:
            return await self._spawn(argv, background=True)
        return await self._spawn(argv, background=True, stdin=asyncio.subprocess.PIPE)

    async def stop_process(self, process: asyncio.subprocess.Process) -> None:
        """Stop a program `start_process` started, and everything it started."""
        await self._stop(process)

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


def command_env() -> dict[str, str]:
    env = {name: value for name, value in os.environ.items() if name.upper() not in SECRET_VARS}
    env["PYTHONUTF8"] = "1"  # Python programs print UTF-8, which is how we decode output
    return env


def own_process_group() -> dict[str, Any]:
    """Start a command in its own process group, so it can be stopped with everything it started."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


async def kill_tree(process: asyncio.subprocess.Process) -> None:
    """Stop a program started with `own_process_group`, and everything it started."""
    if sys.platform == "win32":
        if process.returncode is None:
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
        # The whole group, even when the program itself has exited: what it left running in
        # the background, such as `server &`, is still in the group. Already gone: macOS says
        # EPERM rather than ESRCH when the group's only member is a zombie, as `docker exec`
        # is once the command in the container has been killed.
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
    await wait_exit(process)


async def wait_exit(process: asyncio.subprocess.Process, timeout: float | None = None) -> bool:
    """Wait until a program exits, or `timeout` seconds pass, and say whether it exited.
    Unlike `process.wait()`, this doesn't also wait for its output to close."""
    loop = asyncio.get_running_loop()
    deadline = None if timeout is None else loop.time() + timeout
    delay = 0.001  # short at first, so quick commands return quickly
    while process.returncode is None:
        if deadline is not None:
            left = deadline - loop.time()
            if left <= 0:
                return False
            delay = min(delay, left)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 0.05)
    return True


def close_pipes(process: asyncio.subprocess.Process) -> None:
    """Close a finished program's pipes that something else still holds open, so they aren't
    left for the garbage collector after the event loop has closed."""
    transport = getattr(process, "_transport", None)  # asyncio has no public way to do this
    if transport is not None:
        transport.close()


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
            data += f"\n{DROPPED_NOTE.format(dropped)}\n".encode()
        data += bytes(self.tail)
        return data.decode("utf-8", errors="replace").replace("\r\n", "\n")


async def _pump(stream: asyncio.StreamReader, output: _Output) -> None:
    while chunk := await stream.read(65536):
        output.feed(chunk)
