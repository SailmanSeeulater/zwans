"""The `zwans` command: a chat when run alone, or `zwans run "<task>"` for a single task."""

import asyncio
import io
import secrets
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from zwans import __version__
from zwans.cli.render import Renderer
from zwans.config import ConfigError, load_config, load_credential
from zwans.executor.local import LocalExecutor, find_bash
from zwans.pricing import CostMeter
from zwans.prompt import system_prompt
from zwans.providers.anthropic import AnthropicProvider
from zwans.providers.base import Provider
from zwans.providers.fake import FakeProvider
from zwans.session import Session
from zwans.tools.base import ToolContext
from zwans.tools.bash import BashTool
from zwans.tools.edit import EditTool
from zwans.tools.glob import GlobTool
from zwans.tools.grep import GrepTool
from zwans.tools.read import ReadTool
from zwans.tools.write import WriteTool
from zwans.transcript import TranscriptWriter

app = typer.Typer(add_completion=False)

EXIT_INTERRUPTED = 130  # the usual exit code after Ctrl+C

Workspace = Annotated[
    Path,
    typer.Option(
        "--workspace", "-w", exists=True, file_okay=False, help="Folder the agent works in."
    ),
]
Model = Annotated[str | None, typer.Option(help="Model to use instead of the configured one.")]
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
    fake_script: FakeScript = None,
) -> None:
    """Zwans: a coding agent built from scratch. With no command, starts a chat."""
    if ctx.invoked_subcommand is None:
        raise typer.Exit(_start(workspace, model, fake_script, task=None))


@app.command()
def run(
    task: Annotated[str, typer.Argument(help="What the agent should do.")],
    workspace: Workspace = Path("."),
    model: Model = None,
    fake_script: FakeScript = None,
) -> None:
    """Do one task, then exit. The exit code is 0 when the model finished normally."""
    raise typer.Exit(_start(workspace, model, fake_script, task=task))


def _start(workspace: Path, model: str | None, fake_script: Path | None, task: str | None) -> int:
    _tolerate_unprintable_text()
    try:
        session, transcript, meter = _open_session(workspace, model, fake_script)
    except ConfigError as exc:
        typer.secho(str(exc), fg="red", err=True)
        return 2
    # One event loop for the whole session, so the API client's connections stay usable.
    with asyncio.Runner() as runner:
        try:
            if task is None:
                return _chat(session, runner)
            return _run_once(session, runner, task)
        finally:
            runner.run(session.provider.aclose())
            transcript.close()
            typer.secho(f"\nSession cost: {meter.summary()}", dim=True)
            typer.secho(f"Transcript: {transcript.path}", dim=True)


def _open_session(
    workspace: Path, model: str | None, fake_script: Path | None
) -> tuple[Session, TranscriptWriter, CostMeter]:
    config = load_config()
    if model:
        config = config.model_copy(update={"model": model})
    root = workspace.resolve()
    provider: Provider
    if fake_script is not None:
        provider = FakeProvider.from_file(fake_script)
    else:
        credential = load_credential(config)
        provider = AnthropicProvider(credential, config.model, config.effort, config.max_tokens)

    session_id = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    transcript = TranscriptWriter(config.transcript_dir / f"{session_id}.jsonl")
    meter = CostMeter()
    session = Session(
        provider=provider,
        tools=[ReadTool(), WriteTool(), EditTool(), GlobTool(), GrepTool(), BashTool()],
        ctx=ToolContext(executor=LocalExecutor(root, shell=config.shell)),
        system=system_prompt(root, _describe_shell(config.shell)),
        listeners=[Renderer().on_event, transcript.on_event, meter.on_event],
        max_steps=config.max_steps,
    )
    label = "scripted responses" if fake_script else f"{config.model}, effort {config.effort}"
    typer.secho(f"Zwans {__version__} | {label} | {root}", dim=True)
    return session, transcript, meter


def _chat(session: Session, runner: asyncio.Runner) -> int:
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
            runner.run(session.send(task))
        except KeyboardInterrupt:
            typer.secho("Interrupted. The conversation is kept, so carry on.", fg="yellow")


def _run_once(session: Session, runner: asyncio.Runner, task: str) -> int:
    try:
        stop_reason = runner.run(session.send(task))
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    return 0 if stop_reason == "end_turn" else 1


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
