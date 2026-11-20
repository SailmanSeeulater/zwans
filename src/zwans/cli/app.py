"""The `zwans` command: a chat when run alone, or `zwans run "<task>"` for a single task."""

import asyncio
import io
import sys
from contextlib import AbstractContextManager, nullcontext
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from zwans import __version__
from zwans.cli.approval import can_prompt, load_with_trust, terminal_approver
from zwans.cli.attach import Attached, AttachError, open_remote
from zwans.cli.commands import COMMANDS, Commands, Quit, Reopen, is_command
from zwans.cli.evals import eval_app
from zwans.cli.input import MENTIONED, Composer, echoing, expand_mentions
from zwans.cli.render import Renderer
from zwans.cli.serve import read_server_file, serve
from zwans.config import ConfigError, load_settings
from zwans.context.compaction import SUMMARY_HEADER
from zwans.events import TextDelta, ToolCallRequested, ToolResult, TurnEnded
from zwans.executor.docker import DockerError
from zwans.messages import TextBlock, ToolResultBlock, ToolUseBlock
from zwans.policy import PolicyError
from zwans.policy.engine import Approval, PermissionRequest
from zwans.runtime import OpenedSession, open_session
from zwans.store import SessionError, SessionStore

app = typer.Typer(add_completion=False)
app.add_typer(eval_app, name="eval")
app.command()(serve)

EXIT_INTERRUPTED = 130  # the usual exit code after Ctrl+C
REPLAYED_TURNS = 3  # of a resumed session, shown again in the chat

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
    except ConfigError as exc:
        typer.secho(str(exc), fg="red", err=True)
        return 2
    # /clear, /resume and /undo close the session and open another, so this can go round again.
    switch: Reopen | None = None  # how the last session ended, when it was switched away from
    left: str | None = None  # that session's id
    while True:
        try:
            opened = open_session(
                config,
                env,
                workspace=workspace,
                resume=resume,
                rewind=rewind,
                model=model,
                mode=mode.value if mode else None,
                approver=_approve_with_echo if can_prompt() else None,
                listeners=[Renderer().on_event],
                policy_loader=load_with_trust,
                fake_script=fake_script,
            )
        except (ConfigError, SessionError, PolicyError) as exc:
            typer.secho(str(exc), fg="red", err=True)
            if left is None:
                return 2
            # Go back to the session that was open rather than quit in the middle of a chat.
            resume, rewind, switch, left = left, None, None, None
            continue
        scripted = fake_script is not None
        outcome = _run_session(opened, task, scripted, switch)
        if not isinstance(outcome, Reopen):
            return outcome
        workspace = Path(opened.info.workspace)
        resume, rewind, model = outcome.resume, outcome.rewind, opened.model
        switch, left = outcome, opened.id


async def _approve_with_echo(request: PermissionRequest) -> Approval:
    """Ask in the terminal, with typing shown again: the chat hides it while a turn runs."""
    with echoing():
        return await terminal_approver(request)


def _run_session(
    opened: OpenedSession, task: str | None, scripted: bool, switch: Reopen | None = None
) -> int | Reopen:
    rewind = switch.rewind if switch is not None else None
    rewound = rewind is not None
    if rewind is not None:  # the same session as before, so the banner would only repeat
        typer.secho(f"Went back to before turn {rewind + 1}.", dim=True)
    else:
        _banner(opened, scripted)
        if opened.resumed and task is None:
            _replay(opened)
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
        if opened.mcp is not None and not rewound:
            for name in opened.mcp.servers:
                count = sum(t.connection.name == name for t in tools)
                if count:
                    typer.secho(f"MCP {name}: {_count(count, 'tool')}", dim=True)
        outcome: int | Reopen = 1
        try:
            if task is None:
                outcome = _chat(opened, runner, switch.draft if switch else "", hint=not rewound)
            else:
                outcome = _run_once(opened, runner, task)
            return outcome
        finally:
            runner.run(opened.close())
            if not isinstance(outcome, Reopen):
                typer.secho(f"\nSession cost: {opened.meter.summary()}", dim=True)
                typer.secho(f"To continue it: zwans --resume {opened.id}", dim=True)
            elif outcome.resume != opened.id:  # switching to another, so say what this one cost
                typer.secho(f"Left {opened.id}, which cost {opened.meter.summary()}.", dim=True)


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


def _replay(opened: OpenedSession) -> None:
    """Show the last few turns of a resumed session again, so it's clear where it left off."""
    session = opened.session
    first = session.turn - REPLAYED_TURNS + 1
    start = next(
        (i for i, m in enumerate(session.messages) if m.turn is not None and m.turn >= first),
        len(session.messages),
    )
    if start > 0:
        typer.secho("(Earlier turns aren't shown.)", dim=True)
    renderer = Renderer()  # its own, so these lines aren't mixed up with the live ones
    prompted: set[int | None] = set()  # turns whose prompt is shown: later texts are notes
    for message in session.messages[start:]:
        for block in message.content:
            if isinstance(block, TextBlock) and message.role == "assistant":
                renderer.on_event(TextDelta(text=block.text))
            elif isinstance(block, TextBlock) and block.text.startswith(SUMMARY_HEADER):
                prompted.add(message.turn)  # that turn's prompt is in the summary
                typer.secho("[Older messages were summarized here]", fg="magenta")
            elif isinstance(block, TextBlock) and message.turn not in prompted:
                prompted.add(message.turn)
                typer.secho(f"\n> {block.text.split(MENTIONED)[0]}", bold=True)
            elif isinstance(block, TextBlock):  # such as a stop hook's, sent back to the model
                typer.secho(f"  {block.text.splitlines()[0] if block.text else ''}", dim=True)
            elif isinstance(block, ToolUseBlock):
                renderer.on_event(
                    ToolCallRequested(call_id=block.id, name=block.name, args=block.input)
                )
            elif isinstance(block, ToolResultBlock):
                result = block.text()
                renderer.on_event(
                    ToolResult(call_id=block.tool_use_id, content=result, is_error=block.is_error)
                )
        renderer.on_event(TurnEnded(stop_reason="end_turn"))  # ends its last line


def _chat(
    opened: OpenedSession, runner: asyncio.Runner, draft: str = "", hint: bool = True
) -> int | Reopen:
    workspace = Path(opened.info.workspace)
    commands = Commands(opened)
    composer: Composer | None = None
    if can_prompt():
        composer = Composer(
            COMMANDS, workspace, opened.config.home / "history", status=lambda: _status(opened)
        )
        if hint:
            typer.secho(
                "Type a task, or /help. Ctrl+C stops a running turn; Ctrl+D quits.", dim=True
            )
    while True:
        try:
            if composer is not None:
                typer.echo()
                line = runner.run(composer.read(draft)).strip()
                draft = ""
            else:
                line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if line in ("exit", "quit"):
            return 0
        if not line:
            continue
        if is_command(line):
            with _typing_ahead(composer, runner):  # /compact can take a while
                outcome = runner.run(commands.run(line))
            if isinstance(outcome, Quit):
                return 0
            if isinstance(outcome, Reopen):
                return outcome
            continue
        mentions = expand_mentions(line, workspace)
        for problem in mentions.problems:
            typer.secho(problem, fg="yellow")
        if mentions.files:
            typer.secho(f"Sending {', '.join(mentions.files)} with it.", dim=True)
            if opened.session.permissions is not None:
                # File contents may carry instructions, just as when the model reads them.
                opened.session.permissions.observe("Read", is_error=False)
        checkpoint_problem = opened.checkpoints.problem if opened.checkpoints else None
        try:
            with _typing_ahead(composer, runner):
                runner.run(opened.session.send(mentions.text, mentions.images))
        except KeyboardInterrupt:
            typer.secho("Interrupted. The conversation is kept, so carry on.", fg="yellow")
        if opened.checkpoints and opened.checkpoints.problem != checkpoint_problem:
            typer.secho(str(opened.checkpoints.problem), fg="yellow")
        _print_turn(opened)


def _typing_ahead(
    composer: Composer | None, runner: asyncio.Runner
) -> AbstractContextManager[None]:
    return composer.typing_ahead(runner.get_loop()) if composer else nullcontext()


def _status(opened: OpenedSession) -> str:
    mode = opened.policy.policy.mode
    context = opened.session.context_tokens()
    dollars = opened.meter.session_dollars
    return f"{opened.model} · {mode} · context {context / 1000:.0f}k · ${dollars:.2f}"


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
