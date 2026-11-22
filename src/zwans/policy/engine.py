"""Decides, before each tool call, whether it runs, asks the user first, or is refused.

The verdict depends on the rules, the mode, and whether untrusted content (a file, a command's
output, a web page) is already in the conversation, since that content may carry instructions
planted for the model. A refusal goes back to the model as a tool error that says why.
"""

import asyncio
import glob
import itertools
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from zwans.policy.classify import Action, Kind, analyze
from zwans.policy.rules import (
    FILE_CHANGE_TOOLS,
    SEARCH_TOOLS,
    Decision,
    Policy,
    Rule,
    normalize,
    strictest,
)

# Tools whose output comes from outside: files, programs, the web. Instructions inside it
# are data, not the user's.
# A subagent's report (Task) is made from what it read, so it counts too.
UNTRUSTED_OUTPUT = frozenset(
    {
        "Read",
        "Grep",
        "Bash",
        "BashOutput",
        "Diagnostics",
        "RunTests",
        "Python",
        "Docs",
        "Outline",
        "References",
        "ShowChanges",
        "web_search",
        "web_fetch",
        "WebSearch",
        "WebFetch",
        "Skill",
        "Task",
    }
)
MCP_PREFIX = "mcp__"
MAX_GLOB_NAMES = 1000  # the files of a command's glob looked at for links out of the workspace
MAX_ALWAYS = 5  # files a call may change and still be offered "always", which names each one


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
    # What an Edit or Write would change, as a unified diff against the file as it is now
    # (from /dev/null for a new file). None when there's nothing to show or it can't be read.
    preview: str | None = None


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
    # The workspace folder, to see which files a command's globs name. None: globs aren't
    # looked up, and only their text is judged.
    root: Path | None = None
    tainted: bool = False  # untrusted content has been read in this session
    session_rules: list[Rule] = field(default_factory=list)  # added by "always"
    # One question at a time, since subagents running together can each need one.
    _asking: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def check(self, tool: _ToolLike, args: dict[str, Any]) -> Verdict:
        commands = getattr(tool, "commands", None)
        host = getattr(tool, "host", None)
        edited = getattr(tool, "edited_paths", None)
        if tool.name == "Bash" and isinstance(args.get("command"), str):
            verdict = self._check_command(args["command"])
        elif callable(commands):
            # A tool that runs programs (Diagnostics, RunTests) is judged by each command it
            # would run, exactly as if Bash ran it, so the rules about commands cover it too.
            verdict = _combine([self._check_command(command) for command in commands(args)])
        elif callable(host):
            verdict = self._check_network(tool, str(host(args)))
        elif callable(edited):
            # A tool that changes several files (MultiEdit, Rename): each is judged as an
            # Edit of it would be, and one refusal refuses the call.
            paths: Sequence[str | None] = edited(args) or [None]
            verdict = _combine([self._check_tool(tool, path) for path in paths])
            if len(paths) > MAX_ALWAYS:
                verdict = Verdict(verdict.decision, verdict.reason)
        else:
            path = args.get("path")
            verdict = self._check_tool(tool, path if isinstance(path, str) else None)
        # Read-only mode asks nothing, so what an ask rule covers is refused there too.
        if verdict.decision == Decision.ASK and self.policy.mode == "read-only":
            return Verdict(Decision.DENY, f"{verdict.reason}, and Zwans is in read-only mode")
        return verdict

    async def ask(self, request: PermissionRequest) -> Approval:
        if self.approver is None:
            return Approval.NO
        async with self._asking:
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
        # A Grep through a folder that holds covered files is judged like reading them.
        searching = tool.name in SEARCH_TOOLS
        matched = self._match(tool.name, _matches_path(relative, folder=searching))
        what = f"{tool.name} {relative}" if relative else tool.name
        # An MCP tool reaches whatever its server does, so after untrusted content it's
        # judged like a network command: it could carry what was read somewhere else.
        mcp = tool.name.startswith(MCP_PREFIX)
        effect = "can change things outside the workspace" if mcp else "changes files"
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
            return Verdict(Decision.DENY, f"{what} {effect}, and Zwans is in read-only mode")
        elif self.policy.mode == "ask" or tool.name not in FILE_CHANGE_TOOLS:
            verdict = Verdict(Decision.ASK, f"{what} {effect}")
        else:
            verdict = Verdict(Decision.ALLOW)
        after = self.policy.after_untrusted.network if mcp else self.policy.after_untrusted.write
        if self.tainted and strictest(after, verdict.decision) != verdict.decision:
            verdict = Verdict(after, f"{what} {effect} after untrusted content was read")
        # An allow rule from "always" would be overruled by the untrusted content, so it isn't
        # offered then.
        if verdict.decision == Decision.ASK and not (self.tainted and after != Decision.ALLOW):
            always = f"{tool.name}({relative})" if relative else tool.name
            return Verdict(Decision.ASK, verdict.reason, (always,))
        return verdict

    # -- tools that send a request out

    def _check_network(self, tool: _ToolLike, host: str) -> Verdict:
        """A tool that sends a request to `host` (WebFetch, WebSearch), judged like a command
        that uses the network. Its rules name hosts: WebFetch(docs.python.org) or
        WebFetch(*.python.org), and WebFetch alone for every host."""
        what = f"{tool.name} {host}" if host else tool.name

        def matches(rule: Rule) -> bool:
            return rule.pattern is None or (bool(host) and fnmatchcase(host, rule.pattern))

        matched = self._match(tool.name, matches)
        if matched is not None:
            decision, rule = matched
            if decision != Decision.ALLOW:
                return Verdict(
                    decision, f"{what} matches the {decision} rule {rule} ({rule.source})"
                )
            verdict = Verdict(Decision.ALLOW)
        elif self.policy.mode == "read-only":
            return Verdict(
                Decision.DENY, f"{what} uses the network, and Zwans is in read-only mode"
            )
        else:
            verdict = Verdict(Decision.ASK, f"{what} uses the network")
        # What was read could be sent out in the address or the search itself.
        after = self.policy.after_untrusted.network
        if self.tainted and strictest(after, verdict.decision) != verdict.decision:
            verdict = Verdict(after, f"{what} uses the network after untrusted content was read")
        if verdict.decision == Decision.ASK and not (self.tainted and after != Decision.ALLOW):
            always = f"{tool.name}({host})" if host else tool.name
            return Verdict(Decision.ASK, verdict.reason, (always,))
        return verdict

    # -- Bash

    def _check_command(self, command: str) -> Verdict:
        return _combine([self._check_action(action) for action in analyze(command, self.inside)])

    def _check_action(self, action: Action) -> Verdict:
        shown = f"`{_brief(action.display)}`"
        # File rules apply to the files a command names, as they do to the file tools.
        by_file = self._check_files(action, shown)
        texts = {action.command, action.display, action.bare}
        matched = self._match(
            "Bash",
            lambda rule: any(rule.matches_command(t) for t in texts if t),
            allows=lambda rule: _allows(rule, action),
        )
        by_rule = None
        if matched is not None and matched[0] != Decision.ALLOW:
            decision, rule = matched
            reason = f"{shown} matches the {decision} rule {rule} ({rule.source})"
            by_rule = Verdict(decision, reason)
        # Deny wins over ask, whichever kind of rule says it. A file rule that asks wins over
        # any allow rule, so "always" couldn't help and isn't offered.
        found = [v for v in (by_file, by_rule) if v is not None]
        if found:
            worst = strictest(*(v.decision for v in found))
            return next(v for v in found if v.decision == worst)
        verdict = Verdict(Decision.ALLOW) if matched is not None else self._by_mode(action, shown)
        after = self._after_untrusted(action.kind) if self.tainted else None
        if after is not None and strictest(after, verdict.decision) != verdict.decision:
            what = "uses the network" if action.kind == Kind.NETWORK else "changes files"
            verdict = Verdict(after, f"{shown} {what} after untrusted content was read")
        # After untrusted content, an allow rule from "always" would be overruled for this kind
        # of command, so it isn't offered.
        # Nor when the command's text doesn't show what runs, so no rule could say.
        lasting = (after is None or after == Decision.ALLOW) and not action.opaque
        if verdict.decision == Decision.ASK and lasting:
            return Verdict(Decision.ASK, verdict.reason, (_exact_rule(action.display),))
        return verdict

    def _after_untrusted(self, kind: Kind) -> Decision | None:
        """What the policy says about this kind of command once untrusted content is read."""
        if kind == Kind.NETWORK:
            return self.policy.after_untrusted.network
        if kind == Kind.WRITE:
            return self.policy.after_untrusted.write
        return None

    def _check_files(self, action: Action, shown: str) -> Verdict | None:
        """The strictest file rule, other than allow, for the files a command names."""
        found: list[Verdict] = []
        for verb, paths in (("writes", action.writes), ("reads", action.reads)):
            for path in paths:
                if self._leaves_by_link(path):
                    # `cat notes` where notes links to ~/.aws/credentials. No rule can say.
                    reason = f"{shown} {verb} {path}, which leads outside the workspace"
                    found.append(Verdict(Decision.ASK, f"{reason} through a symbolic link"))
                    continue
                relative = self._rule_path(path)
                matched = self._match_file(verb, relative)
                if matched is not None and matched[0] != Decision.ALLOW:
                    decision, rule = matched
                    reason = f"{shown} {verb} {relative}, which matches the {decision} rule {rule}"
                    found.append(Verdict(decision, f"{reason} ({rule.source})"))
        if not found:
            return None
        worst = strictest(*(v.decision for v in found))
        return next(v for v in found if v.decision == worst)

    def _match_file(self, verb: str, path: str) -> tuple[Decision, Rule] | None:
        # A folder counts as the files in it: writing to it (rm -rf .git) changes them, and
        # reading it may read them all (grep -r KEY secrets, cp -r secrets /tmp, mv secrets x).
        tool = "Write" if verb == "writes" else "Read"
        return self._match(tool, lambda rule: rule.may_cover(path, folder=True))

    def _leaves_by_link(self, path: str) -> bool:
        """Whether a path that looks like it's in the workspace leads out of it through a
        symbolic link, which a cloned project can bring with it."""
        parts = PurePosixPath(path).parts
        if not parts or parts[0] in ("/", "~") or path.startswith("~") or ".." in parts:
            return False  # outside on its face, which the classifier judges
        if not self.inside(path):
            return True
        if self.root is None or not any(c in path for c in "*?["):
            return False
        # A glob counts as the files it names now: `cat docs/*` may name such a link. `**`
        # is taken as `*` here, which keeps the look-up quick.
        names = itertools.islice(glob.iglob(path, root_dir=self.root), MAX_GLOB_NAMES)
        return any(not self.inside(name) for name in names)

    def _rule_path(self, path: str) -> str:
        """A path from a command as file rules see it: relative to the workspace root."""
        try:
            return self.relative(path)
        except (OSError, ValueError):
            return normalize(path)  # outside the workspace, such as /tmp

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

    def _match(
        self,
        tool: str,
        matches: Callable[[Rule], bool],
        allows: Callable[[Rule], bool] | None = None,
    ) -> tuple[Decision, Rule] | None:
        """The strictest rule that matches, or None. `allows` replaces `matches` for allow
        rules, when they need a closer look."""
        session = {Decision.ALLOW: self.session_rules}
        for decision in (Decision.DENY, Decision.ASK, Decision.ALLOW):
            test = allows if decision == Decision.ALLOW and allows is not None else matches
            for rule in [*self.policy.rules[decision], *session.get(decision, [])]:
                if rule.covers(tool) and test(rule):
                    return decision, rule
        return None


def _combine(verdicts: Sequence[Verdict]) -> Verdict:
    """One verdict for a call that does several things: the strictest of theirs."""
    if not verdicts:
        return Verdict(Decision.ALLOW)
    worst = strictest(*(v.decision for v in verdicts))
    if worst == Decision.ALLOW:
        return Verdict(Decision.ALLOW)
    chosen = [v for v in verdicts if v.decision == worst]
    reason = "; ".join(dict.fromkeys(v.reason for v in chosen))
    asked = [v for v in verdicts if v.decision == Decision.ASK]
    # "Always" is offered only when its rules would let this whole call run next time.
    rules: tuple[str, ...] = ()
    if all(v.rules for v in asked):
        rules = tuple(dict.fromkeys(r for v in asked for r in v.rules))
    return Verdict(worst, reason, rules)


def _allows(rule: Rule, action: Action) -> bool:
    """Whether an allow rule covers a command. Not by its words alone, so `Bash(cat)` doesn't
    allow `cat > app.py`, nor `bash` fed a here-document. Only a rule for that exact command
    covers one that reaches outside the workspace: `Bash(cat *)` doesn't allow
    `cat < ~/.ssh/id_rsa`. And none covers one whose text doesn't show what it runs or reads,
    such as `cat $(...)` or `... | bash`."""
    if action.opaque:
        return False
    if action.outside and (rule.pattern is None or _has_wildcard(rule.pattern)):
        return False
    # A here-document is part of what runs, so the rule must match the text that shows it.
    texts = {action.display} if action.heredocs else {action.command, action.display}
    return any(rule.matches_command(text) for text in texts)


def _has_wildcard(pattern: str) -> bool:
    unescaped = pattern.replace("[[]", "").replace("[*]", "").replace("[?]", "")
    return any(c in unescaped for c in "*?[")


def _exact_rule(command: str) -> str:
    """A Bash rule for exactly this command, with *, ? and [ escaped so they match themselves."""
    escaped = command.replace("[", "[[]").replace("*", "[*]").replace("?", "[?]")
    return f"Bash({escaped})"


def _brief(command: str, limit: int = 80) -> str:
    """A command's first line, cut short, for a reason the user and the model read."""
    first, newline, _ = command.partition("\n")
    if len(first) > limit or newline:
        return first[:limit].rstrip() + " ..."
    return first


def _matches_path(path: str | None, *, folder: bool = False) -> Callable[[Rule], bool]:
    def matches(rule: Rule) -> bool:
        if rule.pattern is None:
            return True
        if path is None:
            return False
        return rule.may_cover(path, folder=True) if folder else rule.matches_path(path)

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
