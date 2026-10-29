"""The `zwans` command: a chat when run alone, or `zwans run "<task>"` for a single task."""

import asyncio
import io
import secrets
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from zwans import __version__
from zwans.cli.approval import can_prompt, load_with_trust, terminal_approver
from zwans.cli.evals import eval_app
from zwans.cli.render import Renderer
from zwans.config import ConfigError, load_credential, load_settings
from zwans.context.compaction import Compactor
from zwans.context.instructions import load_instructions
from zwans.executor.docker import SANDBOX_OS, DockerError, DockerExecutor
from zwans.executor.local import LocalExecutor, find_bash
from zwans.messages import Message
from zwans.policy import Permissions, PolicyError
from zwans.pricing import CostMeter
from zwans.prompt import system_prompt
from zwans.providers.anthropic import AnthropicProvider
from zwans.providers.base import Provider
from zwans.providers.fake import FakeProvider
from zwans.session import Session
from zwans.store import SessionError, SessionInfo, SessionRecorder, SessionStore, load_session
from zwans.tools.base import ToolContext
from zwans.tools.bash import BashTool
from zwans.tools.edit import EditTool
from zwans.tools.glob import GlobTool
from zwans.tools.grep import GrepTool
from zwans.tools.read import ReadTool
from zwans.tools.write import WriteTool
from zwans.transcript import TranscriptWriter

app = typer.Typer(add_completion=False)
app.add_typer(eval_app, name="eval")

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


@dataclass
class _Opened:
    session: Session
    executor: LocalExecutor
    meter: CostMeter
    transcript: TranscriptWriter
    store: SessionStore
    session_id: str


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
        opened = _open(workspace, model, resume, rewind, mode, fake_script)
    except (ConfigError, SessionError, PolicyError) as exc:
        typer.secho(str(exc), fg="red", err=True)
        return 2
    # One event loop for the whole session, so the API client's connections stay usable.
    with asyncio.Runner() as runner:
        if isinstance(opened.executor, DockerExecutor):
            try:
                runner.run(opened.executor.start())
            except DockerError as exc:
                typer.secho(str(exc), fg="red", err=True)
                opened.transcript.close()
                opened.store.close()
                return 2
        try:
            if task is None:
                return _chat(opened, runner)
            return _run_once(opened, runner, task)
        finally:
            if isinstance(opened.executor, DockerExecutor):
                runner.run(opened.executor.stop())
            runner.run(opened.session.provider.aclose())
            opened.transcript.close()
            opened.store.close()
            typer.secho(f"\nSession cost: {opened.meter.summary()}", dim=True)
            typer.secho(f"To continue it: zwans --resume {opened.session_id}", dim=True)


def _open(
    workspace: Path,
    model: str | None,
    resume: str | None,
    rewind: int | None,
    mode: ModeName | None,
    fake_script: Path | None,
) -> _Opened:
    config, env = load_settings()
    store = SessionStore(config.home / "sessions.db")
    messages: list[Message] = []
    repaired = False
    if resume is not None:
        info, messages, repaired = load_session(store, resume, rewind)
        meter = CostMeter.restore(info.usage)
    else:
        root = workspace.resolve()
        instructions = load_instructions(root, config.home)
        if config.executor == "docker":
            system = system_prompt(root, "bash", instructions, SANDBOX_OS)
        else:
            system = system_prompt(root, _describe_shell(config.shell), instructions)
        session_id = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        info = SessionInfo(id=session_id, workspace=str(root), model=config.model, system=system)
        meter = CostMeter()
        for path, _ in instructions:
            typer.secho(f"Following {path}", dim=True)
    model = model or info.model

    provider: Provider
    if fake_script is not None:
        provider = FakeProvider.from_file(fake_script)
    else:
        credential = load_credential(config, env)
        provider = AnthropicProvider(credential, model, config.effort, config.max_tokens)
    if resume is None:
        store.create(info)  # only once the credential is known to be there

    root = Path(info.workspace)
    policy = load_with_trust(root, config.home, mode.value if mode else None).policy
    transcript = TranscriptWriter(config.home / "transcripts" / f"{info.id}.jsonl")
    spill_dir = config.home / "tool-output" / info.id
    executor: LocalExecutor
    if config.executor == "docker":
        executor = DockerExecutor(root, spill_dir=spill_dir)
    else:
        executor = LocalExecutor(root, shell=config.shell, spill_dir=spill_dir)
    permissions = Permissions(
        policy,
        inside=executor.contains,
        relative=executor.relative,
        approver=terminal_approver if can_prompt() else None,
    )
    session = Session(
        provider=provider,
        tools=[ReadTool(), WriteTool(), EditTool(), GlobTool(), GrepTool(), BashTool()],
        ctx=ToolContext(executor=executor),
        system=info.system,  # a resumed session keeps the exact prompt it started with
        listeners=[Renderer().on_event, transcript.on_event, meter.on_event],
        max_steps=config.max_steps,
        compactor=Compactor(provider, config.compact_at, config.keep_messages),
        permissions=permissions,
    )
    session.messages = messages
    session.turn = info.turns
    saved = len(messages) - (1 if repaired else 0)
    recorder = SessionRecorder(store, info.id, session, meter, saved=saved, title=info.title)
    session.listeners.append(recorder.on_event)
    recorder.save()  # saves the answers to any cut-off tool calls right away

    label = "scripted responses" if fake_script else f"{model}, effort {config.effort}"
    label += f" | {config.executor}"
    typer.secho(f"Zwans {__version__} | {label} | mode {policy.mode} | {root}", dim=True)
    if resume is not None:
        typer.secho(f"Resumed {info.id} after {_count(info.turns, 'turn')}: {info.title}", dim=True)
    if repaired:
        typer.secho("Its last turn was cut off mid-tool; those calls are marked unfinished.")
    return _Opened(session, executor, meter, transcript, store, info.id)


def _chat(opened: _Opened, runner: asyncio.Runner) -> int:
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


def _run_once(opened: _Opened, runner: asyncio.Runner, task: str) -> int:
    try:
        stop_reason = runner.run(opened.session.send(task))
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    _print_turn(opened)
    return 0 if stop_reason == "end_turn" else 1


def _print_turn(opened: _Opened) -> None:
    context = f"context about {opened.session.context_tokens():,} tokens"
    hits = f"{opened.meter.cache_hit_rate:.0%} of input from cache so far"
    typer.secho(f"Turn cost ${opened.meter.turn_dollars:.4f}, {context}, {hits}", dim=True)


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _describe_shell(configured: str | None) -> str:
    try:
        return configured or find_bash()
    except FileNotFoundError:
        return "none found, so the Bash tool will fail"


def _tolerate_unprintable_text() -> None:
    """Show characters the terminal can't encode as "?" instead of crashing on them."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")
