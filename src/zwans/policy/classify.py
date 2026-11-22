"""Sorts each simple command in a Bash call by what it can do: read, write, run code, use the
network, or something this can't tell.

The tables cover common development commands. A program that isn't in them, or a use of one
that can reach outside the workspace, is "unknown", which the policy treats as the riskiest.
"""

import os
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
    # Its text doesn't show what it runs or reads: a variable or $(...) in a file name, a
    # script piped to a shell, a command run in a folder it doesn't name. No rule can allow it.
    opaque: bool = False
    heredocs: bool = False  # `shown` ends with here-documents, which are part of what runs

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
    "echo printf true false pwd sleep seq basename dirname export unset set shopt "
    "local declare read wait : which type"
)
# Long options whose value is a file the program reads, as in `diff --from-file=.env x`, or
# `file --files-from=.env`, which prints each line it can't open.
# Written with the shortest shortening taken as one: grep's --include and rg's --files are
# options of their own.
FILE_OPTIONS = (
    "--from-file",
    "--to-file",
    "--file",
    "--exclude-[from]",
    "--include-[from]",
    "--files-[from]",
)
FILES0_FROM = "--files0[-from]"
# Short options that name a file of patterns or names, which may carry it (`grep -f.env`),
# with each program's other short options that take a value.
SHORT_FILE_OPTIONS = {
    "grep": "ABCDdem",
    "egrep": "ABCDdem",
    "fgrep": "ABCDdem",
    "rg": "ABCEMTdegjmrt",
    "file": "eFmP",
}
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
# Variables that change which program runs or what it loads, where `cd` goes (CDPATH, and
# HOME and OLDPWD for `cd` alone, `~` and `cd -`), or what a glob expands to (GLOBIGNORE, and
# BASHOPTS, which can turn on dotglob). PS4 is expanded, $(...) and all, for each line `set -x`
# or `bash -x` traces.
RISKY_VARIABLES = re.compile(
    r"^(PATH|IFS|BASH_ENV|ENV|PROMPT_COMMAND|PYTHONSTARTUP|CDPATH|HOME|OLDPWD|GLOBIGNORE"
    r"|BASHOPTS|SHELLOPTS|PS[0-4]|(LD|DYLD|GIT)_\w*)$"
)
# Variables that make a program load code or settings from elsewhere: PYTHONPATH=. makes
# `pip list` import a ./pip folder, and NODE_OPTIONS=--require=./x.js runs x.js in `npm ls`.
# Set for one command that already runs code (`PYTHONPATH=src pytest`), they change nothing
# the policy cares about; set for one that only reads or writes, or for later commands, they
# make it unknown.
CODE_VARIABLES = re.compile(
    r"^(PYTHON\w*|NODE_OPTIONS|NODE_PATH|PERL5?OPT|PERL5?LIB|PERLLIB|RUBYOPT|RUBYLIB"
    r"|RIPGREP_CONFIG_PATH|PIP_\w*|UV_\w*|AWKPATH|AWKLIBPATH)$"
)
# Also an array's element, with a plain index: in `read 'a[x]'` the index x is evaluated as
# arithmetic, which runs any $(...) that x holds.
VARIABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[([0-9]*|[@*])\])?$")
PRINTS_ENVIRONMENT = "it prints environment variables, which may hold secrets"
CHANGES_GLOBS = "it changes what globs match, so Zwans can't tell what they name"
UNKNOWN_FOLDER = "it moves to a folder Zwans can't tell, so what runs after it can't be checked"
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
VERSIONED = re.compile(r"^(python|pip|pypy)[0-9.]*$")
OUTPUT_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>", "<>", ">&"})
INPUT_REDIRECTS = frozenset({"<", "<>"})
HARMLESS_FILES = frozenset({"/dev/null", "/dev/stdin", "/dev/stdout", "/dev/stderr", "-"})
# What a shell or interpreter reads its program from when it's named as the script.
STDIN_FILES = frozenset({"-", "/dev/stdin", "/dev/fd/0", "/proc/self/fd/0"})
SCRATCH_DIRS = tuple({"/tmp", str(PurePosixPath(tempfile.gettempdir()))})
REAL_SCRATCH_DIRS = tuple({os.path.realpath(d) for d in SCRATCH_DIRS})
SAFE_WORD = re.compile(r"[\w@%+=:,./-]+")  # shown without quotes, as shlex.quote does
SPLITS_WORDS = re.compile(r"[\s;&|'\"\\]")  # would look like more than one word unquoted

GIT_READ = _words(
    "status diff log show blame rev-parse ls-files ls-tree grep shortlog describe cat-file "
    "reflog show-ref merge-base rev-list count-objects whatchanged version help"
)
GIT_NETWORK = _words(
    "clone fetch pull push ls-remote submodule archive request-pull fetch-pack send-pack "
    "http-fetch http-push imap-send send-email svn p4 cvsimport lfs maintenance daemon "
    "instaweb web--browse"
)
# Sub-commands that run a command given to them: `git bisect run CMD`, `git rebase -x CMD`.
GIT_RUNS = _words("bisect filter-branch difftool mergetool")
GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace"})
# Sub-commands that change the files they name. Others that change files (switch, merge,
# reset) don't name them, so file rules can't see what they touch.
GIT_FILE_CHANGES = _words("mv rm checkout restore")
PACKAGE_NETWORK = _words(
    "install i ci add update upgrade publish download wheel fetch get sync lock exec dlx "
    "create init remove uninstall audit outdated view info search index ping whoami login "
    "logout adduser access owner team token star stars unstar dist-tag deprecate unpublish "
    "diff docs repo bugs home"
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
    heredocs: bool = False


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
        folder = _next_folder(simple, folder, stack, inside)
    return actions


def _next_folder(simple: SimpleCommand, folder: str, stack: list[str], inside: Inside) -> str:
    """The folder later commands run in, after this one. Taken as run in order, whatever the
    operators between them, so a `cd` in a subshell or after a failed command counts too."""
    plain = list(simple.words)
    while plain and ASSIGNMENT.match(plain[0].text):
        plain.pop(0)
    inner = _unwrap(plain, inside)  # `builtin cd x` too
    if inner.problem:
        return folder
    words = [word.text for word in inner.words]
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
    names: list[str] = []
    while words and ASSIGNMENT.match(words[0].text):
        names.append(words.pop(0).text.split("=", 1)[0].rstrip("+"))
    risky = next((name for name in names if RISKY_VARIABLES.match(name)), "")
    # A variable set for this command that makes it load code from elsewhere.
    loads = next((name for name in names if CODE_VARIABLES.match(name)), "")
    # Deny and ask rules still see the command itself: `HOME=x git push` is `git push`.
    plain = whole
    if words:
        named = _by_name(words, inside)
        plain = whole._replace(bare=" ".join(word.text for word in _rule_words(named)))
    if risky:
        return [_action(plain, Kind.UNKNOWN, _sets(risky), opaque=True)]
    if loads and not words:  # `PYTHONPATH=.` alone changes what later commands load
        return [_action(whole, Kind.UNKNOWN, _sets(loads), opaque=True)]
    found = _classify_words(simple, words, whole, inside)
    if words and not loads:
        loads = _unwrap(words, inside).loads  # `env PYTHONPATH=. pip list`
    if loads and any(action.kind in (Kind.READ, Kind.WRITE) for action in found):
        # `PYTHONPATH=. pip list` runs whatever ./pip holds.
        return [_action(plain, Kind.UNKNOWN, _sets(loads), opaque=True)]
    return found


def _classify_words(
    simple: SimpleCommand, words: list[Word], whole: "_Texts", inside: Inside
) -> list[Action]:
    """Sort a simple command whose leading assignments have been taken off `words`."""
    redirect_kind, reads, writes, problem = _redirects(simple, inside)
    if problem:
        return [_action(whole, Kind.UNKNOWN, problem.reason, outside=True, opaque=problem.opaque)]
    if not words:  # only assignments or redirections, such as `> out.txt`
        return [_action(whole, redirect_kind, reads=reads, writes=writes)]

    inner = _unwrap(words, inside)
    if inner.problem:
        # Deny and ask rules still see the wrapped command: `env -C . rm -rf x` is `rm -rf x`.
        named = _by_name(inner.words, inside)
        bare = " ".join(word.text for word in _rule_words(named)) if named else ""
        texts = whole._replace(bare=bare or whole.bare)
        return [_action(texts, Kind.UNKNOWN, inner.problem, opaque=True)]
    for path in inner.reads:  # `xargs -a FILE`
        if "$" in path or "`" in path:
            reason = f"{path} comes from a variable, so Zwans can't see which file it is"
            return [_action(whole, Kind.UNKNOWN, reason, outside=True, opaque=True)]
        if not _allowed_path(path, inside):
            return [_action(whole, Kind.UNKNOWN, f"{path} is outside the workspace", outside=True)]
    reads += inner.reads
    words, args_unknown = inner.words, inner.args_unknown
    if not words:
        kind = max(redirect_kind, Kind.READ, key=_rank)
        return [_action(whole, kind, reads=reads, writes=writes)]

    # /usr/bin/git is git to rules and the checks below, but the user sees what was written.
    named = _by_name(words, inside)
    texts = _texts(simple, _rule_words(named), words)
    nested = _shell(named, inside, texts, simple)
    if nested is None:
        nested = _find_exec(named, inside)
    if nested is not None:
        if reads or writes:  # `bash -c '...' > out` writes out whatever runs inside
            nested.append(_action(_texts(simple, words), redirect_kind, reads=reads, writes=writes))
        return nested

    kind, reason = _program_kind(words, inside)
    if kind in (Kind.READ, Kind.WRITE, Kind.EXECUTE):
        found = _outside_argument(words, inside, args_unknown)
        if found:
            return [_action(texts, Kind.UNKNOWN, found.reason, outside=True, opaque=found.opaque)]
    file_reads, file_writes = _file_arguments(words)
    if kind in (Kind.READ, Kind.WRITE, Kind.EXECUTE):
        # Files named in options too, as in `grep -f/etc/passwd` or `--file=$X`.
        for path in (*file_reads, *file_writes):
            if "$" in path or "`" in path:
                reason = f"{path} comes from a variable, so Zwans can't see which file it is"
                return [_action(texts, Kind.UNKNOWN, reason, outside=True, opaque=True)]
            if _looks_outside(path) and not _allowed_path(path, inside):
                reason = f"{path} is outside the workspace"
                return [_action(texts, Kind.UNKNOWN, reason, outside=True)]
    kind = max(kind, redirect_kind, key=_rank)
    # `python3` or `node` with no script runs what's piped in, and `sort --files0-from=-`
    # reads the files named there; the command's text doesn't show which.
    names_from_input = any(_long(word.text, FILES0_FROM) for word in words[1:])
    # And `$(which python3) -m pytest`: a rule for it would allow whatever program runs.
    opaque = _program_from_input(words, simple) or names_from_input or _filled(words[0])
    return [
        _action(
            texts,
            kind,
            reason,
            reads=reads + file_reads,
            writes=writes + file_writes,
            outside=opaque or (bool(simple.heredocs) and _interpreter(words) is not None),
            opaque=opaque,
        )
    ]


class _Problem(NamedTuple):
    reason: str
    opaque: bool = False  # it comes from a variable, so no rule's text could match it


def _sets(name: str) -> str:
    return f"it sets {name}, which changes what later commands run or which files they use"


def _texts(
    simple: SimpleCommand, words: list[Word], shown_words: list[Word] | None = None
) -> _Texts:
    """How rules see a command and how the user sees it. Redirections to files are part of
    both, so a prompt for `cat > notes.txt` says so, and "always" allows only that. What the
    user sees ends with any here-document's lines, so "always" for `bash <<EOF` covers only
    that script."""
    # Here-strings too: for `bash /dev/stdin <<< '...'`, what runs.
    files = [
        (op, target) for op, target in simple.redirects if _names_file(op, target) or op == "<<<"
    ]
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
    return _Texts(command.strip(), shown, bare, bool(heredocs))


def _action(
    texts: _Texts,
    kind: Kind,
    reason: str = "",
    *,
    reads: tuple[str, ...] = (),
    writes: tuple[str, ...] = (),
    outside: bool = False,
    opaque: bool = False,
) -> Action:
    writes, reads = _with_braces(writes), _with_braces(reads)
    return Action(
        texts.command,
        kind,
        reason,
        writes,
        reads,
        texts.shown,
        texts.bare,
        outside,
        opaque,
        texts.heredocs,
    )


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


def _system_name(word: Word, inside: Inside) -> str:
    """A program as rules and checks name it: /usr/bin/git is git. One in the workspace or a
    scratch folder such as /tmp keeps its path, since it may be anything."""
    text = word.text
    if word.dynamic or not text.startswith("/") or _allowed_path(text, inside):
        return text
    return _program_name(text)


def _by_name(words: list[Word], inside: Inside) -> list[Word]:
    if not words:
        return words
    name = _system_name(words[0], inside)
    return words if name == words[0].text else [Word(name), *words[1:]]


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
    # The project's own program runs code. A package manager in it, like .venv/bin/pip, is
    # judged like the one on PATH too, so an install still counts as using the network.
    kind, reason = _named_program_kind(words)
    # One in /tmp too: anything may have been put there.
    if "/" in first.text and _allowed_path(first.text, inside):
        program = _program_name(first.text)
        managed = VERSIONED.match(program) or program in PACKAGE_MANAGERS
        if not managed or _rank(kind) < _rank(Kind.EXECUTE):
            return Kind.EXECUTE, ""  # .venv/bin/pip list runs the project's own pip
    return kind, reason


def _named_program_kind(words: list[Word]) -> tuple[Kind, str]:
    program = _program_name(words[0].text)  # a system program may be named by its full path
    args = [word.text for word in words[1:]]
    sub = next((a for a in args if not a.startswith("-")), "")
    if any(_long(a, FILES0_FROM) for a in args):
        return Kind.UNKNOWN, "it reads the names of its files from a file or its input"

    if VERSIONED.match(program):
        if program.startswith("pip"):
            return _pip_kind(args)
        module = _python_module(args)
        if module is not None and module[0] == "pip":
            kind, reason = _pip_kind(module[1])
            # `python -m` imports from the current folder first, so a ./pip folder would run,
            # unless -I or -P leaves it out.
            options = args[: len(args) - len(module[1])]
            if not any(_short(a) and ("I" in a or "P" in a) for a in options):
                return max(kind, Kind.EXECUTE, key=_rank), reason
            return kind, reason
        return Kind.EXECUTE, ""
    if program == "git":
        return _git_kind(args)
    if program in PACKAGE_MANAGERS:
        if program == "yarn" and not sub:
            return Kind.NETWORK, ""  # plain `yarn` installs
        # Not yarn: a project's .yarnrc.yml can name its own yarn to run (yarnPath).
        if program in ("npm", "pnpm") and sub in ("ls", "list", "why", "--version"):
            return Kind.READ, ""
        if program == "uv":
            return _uv_kind(args, sub)
        return _package_kind(sub)
    if program in ("sed", "gsed"):
        scripts = _sed_scripts(args)
        if scripts is None:
            return Kind.UNKNOWN, "its script comes from a file, which Zwans doesn't read"
        if _from_variable(words, scripts):
            return Kind.UNKNOWN, SCRIPT_FROM_VARIABLE
        if any(_sed_unsafe(script) for script in scripts):
            return Kind.UNKNOWN, "its script may run commands or write files"
        return (Kind.WRITE if _sed_in_place(args) else Kind.READ), ""
    if program in AWKS:
        awk = _awk_program(args)
        if awk is None:
            return Kind.UNKNOWN, "its program reads or writes files, which Zwans doesn't check"
        if _from_variable(words, awk.scripts):
            return Kind.UNKNOWN, SCRIPT_FROM_VARIABLE
        if any(token in script for script in awk.scripts for token in ("system", "|", ">")):
            return Kind.UNKNOWN, "its program may run commands or write files"
        if any(AWK_LOADS.search(script) for script in awk.scripts):
            return Kind.UNKNOWN, "its program may load or read files it names itself"
        if any("ENVIRON" in script for script in awk.scripts):
            return Kind.UNKNOWN, PRINTS_ENVIRONMENT
        return (Kind.WRITE if awk.in_place else Kind.READ), ""
    if program == "jq":
        jq_filter = _jq_filter(args)
        if jq_filter is None:
            return Kind.UNKNOWN, "its filter comes from a file, which Zwans doesn't read"
        if _from_variable(words, [jq_filter]):
            return Kind.UNKNOWN, SCRIPT_FROM_VARIABLE
        if JQ_MODULES.search(jq_filter) or any(a == "-L" or a.startswith("-L") for a in args):
            return Kind.UNKNOWN, "its filter loads modules, which Zwans doesn't read"
        if JQ_ENVIRONMENT.search(jq_filter):
            return Kind.UNKNOWN, PRINTS_ENVIRONMENT
    if program == "sort":
        if any(_long(a, "--compress-program") for a in args):
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
    if (
        program == "tar"
        and "--force-local" not in args
        and any(":" in a.split("/")[0] for a in args if not a.startswith("-"))
    ):
        return Kind.NETWORK, ""  # GNU tar takes HOST:FILE as an archive on another machine
    environment = _environment_kind(program, words[1:])
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


def _environment_kind(program: str, words: list[Word]) -> tuple[Kind, str] | None:
    """Builtins that print every variable, which can hold tokens and keys, or that set one
    that changes what programs run, as `export PATH=.`, `read PATH` and `printf -v PATH`
    do. A name or option the shell fills in could be any of those: `printf "$X" .` with
    X=-vPATH sets PATH."""
    args = [word.text for word in words]
    filled = [word.dynamic and ("$" in word.text or "`" in word.text) for word in words]
    if program == "printenv" or (program == "set" and not args):
        return Kind.UNKNOWN, PRINTS_ENVIRONMENT
    setting = any(a.startswith("-") and "s" in a for a in args)
    if program == "shopt" and setting and (any(a in GLOB_OPTIONS for a in args) or any(filled)):
        return Kind.UNKNOWN, CHANGES_GLOBS
    if program == "read":
        return _assigns(_read_names(args))
    if program == "printf":
        if filled[:1] == [True]:
            return Kind.UNKNOWN, "its first argument comes from a variable and could be -v NAME"
        return _assigns(_printf_names(args))
    if program not in ("export", "declare", "local"):
        return None
    if any(_short(a) and "n" in a[1:] for a in args):
        # `declare -n p=PATH` makes p another name for PATH, so setting p sets PATH.
        return Kind.UNKNOWN, "it makes a name stand for another variable, which Zwans can't follow"
    if any(_short(a) and "i" in a[1:] for a in args):
        # `declare -i y=x` evaluates x as arithmetic, which runs any $(...) x holds.
        return Kind.UNKNOWN, "it evaluates values as arithmetic, which can run commands"
    named = [a for a in args if not a.startswith("-")]
    if not named:  # `export`, `export -p`, `declare -x`
        return Kind.UNKNOWN, PRINTS_ENVIRONMENT
    for name in (a.split("=", 1)[0] for a in named if "=" not in a):  # `export FOO`
        if not VARIABLE_NAME.match(name):
            return Kind.UNKNOWN, f"it sets {name}, a variable whose name Zwans can't tell"
    return _assigns([a.split("=", 1)[0].rstrip("+") for a in named if "=" in a])


# shopt options that make globs match what file rules take them not to: hidden files, or
# names in another case.
GLOB_OPTIONS = frozenset({"dotglob", "nocaseglob"})
READ_VALUES = frozenset("dinNptu")  # read's options that take a value; -a NAME is a name


def _assigns(names: list[str]) -> tuple[Kind, str] | None:
    for name in names:
        bare = name.partition("[")[0]
        if not VARIABLE_NAME.match(name):
            return Kind.UNKNOWN, f"it sets {name}, a variable whose name Zwans can't tell"
        if RISKY_VARIABLES.match(bare) or CODE_VARIABLES.match(bare):
            return Kind.UNKNOWN, _sets(bare)
    return None


def _read_names(args: list[str]) -> list[str]:
    """The variables `read` sets: its names, and the array -a names."""
    names: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        i += 1
        if arg == "--":
            names.extend(args[i:])
            break
        if not _short(arg):
            names.append(arg)
            continue
        for j, flag in enumerate(arg[1:], start=1):
            if flag in READ_VALUES or flag == "a":
                value = arg[j + 1 :]
                if not value and i < len(args):
                    value = args[i]
                    i += 1
                if flag == "a":
                    names.append(value)
                break
    return names or ["REPLY"]


def _printf_names(args: list[str]) -> list[str]:
    """The variable `printf -v NAME` sets, also written -vNAME."""
    for i, arg in enumerate(args):
        if arg == "--" or not arg.startswith("-"):
            break
        if arg.startswith("-v"):
            return [arg[2:] or (args[i + 1] if i + 1 < len(args) else "")]
    return []


def _unknown_folder(args: list[str]) -> bool:
    """Whether `cd` or `pushd` goes somewhere the arguments don't name: home for a bare `cd`,
    the last folder for `cd -`, a folder on the stack for `pushd` alone or `pushd +1`, or one
    found through CDPATH."""
    named = [a for a in args if a == "-" or not a.startswith("-") or a[1:].isdigit()]
    if not named or named[0] == "-":
        return True
    if named[0][0] in "+-" and named[0][1:].isdigit():
        return True
    # With CDPATH set where Zwans runs, which commands inherit, `cd src` may go to some
    # other folder's src. `./src`, `../src` and absolute paths aren't looked up there.
    target = named[0]
    looked_up = not target.startswith(("/", "~")) and target.split("/")[0] not in (".", "..")
    return bool(os.environ.get("CDPATH")) and looked_up


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
        if arg == "-f" or _long(arg, "--file"):
            return None
        if arg == "-e" or (_long(arg, "--expression") and "=" not in arg):
            scripts.append(following)
            i += 1
        elif _long(arg, "--expression"):
            scripts.append(arg.partition("=")[2])
        elif _long(arg, "--line-length") and "=" not in arg:
            i += 1  # its value
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


# sed commands that take no file and run nothing, some with a number after them (l 70, q 1).
SED_PLAIN = frozenset("=dDgGhHxnNpPlLqQzF")
SED_S_FLAGS = frozenset("gpiImM0123456789")


def _sed_unsafe(script: str) -> bool:
    """Whether a sed script may run a command (`e`, or the e flag of s) or read or write a file
    (r, R, w, W, and s's w flag). It's read command by command, and anything this can't
    follow counts as unsafe, so a delimiter or bracket that hides an e can't get past."""
    i, n = 0, len(script)
    while i < n:
        while i < n and script[i] in " \t\n;{}!":
            i += 1
        i = _sed_address(script, i)
        if i < 0:
            return True
        while i < n and script[i] in " \t!":
            i += 1
        if i == n:
            return False
        command = script[i]
        i += 1
        if command in "{}":
            continue
        if command == "#" or command in "aic":  # a comment, or text to the end of the line
            while i < n and script[i] != "\n":
                i += 2 if script[i] == "\\" else 1
            continue
        if command in ":btTv":  # a label or version, to the end of the command
            while i < n and script[i] not in ";\n":
                i += 1
            continue
        if command in "sy":
            i = _sed_parts(script, i, 2)
            if i < 0:
                return True
            if command == "s":
                while i < n and script[i] in SED_S_FLAGS:
                    i += 1
        elif command in SED_PLAIN:
            while i < n and script[i] in " \t0123456789":
                i += 1
        else:
            return True  # e, r, R, w, W, or something this doesn't know
        while i < n and script[i] in " \t":
            i += 1
        if i < n and script[i] not in ";\n}#":
            return True  # what follows isn't another command: s///e, s///w file, ...
    return False


def _sed_address(script: str, i: int) -> int:
    """Skip an address or a range of them (1, $, /re/, \\cREc, 1~2, 1,+3). -1 when it's
    malformed."""
    for _ in range(2):
        while i < len(script) and script[i] in "0123456789$~+":
            i += 1
        if i < len(script) and script[i] in "/\\":
            if script[i] == "\\":
                i += 1
            i = _sed_parts(script, i, 1)
            if i < 0:
                return -1
            while i < len(script) and script[i] in "IM":
                i += 1
        if i >= len(script) or script[i] != ",":
            return i
        i += 1
    return i


def _sed_parts(script: str, i: int, count: int) -> int:
    """Skip `count` parts ended by the delimiter at script[i], as in s/a/b/. Where it ends, or
    -1 when a part is never closed."""
    if i >= len(script) or script[i] in "\\\n":
        return -1
    delimiter = script[i]
    i += 1
    for _ in range(count):
        while i < len(script) and script[i] != delimiter:
            i += 2 if script[i] == "\\" else 1
        if i >= len(script):
            return -1
        i += 1
    return i


class _Awk(NamedTuple):
    scripts: list[str]
    in_place: bool  # gawk -i inplace rewrites the files it reads


AWK_VALUES = frozenset({"--field-separator", "--assign"})
AWK_SOURCES = frozenset({"--source"})
AWK_FILES = frozenset({"--file", "--exec", "--load", "--include"})
# gawk options that write a file (--pretty-print=FILE, ...) or run its debugger.
AWK_WRITES = frozenset({"--pretty-print", "--profile", "--dump-variables", "--debug"})
# Long options in the order a shortening is read as one: --f could be --file or
# --field-separator, and is taken as the riskier.
AWK_LONG = (*sorted(AWK_FILES), *sorted(AWK_WRITES), *AWK_SOURCES, *sorted(AWK_VALUES))
# Short options and the long ones they stand for. d, D, o and p take an optional value.
AWK_SHORT = {
    "F": "--field-separator",
    "v": "--assign",
    "e": "--source",
    "f": "--file",
    "E": "--exec",
    "l": "--load",
    "i": "--include",
    "o": "--pretty-print",
    "p": "--profile",
    "d": "--dump-variables",
    "D": "--debug",
}


def _awk_program(args: list[str]) -> _Awk | None:
    """The program awk runs, from -e or its first argument. None when it comes from a file
    (-f prog.awk), loads one (-i lib, -l ext), or writes one (gawk's -o, -p, -d), which this
    doesn't check; `-i inplace` is the one library it knows. `-W name=value` is gawk's and
    mawk's way to write a long option."""
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
            name, has_value, value = arg.partition("=")
        else:
            letters = arg[1:]
            j = next((k for k, c in enumerate(letters) if c in AWK_SHORT or c == "W"), -1)
            if j < 0:
                continue  # flags only, such as -b
            value = letters[j + 1 :]
            if letters[j] == "W":
                if not value:
                    value = args[i] if i < len(args) else ""
                    i += 1
                name, has_value, value = ("--" + value).partition("=")
            else:
                name, has_value = AWK_SHORT[letters[j]], "=" if value else ""
        option = next((full for full in AWK_LONG if _long(name, full)), "")
        if option in AWK_WRITES:
            return None
        if not option:
            continue
        if not has_value:
            value = args[i] if i < len(args) else ""
            i += 1
        if option in AWK_SOURCES:
            scripts.append(value)
        elif option == "--include" and value in ("inplace", "inplace.awk"):
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


# jq's `env` and `$ENV` hold every environment variable; `.env` is a key, not those.
# `import` and `include` load module files, which may use them.
JQ_MODULES = re.compile(r"\b(import|include)\b")
# gawk's @load runs a library's code and @include reads another program; ARGV and ARGC name
# the files awk reads, and getline reads one itself.
AWK_LOADS = re.compile(r"@\s*(load|include)|\bARG[VC]\b|getline")
SCRIPT_FROM_VARIABLE = "its script comes from a variable, so Zwans can't see what it does"
JQ_ENVIRONMENT = re.compile(r"\$ENV\b|(?<![.\w$])env\b")
# Options of jq's that take values (two for --arg NAME VALUE and friends), before its filter.
JQ_VALUES = {"--indent": 1, "-L": 1, "--arg": 2, "--argjson": 2, "--slurpfile": 2, "--rawfile": 2}


def _jq_filter(args: list[str]) -> str | None:
    """jq's filter: its first argument that isn't an option. None when it comes from a file
    (-f, --from-file)."""
    i = 0
    while i < len(args):
        arg = args[i]
        i += 1
        if arg in ("-f", "--from-file") or arg.startswith("--from-file="):
            return None
        if _short(arg) and "f" in arg[1:]:
            return None
        if arg in JQ_VALUES:
            i += JQ_VALUES[arg]
        elif not arg.startswith("-") or arg == "--":
            return args[i] if arg == "--" and i < len(args) else arg
    return ""


# pip options that make a listing ask an index which packages are out of date, or point it
# at another index. A short option may be in a group, as in -lo.
PIP_NETWORK = ("--outdated", "--uptodate", "--index-url", "--extra-index-url", "--find-links")
PIP_NETWORK_FLAGS = frozenset("oui")


def _pip_kind(args: list[str]) -> tuple[Kind, str]:
    """pip's sub-command, judged with its options: `pip list` only reads, but
    `pip list --outdated` asks the index, whose address can carry any data."""
    sub = next((a for a in args if not a.startswith("-")), "")
    kind, reason = _package_kind(sub, read=PIP_READ)
    if kind == Kind.READ and _asks_an_index(args, files_flag=sub != "show"):
        return Kind.NETWORK, ""
    return kind, reason


def _asks_an_index(args: list[str], *, files_flag: bool = True) -> bool:
    """Whether a listing's options make it use the network. `-f` is --find-links, except for
    `pip show`, where it lists files."""
    flags = PIP_NETWORK_FLAGS | ({"f"} if files_flag else set())
    for arg in args:
        # pip takes any shortening of a long option: --outd is --outdated. uv's --index and
        # --default-index too.
        if any(_long(arg, option) for option in PIP_NETWORK) or arg.startswith(
            ("--index", "--default-index", "--extra-index")
        ):
            return True
        if _short(arg) and any(flag in flags for flag in arg[1:]):
            return True
    return False


def _uv_kind(args: list[str], sub: str) -> tuple[Kind, str]:
    if sub in UV_NESTED:
        rest = args[args.index(sub) + 1 :]
        inner = next((a for a in rest if not a.startswith("-")), "")
        if inner in UV_NESTED[sub] and not _asks_an_index(rest, files_flag=inner != "show"):
            return Kind.READ, ""
        return Kind.NETWORK, ""
    if sub == "run" and any(a.startswith("--with") for a in args):
        return Kind.NETWORK, ""  # `uv run --with requests` installs requests first
    return _package_kind(sub)


def _git_kind(args: list[str]) -> tuple[Kind, str]:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-c" or args[i].startswith("--config-env"):
            return Kind.UNKNOWN, "git -c can make git run any program"
        # Another repository's settings, or another folder of git's own programs, can make
        # git run any program.
        if args[i].startswith(("--exec-path=", "--git-dir")):
            return Kind.UNKNOWN, "it makes git use settings or programs Zwans can't check"
        i += 2 if args[i] in GIT_VALUE_OPTIONS else 1
    if i >= len(args):
        return Kind.READ, ""
    sub, rest = args[i], args[i + 1 :]
    # grep's -O (also in a group, as -lO) and --open-files-in-pager, however shortened, run a
    # program on the files found; --ext-diff runs the configured diff program.
    if any(
        (sub == "grep" and _short(a) and "O" in a)
        or _long(a, "--open-files-in-pager")
        or (_long(a, "--ext-diff") and len(a) > len("--ex"))
        for a in rest
    ):
        return Kind.UNKNOWN, "that option makes git run another program"
    named = [a for a in rest if not a.startswith("-")]
    if _git_output(rest):
        return Kind.WRITE, ""  # `git diff --output=FILE` writes FILE
    if sub == "reflog" and named and named[0] in ("expire", "delete"):
        return Kind.WRITE, ""  # it throws away what `git reflog` would bring back
    if sub in GIT_READ:
        return Kind.READ, ""
    runs = sub == "rebase" and any(
        a in ("-x", "--exec") or a.startswith(("-x", "--exec=")) for a in rest
    )
    if (sub in GIT_RUNS and (sub != "bisect" or "run" in named)) or runs:
        return Kind.UNKNOWN, "it runs a command given to it, which Zwans doesn't check"
    if sub == "remote" and named:
        if named[0] in ("add", "set-url"):
            return Kind.UNKNOWN, "it changes where git sends and fetches code"
        # `git remote show NAME` asks the remote, which may be any address, unless -n.
        if named[0] == "show" and len(named) > 1 and "-n" not in rest:
            return Kind.NETWORK, ""
        if named[0] in ("update", "prune"):
            return Kind.NETWORK, ""
        if named[0] == "get-url":
            return Kind.READ, ""
    if sub in ("branch", "tag", "remote", "stash", "worktree"):
        listing = not named or named[0] in ("list", "show", "-v")
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
    reads, writes = _named_files(program, words, args)
    # `--file=X` and friends: the value is part of the option's word, so not named above.
    option_files = [
        a.partition("=")[2] for a in args if "=" in a and any(_long(a, o) for o in FILE_OPTIONS)
    ]
    if program in SHORT_FILE_OPTIONS:
        option_files += _short_values(args, "f", SHORT_FILE_OPTIONS[program])
    return tuple(dict.fromkeys([*reads, *option_files])), writes


def _named_files(
    program: str, words: list[Word], args: list[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if program == "date":  # `date -f FILE` prints each line of FILE in an error
        return tuple(_short_values(args, "f", "dIrs") + _values(args, "--file")), ()
    if program in ("perl", "ruby"):
        return (), tuple(_in_place_scripts(args))
    rest = _without_pattern(program, words[1:]) if program in PATTERN_FIRST else words[1:]
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


def _in_place_scripts(args: list[str]) -> list[str]:
    """The files `perl -pi -e '...' FILE` and `ruby -i -pe '...' FILE` rewrite: with -i, the
    arguments after the code (-e CODE, or else the script's name)."""
    in_place = False
    named: list[str] = []
    code = False
    i = 0
    while i < len(args):
        arg = args[i]
        i += 1
        if arg == "--":
            named.extend(args[i:])
            break
        if not _short(arg):
            if not arg.startswith("--"):
                named.append(arg)
            continue
        for j, flag in enumerate(arg[1:], start=1):
            if flag == "i":
                in_place = True
                break  # what follows is the backup suffix
            if flag in "eE":
                code = True
                if j + 1 == len(arg):
                    i += 1  # the code is the next argument
                break
            if flag in "IlMmxCdD0F":  # options whose value is the rest of the word
                break
    return (named if code else named[1:]) if in_place else []


def _copy_writes(program: str, args: list[str], named: tuple[str, ...]) -> tuple[str, ...]:
    """What cp, mv and ln change: where they write (the -t folder, or else the last name), and
    each source's name inside it, since `cp -r t/.git .` writes .git. mv also removes its
    sources. A link lets whoever writes to it change what it points to, so for ln (and cp -l
    or -s) the sources count as changed too."""
    # -t may end a group of short options (-rt DIR) or carry its value (-tDIR). -S takes a
    # backup suffix, which could hold a t.
    targets = _short_values(args, "t", "S") + _values(args, "--target-directory")
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
            _long(a, "--link")
            or _long(a, "--symbolic-link")
            or any(f in "ls" for f in _short_flags(a, "tS"))
            for a in args
        )
    )
    changed = list(named) if program == "mv" or links else []
    return tuple(dict.fromkeys([*folders, *landed, *changed]))


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
        if _long(arg, "--output"):
            return [arg.partition("=")[2] if "=" in arg else following]
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
        elif _long(arg, "--in-place"):
            return True
        elif "=" not in arg and any(
            _long(arg, option) for option in ("--expression", "--file", "--line-length")
        ):
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


class _Unwrapped(NamedTuple):
    words: list[Word]  # the wrapped command
    args_unknown: bool  # xargs adds arguments
    problem: str = ""  # why it can't be judged; `words` is still what it runs, for deny rules
    reads: tuple[str, ...] = ()  # files the wrappers read: `xargs -a FILE`
    loads: str = ""  # a variable env sets that makes the command load code, as PYTHONPATH


def _unwrap(words: list[Word], inside: Inside) -> _Unwrapped:
    """Drop wrappers like `timeout 60` and `env X=1`, also named by their full path."""
    args_unknown = False
    problem = ""
    reads: list[str] = []
    loads = ""
    while words and _system_name(words[0], inside) in WRAPPERS and not words[0].dynamic:
        program = _system_name(words[0], inside)
        takes_value = WRAPPERS[program]
        rest = words[1:]
        while rest and rest[0].text.startswith("-") and rest[0].text != "-":
            option = rest.pop(0).text
            if program == "command" and option in ("-v", "-V"):
                return _Unwrapped([], False)  # looks a command up without running it
            if program == "xargs" and (option.startswith("-a") or _long(option, "--arg-file")):
                # Its arguments, which the command may print, come from that file.
                _, equals, value = option.partition("=")
                value = option[2:] if option.startswith("-a") else value
                if not value and not equals and rest:
                    value = rest.pop(0).text
                reads.append(value)
                continue
            if program == "env" and option.startswith(("-S", "--split-string")):
                problem = problem or "env -S splits a string into a command Zwans can't see"
                # `-S'rm x'` and `--split-string=rm x` carry the command themselves.
                value = option[2:] if option.startswith("-S") else option.partition("=")[2]
                if value:
                    rest.insert(0, Word(value))
                break
            if program == "env" and option.startswith(("-C", "--chdir")):
                problem = problem or (
                    "env -C runs it in another folder, so Zwans can't tell which files it uses"
                )
            if option in takes_value and rest:
                rest.pop(0)
        if program == "timeout" and rest:
            rest.pop(0)  # the duration
        if program == "env":
            while rest and ASSIGNMENT.match(rest[0].text):
                name = rest.pop(0).text.split("=", 1)[0]
                if RISKY_VARIABLES.match(name):
                    problem = problem or _sets(name)
                if CODE_VARIABLES.match(name):
                    loads = loads or name
            if not rest:  # `env` alone prints every variable
                return _Unwrapped([], False, problem or PRINTS_ENVIRONMENT)
        if program == "xargs":
            args_unknown = True
        words = rest
    return _Unwrapped(words, args_unknown, problem, tuple(reads), loads)


def _shell(
    words: list[Word], inside: Inside, texts: _Texts, simple: SimpleCommand
) -> list[Action] | None:
    """`bash -c "..."` runs the commands in its string, so judge those instead. So does
    `eval`, with its arguments joined."""
    if words[0].text == "eval" and not words[0].dynamic:
        if any(_filled(word) for word in words[1:]):
            reason = "the commands it runs come from a variable"
            return [_action(texts, Kind.UNKNOWN, reason, outside=True, opaque=True)]
        return analyze(" ".join(word.text for word in words[1:]), inside)
    if words[0].text not in SHELLS:
        return None
    args = words[1:]
    i = 0
    while i < len(args):
        word = args[i]
        i += 1
        if _long(word.text, "--rcfile") or _long(word.text, "--init-file"):
            reason = "it runs a startup file, which Zwans doesn't read"
            return [_action(texts, Kind.UNKNOWN, reason, outside=True)]
        if word.text in ("-o", "+o", "-O", "+O"):  # set and shopt options, with their names
            value = args[i] if i < len(args) else Word("")
            i += 1
            if word.text == "-O" and (value.text in GLOB_OPTIONS or value.dynamic):
                return [_action(texts, Kind.UNKNOWN, CHANGES_GLOBS, opaque=value.dynamic)]
            continue
        if word.text == "-c" or (_short(word.text) and "c" in word.text[1:]):
            if i >= len(args):
                break
            script = args[i]
            if script.dynamic:
                reason = "the commands it runs come from a variable"
                return [_action(texts, Kind.UNKNOWN, reason, outside=True, opaque=True)]
            return analyze(script.text, inside)
        if word.text.startswith(("-", "+")):
            continue
        if word.text in STDIN_FILES:
            break  # its script is its input
        if _filled(word):  # bash <(...), bash $(...)
            reason = "the script it runs comes from a variable or another command"
            return [_action(texts, Kind.UNKNOWN, reason, outside=True, opaque=True)]
        if not _allowed_path(word.text, inside):
            reason = f"{word.text} is outside the workspace"
            return [_action(texts, Kind.UNKNOWN, reason, outside=True)]
        return [_action(texts, Kind.EXECUTE)]
    reason = "it runs commands from its input, which Zwans can't see"
    if simple.heredocs:  # `texts` shows the script, so only a rule for that exact text allows it
        return [_action(texts, Kind.UNKNOWN, reason, outside=True)]
    from_file = any(op in INPUT_REDIRECTS and _names_file(op, t) for op, t in simple.redirects)
    return [_action(texts, Kind.UNKNOWN, reason, opaque=not from_file)]


# Interpreters other than Python, and the short options that give them their program in the
# arguments (as in `perl -ne '...'`). With none of those and no script, they run their input.
INTERPRETER_CODE = {"node": "ep", "ruby": "e", "perl": "eE", "php": "r"}


def _interpreter(words: list[Word]) -> str | None:
    program = _program_name(words[0].text)
    if VERSIONED.match(program) and not program.startswith("pip"):
        return "python"
    return program if program in INTERPRETER_CODE else None


def _program_from_input(words: list[Word], simple: SimpleCommand) -> bool:
    """Whether an interpreter, or `source`, runs a program piped to it or given as a
    here-string, or one another command or a variable gives (`python3 <(...)`), which its text
    doesn't show. A here-document is shown, and a file on its input is named."""
    if words[0].text in ("source", ".") and not simple.heredocs:
        script = next((w for w in words[1:] if not w.text.startswith("-")), None)
        return script is not None and (script.text in STDIN_FILES or _filled(script))
    interpreter = _interpreter(words)
    if interpreter is None or simple.heredocs:
        return False
    if any(op in INPUT_REDIRECTS and _names_file(op, t) for op, t in simple.redirects):
        return False
    args = [word.text for word in words[1:]]
    if any(a in ("--version", "-V", "--help", "-h") for a in args) or (
        interpreter in ("node", "perl", "php") and "-v" in args
    ):
        return False  # it prints its version or help and stops
    i = 0
    while i < len(args):
        arg = args[i]
        i += 1
        if arg in STDIN_FILES:
            return True
        if not arg.startswith("-"):
            return _filled(words[i])  # a script, unless another command or a variable gives it
        if arg.startswith("--"):
            if arg.partition("=")[0] in ("--eval", "--print"):
                return False
            continue
        flags = arg[1:]
        if interpreter != "python":
            if any(flag in INTERPRETER_CODE[interpreter] for flag in flags):
                return False
            continue
        for j, flag in enumerate(flags):
            if flag in "cm":
                return False
            if flag in "WX":
                i += 1 if j + 1 == len(flags) else 0  # its value is the next argument
                break
    return True


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
    # The files it acts on: where it starts and anything under it (at any depth, so a `**`
    # part, which file rules take as any folders, hidden ones too), or those named by -name
    # or -path when given.
    folders = [w.text for w in words[1 : _first_option(words)]] or ["."]
    names, paths = _find_names(words)
    found = [
        *folders,
        *(posixpath.join(folder, "**", name) for folder in folders for name in names),
        *paths,
        *(posixpath.join(folder, "**") for folder in folders if not names and not paths),
    ]
    if deletes:
        # Not the workspace root itself, though: it holds everything, and
        # `find . -name '*.pyc' -delete` is everyday cleanup.
        writes.extend(path for path in found if PurePosixPath(path).parts)
    texts = _texts(SimpleCommand(words=words), words)
    problem = _outside_argument(starts, inside, False)
    if problem:
        return [_action(texts, Kind.UNKNOWN, problem.reason, outside=True, opaque=problem.opaque)]
    per_file = [_per_file(action, found, folders, in_dir) for action, in_dir in actions]
    return [_action(texts, expression_kind, writes=tuple(writes)), *per_file]


def _find_values(words: list[Word], options: tuple[str, ...]) -> list[str]:
    return [words[i + 1].text for i in range(len(words) - 1) if words[i].text in options]


# find's operators that let a file through without its -name: `! -name x`, `-name x -o ...`.
FIND_WIDENS = frozenset({"!", "-not", "-o", "-or", ","})


def _find_names(words: list[Word]) -> tuple[list[str], list[str]]:
    """The names (as file rule paths see them) and paths find's -name and -path tests let
    through. Both empty when they don't narrow what it acts on: an operator lets other files
    through, or a -path glob, whose * also matches / and dots, names any file."""
    if any(word.text in FIND_WIDENS for word in words):
        return [], []
    names: list[str] = []
    for name in _find_values(words, ("-name",)):
        names.extend(_find_name(name))
    for name in _find_values(words, ("-iname",)):
        if "[" in name:
            return [], []
        # Each letter in either case, as a shell class: .ENV stands for .env too.
        spelled = "".join(f"[{c.lower()}{c.upper()}]" if c.isalpha() else c for c in name)
        names.extend(_find_name(spelled))
    paths = _find_values(words, ("-path", "-ipath", "-wholename", "-iwholename"))
    if any(c in path for path in paths for c in "*?[") or (
        paths and any(w.text in ("-ipath", "-iwholename") for w in words)
    ):
        return [], []
    return names, paths


def _find_name(name: str) -> list[str]:
    """A -name pattern as shell globs. find's *, ? and [...] match a leading dot, which a shell
    glob's don't, so `*env` also stands for `.*env`, `?env` for `.env`, and `[.e]nv` for
    `.nv`."""
    if name[:1] == "*":
        return [name, "." + name]
    if name[:1] == "?":
        return [name, "." + name[1:]]
    if name[:1] == "[" and "]" in name[2:]:
        return [name, "." + name[name.index("]", 2) + 1 :]]
    return [name]


def _per_file(action: Action, found: list[str], folders: list[str], in_dir: bool) -> Action:
    """A command find runs per file, with {} as the files it may stand for. -execdir runs it
    in each file's folder, so its other paths are taken from there too."""

    def expand(paths: tuple[str, ...]) -> tuple[str, ...]:
        out: list[str] = []
        for path in paths:
            if "{}" in path:
                out.extend(path.replace("{}", file) for file in found)
            elif in_dir and not path.startswith(("/", "~")):
                for folder in folders:  # each file's folder is the start or one under it
                    out.append(posixpath.normpath(posixpath.join(folder, path)))
                    out.append(posixpath.normpath(posixpath.join(folder, "**", path)))
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
) -> tuple[Kind, tuple[str, ...], tuple[str, ...], _Problem | None]:
    """The kind redirections give a command, the files they read and write, and a problem
    that makes it unknown."""
    kind = Kind.READ
    reads: list[str] = []
    writes: list[str] = []
    for op, target in simple.redirects:
        if not _names_file(op, target):
            continue
        if target.dynamic and ("$" in target.text or "`" in target.text):
            reason = f"it redirects to {target.text}, which comes from a variable"
            return kind, (), (), _Problem(reason, opaque=True)
        if not _allowed_path(target.text, inside):
            reason = f"it redirects to {target.text}, which is outside the workspace"
            return kind, (), (), _Problem(reason)
        if op in OUTPUT_REDIRECTS:
            kind = Kind.WRITE
            writes.append(target.text)
        if op in INPUT_REDIRECTS:
            reads.append(target.text)
    return kind, tuple(reads), tuple(writes), None


def _outside_argument(words: list[Word], inside: Inside, args_unknown: bool) -> _Problem | None:
    program = _program_name(words[0].text)
    if program in NO_FILE_PROGRAMS:
        return None
    if args_unknown:
        reason = "its arguments come from its input, so Zwans can't see which files it touches"
        return _Problem(reason, opaque=True)
    rest = list(words[1:])
    if program in PATTERN_FIRST:
        rest = _without_pattern(program, rest)
    for word in rest:
        if word.dynamic and ("$" in word.text or "`" in word.text):
            reason = f"{word.text} comes from a variable, so Zwans can't see which file it is"
            return _Problem(reason, opaque=True)
        for candidate in (word.text, word.text.partition("=")[2]):
            if _looks_outside(candidate) and not _allowed_path(candidate, inside):
                return _Problem(f"{candidate} is outside the workspace")
    return None


def _looks_outside(path: str) -> bool:
    return path.startswith(("/", "~")) or ".." in PurePosixPath(path).parts


# For programs whose first argument is a pattern or script: their short options that give it
# instead (-e PATTERN, -f FILE), and those that take some other value. A value may be
# attached (-eKEY, -F:) or follow, and sed's -i takes the rest of its word only.
PATTERN_OPTIONS = {
    "grep": ("ef", "ABCDdm"),
    "rg": ("ef", "ABCEMTdgjmrt"),
    "sed": ("ef", "l"),
    "awk": ("ef", "FvilE"),
}
LONG_PATTERN_OPTIONS = ("--regexp", "--expression", "--source", "--file")


def _without_pattern(program: str, args: list[Word]) -> list[Word]:
    """Drop the pattern or script: each -e value, or else the first positional argument.
    What's left are files, and the files -f names, which are read too."""
    if program == "jq":
        return _jq_files(args)
    family = {"egrep": "grep", "fgrep": "grep", "gsed": "sed"}.get(program, program)
    pattern_letters, value_letters = PATTERN_OPTIONS.get(
        "awk" if program in AWKS else family, ("ef", "")
    )
    kept: list[Word] = []
    pattern_seen = False
    i = 0
    while i < len(args):
        word = args[i]
        i += 1
        text = word.text
        if text == "--":
            rest = args[i:]
            return kept + (rest if pattern_seen else rest[1:])
        if text.startswith("--"):
            name, equals, _ = text.partition("=")
            if any(_long(name, option) for option in LONG_PATTERN_OPTIONS):
                pattern_seen = True
                if not equals and i < len(args):
                    value = args[i]
                    i += 1
                    if _long(name, "--file"):
                        kept.append(value)  # a file of patterns, which is read
            else:
                kept.append(word)
            continue
        if not _short(text):
            if pattern_seen:
                kept.append(word)
            else:
                pattern_seen = True
            continue
        for j, letter in enumerate(text[1:], start=1):
            if program in ("sed", "gsed") and letter == "i":
                break  # the rest is a backup suffix
            if letter in pattern_letters:
                pattern_seen = True
            if letter in pattern_letters or letter in value_letters:
                if j + 1 == len(text) and i < len(args):
                    value = args[i]
                    i += 1
                    if letter == "f":
                        kept.append(value)  # a file of patterns or a script, which is read
                elif letter == "e":
                    text = ""  # -eKEY: the word is the pattern, as harmless as one alone
                break
        if text:
            kept.append(word)
    return kept


def _jq_files(args: list[Word]) -> list[Word]:
    """jq's input files: what follows its filter, skipping the values of its options."""
    files: list[Word] = []
    texts = [word.text for word in args]
    from_file = _jq_filter(texts) is None
    i = 0
    while i < len(args):
        text = texts[i]
        i += 1
        if text in JQ_VALUES:
            values = args[i : i + JQ_VALUES[text]]
            if text in ("--slurpfile", "--rawfile"):
                files.extend(values[1:])  # --rawfile NAME FILE reads FILE
            i += JQ_VALUES[text]
        elif text in ("-f", "--from-file"):
            if i < len(args):
                files.append(args[i])
                i += 1
        elif text == "--":
            files.extend(args[i:] if from_file else args[i + 1 :])
            break
        elif not text.startswith("-"):
            if from_file:
                files.append(args[i - 1])
            else:
                from_file = True  # the filter, and from here on, files
        else:
            files.append(args[i - 1])  # options, which the checks skip
    return files


def _allowed_path(path: str, inside: Inside) -> bool:
    if path in HARMLESS_FILES or path.startswith("/dev/fd/"):
        return True
    if path.startswith("~"):
        return False
    # Resolved first, so /tmp/../etc/passwd isn't taken as a file in /tmp.
    real = os.path.realpath(path) if path.startswith("/") else ""
    if any(real == d or real.startswith(os.path.join(d, "")) for d in REAL_SCRATCH_DIRS):
        return True
    return inside(path)


def _option_values(args: list[str], option: str) -> list[str]:
    return [args[i + 1] for i, a in enumerate(args[:-1]) if a == option]


def _short_flags(arg: str, values: str) -> str:
    """The letters of a group of short options, up to one that takes a value (`values`), whose
    value may follow in the same word: -rtdest is r and t."""
    if not _short(arg):
        return ""
    letters = arg[1:]
    cut = next((i + 1 for i, letter in enumerate(letters) if letter in values), len(letters))
    return letters[:cut]


def _short_values(args: list[str], flag: str, others: str) -> list[str]:
    """The values of a short option, which may end a group (`-rt DIR`) or carry its value
    (`-tDIR`). `others` are the program's other short options that take a value, whose value
    could hold the flag's letter."""
    found: list[str] = []
    for i, arg in enumerate(args):
        if arg == "--":
            break
        if not _short(arg):
            continue
        for j, letter in enumerate(arg[1:], start=1):
            if letter in others:
                break
            if letter == flag:
                value = arg[j + 1 :] or (args[i + 1] if i + 1 < len(args) else "")
                if value:
                    found.append(value)
                break
    return found


def _program_name(text: str) -> str:
    """/usr/bin/git is git. `.` (as in `. venv/bin/activate`) stays itself."""
    return PurePosixPath(text).name or text


def _filled(word: Word) -> bool:
    """Whether the shell fills a word in from a variable or another command's output, as with
    $X, $(...), `...` and <(...), rather than only from a glob."""
    return word.dynamic and any(mark in word.text for mark in ("$", "`", "<(", ">("))


def _from_variable(words: list[Word], scripts: list[str]) -> bool:
    """Whether one of a program's scripts comes from $VAR or $(...): a word the shell fills in
    that is, or ends with, the script (as in -e"$X")."""
    filled = [w.text for w in words[1:] if w.dynamic and ("$" in w.text or "`" in w.text)]
    return any(script and text.endswith(script) for script in scripts for text in filled)


def _short(arg: str) -> bool:
    return arg.startswith("-") and not arg.startswith("--") and len(arg) > 1


def _long(arg: str, option: str) -> bool:
    """Whether arg is the long option, with or without `=VALUE`, or a shortening of it, which
    GNU tools and pip accept: `--out=x` is `--output=x` for sort. Any shortening counts,
    though the program may find it ambiguous and refuse it, down to the part before [ when
    the option is written `--files0[-from]`, since a shorter one is another option."""
    name = arg.partition("=")[0]
    shortest, bracket, rest = option.partition("[")
    full = shortest + rest.rstrip("]")
    if not bracket:
        shortest = option[:3]  # -- and a letter
    return name.startswith(shortest) and full.startswith(name)


def _values(args: list[str], option: str) -> list[str]:
    """A long option's values, written `--option VALUE` or `--option=VALUE`, or shortened."""
    found: list[str] = []
    for i, arg in enumerate(args):
        if arg == "--":
            break
        if _long(arg, option):
            _, equals, value = arg.partition("=")
            if equals:
                found.append(value)
            elif i + 1 < len(args):
                found.append(args[i + 1])
    return found


_RANKS = {Kind.READ: 0, Kind.WRITE: 1, Kind.EXECUTE: 2, Kind.NETWORK: 3, Kind.UNKNOWN: 4}


def _rank(kind: Kind) -> int:
    return _RANKS[kind]
