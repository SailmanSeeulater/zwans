"""Runs each command in zwans-jail, Zwans's own sandbox (runtime/, Linux only).

Every command gets a fresh sandbox: its own user, PID, mount, network, IPC and UTS
namespaces; a root that holds only the workspace (read-write), a private /tmp, and the
system folders it needs (read-only); no network; memory and process limits; a seccomp
allowlist; and Landlock path rules. Files still go through the workspace on this machine,
as with the other executors.

Build the jail once:
    cargo build --release --manifest-path runtime/Cargo.toml
"""

import asyncio
import json
import os
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from zwans.config import ConfigError
from zwans.executor.base import CommandResult
from zwans.executor.local import MAX_OUTPUT_BYTES, LocalExecutor, command_env, own_process_group

# The jail built in this checkout, when Zwans is installed from it with pip -e.
CHECKOUT_JAIL = (
    Path(__file__).resolve().parents[3] / "runtime" / "target" / "release" / "zwans-jail"
)
# Folders of system software, visible read-only when they exist.
SYSTEM_FOLDERS = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32", "/etc", "/opt")

# What the system prompt says about where commands run.
JAIL_OS = (
    "Linux, in a sandbox with no network. Only the workspace (read-write), /tmp, and system "
    "folders (read-only) exist there."
)


class JailError(ConfigError):
    pass


def find_jail() -> str:
    """The zwans-jail program: $ZWANS_JAIL, then PATH, then this checkout's build."""
    if sys.platform != "linux":
        raise JailError('The jail executor needs Linux. Use executor = "docker" here.')
    for candidate in (os.environ.get("ZWANS_JAIL"), shutil.which("zwans-jail"), str(CHECKOUT_JAIL)):
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise JailError(
        "zwans-jail isn't built. Build it with: "
        "cargo build --release --manifest-path runtime/Cargo.toml"
    )


class JailExecutor(LocalExecutor):
    def __init__(
        self,
        root: Path,
        spill_dir: Path | None = None,
        max_output_bytes: int = MAX_OUTPUT_BYTES,
        jail: str | None = None,
        memory_mb: int = 2048,
        max_processes: int = 256,
    ) -> None:
        super().__init__(root, shell="bash", spill_dir=spill_dir, max_output_bytes=max_output_bytes)
        self.jail = jail or find_jail()
        self.memory_mb = memory_mb
        self.max_processes = max_processes

    async def run_shell(self, command: str, timeout: float) -> CommandResult:
        return await self.run(["bash", "-c", command], timeout)

    def spec(self, argv: Sequence[str]) -> dict[str, Any]:
        env = command_env()
        env.update({"HOME": "/tmp", "TMPDIR": "/tmp"})  # the real home isn't there
        return {
            "argv": list(argv),
            "workspace": str(self.root),
            "read_only": read_only_paths(env.get("PATH", ""), self.root),
            "env": env,
            "memory_mb": self.memory_mb,
            "max_processes": self.max_processes,
        }

    async def _spawn(self, argv: Sequence[str]) -> asyncio.subprocess.Process:
        process = await asyncio.create_subprocess_exec(
            self.jail,
            cwd=self.root,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **own_process_group(),
        )
        assert process.stdin is not None
        process.stdin.write(json.dumps(self.spec(argv)).encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()
        return process


def read_only_paths(path_variable: str, workspace: Path) -> list[str]:
    """System folders, plus the software on PATH: for a .../bin folder, the environment
    around it (a conda env, a toolcache Python), so its libraries come along. Never the
    home folder itself, and nothing in the workspace, which is mounted read-write."""
    home = Path.home().resolve()
    found: list[str] = [folder for folder in SYSTEM_FOLDERS if Path(folder).exists()]
    for entry in path_variable.split(os.pathsep):
        if not entry or not os.path.isabs(entry):
            continue
        folder = Path(entry).resolve()
        if not folder.is_dir() or folder.is_relative_to(workspace):
            continue
        prefix = folder.parent if folder.name == "bin" else folder
        if prefix == home or home.is_relative_to(prefix):
            prefix = folder  # ~/bin: just the folder, not the home around it
        if not any(prefix.is_relative_to(known) for known in found):
            found.append(str(prefix))
    return found
