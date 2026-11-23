"""Asks the user in the terminal before a tool call the policy wants approved."""

import signal
import sys
from collections.abc import Sequence
from pathlib import Path

import typer

from zwans.cli.diffs import show_change
from zwans.cli.terminal_text import printable
from zwans.executor.shutdown import reading_input
from zwans.policy.engine import Approval, PermissionRequest
from zwans.policy.rules import (
    Decision,
    LoadedPolicy,
    hook_scripts,
    load_policy,
    read_policy_file,
    trust,
)
from zwans.policy.rules import Mode as PolicyMode

ANSWERS = {
    "y": Approval.ONCE,
    "yes": Approval.ONCE,
    "a": Approval.ALWAYS,
    "always": Approval.ALWAYS,
}


def can_prompt() -> bool:
    return sys.stdin.isatty()


async def terminal_approver(request: PermissionRequest) -> Approval:
    typer.secho(f"  ? {printable(request.reason)}", fg="yellow")
    # What the call would do: a file tool's diff, or a long command in full.
    show_change(request.tool, request.args, request.preview)
    if not request.rules:  # "always" couldn't take effect, as after untrusted content
        answer = _prompt("  Allow it? [y]es / [N]o: ")
        return Approval.ONCE if answer.strip().lower() in ("y", "yes") else Approval.NO
    always = printable(", ".join(_cut(rule) for rule in request.rules))
    answer = _prompt(f"  Allow it? [y]es / [a]lways ({always}) / [N]o: ")
    return ANSWERS.get(answer.strip().lower(), Approval.NO)


def terminal_question(question: str, options: Sequence[str]) -> str | None:
    """Put the model's question to the person in the terminal. A number picks an option,
    anything else is the answer, and nothing at all is no answer."""
    typer.secho(f"  ? {printable(question)}", fg="yellow")
    for number, option in enumerate(options, 1):
        typer.echo(f"    {number}. {printable(option)}")
    hint = f"  Answer (1-{len(options)}, or your own words): " if options else "  Answer: "
    answer = _prompt(hint).strip()
    if answer.isdigit() and 1 <= int(answer) <= len(options):
        return options[int(answer) - 1]
    return answer or None


def _cut(text: str, limit: int = 80) -> str:
    first, newline, _ = text.partition("\n")
    return first[:limit] + " ..." if len(first) > limit or newline else first


def load_with_trust(workspace: Path, home: Path, mode: PolicyMode | None) -> LoadedPolicy:
    """Load the policy. A workspace policy that loosens the rules or runs hooks is used in full
    only once the user trusts it; when nobody can answer, those parts are left out."""
    loaded = load_policy(workspace, home, mode)
    if loaded.untrusted is None:
        return loaded
    path = loaded.untrusted
    file = read_policy_file(path)
    assert file is not None
    loosening = [f"allow {rule}" for rule in file.allow]
    if file.mode == "auto":
        loosening.append('mode "auto"')
    if file.after_untrusted is not None:
        for name in ("network", "write"):
            if getattr(file.after_untrusted, name) == Decision.ALLOW:
                loosening.append(f"{name} allowed after untrusted content")
    loosening.extend(f"run the {hook.event} hook `{hook.command}`" for hook in file.hooks)
    root = path.resolve().parent.parent
    scripts = [script.relative_to(root).as_posix() for script in hook_scripts(path)]
    typer.secho(f"{path} came with this workspace and would:", fg="yellow")
    for item in loosening:  # from a file that came with the workspace, so possibly hostile
        typer.secho(f"  {printable(item)}", fg="yellow")
    if scripts:
        typer.secho(
            f"Trusting it also trusts the scripts its hooks run, as they are now: "
            f"{printable(', '.join(scripts))}",
            fg="yellow",
        )
    if can_prompt() and _prompt("Trust this file? [y/N]: ").strip().lower() in ("y", "yes"):
        trust(path, home)
        return load_policy(workspace, home, mode)
    typer.secho("Ignoring those parts; its deny and ask rules still apply.", fg="yellow")
    return loaded


def _prompt(text: str) -> str:
    """Read a line. Ctrl+C or end of input counts as no.

    The event loop's own Ctrl+C handler would only cancel the turn after the next Enter, so
    the default one is put back while waiting for an answer. SIGTERM and SIGHUP likewise stop
    the wait at once rather than after an answer.
    """
    _discard_typeahead()
    previous = signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        with reading_input():
            return input(text)
    except (EOFError, KeyboardInterrupt):
        typer.echo()
        return ""
    finally:
        signal.signal(signal.SIGINT, previous)


def _discard_typeahead() -> None:
    """Drop what was typed while the turn ran, as sudo does, so a stray line can't answer the
    question (and a stray "y" can't allow a call the user never saw)."""
    if not sys.stdin.isatty():
        return
    try:
        if sys.platform == "win32":
            import msvcrt

            while msvcrt.kbhit():
                msvcrt.getwch()
        else:
            import termios

            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except (OSError, ValueError):
        pass  # not a real terminal after all; nothing to drop


def prompt_line(text: str) -> str:
    """Ask a question on the terminal and return the answer, stripped."""
    return _prompt(text).strip()
