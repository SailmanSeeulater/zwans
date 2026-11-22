"""The Diagnostics tool: run the project's own linters and type checkers, and report what
they find.

The model can run these with Bash, but it has to know which ones the project uses, and left
to itself it tends to run only the tests. This finds the checkers from the project's files
and runs them in one call.

The policy judges a call by the commands it would run, exactly as if Bash ran them, so a
rule about `mypy` covers it here too, and it asks or doesn't as those commands would.
"""

import configparser
import os
import shlex
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput

TIMEOUT = 300  # seconds one checker may take
MAX_OUTPUT_CHARS = 12_000  # of one checker's findings
MAX_SUBFOLDERS = 30
MAX_LOOKED_AT = 5_000  # files, when seeing whether a folder holds any a checker checks
NOT_FOUND = (126, 127)  # the shell's exit codes for a program it couldn't run
# Folders that hold other people's code or build output, never a project of the user's.
SKIPPED = frozenset({"node_modules", "venv", "dist", "build", "target", "vendor", "__pycache__"})

PYTHON = (".py", ".pyi")
SCRIPT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
ESLINT_CONFIGS = (
    "eslint.config.js",
    "eslint.config.mjs",
    "eslint.config.cjs",
    "eslint.config.ts",
    ".eslintrc",
    ".eslintrc.js",
    ".eslintrc.cjs",
    ".eslintrc.json",
    ".eslintrc.yml",
    ".eslintrc.yaml",
)
KNOWN = "ruff, mypy, pyright, tsc, eslint, cargo check and go vet"


@dataclass(frozen=True)
class Check:
    name: str  # "ruff", or "tsc in web" for one found in a subfolder
    command: str  # a shell command, run from the workspace root


@dataclass(frozen=True)
class _Found:
    name: str
    command: str
    suffixes: tuple[str, ...]  # the files it checks
    # What to pass for "all of this folder", for a checker that takes paths; None for one that
    # always checks the whole project, whatever it's asked about.
    whole: str | None = None


class DiagnosticsInput(BaseModel):
    paths: list[str] = Field(
        default=[],
        description="Files or folders to check, relative to the workspace. Leave it empty to "
        "check the whole project. A checker that only works on a whole project, such as "
        "tsc, checks all of it either way.",
    )


class DiagnosticsTool:
    name = "Diagnostics"
    description = (
        "Run the project's linters and type checkers and return what they report: type "
        "errors, undefined names, unused imports and the like. It finds the checkers the "
        f"project is set up for ({KNOWN}), so you don't need to know their commands. Call it "
        "after changing code and before saying you're done, as well as running the tests: "
        "it catches mistakes the tests don't exercise."
    )
    input_model = DiagnosticsInput
    read_only = False  # checkers run the project's plugins and configs, which is running code

    def __init__(self, root: Path, commands: Sequence[str] = ()) -> None:
        self.root = root
        self.configured = tuple(commands)  # the user's own, instead of the ones found

    def checks(self, paths: Sequence[str] = ()) -> list[Check]:
        if self.configured:
            return [Check(first_word(command), command) for command in self.configured]
        return find_checks(self.root, paths)

    def commands(self, args: dict[str, Any]) -> list[str]:
        """What a call would run, from its raw input, for the policy to judge."""
        paths = args.get("paths")
        named = [p for p in paths if isinstance(p, str)] if isinstance(paths, list) else []
        return [check.command for check in self.checks(named)]

    async def run(self, args: DiagnosticsInput, ctx: ToolContext) -> ToolOutput:
        paths = [ctx.executor.relative(path) for path in args.paths]  # refuses ones outside
        checks = self.checks(paths)
        if not checks:
            about = " for those paths" if paths else ""
            raise ToolError(
                f"No checker is set up{about} that Diagnostics knows how to run. It looks for "
                f"{KNOWN}. Run the project's own checks with Bash instead."
            )
        clean: list[str] = []
        missing: list[str] = []
        found: list[str] = []
        for check in checks:
            result = await ctx.executor.run_shell(check.command, timeout=TIMEOUT)
            output = result.output.strip()
            if result.timed_out:
                found.append(f"## {check.name}: stopped after {TIMEOUT}s without finishing")
            elif result.exit_code == 0:
                clean.append(check.name)
            elif result.exit_code in NOT_FOUND:
                missing.append(check.name)
            else:
                head = f"## {check.name} (`{check.command}`, exit code {result.exit_code})"
                found.append(f"{head}\n{_shorten(output) or '(no output)'}")
        return ToolOutput(content=_report(found, clean, missing), is_error=not (found or clean))


def find_checks(root: Path, paths: Sequence[str] = ()) -> list[Check]:
    """The checkers this project is set up for, in its root and the folders just inside it,
    which is where a repository with a Python back end and a web front end keeps them.
    `paths` (relative to the root) narrows them to the checkers for those files."""
    return [check for folder in project_folders(root) for check in _checks_in(root, folder, paths)]


def project_folders(root: Path) -> list[str]:
    """Where a project's tools may be set up: the root (""), then the folders just inside
    it, without hidden ones or ones that hold installed packages or build output."""
    try:
        inside = sorted(p.name for p in root.iterdir() if p.is_dir())
    except OSError:
        inside = []
    kept = [n for n in inside if not n.startswith(".") and n not in SKIPPED]
    return ["", *kept[:MAX_SUBFOLDERS]]


def _checks_in(root: Path, folder: str, paths: Sequence[str]) -> list[Check]:
    here = root / folder
    project = read_toml(here / "pyproject.toml").get("tool", {})
    python = any((here / f).is_file() for f in ("pyproject.toml", "setup.py", "setup.cfg"))
    mypy_ini = _ini(here / "mypy.ini") or _ini(here / ".mypy.ini")
    mypy = "mypy" in project or "mypy" in mypy_ini or "mypy" in _ini(here / "setup.cfg")
    found: list[_Found] = []

    if python or (here / "ruff.toml").is_file() or (here / ".ruff.toml").is_file():
        found.append(_Found("ruff", "ruff check --no-fix --output-format=concise", PYTHON, "."))
    if mypy:
        targets = {**project.get("mypy", {}), **mypy_ini.get("mypy", {})}
        # Without paths, mypy checks what its config names, or else everything here.
        everything = "" if {"files", "packages", "modules"} & targets.keys() else "."
        found.append(_Found("mypy", "mypy", PYTHON, everything))
    if "pyright" in project or (here / "pyrightconfig.json").is_file():
        found.append(_Found("pyright", "pyright", PYTHON, ""))
    if (here / "tsconfig.json").is_file():
        found.append(_Found("tsc", "node_modules/.bin/tsc --noEmit -p .", (".ts", ".tsx")))
    if any((here / name).is_file() for name in ESLINT_CONFIGS):
        found.append(_Found("eslint", "node_modules/.bin/eslint", SCRIPT, "."))
    if (here / "Cargo.toml").is_file():
        found.append(_Found("cargo check", "cargo check --quiet --message-format=short", (".rs",)))
    if (here / "go.mod").is_file():
        found.append(_Found("go vet", "go vet ./...", (".go",)))

    checks = []
    for each in found:
        name, command = each.name, each.command
        wanted = within(root, folder, paths, each.suffixes) if paths else None
        if wanted == []:
            continue  # paths were given, and none is this checker's
        if each.whole is not None:  # it takes paths: the ones asked for, or all of the folder
            narrowed = wanted is not None and "." not in wanted
            on = " ".join(shlex.quote(p) for p in wanted or []) if narrowed else each.whole
            command = f"{command} {on}".rstrip()
        if folder:
            checks.append(Check(f"{name} in {folder}", f"cd {shlex.quote(folder)} && {command}"))
        else:
            checks.append(Check(name, command))
    return checks


def within(root: Path, folder: str, paths: Sequence[str], suffixes: tuple[str, ...]) -> list[str]:
    """Of `paths`, the ones a checker in `folder` would look at, relative to that folder. A
    folder that holds the checker's folder counts as all of it ("."), and any other folder
    counts only when it holds files the checker checks: mypy has nothing to say about web/."""
    base = PurePosixPath(folder)
    wanted: list[str] = []
    for raw in paths:
        path = PurePosixPath(raw)
        if path == base or path in base.parents or str(path) == ".":
            wanted.append(".")
        elif folder and base not in path.parents:
            continue
        elif (root / raw).is_dir():
            if _holds(root / raw, suffixes):
                wanted.append(str(path.relative_to(base)) if folder else str(path))
        elif path.suffix in suffixes:
            wanted.append(str(path.relative_to(base)) if folder else str(path))
    return list(dict.fromkeys(wanted))


def _holds(folder: Path, suffixes: tuple[str, ...]) -> bool:
    """Whether a folder has a file with one of these suffixes somewhere in it, without
    looking through installed packages or more than a few thousand files."""
    seen = 0
    for _, folders, files in os.walk(folder):
        folders[:] = [f for f in folders if not f.startswith(".") and f not in SKIPPED]
        if any(name.endswith(suffixes) for name in files):
            return True
        seen += len(files)
        if seen > MAX_LOOKED_AT:
            return True  # too big to be sure it doesn't, so let the checker look
    return False


def _report(found: list[str], clean: list[str], missing: list[str]) -> str:
    lines: list[str] = []
    ran = len(found) + len(clean)
    if found:
        lines.append(f"{len(found)} of {ran} {_plural(ran)} found problems.")
        lines += ["", *"\n\n".join(found).splitlines()]
        if clean:
            lines += ["", f"No problems from: {', '.join(clean)}."]
    elif clean:
        lines.append(f"No problems found by {', '.join(clean)}.")
    if missing:
        note = f"Not installed here, so not run: {', '.join(missing)}."
        lines += ([""] if lines else []) + [note]
    return "\n".join(lines)


def _plural(count: int) -> str:
    return "checker" if count == 1 else "checkers"


def _shorten(output: str) -> str:
    if len(output) <= MAX_OUTPUT_CHARS:
        return output
    rest = len(output) - MAX_OUTPUT_CHARS
    return f"{output[:MAX_OUTPUT_CHARS]}\n[... {rest:,} more characters; name paths to narrow it]"


def first_word(command: str) -> str:
    words = command.split()
    return PurePosixPath(words[0]).name if words else command


def read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _ini(path: Path) -> dict[str, dict[str, str]]:
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError):
        return {}
    return {section: dict(parser[section]) for section in parser.sections()}
