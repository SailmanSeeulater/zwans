"""The Containers tool: Docker containers, their state and their logs, without changing them.

A project run with Docker Compose fails in ways a model can't see from the code: a database
container that keeps restarting, a health check that fails, a service that was killed for
memory. This lists the containers with their state, ports and Compose project (this
project's first), and for one container gives what `docker inspect` says about its state,
health checks, restarts, exit code, ports and mounts, and the end of its logs. Environment
variables are listed by name only; their values are never read out.

It runs the docker CLI (or podman's, which takes the same commands) directly, since the
sandbox can't reach the Docker daemon. It only looks: it starts, stops and removes nothing.
"""

import json
import re
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.ports import run_program

TIMEOUT = 30.0
MAX_ROWS = 80
MAX_CELL = 40
MAX_LOG_LINE = 500
MAX_HEALTH_OUTPUT = 300
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
LOG_TIME = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\.\d+(Z|[+-]\d\d:\d\d)")
LOG_ORDER = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?")
LABEL_START = re.compile(r"^[A-Za-z0-9][\w.\-/]*=")
NO_DAEMON = (
    "cannot connect to the docker daemon",
    "is the docker daemon running",
    "failed to connect to the docker api",
    "cannot connect to podman",
)
PROJECT = "com.docker.compose.project"
SERVICE = "com.docker.compose.service"
WORKING_DIR = "com.docker.compose.project.working_dir"


class ContainersInput(BaseModel):
    container: str | None = Field(
        default=None,
        description="A container's name or id, for its details and logs. Leave it out to "
        "list all containers.",
    )
    tail: int = Field(
        default=40, ge=1, le=300, description="How many of the container's last log lines."
    )


class ContainersTool:
    name = "Containers"
    description = (
        "Look at Docker containers without changing them. Without a container: every "
        "container with its image, state and health, ports, and Compose project and service, "
        "this project's first. With a container's name or id: its state, health check "
        "results, restart count, exit code, whether it was killed for memory, ports, mounts, "
        "the names of its environment variables, and its last log lines. Use it when a "
        "service run with Docker or Compose won't start, keeps restarting or misbehaves."
    )
    input_model = ContainersInput
    read_only = True

    async def run(self, args: ContainersInput, ctx: ToolContext) -> ToolOutput:
        program = shutil.which("docker") or shutil.which("podman")
        if not program:
            raise ToolError("Neither docker nor podman is installed.")
        root = Path(getattr(ctx.executor, "root")).resolve()  # noqa: B009 (not on the protocol)
        name = (args.container or "").strip()
        if not name:
            return ToolOutput(content=await _list(program, root))
        return ToolOutput(content=await _details(program, name, args.tail, root))


async def _docker(program: str, args: list[str], root: Path) -> str:
    ran = await run_program([program, *args], root, TIMEOUT)
    if ran.exit_code != 0:
        said = (ran.stderr.strip() or ran.stdout.strip() or f"exit code {ran.exit_code}")[:500]
        if any(marker in said.lower() for marker in NO_DAEMON):
            raise ToolError(
                f"The {Path(program).name} daemon isn't running, so containers can't be "
                f"seen. Start Docker (or the podman machine) first. It said: {said}"
            )
        raise ToolError(f"{Path(program).name} {args[0]} failed: {said}")
    return ran.stdout


async def _list(program: str, root: Path) -> str:
    out = await _docker(program, ["ps", "-a", "--format", "{{json .}}"], root)
    containers = parse_ps(out)
    if not containers:
        return f"No containers ({Path(program).name} ps -a lists none)."
    rows = []
    for item in containers:
        labels = item["labels"]
        compose = labels.get(PROJECT, "")
        if compose and labels.get(SERVICE):
            compose += "/" + labels[SERVICE]
        ours = _inside(labels.get(WORKING_DIR, ""), root)
        if ours:
            compose += " (this project)"
        cells = [item["name"], item["image"], item["status"], item["ports"], compose]
        rows.append((not ours, [_cap(cell) for cell in cells[:4]] + [compose]))
    rows.sort(key=lambda row: row[0])  # stable: docker's order (newest first) otherwise
    cut = len(rows) - MAX_ROWS
    table = [["NAME", "IMAGE", "STATUS", "PORTS", "COMPOSE"], *[row[1] for row in rows[:MAX_ROWS]]]
    widths = [max(len(line[n]) for line in table) for n in range(4)]
    lines = [
        "  ".join(cell.ljust(width) for cell, width in zip(line[:4], widths, strict=True))
        + "  "
        + line[4]
        for line in table
    ]
    running = sum(1 for item in containers if item["state"] == "running")
    head = f"{len(containers)} containers ({running} running), from {Path(program).name}:"
    tail = ["Give a container's name for its details and logs."]
    if cut > 0:
        tail.insert(0, f"({cut} more not shown.)")
    return "\n".join([head, *(line.rstrip() for line in lines), *tail])


def parse_ps(text: str) -> list[dict[str, Any]]:
    """Containers from `ps -a --format '{{json .}}'`, one JSON object a line. Docker gives
    names, labels and ports as strings, podman as lists and a map; both are read."""
    found = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, list):  # podman without the template prints one array
            items = [entry for entry in item if isinstance(entry, dict)]
        elif isinstance(item, dict):
            items = [item]
        else:
            continue
        for entry in items:
            found.append(_container(entry))
    return found


def _container(item: dict[str, Any]) -> dict[str, Any]:
    names = item.get("Names") or item.get("Name") or ""
    name = ", ".join(names) if isinstance(names, list) else str(names)
    state = str(item.get("State") or "")
    status = str(item.get("Status") or state)
    health = str(item.get("HealthStatus") or item.get("Health") or "")
    if health and health not in ("none", "") and health not in status:
        status += f" ({health})"
    return {
        "name": name,
        "id": str(item.get("ID") or item.get("Id") or "")[:12],
        "image": str(item.get("Image") or ""),
        "state": state.lower(),
        "status": status,
        "ports": _ports(item.get("Ports")),
        "labels": parse_labels(item.get("Labels")),
    }


def parse_labels(labels: Any) -> dict[str, str]:
    """Docker's labels as one string, "a=1,b=2", where a value may itself hold commas (a list
    of compose files); a piece that doesn't start like "key=" belongs to the value before."""
    if isinstance(labels, dict):
        return {str(key): str(value) for key, value in labels.items()}
    if not isinstance(labels, str) or not labels:
        return {}
    found: dict[str, str] = {}
    key = ""
    for piece in labels.split(","):
        if LABEL_START.match(piece) or not key:
            key, _, value = piece.partition("=")
            found[key] = value
        else:
            found[key] += "," + piece
    return found


def _ports(ports: Any) -> str:
    if isinstance(ports, list):  # podman
        shown = []
        for port in ports:
            if not isinstance(port, dict):
                continue
            host = port.get("host_port") or port.get("hostPort")
            inside = port.get("container_port") or port.get("containerPort")
            protocol = port.get("protocol") or "tcp"
            shown.append(f"{host}->{inside}/{protocol}" if host else f"{inside}/{protocol}")
        return ", ".join(shown)
    if not isinstance(ports, str):
        return ""
    pieces = [piece.strip() for piece in ports.split(",") if piece.strip()]
    # "0.0.0.0:5433->5432/tcp, [::]:5433->5432/tcp" is one mapping, on IPv4 and IPv6
    kept = [
        piece
        for piece in pieces
        if not (piece.startswith("[::]:") and "0.0.0.0:" + piece[5:] in pieces)
    ]
    return ", ".join(piece.removeprefix("0.0.0.0") for piece in kept)


def _inside(path: str, root: Path) -> bool:
    if not path:
        return False
    try:
        Path(path).resolve().relative_to(root)
    except (ValueError, OSError):
        return False
    return True


def _cap(text: str, limit: int = MAX_CELL) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def _details(program: str, name: str, tail: int, root: Path) -> str:
    try:
        out = await _docker(program, ["inspect", "--type", "container", name], root)
    except ToolError as exc:
        if "no such" in str(exc).lower():
            raise ToolError(
                f"No container is named {name!r}. Call Containers without a container to list them."
            ) from None
        raise
    try:
        inspected = json.loads(out)
    except json.JSONDecodeError as exc:
        raise ToolError(f"{Path(program).name} inspect gave something unreadable.") from exc
    if not isinstance(inspected, list) or not inspected or not isinstance(inspected[0], dict):
        raise ToolError(f"No container is named {name!r}.")
    lines = describe(inspected[0], root)
    logs = await run_program(
        [program, "logs", "--tail", str(tail), "--timestamps", name], root, TIMEOUT
    )
    lines.append("")
    if logs.exit_code != 0:
        lines.append(f"Its logs couldn't be read: {logs.stderr.strip()[:300]}")
    else:
        lines += log_lines(logs.stdout, logs.stderr, tail)
    return "\n".join(lines)


def describe(data: dict[str, Any], root: Path) -> list[str]:
    """What docker inspect says about a container, as lines. Environment variables are
    named only; their values are dropped here and never shown."""
    config = data.get("Config") or {}
    state = data.get("State") or {}
    name = str(data.get("Name") or "").lstrip("/")
    lines = [f"Container {name} ({str(data.get('Id') or '')[:12]}), image {config.get('Image')}"]

    status = str(state.get("Status") or "unknown")
    started = _time(state.get("StartedAt"))
    finished = _time(state.get("FinishedAt"))
    restarts = data.get("RestartCount", 0)
    if state.get("Running"):
        line = f"State: {status} since {started}"
        if state.get("Pid"):
            line += f" (pid {state.get('Pid')})"
    else:
        line = f"State: {status}, exit code {state.get('ExitCode')}"
        if finished:
            line += f", stopped {finished}"
        if started:
            line += f" (started {started})"
    line += f"; restarted {restarts} time{'s' if restarts != 1 else ''}"
    lines.append(line)
    if state.get("OOMKilled"):
        lines.append("It was killed for running out of memory (OOMKilled).")
    if state.get("Error"):
        lines.append(f"Error: {state.get('Error')}")
    if state.get("Restarting"):
        lines.append("It is restarting now.")
    policy = (data.get("HostConfig") or {}).get("RestartPolicy") or {}
    if policy.get("Name") and policy.get("Name") != "no":
        lines.append(f"Restart policy: {policy.get('Name')}")

    health = state.get("Health") or state.get("Healthcheck")
    if isinstance(health, dict) and health.get("Status"):
        lines.append(
            f"Health: {health.get('Status')}, failing streak {health.get('FailingStreak', 0)}"
        )
        for check in (health.get("Log") or [])[-3:]:
            output = _clean(str(check.get("Output") or "")).strip().replace("\n", " | ")
            lines.append(
                f"  {_time(check.get('End') or check.get('Start'))}  exit "
                f"{check.get('ExitCode')}  {_cap(output, MAX_HEALTH_OUTPUT)}"
            )

    labels = parse_labels(config.get("Labels"))
    if labels.get(PROJECT):
        folder = labels.get(WORKING_DIR, "")
        ours = " (this project)" if _inside(folder, root) else ""
        lines.append(
            f"Compose: project {labels[PROJECT]}, service {labels.get(SERVICE, '?')}, "
            f"folder {folder or '?'}{ours}"
        )

    ports = (data.get("NetworkSettings") or {}).get("Ports") or {}
    shown = []
    for inside, bindings in sorted(ports.items()):
        if not bindings:
            shown.append(f"{inside} (not published)")
            continue
        hosts = sorted({f"{b.get('HostIp') or '0.0.0.0'}:{b.get('HostPort')}" for b in bindings})
        if "0.0.0.0:" + str(bindings[0].get("HostPort")) in hosts:
            hosts = [h for h in hosts if not h.startswith("::")]
        shown.append(f"{inside} -> {', '.join(hosts)}")
    if shown:
        lines.append("Ports: " + "; ".join(shown))

    mounts = data.get("Mounts") or []
    if mounts:
        lines.append("Mounts:")
        for mount in mounts[:15]:
            source = mount.get("Name") if mount.get("Type") == "volume" else mount.get("Source")
            mode = "rw" if mount.get("RW", True) else "ro"
            lines.append(
                f"  {mount.get('Type', '?')} {source} -> {mount.get('Destination')} ({mode})"
            )
        if len(mounts) > 15:
            lines.append(f"  ({len(mounts) - 15} more)")

    names = sorted({str(entry).split("=", 1)[0] for entry in config.get("Env") or []})
    if names:
        lines.append(f"Environment variable names ({len(names)}; values not shown): ")
        lines[-1] += ", ".join(names)
    return lines


def log_lines(stdout: str, stderr: str, tail: int) -> list[str]:
    """The last log lines, from both streams, with colors taken out and times shortened to
    the second. Docker writes the container's stderr to its own stderr, so the two are
    merged by their timestamps."""
    lines = [line for line in (stdout.splitlines() + stderr.splitlines()) if line.strip()]
    lines = [_clean(line) for line in lines]
    lines.sort(key=_log_order)
    lines = lines[-tail:]
    if not lines:
        return ["No log lines."]
    shown = [
        _cap(LOG_TIME.sub(lambda m: m.group(1) + m.group(2), line), MAX_LOG_LINE) for line in lines
    ]
    return [f"Last {len(shown)} log line{'s' if len(shown) != 1 else ''}:", *shown]


def _log_order(line: str) -> tuple[str, float]:
    match = LOG_ORDER.match(line)
    if not match:
        return "", 0.0
    return match.group(1), float("0." + (match.group(2) or "0"))


def _clean(text: str) -> str:
    return ANSI.sub("", text).replace("\r", "")


def _time(value: Any) -> str:
    text = str(value or "")
    if not text or text.startswith("0001-01-01"):
        return ""
    match = LOG_TIME.match(text)
    return match.group(1) + match.group(2) if match else text


def available() -> bool:
    return shutil.which("docker") is not None or shutil.which("podman") is not None
