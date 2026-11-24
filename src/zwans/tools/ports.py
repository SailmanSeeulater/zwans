"""The Ports tool: which processes are listening on which TCP ports.

"Address already in use", a dev server that won't start, a second copy of the app still
running from an hour ago: each starts with knowing what holds a port. This asks lsof (or ss
on Linux) for the listening TCP sockets, then ps for each process's age and command line and
its working folder, and marks the processes started inside this project. IPv4 and IPv6
sockets of one process on one port are one row, and so are the workers sharing a socket.

It only looks. Stopping a process is a Bash `kill`, which the policy judges like any command.
lsof and ps run directly rather than in the sandbox, which would hide other processes.
"""

import asyncio
import contextlib
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput

TIMEOUT = 30.0
MAX_ROWS = 60
MAX_COMMAND = 120
MAX_FOLDER = 50
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}
ALL_HOSTS = {"*", "0.0.0.0", "::", "[::]"}
SS_PROCESS = re.compile(r'\("([^"]*)",pid=(\d+)')


@dataclass(frozen=True)
class Ran:
    exit_code: int
    stdout: str
    stderr: str


async def run_program(
    argv: list[str], cwd: Path | str | None = None, timeout: float = TIMEOUT
) -> Ran:
    """Run a program directly (not in the sandbox), with the environment Zwans has, and wait
    for it. A program that takes longer than `timeout` is stopped and reported."""
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise ToolError(f"Couldn't start {argv[0]}: {exc}") from exc
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise ToolError(f"{Path(argv[0]).name} didn't answer within {timeout:.0f}s.") from None
    except asyncio.CancelledError:
        process.kill()
        raise
    return Ran(
        process.returncode if process.returncode is not None else -1,
        out.decode("utf-8", "replace"),
        err.decode("utf-8", "replace"),
    )


class PortsInput(BaseModel):
    port: int | None = Field(
        default=None, ge=1, le=65535, description="Only this TCP port. Leave it out for all."
    )


@dataclass
class Listener:
    port: int
    pids: list[int] = field(default_factory=list)
    hosts: set[str] = field(default_factory=set)
    program: str = ""  # the short command name lsof or ss gave


class PortsTool:
    name = "Ports"
    description = (
        "See which processes are listening on which TCP ports: for each port, whether it's "
        "open to localhost only or all interfaces, the process id, how long it has run, its "
        "command line and its working folder, with processes started in this project marked. "
        "Give a port to check just that one, as when a server says the address is in use. "
        "It never stops anything: to stop a process, run `kill <pid>` with Bash."
    )
    input_model = PortsInput
    read_only = True

    async def run(self, args: PortsInput, ctx: ToolContext) -> ToolOutput:
        root = Path(getattr(ctx.executor, "root")).resolve()  # noqa: B009 (not on the protocol)
        lsof = shutil.which("lsof")
        ss = shutil.which("ss")
        if lsof:
            listeners = await _lsof_listeners(lsof, root)
        elif ss:
            listeners = await _ss_listeners(ss, root)
        else:
            raise ToolError("Neither lsof nor ss is installed, so ports can't be listed.")
        if args.port is not None:
            listeners = [item for item in listeners if item.port == args.port]
            if not listeners:
                return ToolOutput(
                    content=f"Nothing is listening on TCP port {args.port}; it's free. "
                    "(Processes of other users may be hidden without sudo.)"
                )
        if not listeners:
            return ToolOutput(content="No process is listening on a TCP port.")
        pids = sorted({pid for item in listeners for pid in item.pids})
        processes = await _processes(pids, root)
        folders = await _folders(pids, lsof, root)
        return ToolOutput(content=_table(listeners, processes, folders, root))


async def _lsof_listeners(lsof: str, root: Path) -> list[Listener]:
    ran = await run_program([lsof, "-nP", "-iTCP", "-sTCP:LISTEN", "-FpcnPT"], root)
    if ran.exit_code not in (0, 1) and not ran.stdout.strip():
        raise ToolError(f"lsof failed: {ran.stderr.strip() or f'exit code {ran.exit_code}'}")
    return parse_lsof(ran.stdout)


def parse_lsof(text: str) -> list[Listener]:
    """Listeners from `lsof -F pcnPT` output: a `p` line starts a process, `c` names it, `f`
    starts a file of it, and its `n` line is the address, as "*:8080" or "[::1]:3000"."""
    found: dict[int, Listener] = {}
    pid = 0
    command = ""
    for line in text.splitlines():
        if not line:
            continue
        tag, value = line[0], line[1:]
        if tag == "p":
            pid = int(value) if value.isdigit() else 0
            command = ""
        elif tag == "c":
            command = value
        elif tag == "n":
            parsed = _host_port(value)
            if parsed is None:
                continue
            host, port = parsed
            listener = found.setdefault(port, Listener(port))
            if pid and pid not in listener.pids:
                listener.pids.append(pid)
            listener.hosts.add(host)
            listener.program = listener.program or command
    return sorted(found.values(), key=lambda item: item.port)


async def _ss_listeners(ss: str, root: Path) -> list[Listener]:
    ran = await run_program([ss, "-ltnpH"], root)
    if ran.exit_code != 0:
        raise ToolError(f"ss failed: {ran.stderr.strip() or f'exit code {ran.exit_code}'}")
    return parse_ss(ran.stdout)


def parse_ss(text: str) -> list[Listener]:
    """Listeners from `ss -ltnpH`: state, queues, local address, peer, and the processes,
    as users:(("node",pid=12,fd=20)) when ss may see them."""
    found: dict[int, Listener] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        parsed = _host_port(parts[3])
        if parsed is None:
            continue
        host, port = parsed
        listener = found.setdefault(port, Listener(port))
        listener.hosts.add(host)
        for name, pid in SS_PROCESS.findall(" ".join(parts[5:])):
            if int(pid) not in listener.pids:
                listener.pids.append(int(pid))
            listener.program = listener.program or name
    return sorted(found.values(), key=lambda item: item.port)


def _host_port(address: str) -> tuple[str, int] | None:
    host, _, port = address.rpartition(":")
    if not port.isdigit() or not host:
        return None
    host = host.strip("[]").split("%", 1)[0]  # "[::1]", "127.0.0.53%lo"
    return host or "*", int(port)


def _scope(hosts: set[str]) -> str:
    if hosts & ALL_HOSTS:
        return "all interfaces"
    specific = sorted(hosts - LOCAL_HOSTS)
    if not specific:
        return "localhost only"
    return ", ".join(specific)


@dataclass(frozen=True)
class Process:
    pid: int
    parent: int
    elapsed: str
    command: str


async def _processes(pids: list[int], root: Path) -> dict[int, Process]:
    ps = shutil.which("ps")
    if not ps or not pids:
        return {}
    joined = ",".join(str(pid) for pid in pids)
    ran = await run_program([ps, "-o", "pid=,ppid=,etime=,command=", "-p", joined], root)
    return parse_ps(ran.stdout)


def parse_ps(text: str) -> dict[int, Process]:
    found: dict[int, Process] = {}
    for line in text.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 3 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        command = parts[3] if len(parts) > 3 else ""
        found[int(parts[0])] = Process(int(parts[0]), int(parts[1]), uptime(parts[2]), command)
    return found


def uptime(etime: str) -> str:
    """ps's elapsed time, "[[dd-]hh:]mm:ss", as "16d 4h", "3h 12m", "5m 3s" or "40s"."""
    days, _, clock = etime.rpartition("-")
    pieces = clock.split(":")
    if not all(piece.isdigit() for piece in pieces) or (days and not days.isdigit()):
        return etime
    numbers = [0] * (3 - len(pieces)) + [int(piece) for piece in pieces]
    hours, minutes, seconds = numbers[-3:]
    if days:
        return f"{int(days)}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


async def _folders(pids: list[int], lsof: str | None, root: Path) -> dict[int, str]:
    if not pids:
        return {}
    if lsof:
        joined = ",".join(str(pid) for pid in pids)
        ran = await run_program([lsof, "-a", "-d", "cwd", "-Fn", "-p", joined], root)
        found: dict[int, str] = {}
        pid = 0
        for line in ran.stdout.splitlines():
            if line.startswith("p") and line[1:].isdigit():
                pid = int(line[1:])
            elif line.startswith("n") and pid:
                found[pid] = line[1:]
        return found
    found = {}
    for pid in pids:  # Linux without lsof
        with contextlib.suppress(OSError):
            found[pid] = os.readlink(f"/proc/{pid}/cwd")
    return found


def _folder(path: str, root: Path) -> tuple[str, bool]:
    """How to show a working folder, and whether it's inside the workspace."""
    if not path:
        return "", False
    try:
        inside = Path(path).resolve().relative_to(root)
    except (ValueError, OSError):
        home = str(Path.home())
        shown = "~" + path[len(home) :] if path.startswith(home + os.sep) else path
        if len(shown) > MAX_FOLDER:
            shown = "…" + shown[-(MAX_FOLDER - 1) :]
        return shown, False
    sub = inside.as_posix()
    return ("this project" if sub == "." else f"this project: {sub}"), True


def _table(
    listeners: list[Listener],
    processes: dict[int, Process],
    folders: dict[int, str],
    root: Path,
) -> str:
    rows: list[tuple[bool, int, list[str]]] = []
    for item in listeners:
        # The process that opened the socket, not the workers it shares it with
        mains = [
            pid
            for pid in item.pids
            if processes.get(pid, Process(0, 0, "", "")).parent not in item.pids
        ] or item.pids
        pid = mains[0] if mains else 0
        process = processes.get(pid)
        command = process.command if process else item.program
        if len(command) > MAX_COMMAND:
            command = command[: MAX_COMMAND - 1] + "…"
        others = len(item.pids) - 1
        if others > 0:
            command += f"  (+{others} more process{'es' if others > 1 else ''} on it)"
        folder, ours = _folder(folders.get(pid, ""), root)
        rows.append(
            (
                ours,
                item.port,
                [
                    str(item.port),
                    _scope(item.hosts),
                    str(pid) if pid else "?",
                    process.elapsed if process else "",
                    folder,
                    command,
                ],
            )
        )
    rows.sort(key=lambda row: (not row[0], row[1]))
    cut = len(rows) - MAX_ROWS
    cells = [["PORT", "ADDRESS", "PID", "UP", "FOLDER", "COMMAND"]]
    cells += [row[2] for row in rows[:MAX_ROWS]]
    widths = [max(len(line[n]) for line in cells) for n in range(5)]
    lines = [
        "  ".join(cell.ljust(width) for cell, width in zip(line[:5], widths, strict=True))
        + "  "
        + line[5]
        for line in cells
    ]
    project = sum(1 for row in rows if row[0])
    head = f"{len(rows)} TCP port{'s' if len(rows) != 1 else ''} listening"
    head += f", {project} from this project (listed first)." if project else "."
    lines.insert(0, head)
    if cut > 0:
        lines.append(f"({cut} more not shown. Give a port to see one.)")
    lines.append("Processes of other users may be hidden without sudo. To stop one: kill <pid>.")
    return "\n".join(line.rstrip() for line in lines)


def available() -> bool:
    return shutil.which("lsof") is not None or shutil.which("ss") is not None
