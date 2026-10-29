"""Sorts each simple command in a Bash call by what it can do: read, write, run code, use the
network, or something this can't tell.

The tables cover common development commands. A program that isn't in them, or a use of one
that can reach outside the workspace, is "unknown", which the policy treats as the riskiest.
"""

import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from zwans.policy.shell import ShellParseError, SimpleCommand, Word, parse


class Kind(StrEnum):
    READ = "read"  # only looks: ls, cat, git status
    WRITE = "write"  # changes files in the workspace: mkdir, mv, git commit
    EXECUTE = "execute"  # runs code, usually the project's own: pytest, make, python x.py
    NETWORK = "network"  # talks to other machines: curl, git push, pip install
    UNKNOWN = "unknown"  # anything else, or a use this can't judge


@dataclass(frozen=True)
class Action:
    command: str  # the simple command as rules see it, with wrappers like `timeout 60` removed
    kind: Kind
    reason: str = ""  # why it's unknown, in words the model can act on
    writes: tuple[str, ...] = ()  # files it writes through a redirection


type Inside = Callable[[str], bool]  # whether a path is inside the workspace


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


READ_PROGRAMS = _words(
    "ls cat head tail wc grep egrep fgrep rg pwd echo printf which type file stat du df diff "
    "cmp uniq cut tr true false test [ date basename dirname realpath readlink tree nl od "
    "hexdump xxd md5sum sha1sum sha256sum shasum cd pushd popd sleep seq jq column comm paste "
    "fold expand unexpand whoami uname hostname id printenv export unset set shopt local "
    "declare read wait :"
)
# Programs whose arguments are never file names, so $VAR in them is harmless. Not `test`
# or `[`: `test -f ~/.ssh/id_rsa` tells whether a file outside the workspace exists.
NO_FILE_PROGRAMS = _words(
    "echo printf true false pwd date sleep seq basename dirname export unset set shopt "
    "local declare read wait : which type"
)
WRITE_PROGRAMS = _words(
    "mkdir touch cp mv rm rmdir ln chmod tee truncate patch tar unzip zip gzip gunzip bzip2 xz"
)
EXECUTE_PROGRAMS = _words(
    "pytest py.test node deno bun ruby rake perl php java javac mvn gradle make cmake ninja "
    "ruff mypy black isort flake8 pylint pyright eslint prettier tsc jest vitest tox nox "
    "source ."
)
NETWORK_PROGRAMS = _words(
    "curl wget ssh scp sftp rsync nc ncat netcat telnet ftp socat ping dig nslookup host http "
    "https aria2c npx brew apt apt-get yum dnf pacman apk gem kubectl"
)
SHELLS = _words("bash sh zsh dash ksh fish")
# Programs whose first argument is a pattern or a script, not a file name.
PATTERN_FIRST = frozenset(
    ["grep", "egrep", "fgrep", "rg", "ag", "sed", "gsed", "awk", "gawk", "mawk", "nawk", "jq"]
)
# Programs that run another command given in their arguments, and the options of theirs
# that take a value.
WRAPPERS: dict[str, frozenset[str]] = {
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "nohup": frozenset(),
    "time": frozenset(),
    "command": frozenset(),
    "builtin": frozenset(),
    "exec": frozenset({"-a"}),
    "stdbuf": frozenset({"-i", "-o", "-e"}),
    "env": frozenset({"-u", "--unset", "-C", "--chdir"}),
    "xargs": frozenset({"-n", "-I", "-P", "-d", "-L", "-s", "-E", "-a", "--max-args"}),
}
# Variables that change which program runs or what it loads.
RISKY_VARIABLES = re.compile(
    r"^(PATH|IFS|BASH_ENV|ENV|PROMPT_COMMAND|PYTHONSTARTUP|(LD|DYLD|GIT)_\w*)$"
)
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
VERSIONED = re.compile(r"^(python|pip|pypy)[0-9.]*$")
SED_RUNS_OR_WRITES = re.compile(r"(^|[;{}\n/0-9$])\s*[ewWrR](\s|$|;)")
OUTPUT_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>", "<>", ">&"})
HARMLESS_FILES = frozenset({"/dev/null", "/dev/stdin", "/dev/stdout", "/dev/stderr", "-"})
SCRATCH_DIRS = tuple({"/tmp", str(PurePosixPath(tempfile.gettempdir()))})

GIT_READ = _words(
    "status diff log show blame rev-parse ls-files ls-tree grep shortlog describe cat-file "
    "reflog show-ref merge-base rev-list count-objects whatchanged version help"
)
GIT_NETWORK = frozenset(
    ["clone", "fetch", "pull", "push", "ls-remote", "submodule", "archive", "request-pull"]
)
PACKAGE_NETWORK = _words(
    "install i ci add update upgrade publish download wheel fetch get sync lock exec dlx "
    "create init remove uninstall audit outdated view info search"
)


def analyze(command: str, inside: Inside) -> list[Action]:
    """Every simple command in a Bash call, sorted. A line that can't be parsed is one
    unknown action, so it is never allowed by a rule meant for something simpler."""
    try:
        commands = parse(command)
    except ShellParseError as exc:
        return [Action(command.strip(), Kind.UNKNOWN, f"Zwans can't check it in parts: {exc}")]
    actions: list[Action] = []
    for simple in commands:
        actions.extend(_classify(simple, inside))
    return actions


def _classify(simple: SimpleCommand, inside: Inside) -> list[Action]:
    words = list(simple.words)
    while words and ASSIGNMENT.match(words[0].text):
        name = words[0].text.split("=", 1)[0].rstrip("+")
        if RISKY_VARIABLES.match(name):
            return [_unknown(simple.text, f"it sets {name}, which changes what programs run")]
        words.pop(0)
    redirect_kind, writes, problem = _redirects(simple, inside)
    if problem:
        return [_unknown(simple.text, problem)]
    if not words:  # only assignments or redirections, such as `> out.txt`
        return [Action(simple.text, redirect_kind, writes=writes)]

    inner = _unwrap(words)
    if isinstance(inner, str):
        return [_unknown(simple.text, inner)]
    words, args_unknown = inner
    if not words:
        return [Action(simple.text, max(redirect_kind, Kind.READ, key=_rank), writes=writes)]
    text = " ".join(word.text for word in words)

    nested = _shell(words, inside)
    if nested is not None:
        return nested
    found = _find_exec(words, inside)
    if found is not None:
        return found

    kind, reason = _program_kind(words, inside)
    if kind in (Kind.READ, Kind.WRITE, Kind.EXECUTE):
        problem = _outside_argument(words, inside, args_unknown)
        if problem:
            return [_unknown(text, problem)]
    kind = max(kind, redirect_kind, key=_rank)
    return [Action(text, kind, reason, writes)]


def _program_kind(words: list[Word], inside: Inside) -> tuple[Kind, str]:
    first = words[0]
    if first.dynamic:
        return Kind.UNKNOWN, "the program's name comes from a variable"
    if "/" in first.text:
        if inside(first.text):
            return Kind.EXECUTE, ""
        program = PurePosixPath(first.text).name  # a system program by its full path
    else:
        program = first.text
    args = [word.text for word in words[1:]]
    sub = next((a for a in args if not a.startswith("-")), "")

    if VERSIONED.match(program):
        if program.startswith("pip"):
            return _package_kind(sub, read={"list", "show", "freeze", "check", "--version"})
        if "-m" in args:
            module = args[args.index("-m") + 1] if args.index("-m") + 1 < len(args) else ""
            if module == "pip":
                rest = args[args.index("-m") + 2 :]
                return _package_kind(next((a for a in rest if not a.startswith("-")), ""))
        return Kind.EXECUTE, ""
    if program == "git":
        return _git_kind(args)
    if program in ("npm", "pnpm", "yarn", "cargo", "go", "uv", "poetry", "pdm", "bundle"):
        if program == "yarn" and not sub:
            return Kind.NETWORK, ""  # plain `yarn` installs
        if program in ("npm", "pnpm", "yarn") and sub in ("ls", "list", "why", "--version"):
            return Kind.READ, ""
        return _package_kind(sub)
    if program in ("sed", "gsed"):
        if any(a.startswith("--in-place") or (_short(a) and "i" in a[1:]) for a in args):
            return Kind.WRITE, ""
        scripts = [a for a in args if not a.startswith("-")][:1] + _option_values(args, "-e")
        if any(SED_RUNS_OR_WRITES.search(script) for script in scripts):
            return Kind.UNKNOWN, "its script may run commands or write files"
        return Kind.READ, ""
    if program in ("awk", "gawk", "mawk", "nawk"):
        script = next((a for a in args if not a.startswith("-")), "")
        if any(token in script for token in ("system", "|", ">")):
            return Kind.UNKNOWN, "its program may run commands or write files"
        return Kind.READ, ""
    if program == "sort":
        if any(a in ("-o", "--output") or a.startswith("--output=") for a in args):
            return Kind.WRITE, ""
        return Kind.READ, ""
    if program == "dd":
        return Kind.UNKNOWN, "dd can overwrite devices and files anywhere"
    if program in READ_PROGRAMS:
        return Kind.READ, ""
    if program in WRITE_PROGRAMS:
        return Kind.WRITE, ""
    if program in EXECUTE_PROGRAMS:
        return Kind.EXECUTE, ""
    if program in NETWORK_PROGRAMS:
        return Kind.NETWORK, ""
    return Kind.UNKNOWN, f"{program} isn't a command Zwans recognizes"


def _git_kind(args: list[str]) -> tuple[Kind, str]:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-c" or args[i].startswith("--config-env"):
            return Kind.UNKNOWN, "git -c can make git run any program"
        i += 2 if args[i] in ("-C", "--git-dir", "--work-tree", "--namespace") else 1
    if i >= len(args):
        return Kind.READ, ""
    sub, rest = args[i], args[i + 1 :]
    if any(a in ("-O", "--open-files-in-pager", "--ext-diff") or a.startswith("-O") for a in rest):
        return Kind.UNKNOWN, "that option makes git run another program"
    named = [a for a in rest if not a.startswith("-")]
    if sub in GIT_READ:
        return Kind.READ, ""
    if sub in ("branch", "tag", "remote", "stash", "worktree"):
        listing = not named or named[0] in ("list", "show", "-v")
        if sub == "remote" and named and named[0] in ("add", "set-url"):
            return Kind.UNKNOWN, "it changes where git sends and fetches code"
        return (Kind.READ if listing else Kind.WRITE), ""
    if sub == "config":
        reading = any(a in ("--get", "--get-all", "--list", "-l", "--get-regexp") for a in rest)
        if reading or len(named) <= 1:
            return Kind.READ, ""
        return Kind.UNKNOWN, "git settings can make git run other programs"
    if sub in GIT_NETWORK:
        return Kind.NETWORK, ""
    return Kind.WRITE, ""


def _package_kind(sub: str, read: frozenset[str] | set[str] = frozenset()) -> tuple[Kind, str]:
    if sub in read:
        return Kind.READ, ""
    if not sub or sub in PACKAGE_NETWORK:
        return Kind.NETWORK, ""
    return Kind.EXECUTE, ""  # run, test, build, ...


def _unwrap(words: list[Word]) -> tuple[list[Word], bool] | str:
    """Drop wrappers like `timeout 60` and `env X=1`. Returns the wrapped command and whether
    its arguments are unknown (xargs adds some), or why it can't be judged."""
    args_unknown = False
    while words and words[0].text in WRAPPERS and not words[0].dynamic:
        program = words[0].text
        takes_value = WRAPPERS[program]
        rest = words[1:]
        while rest and rest[0].text.startswith("-") and rest[0].text != "-":
            option = rest.pop(0).text
            if program == "command" and option in ("-v", "-V"):
                return [], False  # looks a command up without running it
            if program == "env" and option in ("-S", "--split-string"):
                return "env -S splits a string into a command Zwans can't see"
            if option in takes_value and rest:
                rest.pop(0)
        if program == "timeout" and rest:
            rest.pop(0)  # the duration
        if program == "env":
            while rest and ASSIGNMENT.match(rest[0].text):
                name = rest.pop(0).text.split("=", 1)[0]
                if RISKY_VARIABLES.match(name):
                    return f"it sets {name}, which changes what programs run"
        if program == "xargs":
            args_unknown = True
        words = rest
    return words, args_unknown


def _shell(words: list[Word], inside: Inside) -> list[Action] | None:
    """`bash -c "..."` runs the commands in its string, so judge those instead."""
    if words[0].text not in SHELLS:
        return None
    args = words[1:]
    for i, word in enumerate(args):
        if word.text == "-c" or (_short(word.text) and "c" in word.text[1:]):
            if i + 1 >= len(args):
                break
            script = args[i + 1]
            if script.dynamic:
                return [_unknown(words[0].text, "the commands it runs come from a variable")]
            return analyze(script.text, inside)
        if not word.text.startswith("-"):
            if not inside(word.text):
                return [_unknown(word.text, f"{word.text} is outside the workspace")]
            return [Action(" ".join(w.text for w in words), Kind.EXECUTE)]
    return [_unknown(words[0].text, "it runs commands from its input, which Zwans can't see")]


def _find_exec(words: list[Word], inside: Inside) -> list[Action] | None:
    """find's -exec runs a command per file; -delete and -fprint write."""
    if words[0].text != "find":
        return None
    actions: list[Action] = []
    expression_kind = Kind.READ
    i = 1
    while i < len(words):
        option = words[i].text
        if option in ("-exec", "-execdir", "-ok", "-okdir"):
            end = i + 1
            while end < len(words) and words[end].text not in (";", "+"):
                end += 1
            inner = SimpleCommand(words=words[i + 1 : end])
            if inner.words:
                actions.extend(_classify(inner, inside))
            i = end + 1
            continue
        if option in ("-delete", "-fprint", "-fprint0", "-fprintf", "-fls"):
            expression_kind = Kind.WRITE
        i += 1
    plain = [w for w in words if w.text not in ("-exec", "-execdir", "-ok", "-okdir")]
    problem = _outside_argument(plain[: _first_option(plain)], inside, False)
    text = " ".join(word.text for word in words)
    if problem:
        return [_unknown(text, problem)]
    return [Action(text, expression_kind), *actions]


def _first_option(words: list[Word]) -> int:
    for i, word in enumerate(words[1:], start=1):
        if word.text.startswith("-") or word.text in ("(", "!"):
            return i
    return len(words)


def _redirects(simple: SimpleCommand, inside: Inside) -> tuple[Kind, tuple[str, ...], str]:
    kind = Kind.READ
    writes: list[str] = []
    for op, target in simple.redirects:
        if op in (">&", "<&") and (target.text.isdigit() or target.text == "-"):
            continue  # 2>&1 and friends copy a file descriptor
        if op == "<<<" or target.text in HARMLESS_FILES:
            continue  # <<< passes a string, not a file
        if target.dynamic and "$" in target.text:
            return kind, (), f"it redirects to {target.text}, which comes from a variable"
        if not _allowed_path(target.text, inside):
            return kind, (), f"it redirects to {target.text}, which is outside the workspace"
        if op in OUTPUT_REDIRECTS:
            kind = Kind.WRITE
            writes.append(target.text)
    return kind, tuple(writes), ""


def _outside_argument(words: list[Word], inside: Inside, args_unknown: bool) -> str:
    program = PurePosixPath(words[0].text).name
    if program in NO_FILE_PROGRAMS:
        return ""
    if args_unknown:
        return "its arguments come from its input, so Zwans can't see which files it touches"
    rest = list(words[1:])
    if program in PATTERN_FIRST:
        rest = _without_pattern(rest)
    for word in rest:
        if word.dynamic and ("$" in word.text or "`" in word.text):
            return f"{word.text} comes from a variable, so Zwans can't see which file it is"
        for candidate in (word.text, word.text.partition("=")[2]):
            outside_looking = (
                candidate.startswith(("/", "~")) or ".." in PurePosixPath(candidate).parts
            )
            if outside_looking and not _allowed_path(candidate, inside):
                return f"{candidate} is outside the workspace"
    return ""


def _without_pattern(args: list[Word]) -> list[Word]:
    """Drop the pattern (the first positional argument, or each -e value)."""
    kept: list[Word] = []
    has_e = any(w.text in ("-e", "--regexp") for w in args)
    skip_next = False
    pattern_seen = has_e
    for word in args:
        if skip_next:
            skip_next = False
            continue
        if word.text in ("-e", "--regexp"):
            skip_next = True
            continue
        if word.text in ("-f", "--file"):  # the pattern comes from a file, which is checked
            pattern_seen = True
        if not pattern_seen and not word.text.startswith("-"):
            pattern_seen = True
            continue
        kept.append(word)
    return kept


def _allowed_path(path: str, inside: Inside) -> bool:
    if path in HARMLESS_FILES or path.startswith("/dev/fd/"):
        return True
    if path.startswith("~"):
        return False
    if any(path == d or path.startswith(d + "/") for d in SCRATCH_DIRS):
        return True
    return inside(path)


def _option_values(args: list[str], option: str) -> list[str]:
    return [args[i + 1] for i, a in enumerate(args[:-1]) if a == option]


def _short(arg: str) -> bool:
    return arg.startswith("-") and not arg.startswith("--") and len(arg) > 1


def _unknown(command: str, reason: str) -> Action:
    return Action(command, Kind.UNKNOWN, reason)


_RANKS = {Kind.READ: 0, Kind.WRITE: 1, Kind.EXECUTE: 2, Kind.NETWORK: 3, Kind.UNKNOWN: 4}


def _rank(kind: Kind) -> int:
    return _RANKS[kind]
