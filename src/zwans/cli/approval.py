"""Asks the user in the terminal before a tool call the policy wants approved."""

import signal
import sys
from pathlib import Path

import typer

from zwans.policy.engine import Approval, PermissionRequest
from zwans.policy.rules import Decision, LoadedPolicy, load_policy, read_policy_file, trust
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
    typer.secho(f"  ? {request.reason}", fg="yellow")
    always = ", ".join(request.rules) or request.tool
    answer = _prompt(f"  Allow it? [y]es / [a]lways ({always}) / [N]o: ")
    return ANSWERS.get(answer.strip().lower(), Approval.NO)


def load_with_trust(workspace: Path, home: Path, mode: PolicyMode | None) -> LoadedPolicy:
    """Load the policy. A workspace policy that loosens the rules is used in full only once
    the user trusts it; when nobody can answer, its loosening parts are left out."""
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
    typer.secho(f"{path} came with this workspace and would loosen the policy:", fg="yellow")
    for item in loosening:
        typer.secho(f"  {item}", fg="yellow")
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
