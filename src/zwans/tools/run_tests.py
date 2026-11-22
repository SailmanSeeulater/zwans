"""The RunTests tool: run the project's tests and report what failed.

Models are told to run the tests, and the weaker ones don't: they have to work out the
command first, and then read a screen of dots to find the one failure. This finds the test
runner from the project's files, runs it, and returns the failures, or one line when
everything passed.

Like Diagnostics, the policy judges a call by the commands it would run, as if Bash ran them.
"""

import json
import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.diagnostics import (
    NOT_FOUND,
    PYTHON,
    SCRIPT,
    Check,
    first_word,
    project_folders,
    read_toml,
    within,
)

TIMEOUT = 600  # seconds one test run may take
MAX_OUTPUT_CHARS = 12_000  # of one runner's output: its end, where the failures are
NO_TESTS = 5  # pytest's exit code when it collected nothing
KNOWN = "pytest, the test script in package.json, cargo test and go test"
# Runners a package.json test script may start with, run straight from node_modules so the
# call is one program the policy can judge, without npm in between.
NODE_RUNNERS = ("vitest", "jest", "mocha")


class RunTestsInput(BaseModel):
    paths: list[str] = Field(
        default=[],
        description="Test files or folders to run, relative to the workspace. Leave it empty "
        "to run every test.",
    )
    filter: str = Field(
        default="",
        description="Run only the tests whose names match this, as pytest's -k or jest's -t "
        "would. Leave it empty to run all of them.",
    )


class RunTestsTool:
    name = "RunTests"
    description = (
        "Run the project's tests and return the result: one line when they all pass, or the "
        f"failures with their messages. It finds the runner the project uses ({KNOWN}), so "
        "you don't need to know its command. Call it before changing code, to see what "
        "fails, and again after, to check the change. Narrow it with paths or filter."
    )
    input_model = RunTestsInput
    read_only = False  # tests are the project's code, and they run

    def __init__(self, root: Path, commands: Sequence[str] = ()) -> None:
        self.root = root
        self.configured = tuple(commands)  # the user's own, instead of the ones found

    def runs(self, paths: Sequence[str] = (), only: str = "") -> list[Check]:
        if self.configured:
            return [Check(first_word(command), command) for command in self.configured]
        return find_runs(self.root, paths, only)

    def commands(self, args: dict[str, Any]) -> list[str]:
        """What a call would run, from its raw input, for the policy to judge."""
        paths, only = args.get("paths"), args.get("filter")
        named = [p for p in paths if isinstance(p, str)] if isinstance(paths, list) else []
        return [run.command for run in self.runs(named, only if isinstance(only, str) else "")]

    async def run(self, args: RunTestsInput, ctx: ToolContext) -> ToolOutput:
        paths = [ctx.executor.relative(path) for path in args.paths]  # refuses ones outside
        runs = self.runs(paths, args.filter.strip())
        if not runs:
            about = " for those paths" if paths else ""
            raise ToolError(
                f"No test runner is set up{about} that RunTests knows how to run. It looks "
                f"for {KNOWN}. Run the project's tests with Bash instead."
            )
        passed: list[str] = []
        failed: list[str] = []
        other: list[str] = []
        for each in runs:
            result = await ctx.executor.run_shell(each.command, timeout=TIMEOUT)
            output = result.output.strip()
            if result.timed_out:
                failed.append(f"## {each.name}: stopped after {TIMEOUT}s without finishing")
            elif result.exit_code == 0:
                passed.append(f"{each.name}: {_last_line(output) or 'passed'}")
            elif result.exit_code in NOT_FOUND:
                other.append(f"{each.name} isn't installed here, so it wasn't run.")
            elif result.exit_code == NO_TESTS and each.name.startswith("pytest"):
                other.append(f"{each.name} found no tests to run.")
            else:
                head = f"## {each.name} failed (`{each.command}`, exit code {result.exit_code})"
                failed.append(f"{head}\n{_end(output) or '(no output)'}")
        lines: list[str] = []
        if failed:
            lines += ["Tests failed.", "", *"\n\n".join(failed).splitlines()]
            if passed:
                lines += ["", "Passed:", *passed]
        elif passed:
            lines += ["All tests passed.", *passed]
        lines += ([""] if lines and other else []) + other
        return ToolOutput(content="\n".join(lines), is_error=not (failed or passed))


def find_runs(root: Path, paths: Sequence[str] = (), only: str = "") -> list[Check]:
    """The test runners this project is set up for, in its root and the folders just inside
    it. `paths` narrows them to the runners for those files, and `only` to matching tests."""
    return [run for folder in project_folders(root) for run in _runs_in(root, folder, paths, only)]


def _runs_in(root: Path, folder: str, paths: Sequence[str], only: str) -> list[Check]:
    here = root / folder
    found: list[tuple[str, str, tuple[str, ...], str]] = []  # name, command, suffixes, filter
    if _has_pytest(here, nested=bool(folder)):
        command = "python -m pytest -q --tb=short -p no:cacheprovider"
        found.append(("pytest", command, PYTHON, "-k"))
    script = _test_script(here)
    if script:
        found.append((script[0], script[1], SCRIPT, "-t"))
    if (here / "Cargo.toml").is_file():
        found.append(("cargo test", "cargo test --quiet", (".rs",), ""))
    if (here / "go.mod").is_file():
        found.append(("go test", "go test ./...", (".go",), "-run"))

    runs = []
    for name, command, suffixes, filter_flag in found:
        wanted = within(root, folder, paths, suffixes) if paths else None
        if wanted == []:
            continue  # paths were given, and none is this runner's
        takes_paths = name not in ("cargo test", "go test")
        if takes_paths and wanted and "." not in wanted:
            separator = " -- " if command.startswith("npm ") else " "
            command += separator + " ".join(shlex.quote(p) for p in wanted)
        if only:
            if name == "cargo test":
                command += f" {shlex.quote(only)}"  # cargo takes the filter as a bare word
            elif command.startswith("npm ") and " -- " not in command:
                command += f" -- {filter_flag} {shlex.quote(only)}"
            else:
                command += f" {filter_flag} {shlex.quote(only)}"
        label = f"{name} in {folder}" if folder else name
        runs.append(Check(label, f"cd {shlex.quote(folder)} && {command}" if folder else command))
    return runs


def _has_pytest(here: Path, nested: bool) -> bool:
    """Whether a folder's tests are pytest's: it is configured, or there are test files where
    pytest looks for them. A folder inside the workspace counts only as a project of its
    own; a plain tests/ folder is run by the project above it."""
    own = ("pyproject.toml", "setup.py", "setup.cfg", "pytest.ini")
    if nested and not any((here / name).is_file() for name in own):
        return False
    project = read_toml(here / "pyproject.toml").get("tool", {})
    if "pytest" in project or (here / "pytest.ini").is_file() or (here / "conftest.py").is_file():
        return True
    for folder in (here, here / "tests", here / "test"):
        try:
            names = [p.name for p in folder.iterdir() if p.is_file()]
        except OSError:
            continue
        if any(
            n.endswith(".py") and (n.startswith("test_") or n.endswith("_test.py")) for n in names
        ):
            return True
    return False


def _test_script(here: Path) -> tuple[str, str] | None:
    """The name and command for a package.json's test script, or None when it has none."""
    try:
        package = json.loads((here / "package.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    scripts = package.get("scripts") if isinstance(package, dict) else None
    script = scripts.get("test") if isinstance(scripts, dict) else None
    if not isinstance(script, str) or not script.strip() or "no test specified" in script:
        return None
    words = script.split()
    if words[0] in NODE_RUNNERS and not any(c in script for c in "&|;<>$`"):
        return words[0], f"node_modules/.bin/{script.strip()}"
    return "npm test", "npm test --silent"


def _last_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1].strip("= ") if lines else ""


def _end(output: str) -> str:
    """The end of a failed run's output, which is where runners put the failures and the
    count."""
    if len(output) <= MAX_OUTPUT_CHARS:
        return output
    cut = len(output) - MAX_OUTPUT_CHARS
    return (
        f"[... {cut:,} earlier characters not shown; narrow it with paths or filter]\n"
        + (output[-MAX_OUTPUT_CHARS:])
    )
