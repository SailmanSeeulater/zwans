"""Decides, before each tool call, whether it runs, asks the user first, or is refused.

The verdict depends on the rules, the mode, and whether untrusted content (a file, a command's
output, a web page) is already in the conversation, since that content may carry instructions
planted for the model. A refusal goes back to the model as a tool error that says why.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from zwans.policy.classify import Action, Kind, analyze
from zwans.policy.rules import Decision, Policy, Rule, strictest

# Tools whose output comes from outside: files, programs, the web. Instructions inside it
# are data, not the user's.
UNTRUSTED_OUTPUT = frozenset({"Read", "Grep", "Bash", "WebFetch"})
MCP_PREFIX = "mcp__"


class Approval(StrEnum):
    ONCE = "once"
    ALWAYS = "always"  # also allow the same call for the rest of the session
    NO = "no"


@dataclass(frozen=True)
class Verdict:
    decision: Decision
    reason: str = ""
    # Rules that would allow this exact call, which "always" adds for the session.
    rules: tuple[str, ...] = ()


@dataclass(frozen=True)
class PermissionRequest:
    call_id: str
    tool: str
    args: dict[str, Any]
    reason: str
    rules: tuple[str, ...]


class Approver(Protocol):
    def __call__(self, request: PermissionRequest) -> Awaitable[Approval]: ...


class _ToolLike(Protocol):
    name: str
    read_only: bool


@dataclass
class Permissions:
    policy: Policy
    inside: Callable[[str], bool]  # whether a path is inside the workspace
    relative: Callable[[str], str]  # a path relative to the workspace root; raises if outside
    approver: Approver | None = None  # None: nobody can answer, so asking means refusing
    tainted: bool = False  # untrusted content has been read in this session
    session_rules: list[Rule] = field(default_factory=list)  # added by "always"

    def check(self, tool: _ToolLike, args: dict[str, Any]) -> Verdict:
        if tool.name == "Bash" and isinstance(args.get("command"), str):
            return self._check_command(args["command"])
        path = args.get("path")
        return self._check_tool(tool, path if isinstance(path, str) else None)

    async def ask(self, request: PermissionRequest) -> Approval:
        if self.approver is None:
            return Approval.NO
        approval = await self.approver(request)
        if approval == Approval.ALWAYS:
            self.session_rules.extend(Rule.parse(r, "this session") for r in request.rules)
        return approval

    def observe(self, tool_name: str, is_error: bool) -> bool:
        """Note a tool's result. Returns whether its output is untrusted."""
        untrusted = tool_name in UNTRUSTED_OUTPUT or tool_name.startswith(MCP_PREFIX)
        if untrusted and not is_error:
            self.tainted = True
        return untrusted

    # -- file and other tools

    def _check_tool(self, tool: _ToolLike, path: str | None) -> Verdict:
        relative = None
        if path is not None:
            try:
                relative = self.relative(path)
            except OSError:
                relative = None  # outside the workspace: the executor refuses it anyway
        matched = self._match(tool.name, _matches_path(relative))
        what = f"{tool.name} {relative}" if relative else tool.name
        if matched is not None:
            decision, rule = matched
            if decision != Decision.ALLOW:
                return Verdict(
                    decision, f"{what} matches the {decision} rule {rule} ({rule.source})"
                )
            verdict = Verdict(Decision.ALLOW)
        elif tool.read_only:
            return Verdict(Decision.ALLOW)
        elif self.policy.mode == "read-only":
            return Verdict(Decision.DENY, f"{what} changes things, and Zwans is in read-only mode")
        elif self.policy.mode == "ask" or tool.name not in ("Edit", "Write"):
            verdict = Verdict(Decision.ASK, f"{what} changes files")
        else:
            verdict = Verdict(Decision.ALLOW)
        if self.tainted and verdict.decision != Decision.DENY:
            after = self.policy.after_untrusted.write
            if strictest(after, verdict.decision) != verdict.decision:
                reason = f"{what} changes files after untrusted content was read"
                verdict = Verdict(after, reason)
        if verdict.decision == Decision.ASK:
            always = f"{tool.name}({relative})" if relative else tool.name
            return Verdict(Decision.ASK, verdict.reason, (always,))
        return verdict

    # -- Bash

    def _check_command(self, command: str) -> Verdict:
        verdicts = [self._check_action(action) for action in analyze(command, self.inside)]
        if not verdicts:
            return Verdict(Decision.ALLOW)
        worst = strictest(*(v.decision for v in verdicts))
        if worst == Decision.ALLOW:
            return Verdict(Decision.ALLOW)
        chosen = [v for v in verdicts if v.decision == worst]
        reason = "; ".join(dict.fromkeys(v.reason for v in chosen))
        rules = tuple(
            dict.fromkeys(r for v in verdicts if v.decision == Decision.ASK for r in v.rules)
        )
        return Verdict(worst, reason, rules)

    def _check_action(self, action: Action) -> Verdict:
        shown = f"`{action.command}`"
        for path in action.writes:
            matched = self._match("Write", _matches_path(path))
            if matched is not None and matched[0] != Decision.ALLOW:
                decision, rule = matched
                return Verdict(
                    decision,
                    f"{shown} writes {path}, which matches the {decision} rule {rule}",
                    (_exact_rule(action.command),),
                )
        matched = self._match("Bash", lambda rule: rule.matches_command(action.command))
        if matched is not None:
            decision, rule = matched
            if decision != Decision.ALLOW:
                reason = f"{shown} matches the {decision} rule {rule} ({rule.source})"
                return Verdict(decision, reason, (_exact_rule(action.command),))
            verdict = Verdict(Decision.ALLOW)
        else:
            verdict = self._by_mode(action, shown)
        if self.tainted and verdict.decision != Decision.DENY:
            after = None
            if action.kind == Kind.NETWORK:
                after = self.policy.after_untrusted.network
            elif action.kind == Kind.WRITE:
                after = self.policy.after_untrusted.write
            if after is not None and strictest(after, verdict.decision) != verdict.decision:
                what = "uses the network" if action.kind == Kind.NETWORK else "changes files"
                reason = f"{shown} {what} after untrusted content was read"
                verdict = Verdict(after, reason)
        if verdict.decision == Decision.ASK:
            return Verdict(Decision.ASK, verdict.reason, (_exact_rule(action.command),))
        return verdict

    def _by_mode(self, action: Action, shown: str) -> Verdict:
        what = {
            Kind.READ: "only reads",
            Kind.WRITE: "changes files",
            Kind.EXECUTE: "runs code",
            Kind.NETWORK: "uses the network",
            Kind.UNKNOWN: action.reason or "can't be checked",
        }[action.kind]
        if action.kind == Kind.READ:
            return Verdict(Decision.ALLOW)
        reason = f"{shown} {what}"
        if self.policy.mode == "read-only":
            return Verdict(Decision.DENY, f"{reason}, and Zwans is in read-only mode")
        if self.policy.mode == "auto" and action.kind in (Kind.WRITE, Kind.EXECUTE):
            return Verdict(Decision.ALLOW)
        return Verdict(Decision.ASK, reason)

    def _match(self, tool: str, matches: Callable[[Rule], bool]) -> tuple[Decision, Rule] | None:
        """The strictest rule that matches, or None."""
        session = {Decision.ALLOW: self.session_rules}
        for decision in (Decision.DENY, Decision.ASK, Decision.ALLOW):
            for rule in [*self.policy.rules[decision], *session.get(decision, [])]:
                if rule.covers(tool) and matches(rule):
                    return decision, rule
        return None


def _exact_rule(command: str) -> str:
    """A Bash rule for exactly this command, with *, ? and [ escaped so they match themselves."""
    escaped = command.replace("[", "[[]").replace("*", "[*]").replace("?", "[?]")
    return f"Bash({escaped})"


def _matches_path(path: str | None) -> Callable[[Rule], bool]:
    def matches(rule: Rule) -> bool:
        if rule.pattern is None:
            return True
        return path is not None and rule.matches_path(path)

    return matches


def denial_message(verdict: Verdict, approval: Approval | None, can_ask: bool) -> str:
    """What the model is told when a call doesn't run, worded so it can choose what to do next."""
    if verdict.decision == Decision.DENY:
        return (
            f"Not run: {verdict.reason}. The user's policy forbids this. Don't try to get the "
            "same effect another way; if the task can't be done without it, say so."
        )
    if not can_ask:
        return (
            f"Not run: {verdict.reason}, which needs the user's approval, and no one is "
            "available to approve it in this run. Find another way that doesn't need it, or "
            "explain what you would have run and why."
        )
    if approval == Approval.NO:
        return (
            f"Not run: the user declined it ({verdict.reason}). Don't retry it; do the task "
            "another way, or ask the user what they'd prefer."
        )
    return f"Not run: {verdict.reason}."
