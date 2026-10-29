"""The policy file: which tool calls run, which ask first, and which never run.

~/.zwans/policy.toml applies everywhere, and <workspace>/.zwans/policy.toml adds to it:

    mode = "ask"                       # read-only, ask, or auto
    allow = ["Bash(pytest *)", "Bash(git commit *)"]
    ask = ["Edit(migrations/**)"]
    deny = ["Bash(git push *)", "Read(.env)"]

    [after_untrusted]                  # once a file, page or command output has been read
    network = "ask"                    # commands that use the network
    write = "allow"                    # file changes

A rule is a tool name, optionally with a pattern: a command pattern for Bash, where * matches
anything, or a path glob for the file tools. Deny wins over ask, and ask over allow.

A workspace's file comes with the code, so it may have been written by someone else. Its deny
and ask rules always apply, but anything that loosens the policy (allow rules, mode "auto",
"allow" after untrusted content) applies only once the user has trusted that exact file.
"""

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

type Mode = Literal["read-only", "ask", "auto"]
MODES: tuple[Mode, ...] = ("read-only", "ask", "auto")  # from the strictest to the loosest

RULE = re.compile(r"^\s*([A-Za-z_][\w.-]*)\s*(?:\((.*)\))?\s*$", re.DOTALL)
# Edit and Write both change files, so a rule for one covers the other.
FILE_CHANGE_TOOLS = frozenset({"Edit", "Write"})


class PolicyError(Exception):
    pass


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
    return re.compile(regex + r"\Z")


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

    def loosens(self) -> bool:
        relaxed = self.after_untrusted is not None and (
            self.after_untrusted.network == Decision.ALLOW
            or self.after_untrusted.write == Decision.ALLOW
        )
        return bool(self.allow) or self.mode == "auto" or relaxed


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


def read_policy_file(path: Path) -> PolicyFile | None:
    if not path.is_file():
        return None
    try:
        file = PolicyFile.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise PolicyError(f"{path}: {exc}") from exc
    for decision in Decision:
        for text in getattr(file, decision.value):
            Rule.parse(text, str(path))  # reports a bad rule now, not on first use
    return file


@dataclass
class LoadedPolicy:
    policy: Policy
    # A workspace policy that would loosen the rules but isn't trusted yet; its loosening
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
        if workspace_file.loosens() and not trusted:
            untrusted = path
        policy.add(workspace_file, str(path), loosen=trusted)
    if mode is not None:
        policy.mode = mode
    return LoadedPolicy(policy, untrusted)


def _trust_file(home: Path) -> Path:
    return home / "trusted-policies.json"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
