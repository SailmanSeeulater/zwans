"""Asks the user in the terminal before a tool call the policy wants approved."""

import signal
import sys
from pathlib import Path

import typer

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
    command = request.args.get("command")
    if request.tool == "Bash" and isinstance(command, str) and "\n" in command:
        # The tool line above shows only the first line; a here-document's body matters too.
        for line in _shown_lines(command):
            typer.secho(f"  | {line}", dim=True)
    typer.secho(f"  ? {request.reason}", fg="yellow")
    if not request.rules:  # "always" couldn't take effect, as after untrusted content
        answer = _prompt("  Allow it? [y]es / [N]o: ")
        return Approval.ONCE if answer.strip().lower() in ("y", "yes") else Approval.NO
    always = ", ".join(_cut(rule) for rule in request.rules)
    answer = _prompt(f"  Allow it? [y]es / [a]lways ({always}) / [N]o: ")
    return ANSWERS.get(answer.strip().lower(), Approval.NO)


MAX_SHOWN_LINES = 20


def _shown_lines(command: str) -> list[str]:
    lines = [_cut(line, 160) for line in command.splitlines()]
    if len(lines) > MAX_SHOWN_LINES:
        more = len(lines) - MAX_SHOWN_LINES + 1
        lines = [*lines[: MAX_SHOWN_LINES - 1], f"... ({more} more lines)"]
    return lines


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
    for item in loosening:
        typer.secho(f"  {item}", fg="yellow")
    if scripts:
        typer.secho(
            f"Trusting it also trusts the scripts its hooks run, as they are now: "
            f"{', '.join(scripts)}",
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
    the default one is put back while waiting for an answer.
    """
    previous = signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        return input(text)
    except (EOFError, KeyboardInterrupt):
        typer.echo()
        return ""
    finally:
        signal.signal(signal.SIGINT, previous)
