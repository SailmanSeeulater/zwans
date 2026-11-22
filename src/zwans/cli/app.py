"""The `zwans` command: a chat when run alone, or `zwans run "<task>"` for a single task."""

import asyncio
import io
import os
import sys
from collections.abc import Sequence
from contextlib import AbstractContextManager, nullcontext
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from prompt_toolkit.input import Input, create_input
from prompt_toolkit.input.typeahead import get_typeahead

from zwans import __version__
from zwans.cli.approval import (
    can_prompt,
    load_with_trust,
    terminal_approver,
    terminal_question,
)
from zwans.cli.attach import Attached, AttachError, open_remote
from zwans.cli.commands import COMMANDS, Commands, Quit, Reopen, is_command
from zwans.cli.evals import eval_app
from zwans.cli.input import MENTIONED, Composer, echoing, expand_mentions
from zwans.cli.render import Renderer
from zwans.cli.room import room
from zwans.cli.serve import read_server_file, serve
from zwans.cli.terminal_text import printable
from zwans.config import ConfigError, load_settings
from zwans.context.compaction import SUMMARY_HEADER
from zwans.events import TextDelta, ToolCallRequested, ToolResult, TurnEnded
from zwans.executor.docker import DockerError
from zwans.executor.shutdown import SessionRunner
from zwans.messages import TextBlock, ToolResultBlock, ToolUseBlock
from zwans.policy import PolicyError
from zwans.policy.engine import Approval, PermissionRequest
from zwans.providers.catalog import list_all
from zwans.runtime import OpenedSession, open_session
from zwans.store import SessionError, SessionStore

app = typer.Typer(add_completion=False)
app.add_typer(eval_app, name="eval")
app.command()(serve)
app.command()(room)

EXIT_INTERRUPTED = 130  # the usual exit code after Ctrl+C
REPLAYED_TURNS = 3  # of a resumed session, shown again in the chat
WORKSPACE_WIDTH = 24  # characters of a session's folder that `zwans sessions` shows

Workspace = Annotated[
    Path,
    typer.Option(
        "--workspace", "-w", exists=True, file_okay=False, help="Folder the agent works in."
    ),
]
# None when not given, so --resume can tell a -w for another folder from the default
SessionWorkspace = Annotated[
    Path | None,
    typer.Option(
        "--workspace",
        "-w",
        exists=True,
        file_okay=False,
        help="Folder the agent works in: this one unless given. A resumed session keeps its own.",
        show_default=False,
    ),
]
Model = Annotated[str | None, typer.Option(help="Model to use instead of the configured one.")]
Resume = Annotated[
    str | None,
    typer.Option(help="Continue a saved session: its id from `zwans sessions`, or its start."),
]
Rewind = Annotated[
    int | None,
    typer.Option(
        min=1,
        help="With --resume, first drop every turn after this one from the conversation. "
        "The files stay as they are; /rewind in a chat puts them back too.",
    ),
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
    workspace: SessionWorkspace = None,
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
    workspace: SessionWorkspace = None,
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
    _tolerate_unprintable_text()  # titles and shortened folders can hold any character
    try:
        config, _ = load_settings()
    except ConfigError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2) from exc
    store = SessionStore(config.home / "sessions.db")
    found = store.recent(limit)
    store.close()
    if not found:
        typer.echo("No saved sessions yet.")
    for info in found:
        when = info.updated_at.replace("T", " ")[:16]
        dollars = float(info.usage.get("dollars", 0.0))
        turns = f"{info.turns:>4} {'turn' if info.turns == 1 else 'turns':<5}"
        folder = _short_path(printable(info.workspace), WORKSPACE_WIDTH)
        line = f"{info.id}  {when}  {turns}  ${dollars:7.4f}  {folder:<{WORKSPACE_WIDTH}}"
        # A title is the start of a prompt, which may have come from the web UI or a script.
        typer.echo(f"{line}  {printable(info.label)}".rstrip())


@app.command()
def models(
    provider: Annotated[
        str | None,
        typer.Argument(help="Only this provider, asking it for its whole list (as openrouter)."),
    ] = None,
) -> None:
    """List the models Zwans can use, by where they run."""
    try:
        config, env = load_settings()
        listings = asyncio.run(
            list_all(config, env, only=provider, timeout=5.0 if provider else 2.0)
        )
    except ConfigError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2) from exc
    for listing in listings:
        state = (
            typer.style("ready", fg="green")
            if listing.ready
            else typer.style("not ready", dim=True)
        )
        note = f" ({listing.note})" if listing.note else ""
        typer.echo(f"{typer.style(listing.provider, bold=True)}: {listing.about}, {state}{note}")
        for name in listing.models:
            typer.echo(f"  {name}")
    if provider is None:
        typer.secho(
            '\nUse one with --model, /model, or model = "..." in the config. Other providers\' '
            "models are <provider>/<model ID>; add your own under [providers.<name>].",
            dim=True,
        )


def _short_path(path: str, width: int) -> str:
    """`path` with the home folder as ~, and its start left out if it's still too long."""
    home = str(Path.home())
    if path == home or path.startswith(home + os.sep):
        path = "~" + path[len(home) :]
    return path if len(path) <= width else "…" + path[-(width - 1) :]


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
    except AttachError as exc:  # its detail can name the workspace or the session asked for
        typer.secho(printable(str(exc)), fg="red", err=True)
        raise typer.Exit(2) from exc
    label = f"{status['model']} | mode {status['mode']} | {status['workspace']}"
    typer.secho(printable(f"Attached to {status['id']} | {label}"), dim=True)
    for warning in status.get("warnings", []):  # such as an MCP server's error
        typer.secho(printable(str(warning)), fg="yellow")
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
    given_workspace: Path | None,
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
    files_kept = rewind is not None  # --rewind leaves the files; /rewind and /undo don't
    workspace = given_workspace or Path(".")
    # A resumed session keeps its own folder, so a -w given with --resume is ignored.
    ignored = given_workspace.resolve() if resume and given_workspace else None
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
                approver=(asking := EchoingApprover() if can_prompt() else None),
                asker=asking.ask if asking is not None else None,
                listeners=[Renderer(spinner=True).on_event],
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
        if ignored is not None and ignored != Path(opened.info.workspace):
            typer.secho(
                printable(
                    f"Session {opened.id} works in {opened.info.workspace}, so -w {ignored} "
                    "is ignored."
                ),
                fg="yellow",
                err=True,
            )
        scripted = fake_script is not None
        outcome = _run_session(opened, task, scripted, switch, files_kept)
        if not isinstance(outcome, Reopen):
            return outcome
        workspace = Path(opened.info.workspace)
        resume, rewind = outcome.resume, outcome.rewind
        # A new session, or this one again, keeps the current model; another saved session
        # opens with its own.
        model = opened.model if resume in (None, opened.id) else None
        switch, left = outcome, opened.id
        files_kept, ignored = False, None


class EchoingApprover:
    """Asks in the terminal, with typing shown again: the chat hides it while a turn runs."""

    def __init__(self) -> None:
        # The chat's composer, holding what was typed ahead during the turn. That was typed
        # before the question, perhaps meant as its answer, so it mustn't be sent to the model
        # afterwards, where a stray "y" would answer whatever the model last asked.
        self.composer: Composer | None = None

    async def __call__(self, request: PermissionRequest) -> Approval:
        if self.composer is not None and self.composer.drop_typed_ahead():
            typer.secho("  What you typed before this question was dropped.", dim=True)
        with echoing():
            return await terminal_approver(request)

    async def ask(self, question: str, options: Sequence[str]) -> str | None:
        """The model's own question, asked the same way."""
        if self.composer is not None and self.composer.drop_typed_ahead():
            typer.secho("  What you typed before this question was dropped.", dim=True)
        with echoing():
            return terminal_question(question, options)


def _run_session(
    opened: OpenedSession,
    task: str | None,
    scripted: bool,
    switch: Reopen | None = None,
    files_kept: bool = False,
) -> int | Reopen:
    rewind = switch.rewind if switch is not None else None
    rewound = rewind is not None
    if rewind is not None:  # the same session as before, so the banner would only repeat
        typer.secho(f"Went back to before turn {rewind + 1}.", dim=True)
    else:
        _banner(opened, scripted, files_kept)
        if opened.resumed and task is None:
            _replay(opened)
    # One event loop for the whole session, so the API client's connections stay usable.
    # SIGTERM and SIGHUP (the terminal closing) still close the session, stopping its jobs.
    with SessionRunner() as runner:
        outcome: int | Reopen = 1
        started = False
        try:
            # Inside the try, so a signal or Ctrl+C while MCP servers or the container start
            # still closes whatever had started.
            try:
                tools, problems = runner.run(opened.start())
            except DockerError as exc:
                typer.secho(str(exc), fg="red", err=True)
                outcome = 2
                return outcome
            started = True
            for problem in problems:
                typer.secho(printable(f"MCP server skipped: {problem}"), fg="yellow", err=True)
            if opened.mcp is not None and not rewound:
                for name in opened.mcp.servers:
                    count = sum(t.connection.name == name for t in tools)
                    if count:
                        typer.secho(f"MCP {name}: {_count(count, 'tool')}", dim=True)
            if task is None:
                outcome = _chat(opened, runner, switch.draft if switch else "", hint=not rewound)
            else:
                outcome = _run_once(opened, runner, task)
            return outcome
        finally:
            runner.run_cleanup(opened.close())
            if started:  # one that never started has nothing to report
                _report_leaving(opened, outcome)


def _report_leaving(opened: OpenedSession, outcome: int | Reopen) -> None:
    if not isinstance(outcome, Reopen):  # only when leaving Zwans, not switching
        typer.secho(f"\nSession cost: {opened.meter.summary()}", dim=True)
        if not opened.empty:  # an empty session isn't kept
            typer.secho(f"To continue it: zwans --resume {opened.id}", dim=True)
    elif outcome.resume != opened.id and not opened.empty:
        # Switching to another, so say what this one cost. An empty one is gone, and cost nothing.
        typer.secho(f"Left {opened.id}, which cost {opened.meter.summary()}.", dim=True)


def _banner(opened: OpenedSession, scripted: bool, files_kept: bool = False) -> None:
    for path in opened.instructions:
        typer.secho(printable(f"Following {path}"), dim=True)
    config, info = opened.config, opened.info
    label = "scripted responses" if scripted else f"{opened.model}, effort {config.effort}"
    label += f" | {config.executor}"
    mode = opened.policy.policy.mode
    # The folder's name and the title (the first prompt's start) can hold any character.
    banner = f"Zwans {__version__} | {label} | mode {mode} | {info.workspace}"
    typer.secho(printable(banner), dim=True)
    if opened.resumed:
        resumed = f"Resumed {info.id} after {_count(info.turns, 'turn')}: {info.title}"
        typer.secho(printable(resumed), dim=True)
        if files_kept:
            typer.secho(
                f"Turns after turn {info.turns} were dropped from the conversation. The files "
                "were left as they are.",
                dim=True,
            )
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
                # The prompt may have come from the web UI, another terminal or a script.
                typer.secho(f"\n> {printable(block.text.split(MENTIONED)[0])}", bold=True)
            elif isinstance(block, TextBlock):  # such as a stop hook's, sent back to the model
                note = block.text.splitlines()[0] if block.text else ""
                typer.secho(f"  {printable(note)}", dim=True)
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
    keys: Input | None = None  # the composer's, whose typed-ahead keys may need dropping
    if can_prompt():
        keys = create_input()
        composer = Composer(
            COMMANDS,
            workspace,
            opened.config.home / "history",
            status=lambda: _status(opened),
            input=keys,
        )
        approver = opened.session.permissions.approver if opened.session.permissions else None
        if isinstance(approver, EchoingApprover):
            approver.composer = composer
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
            try:
                with _typing_ahead(composer, runner):  # /compact and /loop can take a while
                    outcome = runner.run(commands.run(line))
            except KeyboardInterrupt:
                typer.secho("Interrupted. The conversation is kept, so carry on.", fg="yellow")
                continue
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
        turns = opened.session.turn
        try:
            with _typing_ahead(composer, runner):
                runner.run(opened.session.send(mentions.text, mentions.images))
        except KeyboardInterrupt:
            typer.secho("Interrupted. The conversation is kept, so carry on.", fg="yellow")
        failed = opened.session.turn == turns
        if failed and composer is not None:
            draft = line  # it failed before the model answered, so it wasn't kept
            typer.secho("Your message is back in the input, to send again.", dim=True)
        # Lines typed ahead were meant to follow this message, so they'd go without it, or
        # merge with it back in the input.
        if keys is not None and failed and get_typeahead(keys):  # which takes them out
            typer.secho("What you typed during the turn was dropped, as it failed.", dim=True)
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
