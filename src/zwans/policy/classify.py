"""Sorts each simple command in a Bash call by what it can do: read, write, run code, use the
network, or something this can't tell.

The tables cover common development commands. A program that isn't in them, or a use of one
that can reach outside the workspace, is "unknown", which the policy treats as the riskiest.
"""

import posixpath
import re
import shlex
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import PurePosixPath
from typing import NamedTuple

from zwans.policy.shell import ShellParseError, SimpleCommand, Word, parse


class Kind(StrEnum):
    READ = "read"  # only looks: ls, cat, git status
    WRITE = "write"  # changes files in the workspace: mkdir, mv, git commit
    EXECUTE = "execute"  # runs code, usually the project's own: pytest, make, python x.py
    NETWORK = "network"  # talks to other machines: curl, git push, pip install
    UNKNOWN = "unknown"  # anything else, or a use this can't judge


@dataclass(frozen=True)
class Action:
    # The simple command as rules see it: its words without quotes, with wrappers like
    # `timeout 60` removed, then its redirections to files, as in `cat > notes.txt`.
    command: str
    kind: Kind
    reason: str = ""  # why it's unknown, in words the model can act on
    writes: tuple[str, ...] = ()  # files it writes or removes, from redirections and arguments
    reads: tuple[str, ...] = ()  # files it reads, from redirections and arguments
    shown: str = ""  # as the user sees it, with quotes and here-documents; empty: as command
    bare: str = ""  # the words alone, which deny and ask rules check too; empty: as command
    # Unknown because it reaches outside the workspace or names a file through a variable.
    outside: bool = False

    @property
    def display(self) -> str:
        return self.shown or self.command


type Inside = Callable[[str], bool]  # whether a path is inside the workspace


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


READ_PROGRAMS = _words(
    "ls cat head tail wc grep egrep fgrep rg pwd echo printf which type file stat du df diff "
    "cmp uniq cut tr true false test [ date basename dirname realpath readlink tree nl od "
    "hexdump xxd md5sum sha1sum sha256sum shasum cd pushd popd sleep seq jq column comm paste "
    "fold expand unexpand whoami uname hostname id export unset set shopt local "
    "declare read wait :"
)
# Programs whose arguments are never file names, so $VAR in them is harmless. Not `test`
# or `[`: `test -f ~/.ssh/id_rsa` tells whether a file outside the workspace exists.
NO_FILE_PROGRAMS = _words(
    "echo printf true false pwd date sleep seq basename dirname export unset set shopt "
    "local declare read wait : which type"
)
# Programs that look at files' names, not what's in them, so a Read rule doesn't apply.
NAME_ONLY_PROGRAMS = _words("ls stat du df test [ realpath readlink cd pushd popd tree")
WRITE_PROGRAMS = _words(
    "mkdir touch cp mv rm rmdir ln chmod tee truncate patch tar unzip zip gzip gunzip bzip2 xz"
)
# Write programs that also read what they're given: a copy of .env is as good as .env.
# cp and ln too, though they write only to their last argument.
COPY_PROGRAMS = _words("mv tar zip gzip bzip2 xz")
EXECUTE_PROGRAMS = _words(
    "pytest py.test node deno bun ruby rake perl php java javac mvn gradle make cmake ninja "
    "ruff mypy black isort flake8 pylint pyright eslint prettier tsc jest vitest tox nox "
    "source ."
)
NETWORK_PROGRAMS = _words(
    "curl wget ssh scp sftp rsync nc ncat netcat telnet ftp socat ping dig nslookup host http "
    "https aria2c npx brew apt apt-get yum dnf pacman apk gem kubectl"
)
PACKAGE_MANAGERS = _words("npm pnpm yarn cargo go uv poetry pdm bundle")
SHELLS = _words("bash sh zsh dash ksh fish")
# Programs whose first argument is a pattern or a script, not a file name.
PATTERN_FIRST = frozenset(
    ["grep", "egrep", "fgrep", "rg", "ag", "sed", "gsed", "awk", "gawk", "mawk", "nawk", "jq"]
)
AWKS = _words("awk gawk mawk nawk")
# Options that take a value, for programs whose second file name is where they write.
UNIQ_VALUES = frozenset({"-f", "-s", "-w", "--skip-fields", "--skip-chars", "--check-chars"})
XXD_VALUES = _words("-c -cols -g -groupsize -l -len -o -offset -s -seek -n -name")
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
PRINTS_ENVIRONMENT = "it prints environment variables, which may hold secrets"
UNKNOWN_FOLDER = "it moves to a folder Zwans can't tell, so what runs after it can't be checked"
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
VERSIONED = re.compile(r"^(python|pip|pypy)[0-9.]*$")
SED_RUNS_OR_WRITES = re.compile(r"(^|[;{}\n/0-9$])\s*[ewWrR](\s|$|;)")
OUTPUT_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>", "<>", ">&"})
INPUT_REDIRECTS = frozenset({"<", "<>"})
HARMLESS_FILES = frozenset({"/dev/null", "/dev/stdin", "/dev/stdout", "/dev/stderr", "-"})
SCRATCH_DIRS = tuple({"/tmp", str(PurePosixPath(tempfile.gettempdir()))})
SAFE_WORD = re.compile(r"[\w@%+=:,./-]+")  # shown without quotes, as shlex.quote does
SPLITS_WORDS = re.compile(r"[\s;&|'\"\\]")  # would look like more than one word unquoted

GIT_READ = _words(
    "status diff log show blame rev-parse ls-files ls-tree grep shortlog describe cat-file "
    "reflog show-ref merge-base rev-list count-objects whatchanged version help"
)
GIT_NETWORK = frozenset(
    ["clone", "fetch", "pull", "push", "ls-remote", "submodule", "archive", "request-pull"]
)
GIT_VALUE_OPTIONS = frozenset({"-C", "--git-dir", "--work-tree", "--namespace"})
# Sub-commands that change the files they name. Others that change files (switch, merge,
# reset) don't name them, so file rules can't see what they touch.
GIT_FILE_CHANGES = _words("mv rm checkout restore")
PACKAGE_NETWORK = _words(
    "install i ci add update upgrade publish download wheel fetch get sync lock exec dlx "
    "create init remove uninstall audit outdated view info search"
)
PIP_READ = frozenset({"list", "show", "freeze", "check", "--version"})
# uv commands with their own sub-commands, and the ones of those that only look. The rest
# use the network: `uv pip install`, and `uv tool run`, which fetches the tool.
UV_NESTED = {
    "pip": frozenset({"list", "show", "freeze", "check", "tree"}),
    "tool": frozenset({"list", "dir"}),
}


class _Texts(NamedTuple):
    command: str
    shown: str
    bare: str


def analyze(command: str, inside: Inside) -> list[Action]:
    """Every simple command in a Bash call, sorted. A line that can't be parsed is one
    unknown action, so it is never allowed by a rule meant for something simpler."""
    try:
        commands = parse(command)
    except ShellParseError as exc:
        return [Action(command.strip(), Kind.UNKNOWN, f"Zwans can't check it in parts: {exc}")]
    actions: list[Action] = []
    folder = ""  # where the next command runs after a `cd`, relative to the workspace root
    stack: list[str] = []  # pushd's folders
    for simple in commands:
        found = _classify(simple, inside)
        if folder:  # `cd .git/hooks && cp x pre-commit` writes .git/hooks/pre-commit
            found = [_in_folder(action, folder) for action in found]
        actions.extend(found)
        folder = _next_folder(simple, folder, stack)
    return actions


def _next_folder(simple: SimpleCommand, folder: str, stack: list[str]) -> str:
    """The folder later commands run in, after this one. Taken as run in order, whatever the
    operators between them, so a `cd` in a subshell or after a failed command counts too."""
    plain = list(simple.words)
    while plain and ASSIGNMENT.match(plain[0].text):
        plain.pop(0)
    inner = _unwrap(plain)  # `builtin cd x` too
    if isinstance(inner, str):
        return folder
    words = [word.text for word in inner[0]]
    if not words or words[0] not in ("cd", "pushd", "popd"):
        return folder
    if words[0] == "popd":
        return stack.pop() if stack else folder
    target = next((w for w in words[1:] if not w.startswith("-")), None)
    if target is None:
        return folder  # `cd` alone is unknown already; see _program_kind
    if words[0] == "pushd":
        stack.append(folder)
    joined = posixpath.normpath(posixpath.join(folder, target))
    return "" if joined == "." else joined


def _in_folder(action: Action, folder: str) -> Action:
    def moved(paths: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            p if p.startswith(("/", "~")) else posixpath.normpath(posixpath.join(folder, p))
            for p in paths
        )

    return replace(action, reads=moved(action.reads), writes=moved(action.writes))


def _classify(simple: SimpleCommand, inside: Inside) -> list[Action]:
    whole = _texts(simple, simple.words)
    words = list(simple.words)
    while words and ASSIGNMENT.match(words[0].text):
        name = words[0].text.split("=", 1)[0].rstrip("+")
        if RISKY_VARIABLES.match(name):
            return [
                _action(whole, Kind.UNKNOWN, f"it sets {name}, which changes what programs run")
            ]
        words.pop(0)
    redirect_kind, reads, writes, problem = _redirects(simple, inside)
    if problem:
        return [_action(whole, Kind.UNKNOWN, problem, outside=True)]
    if not words:  # only assignments or redirections, such as `> out.txt`
        return [_action(whole, redirect_kind, reads=reads, writes=writes)]

    inner = _unwrap(words)
    if isinstance(inner, str):
        return [_action(whole, Kind.UNKNOWN, inner)]
    words, args_unknown = inner
    if not words:
        kind = max(redirect_kind, Kind.READ, key=_rank)
        return [_action(whole, kind, reads=reads, writes=writes)]

    texts = _texts(simple, _rule_words(words), words)
    nested = _shell(words, inside, texts)
    if nested is None:
        nested = _find_exec(words, inside)
    if nested is not None:
        if reads or writes:  # `bash -c '...' > out` writes out whatever runs inside
            nested.append(_action(_texts(simple, words), redirect_kind, reads=reads, writes=writes))
        return nested

    kind, reason = _program_kind(words, inside)
    if kind in (Kind.READ, Kind.WRITE, Kind.EXECUTE):
        problem = _outside_argument(words, inside, args_unknown)
        if problem:
            return [_action(texts, Kind.UNKNOWN, problem, outside=True)]
    file_reads, file_writes = _file_arguments(words)
    kind = max(kind, redirect_kind, key=_rank)
    return [_action(texts, kind, reason, reads=reads + file_reads, writes=writes + file_writes)]


def _texts(
    simple: SimpleCommand, words: list[Word], shown_words: list[Word] | None = None
) -> _Texts:
    """How rules see a command and how the user sees it. Redirections to files are part of
    both, so a prompt for `cat > notes.txt` says so, and "always" allows only that. What the
    user sees ends with any here-document's lines, so "always" for `bash <<EOF` covers only
    that script."""
    files = [(op, target) for op, target in simple.redirects if _names_file(op, target)]
    bare = " ".join(word.text for word in words)
    command = " ".join([bare, *(f"{op} {target.text}" for op, target in files)])
    heredocs = [heredoc.partition("\n") for heredoc in simple.heredocs]
    shown = " ".join(
        [
            *(_quote(word) for word in (shown_words or words)),
            *(f"{op} {_quote(target)}" for op, target in files),
            *(marker for marker, _, _ in heredocs),
        ]
    )
    shown += "".join(f"\n{body}" for _, _, body in heredocs if body)
    return _Texts(command.strip(), shown, bare)


def _action(
    texts: _Texts,
    kind: Kind,
    reason: str = "",
    *,
    reads: tuple[str, ...] = (),
    writes: tuple[str, ...] = (),
    outside: bool = False,
) -> Action:
    writes, reads = _with_braces(writes), _with_braces(reads)
    return Action(texts.command, kind, reason, writes, reads, texts.shown, texts.bare, outside)


BRACES = re.compile(r"\{([^{}]*,[^{}]*)\}")
MAX_BRACE_NAMES = 64


def _with_braces(paths: tuple[str, ...]) -> tuple[str, ...]:
    """Each name a path stands for after brace expansion: `.git{,}` and `{.git,x}` name .git.
    Expansion stops once there are many names, leaving the rest of the braces as written."""
    found: list[str] = []
    for path in paths:
        names = [path]
        while len(names) <= MAX_BRACE_NAMES and any(BRACES.search(name) for name in names):
            expanded: list[str] = []
            for name in names:
                match = BRACES.search(name)
                if match is None:
                    expanded.append(name)
                    continue
                before, after = name[: match.start()], name[match.end() :]
                expanded.extend(before + choice + after for choice in match.group(1).split(","))
            names = expanded
        found.extend(names)
    return tuple(dict.fromkeys(found))


def _names_file(op: str, target: Word) -> bool:
    if op in (">&", "<&") and (target.text.isdigit() or target.text == "-"):
        return False  # 2>&1 and friends copy a file descriptor
    return op != "<<<" and target.text not in HARMLESS_FILES


def _quote(word: Word) -> str:
    """A word as the shell would need it written, so `-m 'a; b'` doesn't look like two
    commands. $VAR and globs stay bare, since the shell fills them in."""
    if SAFE_WORD.fullmatch(word.text):
        return word.text
    if word.dynamic:
        if not SPLITS_WORDS.search(word.text):
            return word.text
        return '"' + word.text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return shlex.quote(word.text)


def _rule_words(words: list[Word]) -> list[Word]:
    """The words rules see. git's global options (-C dir, --no-pager) are left out, so a rule
    for `git push *` also covers `git -C . push`; their paths are still checked."""
    if words[0].text != "git" or words[0].dynamic:
        return words
    i = 1
    while i < len(words) and words[i].text.startswith("-"):
        i += 2 if words[i].text in GIT_VALUE_OPTIONS else 1
    return [words[0], *words[i:]]


def _program_kind(words: list[Word], inside: Inside) -> tuple[Kind, str]:
    first = words[0]
    if first.dynamic:
        return Kind.UNKNOWN, "the program's name comes from a variable"
    program = _program_name(first.text)  # a system program may be named by its full path
    # The project's own program runs code. A package manager in it, like .venv/bin/pip, is
    # judged like the one on PATH, so an install still counts as using the network.
    managed = VERSIONED.match(program) or program in PACKAGE_MANAGERS
    if "/" in first.text and inside(first.text) and not managed:
        return Kind.EXECUTE, ""
    args = [word.text for word in words[1:]]
    sub = next((a for a in args if not a.startswith("-")), "")

    if VERSIONED.match(program):
        if program.startswith("pip"):
            return _package_kind(sub, read=PIP_READ)
        module = _python_module(args)
        if module is not None and module[0] == "pip":
            return _package_kind(
                next((a for a in module[1] if not a.startswith("-")), ""), PIP_READ
            )
        return Kind.EXECUTE, ""
    if program == "git":
        return _git_kind(args)
    if program in PACKAGE_MANAGERS:
        if program == "yarn" and not sub:
            return Kind.NETWORK, ""  # plain `yarn` installs
        if program in ("npm", "pnpm", "yarn") and sub in ("ls", "list", "why", "--version"):
            return Kind.READ, ""
        if program == "uv":
            return _uv_kind(args, sub)
        return _package_kind(sub)
    if program in ("sed", "gsed"):
        if _sed_in_place(args):
            return Kind.WRITE, ""
        scripts = _sed_scripts(args)
        if scripts is None:
            return Kind.UNKNOWN, "its script comes from a file, which Zwans doesn't read"
        if any(SED_RUNS_OR_WRITES.search(script) for script in scripts):
            return Kind.UNKNOWN, "its script may run commands or write files"
        return Kind.READ, ""
    if program in AWKS:
        awk = _awk_program(args)
        if awk is None:
            return Kind.UNKNOWN, "its program comes from a file, which Zwans doesn't read"
        if any(token in script for script in awk.scripts for token in ("system", "|", ">")):
            return Kind.UNKNOWN, "its program may run commands or write files"
        return (Kind.WRITE if awk.in_place else Kind.READ), ""
    if program == "sort":
        if any(a.startswith("--compress-program") for a in args):
            return Kind.UNKNOWN, "--compress-program makes sort run another program"
        return (Kind.WRITE if _sort_output(args) else Kind.READ), ""
    if program == "rg" and any(a == "--pre" or a.startswith("--pre=") for a in args):
        return Kind.UNKNOWN, "--pre makes rg run another program on each file"
    if program in ("cd", "pushd") and _unknown_folder(args):
        return Kind.UNKNOWN, UNKNOWN_FOLDER
    # `uniq IN OUT` and `xxd IN OUT` write OUT, and `tree -o FILE` writes FILE.
    if program == "uniq":
        return (Kind.WRITE if len(_positional(args, UNIQ_VALUES)) > 1 else Kind.READ), ""
    if program == "xxd":
        return (Kind.WRITE if len(_positional(args, XXD_VALUES)) > 1 else Kind.READ), ""
    if program == "tree":
        return (Kind.WRITE if _tree_output(args) else Kind.READ), ""
    if program == "dd":
        return Kind.UNKNOWN, "dd can overwrite devices and files anywhere"
    environment = _environment_kind(program, args)
    if environment is not None:
        return environment
    if program in READ_PROGRAMS:
        return Kind.READ, ""
    if program in WRITE_PROGRAMS:
        return Kind.WRITE, ""
    if program in EXECUTE_PROGRAMS:
        return Kind.EXECUTE, ""
    if program in NETWORK_PROGRAMS:
        return Kind.NETWORK, ""
    return Kind.UNKNOWN, f"{program} isn't a command Zwans recognizes"


def _environment_kind(program: str, args: list[str]) -> tuple[Kind, str] | None:
    """Builtins that print every variable, which can hold tokens and keys, or that set one
    that changes what programs run, as `export PATH=.` does."""
    if program == "printenv" or (program == "set" and not args):
        return Kind.UNKNOWN, PRINTS_ENVIRONMENT
    if program not in ("export", "declare", "local"):
        return None
    named = [a for a in args if not a.startswith("-")]
    if not named:  # `export`, `export -p`, `declare -x`
        return Kind.UNKNOWN, PRINTS_ENVIRONMENT
    for arg in named:
        name = arg.split("=", 1)[0].rstrip("+")
        if "=" in arg and RISKY_VARIABLES.match(name):
            return Kind.UNKNOWN, f"it sets {name}, which changes what programs run"
    return None


def _unknown_folder(args: list[str]) -> bool:
    """Whether `cd` or `pushd` goes somewhere the arguments don't name: home for a bare `cd`,
    the last folder for `cd -`, a folder on the stack for `pushd` alone or `pushd +1`."""
    named = [a for a in args if a == "-" or not a.startswith("-") or a[1:].isdigit()]
    if not named or named[0] == "-":
        return True
    return named[0][0] in "+-" and named[0][1:].isdigit()


def _sed_scripts(args: list[str]) -> list[str] | None:
    """The scripts sed runs: each -e value (also written -eSCRIPT or --expression=SCRIPT), or
    else its first argument. None when one comes from a file (-f), which this doesn't read."""
    scripts: list[str] = []
    positional: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        following = args[i + 1] if i + 1 < len(args) else ""
        i += 1
        if arg in ("-f", "--file") or arg.startswith("--file="):
            return None
        if arg in ("-e", "--expression"):
            scripts.append(following)
            i += 1
        elif arg.startswith("--expression="):
            scripts.append(arg.partition("=")[2])
        elif _short(arg):
            for j, flag in enumerate(arg[1:], start=1):
                if flag == "f":
                    return None
                if flag in "el":  # -e SCRIPT, -l N
                    value = arg[j + 1 :]
                    if not value:
                        value = following
                        i += 1
                    if flag == "e":
                        scripts.append(value)
                    break
                if flag == "i":
                    break  # what follows is the backup suffix
        elif not arg.startswith("-"):
            positional.append(arg)
    return scripts or positional[:1]


class _Awk(NamedTuple):
    scripts: list[str]
    in_place: bool  # gawk -i inplace rewrites the files it reads


AWK_VALUES = frozenset({"-F", "-v", "--field-separator", "--assign"})
AWK_SOURCES = frozenset({"-e", "--source"})
AWK_FILES = frozenset({"-f", "--file", "-E", "--exec", "-l", "--load", "-i", "--include"})


def _awk_program(args: list[str]) -> _Awk | None:
    """The program awk runs, from -e or its first argument. None when it comes from a file
    (-f prog.awk) or loads one (-i lib, -l ext), which this doesn't read; `-i inplace` is the
    one library it knows."""
    scripts: list[str] = []
    positional: list[str] = []
    in_place = False
    i = 0
    while i < len(args):
        arg = args[i]
        i += 1
        if arg == "--":
            positional.extend(args[i:])
            break
        if not arg.startswith("-") or arg == "-":
            positional.append(arg)
            continue
        if arg.startswith("--"):
            option, has_value, value = arg.partition("=")
        else:
            option, value = arg[:2], arg[2:]
            has_value = "=" if value else ""
        if option not in AWK_VALUES | AWK_SOURCES | AWK_FILES:
            continue
        if not has_value:
            value = args[i] if i < len(args) else ""
            i += 1
        if option in AWK_SOURCES:
            scripts.append(value)
        elif option in ("-i", "--include") and value in ("inplace", "inplace.awk"):
            in_place = True
        elif option in AWK_FILES:
            return None
    return _Awk(scripts or positional[:1], in_place)


def _python_module(args: list[str]) -> tuple[str, list[str]] | None:
    """The module `python -m X` runs (also written -mX or -Im X), and the arguments after it."""
    i = 0
    while i < len(args):
        arg = args[i]
        if not arg.startswith("-") or arg in ("-", "--"):
            return None  # a script, or code from stdin
        i += 1
        if arg.startswith("--"):
            continue
        for j, flag in enumerate(arg[1:], start=1):
            if flag == "m":
                if j + 1 < len(arg):
                    return arg[j + 1 :], args[i:]
                return (args[i], args[i + 1 :]) if i < len(args) else None
            if flag == "c":
                return None
            if flag in "WX":
                if j + 1 == len(arg):
                    i += 1  # its value is the next argument
                break
    return None


def _uv_kind(args: list[str], sub: str) -> tuple[Kind, str]:
    if sub in UV_NESTED:
        rest = args[args.index(sub) + 1 :]
        inner = next((a for a in rest if not a.startswith("-")), "")
        return (Kind.READ if inner in UV_NESTED[sub] else Kind.NETWORK), ""
    if sub == "run" and any(a.startswith("--with") for a in args):
        return Kind.NETWORK, ""  # `uv run --with requests` installs requests first
    return _package_kind(sub)


def _git_kind(args: list[str]) -> tuple[Kind, str]:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-c" or args[i].startswith("--config-env"):
            return Kind.UNKNOWN, "git -c can make git run any program"
        i += 2 if args[i] in GIT_VALUE_OPTIONS else 1
    if i >= len(args):
        return Kind.READ, ""
    sub, rest = args[i], args[i + 1 :]
    if any(a in ("-O", "--open-files-in-pager", "--ext-diff") or a.startswith("-O") for a in rest):
        return Kind.UNKNOWN, "that option makes git run another program"
    named = [a for a in rest if not a.startswith("-")]
    if _git_output(rest):
        return Kind.WRITE, ""  # `git diff --output=FILE` writes FILE
    if sub == "reflog" and named and named[0] in ("expire", "delete"):
        return Kind.WRITE, ""  # it throws away what `git reflog` would bring back
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


def _file_arguments(words: list[Word]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The files a command reads and writes, as far as its arguments tell, so file rules such
    as Read(.env) and Edit(.git/**) apply to `cat .env` and `cp x .git/hooks/` too."""
    program = _program_name(words[0].text)
    args = [word.text for word in words[1:]]
    if program == "git":
        return _git_files(args)
    if program == "tree":
        return (), tuple(_tree_output(args))
    if program in NO_FILE_PROGRAMS or program in NAME_ONLY_PROGRAMS:
        return (), ()
    rest = _without_pattern(words[1:]) if program in PATTERN_FIRST else words[1:]
    named = tuple(word.text for word in rest if not word.text.startswith("-"))
    if program in ("source", "."):
        return named[:1], ()
    if program in ("sed", "gsed") and _sed_in_place(args):
        return named, named
    if program in AWKS:
        awk = _awk_program(args)
        return named, (named if awk is not None and awk.in_place else ())
    if program in ("cp", "mv", "ln"):
        return named, _copy_writes(program, args, named)
    if program == "tar":  # -C DIR is among the names already
        return named, named + tuple(_values(args, "--directory"))
    if program in WRITE_PROGRAMS:
        return (named if program in COPY_PROGRAMS else ()), named
    if program == "sort":
        return named, tuple(_sort_output(args))
    if program in ("uniq", "xxd"):
        files = tuple(_positional(args, UNIQ_VALUES if program == "uniq" else XXD_VALUES))
        return files[:1], files[1:2]
    if program in READ_PROGRAMS or program in PATTERN_FIRST:
        return named, ()
    return (), ()


def _copy_writes(program: str, args: list[str], named: tuple[str, ...]) -> tuple[str, ...]:
    """What cp, mv and ln change: where they write (the -t folder, or else the last name), and
    each source's name inside it, since `cp -r t/.git .` writes .git. mv also removes its
    sources. A link lets whoever writes to it change what it points to, so for ln (and cp -l
    or -s) the sources count as changed too."""
    targets = _option_values(args, "-t") + _values(args, "--target-directory")
    sources = [a for a in named if a not in targets] if targets else list(named[:-1])
    folders = targets or list(named[-1:])
    landed: list[str] = []
    for folder in folders:
        for source in sources:
            # `cp -r t/. .` copies what's in t, dotfiles too, so any name may land there.
            contents = source == "." or source.endswith(("/", "/."))
            landed.append(posixpath.join(folder, ".*" if contents else posixpath.basename(source)))
    links = program == "ln" or (
        program == "cp"
        and any(
            a in ("--link", "--symbolic-link") or (_short(a) and ("l" in a or "s" in a))
            for a in args
        )
    )
    changed = list(named) if program == "mv" or links else []
    return tuple(dict.fromkeys([*folders, *landed, *changed]))


def _values(args: list[str], option: str) -> list[str]:
    """A long option's values, written `--option VALUE` or `--option=VALUE`."""
    return _option_values(args, option) + [
        a.partition("=")[2] for a in args if a.startswith(option + "=")
    ]


def _git_files(args: list[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """What a git command reads from the work tree or history (`git show HEAD:.env` reads
    .env), and what --output writes."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in GIT_VALUE_OPTIONS else 1
    if i >= len(args):
        return (), ()
    sub, rest = args[i], args[i + 1 :]
    writes = tuple(_git_output(rest))
    if sub in GIT_FILE_CHANGES:  # `git checkout HEAD~3 -- .zwans/policy.toml`
        return (), writes + tuple(a for a in rest if not a.startswith("-"))
    if sub not in GIT_READ:
        return (), writes
    named = [a for a in rest if not a.startswith("-") and a not in writes]
    if sub == "grep" and "-e" not in rest:
        named = named[1:]  # the pattern
    return tuple(a.partition(":")[2] if ":" in a else a for a in named), writes


def _git_output(args: list[str]) -> list[str]:
    return _values(args, "--output")


def _sort_output(args: list[str]) -> list[str]:
    """Where `sort -o FILE` writes, also written -oFILE, -uo FILE or --output=FILE."""
    for i, arg in enumerate(args):
        following = args[i + 1] if i + 1 < len(args) else ""
        if arg == "--output":
            return [following]
        if arg.startswith("--output="):
            return [arg.partition("=")[2]]
        if not _short(arg):
            continue
        for j, flag in enumerate(arg[1:], start=1):
            if flag in "ktST":  # options whose value follows, which could hold an o
                break
            if flag == "o":
                return [arg[j + 1 :] or following]
    return []


def _tree_output(args: list[str]) -> list[str]:
    for i, arg in enumerate(args):
        if _short(arg) and "o" in arg[1:]:
            return [args[i + 1] if i + 1 < len(args) else ""]
    return []


def _sed_in_place(args: list[str]) -> bool:
    """Whether sed has -i, which isn't the i in a script such as `-e'1i text'`."""
    value_next = False
    for arg in args:
        if value_next:
            value_next = False
        elif arg.startswith("--in-place"):
            return True
        elif arg in ("--expression", "--file", "--line-length"):
            value_next = True
        elif _short(arg):
            for j, flag in enumerate(arg[1:], start=1):
                if flag == "i":
                    return True
                if flag in "efl":  # the rest, or the next argument, is its value
                    value_next = j + 1 == len(arg)
                    break
    return False


def _positional(args: list[str], takes_value: frozenset[str]) -> list[str]:
    """The arguments that aren't options or option values."""
    found: list[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
        elif arg in takes_value:
            skip = True
        elif not arg.startswith("-") or arg == "-":
            found.append(arg)
    return found


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
            if program == "env" and (option in ("-C", "--chdir") or option.startswith("--chdir=")):
                return "env -C runs it in another folder, so Zwans can't tell which files it uses"
            if option in takes_value and rest:
                rest.pop(0)
        if program == "timeout" and rest:
            rest.pop(0)  # the duration
        if program == "env":
            while rest and ASSIGNMENT.match(rest[0].text):
                name = rest.pop(0).text.split("=", 1)[0]
                if RISKY_VARIABLES.match(name):
                    return f"it sets {name}, which changes what programs run"
            if not rest:  # `env` alone prints every variable
                return PRINTS_ENVIRONMENT
        if program == "xargs":
            args_unknown = True
        words = rest
    return words, args_unknown


def _shell(words: list[Word], inside: Inside, texts: _Texts) -> list[Action] | None:
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
                reason = "the commands it runs come from a variable"
                return [_action(texts, Kind.UNKNOWN, reason, outside=True)]
            return analyze(script.text, inside)
        if not word.text.startswith("-"):
            if not inside(word.text):
                reason = f"{word.text} is outside the workspace"
                return [_action(texts, Kind.UNKNOWN, reason, outside=True)]
            return [_action(texts, Kind.EXECUTE)]
    # What it runs is on its input, such as a here-document, which `texts` shows in full.
    return [_action(texts, Kind.UNKNOWN, "it runs commands from its input, which Zwans can't see")]


def _find_exec(words: list[Word], inside: Inside) -> list[Action] | None:
    """find's -exec runs a command per file; -delete and -fprint write."""
    if words[0].text != "find":
        return None
    actions: list[tuple[Action, bool]] = []  # each with whether it runs in the file's folder
    expression_kind = Kind.READ
    writes: list[str] = []
    deletes = False
    i = 1
    while i < len(words):
        option = words[i].text
        if option in ("-exec", "-execdir", "-ok", "-okdir"):
            end = i + 1
            while end < len(words) and words[end].text not in (";", "+"):
                end += 1
            inner = SimpleCommand(words=words[i + 1 : end])
            if inner.words:
                in_dir = option.endswith("dir")
                actions.extend((action, in_dir) for action in _classify(inner, inside))
            i = end + 1
            continue
        if option in ("-delete", "-fprint", "-fprint0", "-fprintf", "-fls"):
            expression_kind = Kind.WRITE
            if option == "-delete":
                deletes = True
            elif i + 1 < len(words):
                writes.append(words[i + 1].text)
        i += 1
    plain = [w for w in words if w.text not in ("-exec", "-execdir", "-ok", "-okdir")]
    starts = plain[: _first_option(plain)]
    # The files it acts on: under where it starts, and named by -name or -path when given.
    folders = [w.text for w in words[1 : _first_option(words)]] or ["."]
    names = _find_values(words, ("-name", "-iname"))
    found = [
        *folders,
        *(posixpath.join(folder, name) for folder in folders for name in names),
        *_find_values(words, ("-path", "-ipath", "-wholename", "-iwholename")),
    ]
    if deletes:
        # Not the workspace root itself, though: it holds everything, and
        # `find . -name '*.pyc' -delete` is everyday cleanup.
        writes.extend(path for path in found if PurePosixPath(path).parts)
    texts = _texts(SimpleCommand(words=words), words)
    problem = _outside_argument(starts, inside, False)
    if problem:
        return [_action(texts, Kind.UNKNOWN, problem, outside=True)]
    per_file = [_per_file(action, found, folders, in_dir) for action, in_dir in actions]
    return [_action(texts, expression_kind, writes=tuple(writes)), *per_file]


def _find_values(words: list[Word], options: tuple[str, ...]) -> list[str]:
    return [words[i + 1].text for i in range(len(words) - 1) if words[i].text in options]


def _per_file(action: Action, found: list[str], folders: list[str], in_dir: bool) -> Action:
    """A command find runs per file, with {} as the files it may stand for. -execdir runs it
    in each file's folder, so its other paths are taken from there too."""

    def expand(paths: tuple[str, ...]) -> tuple[str, ...]:
        out: list[str] = []
        for path in paths:
            if "{}" in path:
                out.extend(path.replace("{}", file) for file in found)
            elif in_dir and not path.startswith(("/", "~")):
                out.extend(posixpath.normpath(posixpath.join(f, path)) for f in folders)
            else:
                out.append(path)
        return tuple(dict.fromkeys(out))

    return replace(action, reads=expand(action.reads), writes=expand(action.writes))


def _first_option(words: list[Word]) -> int:
    for i, word in enumerate(words[1:], start=1):
        if word.text.startswith("-") or word.text in ("(", "!"):
            return i
    return len(words)


def _redirects(
    simple: SimpleCommand, inside: Inside
) -> tuple[Kind, tuple[str, ...], tuple[str, ...], str]:
    """The kind redirections give a command, the files they read and write, and a problem
    that makes it unknown."""
    kind = Kind.READ
    reads: list[str] = []
    writes: list[str] = []
    for op, target in simple.redirects:
        if not _names_file(op, target):
            continue
        if target.dynamic and "$" in target.text:
            return kind, (), (), f"it redirects to {target.text}, which comes from a variable"
        if not _allowed_path(target.text, inside):
            return kind, (), (), f"it redirects to {target.text}, which is outside the workspace"
        if op in OUTPUT_REDIRECTS:
            kind = Kind.WRITE
            writes.append(target.text)
        if op in INPUT_REDIRECTS:
            reads.append(target.text)
    return kind, tuple(reads), tuple(writes), ""


def _outside_argument(words: list[Word], inside: Inside, args_unknown: bool) -> str:
    program = _program_name(words[0].text)
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


def _program_name(text: str) -> str:
    """/usr/bin/git is git. `.` (as in `. venv/bin/activate`) stays itself."""
    return PurePosixPath(text).name or text


def _short(arg: str) -> bool:
    return arg.startswith("-") and not arg.startswith("--") and len(arg) > 1


_RANKS = {Kind.READ: 0, Kind.WRITE: 1, Kind.EXECUTE: 2, Kind.NETWORK: 3, Kind.UNKNOWN: 4}


def _rank(kind: Kind) -> int:
    return _RANKS[kind]
