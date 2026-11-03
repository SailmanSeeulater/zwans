"""The `zwans` command: a chat when run alone, or `zwans run "<task>"` for a single task."""

import asyncio
import io
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from zwans import __version__
from zwans.cli.approval import can_prompt, load_with_trust, terminal_approver
from zwans.cli.attach import Attached, AttachError, open_remote
from zwans.cli.evals import eval_app
from zwans.cli.render import Renderer
from zwans.cli.serve import read_server_file, serve
from zwans.config import ConfigError, load_settings
from zwans.executor.docker import DockerError
from zwans.policy import PolicyError
from zwans.runtime import OpenedSession, open_session
from zwans.store import SessionError, SessionStore

app = typer.Typer(add_completion=False)
app.add_typer(eval_app, name="eval")
app.command()(serve)

EXIT_INTERRUPTED = 130  # the usual exit code after Ctrl+C

Workspace = Annotated[
    Path,
    typer.Option(
        "--workspace", "-w", exists=True, file_okay=False, help="Folder the agent works in."
    ),
]
Model = Annotated[str | None, typer.Option(help="Model to use instead of the configured one.")]
Resume = Annotated[
    str | None,
    typer.Option(help="Continue a saved session: its id from `zwans sessions`, or its start."),
]
Rewind = Annotated[
    int | None, typer.Option(min=1, help="With --resume, first drop every turn after this one.")
]


class ModeName(StrEnum):
    read_only = "read-only"
    ask = "ask"
    auto = "auto"


PermissionMode = Annotated[
    ModeName | None,
    typer.Option(
        "--mode",
        help="read-only: only reading. ask (default): ask before changes. auto: edits and local "
        "commands run, network and unknown commands ask. Overrides the policy files.",
    ),
]
FakeScript = Annotated[
    Path | None,
    typer.Option(hidden=True, help="Replay model responses from a JSON file, for demos and tests."),
]


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"zwans {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_show_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
    workspace: Workspace = Path("."),
    model: Model = None,
    resume: Resume = None,
    rewind: Rewind = None,
    mode: PermissionMode = None,
    fake_script: FakeScript = None,
) -> None:
    """Zwans: a coding agent built from scratch. With no command, starts a chat."""
    if ctx.invoked_subcommand is None:
        raise typer.Exit(_start(None, workspace, model, resume, rewind, mode, fake_script))


@app.command()
def run(
    task: Annotated[str, typer.Argument(help="What the agent should do.")],
    workspace: Workspace = Path("."),
    model: Model = None,
    resume: Resume = None,
    rewind: Rewind = None,
    mode: PermissionMode = None,
    fake_script: FakeScript = None,
) -> None:
    """Do one task, then exit. The exit code is 0 when the model finished normally."""
    raise typer.Exit(_start(task, workspace, model, resume, rewind, mode, fake_script))


@app.command()
def sessions(limit: Annotated[int, typer.Option(min=1, help="How many to list.")] = 20) -> None:
    """List saved sessions, most recent first."""
    config, _ = load_settings()
    store = SessionStore(config.home / "sessions.db")
    found = store.recent(limit)
    store.close()
    if not found:
        typer.echo("No saved sessions yet.")
    for info in found:
        when = info.updated_at.replace("T", " ")[:16]
        dollars = float(info.usage.get("dollars", 0.0))
        turns = _count(info.turns, "turn")
        typer.echo(f"{info.id}  {when}  {turns:>9}  ${dollars:7.4f}  {info.title}")


@app.command()
def attach(
    session: Annotated[
        str | None,
        typer.Argument(help="A session's id, or its start. Leave it out for a new session."),
    ] = None,
    workspace: Workspace = Path("."),
    mode: PermissionMode = None,
) -> None:
    """Follow and drive a session in a running `zwans serve`, alongside the web UI: one that's
    open there, a saved one, or a new one in --workspace."""
    config, _ = load_settings()
    server = read_server_file(config.home)
    if server is None:
        typer.secho("No Zwans server is running. Start one with `zwans serve`.", fg="red", err=True)
        raise typer.Exit(2)
    url, token = str(server["url"]), str(server["token"])
    try:
        status = open_remote(url, token, session, workspace, mode.value if mode else None)
    except AttachError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2) from exc
    label = f"{status['model']} | mode {status['mode']} | {status['workspace']}"
    typer.secho(f"Attached to {status['id']} | {label}", dim=True)
    for warning in status.get("warnings", []):
        typer.secho(warning, fg="yellow")
    typer.secho(
        "Type a task. Ctrl+C stops a running turn; with nothing running, Ctrl+C or 'exit' "
        "detaches and the session carries on in the server.",
        dim=True,
    )
    try:
        asyncio.run(Attached(url, token, str(status["id"])).run())
    except KeyboardInterrupt:
        pass  # Windows, where Ctrl+C can't be caught to interrupt the turn instead
    except OSError as exc:
        typer.secho(f"Lost the connection to {url}: {exc}", fg="red", err=True)
        raise typer.Exit(1) from exc
    typer.secho(f"\nDetached. Session {status['id']} is still open in {url}/", dim=True)


def _start(
    task: str | None,
    workspace: Path,
    model: str | None,
    resume: str | None,
    rewind: int | None,
    mode: ModeName | None,
    fake_script: Path | None,
) -> int:
    _tolerate_unprintable_text()
    if rewind is not None and resume is None:
        typer.secho("--rewind only works together with --resume.", fg="red", err=True)
        return 2
    try:
        config, env = load_settings()
        opened = open_session(
            config,
            env,
            workspace=workspace,
            resume=resume,
            rewind=rewind,
            model=model,
            mode=mode.value if mode else None,
            approver=terminal_approver if can_prompt() else None,
            listeners=[Renderer().on_event],
            policy_loader=load_with_trust,
            fake_script=fake_script,
        )
    except (ConfigError, SessionError, PolicyError) as exc:
        typer.secho(str(exc), fg="red", err=True)
        return 2
    _banner(opened, scripted=fake_script is not None)
    # One event loop for the whole session, so the API client's connections stay usable.
    with asyncio.Runner() as runner:
        try:
            tools, problems = runner.run(opened.start())
        except DockerError as exc:
            typer.secho(str(exc), fg="red", err=True)
            runner.run(opened.close())
            return 2
        for problem in problems:
            typer.secho(f"MCP server skipped: {problem}", fg="yellow", err=True)
        if opened.mcp is not None:
            for name in opened.mcp.servers:
                count = sum(t.connection.name == name for t in tools)
                if count:
                    typer.secho(f"MCP {name}: {_count(count, 'tool')}", dim=True)
        try:
            if task is None:
                return _chat(opened, runner)
            return _run_once(opened, runner, task)
        finally:
            runner.run(opened.close())
            typer.secho(f"\nSession cost: {opened.meter.summary()}", dim=True)
            typer.secho(f"To continue it: zwans --resume {opened.id}", dim=True)


def _banner(opened: OpenedSession, scripted: bool) -> None:
    for path in opened.instructions:
        typer.secho(f"Following {path}", dim=True)
    config, info = opened.config, opened.info
    label = "scripted responses" if scripted else f"{opened.model}, effort {config.effort}"
    label += f" | {config.executor}"
    mode = opened.policy.policy.mode
    typer.secho(f"Zwans {__version__} | {label} | mode {mode} | {info.workspace}", dim=True)
    if opened.resumed:
        typer.secho(f"Resumed {info.id} after {_count(info.turns, 'turn')}: {info.title}", dim=True)
    if opened.repaired:
        typer.secho("Its last turn was cut off mid-tool; those calls are marked unfinished.")


def _chat(opened: OpenedSession, runner: asyncio.Runner) -> int:
    typer.secho("Type a task. Ctrl+C stops a running turn; 'exit' or Ctrl+C here quits.", dim=True)
    while True:
        try:
            task = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if task in ("exit", "quit"):
            return 0
        if not task:
            continue
        try:
            runner.run(opened.session.send(task))
        except KeyboardInterrupt:
            typer.secho("Interrupted. The conversation is kept, so carry on.", fg="yellow")
        _print_turn(opened)


def _run_once(opened: OpenedSession, runner: asyncio.Runner, task: str) -> int:
    try:
        stop_reason = runner.run(opened.session.send(task))
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    _print_turn(opened)
    return 0 if stop_reason == "end_turn" else 1


def _print_turn(opened: OpenedSession) -> None:
    context = f"context about {opened.session.context_tokens():,} tokens"
    hits = f"{opened.meter.cache_hit_rate:.0%} of input from cache so far"
    typer.secho(f"Turn cost ${opened.meter.turn_dollars:.4f}, {context}, {hits}", dim=True)


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _tolerate_unprintable_text() -> None:
    """Show characters the terminal can't encode as "?" instead of crashing on them."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")
