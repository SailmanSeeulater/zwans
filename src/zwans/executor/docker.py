"""Runs commands in a Docker container; files still go through the workspace on this machine.

The workspace is bind-mounted at the same path it has here, so paths in the system prompt and
in command output mean the same thing on both sides. The container's only network is an
internal one, whose only way out is a proxy that lets through a short list of hosts
(package indexes and GitHub; see sandbox-image/proxy/allow.txt).

Build the images once:
    docker build -t zwans-sandbox:0.1 sandbox-image
    docker build -t zwans-proxy:0.1 sandbox-image/proxy
"""

import asyncio
import os
import secrets
import sys
import weakref
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Self

from zwans.executor.base import CommandResult
from zwans.executor.local import MAX_OUTPUT_BYTES, LocalExecutor, kill_tree, own_process_group

SANDBOX_IMAGE = "zwans-sandbox:0.1"
PROXY_IMAGE = "zwans-proxy:0.1"
NETWORK = "zwans-sandbox"  # internal: no route out except through the proxy
PROXY = "zwans-proxy"
PROXY_URL = f"http://{PROXY}:3128"
BUILD_HINTS = {
    SANDBOX_IMAGE: f"docker build -t {SANDBOX_IMAGE} sandbox-image",
    PROXY_IMAGE: f"docker build -t {PROXY_IMAGE} sandbox-image/proxy",
}

# Starts the command as the leader of a new process group and notes its id, so a timeout or
# Ctrl+C can stop it with everything it started. Killing `docker exec` alone would leave the
# command running inside the container.
WRAPPER = (
    'pidfile=/tmp/.zwans-run-$ZWANS_RUN; setsid "$@" & pid=$!; echo $pid > $pidfile; '
    "wait $pid; code=$?; rm -f $pidfile; exit $code"
)
KILL = (
    "pidfile=/tmp/.zwans-run-{token}; for i in 1 2 3 4 5 6 7 8 9 10; do "
    '[ -s $pidfile ] && break; sleep 0.1; done; kill -KILL -- -"$(cat $pidfile)"; rm -f $pidfile'
)

# What the system prompt says about where commands run.
SANDBOX_OS = (
    "Linux, in a Docker container. Its network reaches only package indexes (PyPI, npm, "
    "crates.io, the Go proxy) and GitHub."
)

# One per event loop, since a lock can't be shared between loops.
_setup_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = (
    weakref.WeakKeyDictionary()
)


class DockerError(Exception):
    pass


@dataclass(frozen=True)
class _Ran:
    returncode: int
    output: str


async def _docker(*args: str, check: bool = True) -> _Ran:
    try:
        process = await asyncio.create_subprocess_exec(
            "docker",
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError as exc:
        raise DockerError("Docker isn't installed, or `docker` isn't on PATH.") from exc
    out, _ = await process.communicate()
    ran = _Ran(process.returncode or 0, out.decode("utf-8", errors="replace").strip())
    if check and ran.returncode != 0:
        raise DockerError(f"docker {args[0]} failed: {ran.output}")
    return ran


async def ensure_sandbox_network() -> None:
    """Create the internal network and start the egress proxy, unless they're already there."""
    lock = _setup_locks.setdefault(asyncio.get_running_loop(), asyncio.Lock())
    async with lock:
        info = await _docker("info", "--format", "{{.ServerVersion}}", check=False)
        if info.returncode != 0:
            raise DockerError(f"Docker isn't running: {info.output}")
        for image, hint in BUILD_HINTS.items():
            if (await _docker("image", "inspect", image, check=False)).returncode != 0:
                raise DockerError(f"The image {image} isn't built yet. Build it with: {hint}")
        if (await _docker("network", "inspect", NETWORK, check=False)).returncode != 0:
            await _docker("network", "create", "--internal", NETWORK)
        running = await _docker("inspect", "-f", "{{.State.Running}}", PROXY, check=False)
        if running.output != "true":
            await _docker("rm", "-f", PROXY, check=False)
            await _docker("run", "-d", "--rm", "--name", PROXY, "--network", "bridge", PROXY_IMAGE)
            await _docker("network", "connect", NETWORK, PROXY)


class DockerExecutor(LocalExecutor):
    """Use as `async with DockerExecutor(root) as executor:`, which starts and removes the
    container."""

    def __init__(
        self,
        root: Path,
        spill_dir: Path | None = None,
        max_output_bytes: int = MAX_OUTPUT_BYTES,
        image: str = SANDBOX_IMAGE,
    ) -> None:
        super().__init__(root, shell="bash", spill_dir=spill_dir, max_output_bytes=max_output_bytes)
        self.image = image
        self.container = f"zwans-{secrets.token_hex(4)}"
        self._tokens: dict[int, str] = {}  # pid of each `docker exec` -> its run token

    async def start(self) -> None:
        await ensure_sandbox_network()
        self.spill_dir.mkdir(parents=True, exist_ok=True)
        user: list[str] = []
        if sys.platform != "win32":  # an if statement, so mypy knows getuid exists here
            user = ["--user", f"{os.getuid()}:{os.getgid()}"]
        proxy = [f"{name}={PROXY_URL}" for name in ("HTTP_PROXY", "HTTPS_PROXY")]
        proxy += [f"{name.lower()}={PROXY_URL}" for name in ("HTTP_PROXY", "HTTPS_PROXY")]
        env = [*proxy, "NO_PROXY=localhost,127.0.0.1", "no_proxy=localhost,127.0.0.1"]
        await _docker(
            "run",
            "-d",
            "--rm",
            "--init",  # a real PID 1 that reaps finished processes
            "--name",
            self.container,
            "--network",
            NETWORK,
            "--volume",
            f"{self.root}:{self.root}",
            "--volume",
            f"{self.spill_dir}:{self.spill_dir}:ro",
            "--workdir",
            str(self.root),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "1024",
            "--memory",
            "4g",
            *user,
            *[arg for value in env for arg in ("--env", value)],
            self.image,
            "sleep",
            "infinity",
        )

    async def stop(self) -> None:
        await _docker("rm", "-f", self.container, check=False)

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.stop()

    async def run_shell(self, command: str, timeout: float) -> CommandResult:
        return await self.run(["bash", "-c", command], timeout)

    async def _spawn(self, argv: Sequence[str]) -> asyncio.subprocess.Process:
        token = secrets.token_hex(6)
        process = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            "--env",
            f"ZWANS_RUN={token}",
            self.container,
            "bash",
            "-c",
            WRAPPER,
            "zwans",  # $0 for the wrapper; the command follows as "$@"
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **own_process_group(),
        )
        self._tokens[process.pid] = token
        return process

    async def _stop(self, process: asyncio.subprocess.Process) -> None:
        token = self._tokens.pop(process.pid, None)
        if process.returncode is None and token is not None:
            await _docker(
                "exec", self.container, "bash", "-c", KILL.format(token=token), check=False
            )
        await kill_tree(process)
