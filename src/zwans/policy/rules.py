"""The policy file: which tool calls run, which ask first, and which never run.

~/.zwans/policy.toml applies everywhere, and <workspace>/.zwans/policy.toml adds to it:

    mode = "ask"                       # read-only, ask, or auto
    allow = ["Bash(pytest *)", "Bash(git commit *)"]
    ask = ["Edit(migrations/**)"]
    deny = ["Bash(git push *)", "Read(.env)"]

    [after_untrusted]                  # once a file, page or command output has been read
    network = "ask"                    # commands that use the network
    write = "allow"                    # file changes

    [[hooks]]                          # commands that check calls; see ext/hooks.py
    event = "pre_tool"
    tools = "Bash"
    command = "python3 ~/.zwans/hooks/no_push.py"

A rule is a tool name, optionally with a pattern: a command pattern for Bash, where * matches
anything, or a path glob for the file tools. Deny wins over ask, and ask over allow.

A workspace's file comes with the code, so it may have been written by someone else. Its deny
and ask rules always apply, but anything that loosens the policy (allow rules, mode "auto",
"allow" after untrusted content) or runs a command (hooks) applies only once the user has
trusted that exact file.
"""

import hashlib
import json
import re
import shlex
import sys
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from zwans.ext.hooks import HookSpec

type Mode = Literal["read-only", "ask", "auto"]
MODES: tuple[Mode, ...] = ("read-only", "ask", "auto")  # from the strictest to the loosest

RULE = re.compile(r"^\s*([A-Za-z_][\w.-]*)\s*(?:\((.*)\))?\s*$", re.DOTALL)
# These all change files, so a rule for one covers the others. Memory's file is Zwans's
# own, outside the workspace, but what it holds steers later sessions, so it's judged as
# a change too.
FILE_CHANGE_TOOLS = frozenset({"Edit", "MultiEdit", "Write", "Rename", "Memory"})
# These show what's in the files they look through, so a rule about reading covers them.
SEARCH_TOOLS = frozenset({"Grep", "Outline", "References"})
# These show a file's content in another form, so a rule about reading it covers them too.
VIEW_TOOLS = frozenset({"Video"})
# The built-in tools' names, so a rule for a misspelled one is reported instead of never
# matching. MCP tools are named mcp__<server>__<tool>. tests/test_policy.py checks that this
# lists every tool in zwans.tools.
TOOL_NAMES = frozenset(
    {
        "Bash",
        "BashOutput",
        "KillBash",
        "Read",
        "Video",
        "Write",
        "Edit",
        "MultiEdit",
        "Rename",
        "Outline",
        "References",
        "ShowChanges",
        "RunTests",
        "Diagnostics",
        "Docs",
        "Python",
        "Memory",
        "AskUser",
        "WebFetch",
        "WebSearch",
        "Glob",
        "Grep",
        "Skill",
        "Task",
        "TodoWrite",
        "web_search",
        "web_fetch",
    }
)
MCP_PREFIX = "mcp__"
# macOS and Windows file systems ignore case by default, so .GIT/config is .git/config there
# and path rules must match it too.
IGNORE_CASE = sys.platform in ("darwin", "win32")


class PolicyError(Exception):
    """A policy file that can't be used. The message is safe to print: a workspace's file can
    hold escape codes in its keys and rules, and they are shown as text (such as \\x1b)."""

    def __init__(self, message: str) -> None:
        super().__init__(UNSAFE.sub(_escape, message))


# Control characters other than tab and newline, and the bidirectional overrides, as in
# zwans.cli.terminal_text, which the policy doesn't import.
UNSAFE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f‪-‮⁦-⁩]")


def _escape(match: re.Match[str]) -> str:
    code = ord(match.group())
    return f"\\x{code:02x}" if code < 0x100 else f"\\u{code:04x}"


class Decision(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


DECISION_ORDER = (Decision.ALLOW, Decision.ASK, Decision.DENY)


def strictest(*decisions: Decision) -> Decision:
    return max(decisions, key=DECISION_ORDER.index)


@dataclass(frozen=True)
class Rule:
    tool: str
    pattern: str | None = None  # None matches every call to the tool
    source: str = ""  # where the rule came from, for messages

    @classmethod
    def parse(cls, text: str, source: str = "") -> "Rule":
        match = RULE.match(text)
        if not match:
            raise PolicyError(f'{source}: "{text}" is not a rule like "Bash(git push *)"')
        tool, pattern = match.group(1), match.group(2)
        if pattern is not None:
            pattern = pattern.strip()
        return cls(tool, pattern or None, source)

    def __str__(self) -> str:
        return self.tool if self.pattern is None else f"{self.tool}({self.pattern})"

    def covers(self, tool: str) -> bool:
        if self.tool in FILE_CHANGE_TOOLS and tool in FILE_CHANGE_TOOLS:
            return True
        # A search shows what's in the files it looks through, so a Read rule applies to it.
        if self.tool == "Read" and (tool in SEARCH_TOOLS or tool in VIEW_TOOLS):
            return True
        return self.tool == tool

    def matches_command(self, command: str) -> bool:
        if self.pattern is None:
            return True
        if fnmatchcase(command, self.pattern):
            return True
        # "git push *" also covers a bare "git push"
        return self.pattern.endswith(" *") and fnmatchcase(command, self.pattern[:-2])

    def matches_path(self, path: str) -> bool:
        return self.pattern is None or path_glob(self.pattern).match(path) is not None

    def may_cover(self, path: str, *, folder: bool) -> bool:
        """Whether a path a command names could be a file this rule covers: the path itself, a
        glob that could expand to one (`.e*` for `.env`), or, with `folder`, a folder that
        holds one (`.git` for `.git/**`), since removing or moving it changes what's inside.
        Globs count in any part of the path (`secre*/key.pem`, `.gi?/hooks`), and a `**` part
        stands for any number of folders, as in `find . -name x`.
        The workspace root isn't counted as such a folder: it holds everything."""
        if self.pattern is None or self.matches_path(path):
            return True
        parts = PurePosixPath(path).parts
        if not parts or parts[0] in ("/", ".."):
            return False
        pattern = self.pattern.removeprefix("./")
        if pattern.endswith("/"):
            pattern += "**"
        rule_parts = tuple(pattern.split("/"))
        if len(rule_parts) == 1:  # a name at any depth, like .env or *.pem
            return parts[-1] == "**" or _could_match(parts[-1], pattern)
        return _parts_cover(tuple(parts), rule_parts, folder)


def _parts_cover(path: tuple[str, ...], rule: tuple[str, ...], folder: bool) -> bool:
    """Whether a path's parts, each a shell glob, could name a file the rule's parts match.
    A `**` in the rule spans folders, at least one when it ends the rule; a `**` in the path
    spans any folders, hidden ones too. A path that ends first is a folder holding the file."""
    seen: dict[tuple[int, int], bool] = {}

    def cover(p: int, r: int) -> bool:
        if (p, r) in seen:
            return seen[(p, r)]
        if r == len(rule):
            result = all(part == "**" for part in path[p:])
        elif p == len(path):
            result = folder
        elif path[p] == "**":
            result = cover(p + 1, r) or cover(p, r + 1)
        elif rule[r] == "**":
            last = r == len(rule) - 1
            result = cover(p + 1, r) or cover(p + 1 if last else p, r + 1)
        else:
            result = _could_match(path[p], rule[r]) and cover(p + 1, r + 1)
        seen[(p, r)] = result
        return result

    return cover(0, 0)


@dataclass(frozen=True)
class _Chars:
    """One character of a glob: one of `chars`, or with `negated`, any other."""

    chars: frozenset[str]
    negated: bool = False

    def meets(self, other: "_Chars") -> bool:
        """Whether some character fits both."""
        if self.negated and other.negated:
            return True  # two exclusions always leave something
        if self.negated:
            return bool(other.chars - self.chars)
        if other.negated:
            return bool(self.chars - other.chars)
        return bool(self.chars & other.chars)


ANY_CHAR = _Chars(frozenset(), negated=True)
DOT = _Chars(frozenset("."))
NOT_DOT = _Chars(frozenset("."), negated=True)
MAX_CLASS = 256  # a bigger range, like [!-~], is taken as any character
type _Token = _Chars | None  # None is *


def _could_match(word: str, name: str) -> bool:
    """Whether a shell word could stand for a file whose name the rule's glob `name` matches:
    some name fits both. A shell glob doesn't match a leading dot unless it starts with one,
    so `*` doesn't stand for `.git`. Rule globs know only * and ?, so [ is a plain letter."""
    if IGNORE_CASE:
        word, name = word.lower(), name.lower()
    if word == name:
        return True
    a, b = _glob_tokens(word, classes=True), _glob_tokens(name, classes=False)
    seen: dict[tuple[int, int, bool], bool] = {}

    def fits(i: int, j: int, started: bool) -> bool:
        key = (i, j, started)
        if key not in seen:
            seen[key] = step(i, j, started)
        return seen[key]

    def step(i: int, j: int, started: bool) -> bool:
        if i == len(a) and j == len(b):
            return True
        x = a[i] if i < len(a) else ANY_CHAR  # ANY_CHAR stands in for "nothing left"
        y = b[j] if j < len(b) else ANY_CHAR
        if x is None:
            if fits(i + 1, j, started):  # the word's * matches nothing
                return True
            if y is None:  # both stars: either matches nothing, or both take a plain letter
                return fits(i, j + 1, started) or (not started and fits(i, j, True))
            # The word's * takes the rule's next character, which can't be a leading dot.
            return j < len(b) and (started or y.meets(NOT_DOT)) and fits(i, j + 1, True)
        if y is None:
            return fits(i, j + 1, started) or (i < len(a) and fits(i + 1, j, True))
        if i == len(a) or j == len(b):
            return False
        if not started and x != DOT and not y.meets(NOT_DOT):
            return False  # only a literal dot in the word matches a leading dot
        return x.meets(y) and fits(i + 1, j + 1, True)

    return fits(0, 0, False)


def _glob_tokens(text: str, *, classes: bool) -> list[_Token]:
    tokens: list[_Token] = []
    i = 0
    while i < len(text):
        c = text[i]
        i += 1
        if c == "*":
            if not tokens or tokens[-1] is not None:
                tokens.append(None)
        elif c == "?":
            tokens.append(ANY_CHAR)
        elif c == "[" and classes and (found := _char_class(text, i)) is not None:
            token, i = found
            tokens.append(token)
        else:
            tokens.append(_Chars(frozenset(c)))
    return tokens


def _char_class(text: str, start: int) -> tuple[_Chars, int] | None:
    """The shell class `[...]` whose body starts at `start`, and where it ends, or None when
    it isn't closed (the [ is then a plain letter)."""
    i = start
    negated = i < len(text) and text[i] in "!^"
    if negated:
        i += 1
    end = i + 1 if i < len(text) and text[i] == "]" else i  # a ] first is a plain letter
    named = False
    while end < len(text) and text[end] != "]":
        # [:alpha:], [=e=] and [.e.] end with their own ], which doesn't close the class.
        if text[end] == "[" and text[end + 1 : end + 2] in (":", "=", "."):
            close = text.find(text[end + 1] + "]", end + 2)
            if close < 0:
                return None
            named = True
            end = close + 2
        else:
            end += 1
    if end >= len(text):
        return None
    if named:
        return ANY_CHAR, end + 1  # named classes: any character, which only covers more
    body = text[i:end]
    chars: set[str] = set()
    k = 0
    while k < len(body):
        if k + 2 < len(body) and body[k + 1] == "-":
            low, high = ord(body[k]), ord(body[k + 2])
            if high - low > MAX_CLASS:
                return ANY_CHAR, end + 1
            chars.update(chr(code) for code in range(low, high + 1))
            k += 3
        else:
            chars.add(body[k])
            k += 1
    if IGNORE_CASE:
        chars = {c.lower() for c in chars}
    return _Chars(frozenset(chars), negated), end + 1


def path_glob(pattern: str) -> re.Pattern[str]:
    """Compile a gitignore-style glob. A pattern without a slash matches at any depth, ** spans
    folders, and a trailing slash means everything in that folder."""
    pattern = pattern.removeprefix("./")
    if pattern.endswith("/"):
        pattern += "**"
    if "/" not in pattern:
        pattern = "**/" + pattern
    regex = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            regex += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            regex += ".*"
            i += 2
        elif pattern[i] == "*":
            regex += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            regex += "[^/]"
            i += 1
        else:
            regex += re.escape(pattern[i])
            i += 1
    return re.compile(regex + r"\Z", re.IGNORECASE if IGNORE_CASE else 0)


class AfterUntrusted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    network: Decision = Decision.ASK
    write: Decision = Decision.ALLOW


class PolicyFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode | None = None
    allow: list[str] = []
    ask: list[str] = []
    deny: list[str] = []
    after_untrusted: AfterUntrusted | None = None
    hooks: list[HookSpec] = []

    def needs_trust(self) -> bool:
        """Whether it loosens the policy or runs commands, so a workspace's copy must be
        trusted first."""
        relaxed = self.after_untrusted is not None and (
            self.after_untrusted.network == Decision.ALLOW
            or self.after_untrusted.write == Decision.ALLOW
        )
        return bool(self.allow) or self.mode == "auto" or relaxed or bool(self.hooks)


# Built in, so they apply whatever the files say: the agent can't quietly rewrite its own
# policy, or git's hooks and config, which run programs later.
BUILT_IN_ASK = ("Edit(.zwans/**)", "Edit(.git/**)")


@dataclass
class Policy:
    mode: Mode = "ask"
    rules: dict[Decision, list[Rule]] = field(
        default_factory=lambda: {decision: [] for decision in Decision}
    )
    after_untrusted: AfterUntrusted = field(default_factory=AfterUntrusted)
    hooks: list[HookSpec] = field(default_factory=list)

    @classmethod
    def default(cls) -> "Policy":
        policy = cls()
        policy.rules[Decision.ASK] = [Rule.parse(r, "built in") for r in BUILT_IN_ASK]
        return policy

    def add(self, file: PolicyFile, source: str, *, loosen: bool = True) -> None:
        for decision in Decision:
            if decision == Decision.ALLOW and not loosen:
                continue
            texts: list[str] = getattr(file, decision.value)
            self.rules[decision].extend(Rule.parse(text, source) for text in texts)
        if file.mode is not None and (loosen or MODES.index(file.mode) < MODES.index(self.mode)):
            self.mode = file.mode
        if file.after_untrusted is not None:
            for name in ("network", "write"):
                new: Decision = getattr(file.after_untrusted, name)
                old: Decision = getattr(self.after_untrusted, name)
                if loosen or strictest(new, old) == new:
                    setattr(self.after_untrusted, name, new)
        if loosen:
            self.hooks.extend(file.hooks)

    def hidden_from_search(self, search: str) -> list[str]:
        """Globs, for ripgrep's --glob (gitignore-style, from the workspace root), for the files
        that Read deny and ask rules cover, so a Grep through a folder doesn't show them. Such
        a rule that covers the searched path itself was applied to the call already (it was
        refused, or the user said yes), so it's left out."""
        globs: list[str] = []
        for decision in (Decision.DENY, Decision.ASK):
            for rule in self.rules[decision]:
                if rule.pattern is None or not rule.covers("Grep"):
                    continue
                if rule.may_cover(search, folder=True):
                    continue
                pattern = rule.pattern.removeprefix("./")
                if pattern.endswith("/"):
                    pattern += "**"
                # Rule globs know only * and ?; ripgrep's other special letters are escaped.
                globs.append(re.sub(r"([\[\]{}\\!])", r"\\\1", pattern))
        return list(dict.fromkeys(globs))


def read_policy_file(path: Path) -> PolicyFile | None:
    if not path.is_file():
        return None
    try:
        file = PolicyFile.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
    except ValidationError as exc:
        raise PolicyError(f"{path}: {_describe(exc)}") from exc
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PolicyError(f"{path}: {exc}") from exc
    for decision in Decision:
        for text in getattr(file, decision.value):
            # Reports a bad rule now, not on first use, and one that could never match.
            _check_tool_name(Rule.parse(text, str(path)), path)
    return file


def _check_tool_name(rule: Rule, path: Path) -> None:
    if rule.tool in TOOL_NAMES or rule.tool.startswith(MCP_PREFIX):
        return
    same = [name for name in TOOL_NAMES if name.lower() == rule.tool.lower()]
    if same:
        raise PolicyError(f"{path}: the rule {rule} names {rule.tool}; did you mean {same[0]}?")
    names = ", ".join(sorted(TOOL_NAMES, key=str.lower))
    raise PolicyError(
        f"{path}: the rule {rule} names {rule.tool}, which isn't a Zwans tool. The tools are "
        f"{names}, and MCP tools are named {MCP_PREFIX}<server>__<tool>."
    )


# The keys each part of a policy file takes, for messages about one that isn't known.
_SECTIONS: dict[tuple[str, ...], type[BaseModel]] = {
    (): PolicyFile,
    ("after_untrusted",): AfterUntrusted,
    ("hooks",): HookSpec,
}


def _describe(exc: ValidationError) -> str:
    """Pydantic's errors, said plainly: `unknown key alow (expected mode, allow, ...)`."""
    problems: list[str] = []
    for error in exc.errors():
        where = ".".join(str(part) for part in error["loc"])
        if error["type"] == "extra_forbidden":
            section = tuple(str(p) for p in error["loc"][:-1] if not isinstance(p, int))
            model = _SECTIONS.get(section)
            expected = f" (expected {', '.join(model.model_fields)})" if model else ""
            problems.append(f"unknown key `{where}`{expected}")
        else:
            problems.append(f"`{where}`: {error['msg']}")
    return "; ".join(problems)


@dataclass
class LoadedPolicy:
    policy: Policy
    # A workspace policy that would loosen the rules or run hooks but isn't trusted yet; those
    # parts were left out.
    untrusted: Path | None = None


def load_policy(workspace: Path, home: Path, mode: Mode | None = None) -> LoadedPolicy:
    """The user's policy, then the workspace's, then `mode` from the command line."""
    policy = Policy.default()
    user_file = read_policy_file(home / "policy.toml")
    if user_file is not None:
        policy.add(user_file, str(home / "policy.toml"))
    untrusted = None
    path = workspace / ".zwans" / "policy.toml"
    workspace_file = read_policy_file(path)
    if workspace_file is not None:
        trusted = is_trusted(path, home)
        if workspace_file.needs_trust() and not trusted:
            untrusted = path
        policy.add(workspace_file, str(path), loosen=trusted)
    if mode is not None:
        policy.mode = mode
    return LoadedPolicy(policy, untrusted)


def _trust_file(home: Path) -> Path:
    return home / "trusted-policies.json"


def _digest(path: Path) -> str:
    """The policy's content, with the hook scripts it runs from the workspace."""
    digest = hashlib.sha256(path.read_bytes())
    workspace = path.resolve().parent.parent
    for script in hook_scripts(path):
        name = script.relative_to(workspace).as_posix()
        digest.update(f"\0{name}\0".encode())
        digest.update(hashlib.sha256(script.read_bytes()).digest())
    return digest.hexdigest()


def hook_scripts(path: Path) -> list[Path]:
    """The workspace files that a workspace policy's hooks run, like .zwans/hooks/check.py in
    `python3 .zwans/hooks/check.py`. Trusting the policy covers them, so a change to one
    needs trusting again."""
    try:
        file = PolicyFile.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
    except (OSError, tomllib.TOMLDecodeError, ValidationError):
        return []
    workspace = path.resolve().parent.parent
    found: set[Path] = set()
    for hook in file.hooks:
        try:
            tokens = shlex.split(hook.command)
        except ValueError:
            tokens = hook.command.split()
        for token in tokens:
            candidate = (workspace / token).resolve()  # hooks run in the workspace folder
            if candidate.is_relative_to(workspace) and candidate.is_file():
                found.add(candidate)
    return sorted(found)


def is_trusted(path: Path, home: Path) -> bool:
    try:
        trusted = json.loads(_trust_file(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(trusted, dict) and trusted.get(str(path.resolve())) == _digest(path)


def trust(path: Path, home: Path) -> None:
    """Trust this exact content of a workspace policy. Any later change needs trusting again."""
    store = _trust_file(home)
    try:
        trusted = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        trusted = {}
    trusted[str(path.resolve())] = _digest(path)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(trusted, indent=2), encoding="utf-8")


def normalize(path: str) -> str:
    return PurePosixPath(path).as_posix().removeprefix("./")
