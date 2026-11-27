"""Runs each command under Seatbelt, the sandbox built into macOS.

A command can write only inside the workspace and the temporary folders, has no network,
and can't read the folders where credentials usually live. Nothing is installed and nothing
is started first: `sandbox-exec` applies the rules to the one process and whatever it
starts, in about the time it takes to start the process at all.

It is narrower than the jail (executor/jail.py), which shows a command nothing but the
workspace and system folders. Here the rest of the disk stays readable, because macOS
programs read from all over it, so what it promises is the three things above and no more.
Files Zwans's own tools read and write still go through the workspace on this machine, as
with the other executors.

Apple marks `sandbox-exec` as deprecated but ships it, and uses the same mechanism for its
own apps. If a macOS release removes it, this executor says so when a session starts.
"""

import asyncio
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from zwans.config import ConfigError
from zwans.executor.local import (
    MAX_OUTPUT_BYTES,
    LocalExecutor,
    command_env,
    find_program,
    own_process_group,
)

SANDBOX_EXEC = "/usr/bin/sandbox-exec"

# What the system prompt says about where commands run.
SEATBELT_OS = (
    "macOS, in a sandbox: commands can write only inside the workspace and the temporary "
    "folders, and have no network."
)

# Under the home folder: where keys, tokens and passwords are usually kept.
CREDENTIAL_FOLDERS = (
    ".ssh",
    ".aws",
    ".gnupg",
    ".kube",
    ".docker",
    ".config/gh",
    ".config/gcloud",
    "Library/Keychains",
)
CREDENTIAL_FILES = (".netrc", ".npmrc", ".pypirc", ".zwans/.env")
# Devices a program may write to: discarding output, and the terminal.
DEVICES = ("/dev/null", "/dev/zero", "/dev/dtracehelper", "/dev/tty")


class SeatbeltError(ConfigError):
    pass


def find_sandbox() -> str:
    if sys.platform != "darwin":
        raise SeatbeltError(
            'The seatbelt executor needs macOS. On Linux use executor = "jail", '
            'and anywhere else executor = "docker".'
        )
    if not os.access(SANDBOX_EXEC, os.X_OK):
        raise SeatbeltError(
            f"{SANDBOX_EXEC} is missing, so this macOS has no Seatbelt command. Use "
            'executor = "docker" instead.'
        )
    return SANDBOX_EXEC


class SeatbeltExecutor(LocalExecutor):
    def __init__(
        self,
        root: Path,
        shell: str | None = None,
        spill_dir: Path | None = None,
        max_output_bytes: int = MAX_OUTPUT_BYTES,
        home: Path | None = None,
    ) -> None:
        super().__init__(root, shell, spill_dir, max_output_bytes)
        self.home = home
        self.sandbox = find_sandbox()
        self.profile = profile(self.root, home or Path.home())

    def at(self, root: Path) -> "SeatbeltExecutor":
        return SeatbeltExecutor(root, self._shell, self.spill_dir, self.max_output_bytes, self.home)

    async def _spawn(
        self, argv: Sequence[str], background: bool = False, stdin: int = asyncio.subprocess.DEVNULL
    ) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
            self.sandbox,
            "-p",
            self.profile,
            find_program(argv[0]),
            *argv[1:],
            cwd=self.root,
            env=command_env(),
            stdin=stdin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **own_process_group(),
        )


def profile(workspace: Path, home: Path) -> str:
    """The Seatbelt rules for commands in `workspace`. The last rule that matches wins, so
    the broad ones come first."""
    temp = Path(tempfile.gettempdir()).resolve()
    # macOS gives each user /private/var/folders/xx/yyyy/, with T (temporary files) and C
    # (caches) inside; programs use both.
    per_user = temp.parent if temp.name == "T" else temp
    writable = [workspace.resolve(), per_user, Path("/private/tmp"), Path("/private/var/tmp")]
    home = home.resolve()
    lines = [
        "(version 1)",
        "(allow default)",
        "(deny network*)",
        "(deny file-write*)",
        "(allow file-write*",
        *(f"  (subpath {_quoted(folder)})" for folder in dict.fromkeys(writable)),
        *(f"  (literal {_quoted(Path(device))})" for device in DEVICES),
        ")",
        "(deny file-read*",
        *(f"  (subpath {_quoted(home / folder)})" for folder in CREDENTIAL_FOLDERS),
        *(f"  (literal {_quoted(home / file)})" for file in CREDENTIAL_FILES),
        ")",
    ]
    return "\n".join(lines)


def _quoted(path: Path) -> str:
    """A path as a string in the profile's language, which is a Scheme."""
    text = str(path).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'
