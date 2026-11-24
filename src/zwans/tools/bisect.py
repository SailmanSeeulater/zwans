"""The Bisect tool: find the commit that broke something, by running a test across history.

"It worked last week" is a search problem: between a commit where it worked and one where it
doesn't, `git bisect` checks out the commit halfway, runs a test, and halves the range again
until one commit is left. This runs that whole search in one call and returns the first bad
commit with its message and what it changed, and each step it took.

The search moves HEAD, so it only runs on a clean working tree, and always ends with
`git bisect reset`, which puts the branch back as it was. With uncommitted changes it can
run in a temporary `git worktree` instead, which is removed afterwards.

The policy judges a call as `git bisect start` and the test command, as if Bash ran them.
"""

import re
import secrets
import shlex
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.history import FORMAT, github_repo, parse_log, pr_link

GIT_TIMEOUT = 120  # for each git command around the search
MAX_BODY = 2_000
MAX_STAT_LINES = 20
MAX_TEST_OUTPUT = 2_500  # characters of what the test printed at the first bad commit
MAX_TAIL = 3_000  # characters of git's output when no single commit came out
SHA = re.compile(r"\b[0-9a-f]{40}\b")
CHECKED_OUT = re.compile(r"^\[([0-9a-f]{40})\]")
FIRST_BAD = re.compile(r"^([0-9a-f]{40}) is the first bad commit", re.M)
LOG_ENTRY = re.compile(r"^# (good|bad|skip): \[([0-9a-f]{40})\] ?(.*)$")


class BisectInput(BaseModel):
    good: str = Field(description="A commit, tag or branch where it still worked.")
    bad: str = Field(default="HEAD", description="A commit where it's broken (default HEAD).")
    test: str = Field(
        description="A shell command run at each commit, from the workspace folder: exit 0 "
        "means good, 125 means this commit can't be tested (skip it), any other code from 1 "
        "to 127 means bad. For example: pytest -x -q tests/test_parser.py"
    )
    timeout: int = Field(
        default=1800, ge=10, le=3600, description="Seconds the whole search may take."
    )
    use_worktree: bool = Field(
        default=False,
        description="Search in a temporary copy of the repository (a git worktree), for when "
        "the working tree has uncommitted changes. Untracked files, such as node_modules or "
        ".venv, aren't in that copy.",
    )


@dataclass
class Step:
    verdict: str  # good, bad or skip
    sha: str
    subject: str
    given: bool  # one of the ends the search started from


@dataclass
class Search:
    output: str = ""  # what `git bisect run` printed
    timed_out: bool = False
    start_output: str = ""
    steps: list[Step] = field(default_factory=list)
    first_bad: str | None = None
    details: str = ""  # git show of the first bad commit


class BisectTool:
    name = "Bisect"
    description = (
        "Find the commit that broke something: give a commit where it worked, and a shell "
        "command that exits 0 when things are fine and non-zero when they're broken, and "
        "git bisect runs it on commits in between, halving the range each time, until it "
        "names the first bad commit, with its message and what it changed. Needs a clean "
        "working tree (or use_worktree); the branch is put back afterwards."
    )
    input_model = BisectInput
    read_only = False  # it checks out commits and runs the test on each

    def commands(self, args: dict[str, Any]) -> list[str]:
        """What a call would run, from its raw input, for the policy to judge."""
        test = args.get("test")
        return ["git bisect start", *([test] if isinstance(test, str) and test else [])]

    async def run(self, args: BisectInput, ctx: ToolContext) -> ToolOutput:
        started = time.monotonic()
        test = args.test.strip()
        if not test:
            raise ToolError("test is the shell command to run at each commit.")
        if (await _git(ctx, ["rev-parse", "--is-inside-work-tree"])).strip() != "true":
            raise ToolError("The workspace isn't a git repository.")
        log_path = (await _git(ctx, ["rev-parse", "--git-path", "BISECT_LOG"])).strip()
        if (await ctx.executor.run(["test", "-e", log_path], timeout=GIT_TIMEOUT)).exit_code == 0:
            raise ToolError(
                "A bisect is already in progress here. Finish it, or end it with "
                "`git bisect reset`, before starting another."
            )
        good = await _commit(ctx, args.good, "good")
        bad = await _commit(ctx, args.bad, "bad")
        if good == bad:
            raise ToolError("good and bad are the same commit.")
        changes = await _git(ctx, ["status", "--porcelain", "--untracked-files=no"])
        if changes.strip() and not args.use_worktree:
            raise ToolError(
                "The working tree has uncommitted changes to tracked files, and bisect checks "
                "out other commits over them. Commit or stash them first, or pass "
                "use_worktree=true to search in a temporary copy of the repository:\n"
                + changes.rstrip()[:1_500]
            )
        prefix = (await _git(ctx, ["rev-parse", "--show-prefix"])).strip()
        # `git bisect run` runs the test from the top of the repository; start it from the
        # workspace folder, as the model would expect.
        script = f"cd {shlex.quote(prefix)} || exit 125; {test}" if prefix else test
        place: list[str] = []
        folder = ""
        notes: list[str] = []
        search = Search()
        try:
            if args.use_worktree:
                folder = f".zwans-bisect-{secrets.token_hex(3)}"
                await _git(ctx, ["worktree", "add", "--detach", folder, bad])
                place = ["-C", folder]
                notes.append(
                    "Searched in a temporary git worktree, removed afterwards. Untracked "
                    "files (such as node_modules or .venv) weren't in it."
                )
            search = await _search(ctx, place, bad, good, script, args.timeout, started)
        finally:
            reset = await ctx.executor.run(["git", *place, "bisect", "reset"], GIT_TIMEOUT)
            if folder:
                removed = await ctx.executor.run(
                    ["git", "worktree", "remove", "--force", folder], GIT_TIMEOUT
                )
                if removed.exit_code != 0:
                    await ctx.executor.run(["rm", "-rf", folder], GIT_TIMEOUT)
                    await ctx.executor.run(["git", "worktree", "prune"], GIT_TIMEOUT)
            elif reset.exit_code != 0:
                notes.append(
                    "git bisect reset failed, so HEAD may still be on an old commit; run "
                    f"`git bisect reset` yourself:\n{reset.output.strip()[-500:]}"
                )
            else:
                notes.append("HEAD and the branch are back where they were (git bisect reset).")
        repo = github_repo(await _git(ctx, ["remote", "get-url", "origin"], check=False))
        return ToolOutput(content=_report(search, good, bad, args.timeout, repo, notes))


async def _git(ctx: ToolContext, argv: list[str], check: bool = True) -> str:
    try:
        result = await ctx.executor.run(["git", "-c", "color.ui=never", *argv], GIT_TIMEOUT)
    except FileNotFoundError as exc:
        raise ToolError("git isn't installed.") from exc
    if check and result.exit_code != 0:
        command = " ".join(argv[:2])
        raise ToolError(f"git {command} failed: {result.output.strip()[-1_000:]}")
    return result.output if result.exit_code == 0 else ""


async def _commit(ctx: ToolContext, rev: str, role: str) -> str:
    if not rev.strip() or rev.startswith("-"):
        raise ToolError(f"{role} names a commit, tag or branch.")
    result = await ctx.executor.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{rev.strip()}^{{commit}}"], GIT_TIMEOUT
    )
    sha = result.output.strip()
    if result.exit_code != 0 or not SHA.fullmatch(sha):
        raise ToolError(f"git doesn't know a commit called {rev!r} (the {role} end).")
    return sha


async def _search(
    ctx: ToolContext,
    place: list[str],
    bad: str,
    good: str,
    script: str,
    timeout: int,
    started: float,
) -> Search:
    search = Search()
    start = await ctx.executor.run(["git", *place, "bisect", "start", bad, good], GIT_TIMEOUT)
    search.start_output = start.output
    if start.exit_code != 0:
        raise ToolError(f"git bisect couldn't start:\n{start.output.strip()[-MAX_TAIL:]}")
    found = FIRST_BAD.search(start.output)
    if not found:
        left = max(10.0, timeout - (time.monotonic() - started))
        result = await ctx.executor.run(
            ["git", *place, "bisect", "run", "sh", "-c", script], timeout=left
        )
        search.output, search.timed_out = result.output, result.timed_out
        found = FIRST_BAD.search(result.output)
    log = await ctx.executor.run(["git", *place, "bisect", "log"], GIT_TIMEOUT)
    search.steps = parse_bisect_log(log.output)
    if found:
        search.first_bad = found[1]
        shown = await ctx.executor.run(
            ["git", *place, "show", "--no-color", "--stat=100", FORMAT, found[1]], GIT_TIMEOUT
        )
        search.details = shown.output
    return search


def parse_bisect_log(log: str) -> list[Step]:
    """Each commit marked in `git bisect log`, in order; the ends given to `bisect start`
    come first."""
    steps = []
    started = False
    for line in log.splitlines():
        if line.startswith("git bisect start"):
            started = True
        entry = LOG_ENTRY.match(line)
        if entry:
            steps.append(Step(entry[1], entry[2], entry[3], given=not started))
    return steps


def printed_by_test(start_output: str, run_output: str) -> dict[str, list[str]]:
    """What the test printed at each commit, from the output of `git bisect run`."""
    current = ""
    for line in start_output.splitlines():
        checked = CHECKED_OUT.match(line)
        if checked:
            current = checked[1]
    printed: dict[str, list[str]] = {}
    capturing = False
    for line in run_output.splitlines():
        checked = CHECKED_OUT.match(line)
        if checked:
            current, capturing = checked[1], False
        elif line.startswith("running "):
            printed[current] = []
            capturing = True
        elif line.startswith(("Bisecting:", "There are only")) or FIRST_BAD.match(line):
            capturing = False
        elif capturing:
            printed[current].append(line)
    return printed


def _report(
    search: Search, good: str, bad: str, timeout: int, repo: str | None, notes: list[str]
) -> str:
    out: list[str] = []
    tested = [step for step in search.steps if not step.given]
    if search.first_bad:
        commits = parse_log(search.details)
        out.append(f"The first bad commit is {search.first_bad[:10]}.")
        if commits:
            commit = commits[0]
            out += [
                "",
                f"commit  {commit.sha}",
                f"author  {commit.author}, {commit.date}",
                f"subject {commit.subject}",
            ]
            link = pr_link(commit.subject, repo)
            if link:
                out.append(f"pull request {link}")
            body = commit.body
            if body:
                if len(body) > MAX_BODY:
                    body = body[:MAX_BODY] + f" [... {len(commit.body) - MAX_BODY:,} more]"
                out += ["", *["  " + line if line else "" for line in body.splitlines()]]
            stat = [line.strip() for line in commit.rest.splitlines() if line.strip()]
            if len(stat) > MAX_STAT_LINES:
                cut = len(stat) - MAX_STAT_LINES
                stat = [*stat[: MAX_STAT_LINES - 1], f"... {cut} more files", stat[-1]]
            if stat:
                out += ["", "What it changed:", *["  " + line for line in stat]]
        if search.first_bad == bad and not any(s.verdict == "bad" for s in tested):
            out += [
                "",
                f"Warning: the test never failed during the search, and it isn't run on the "
                f"bad end ({bad[:10]}) itself, so git named that end. Check that the test "
                "really fails there.",
            ]
        elif tested and not any(s.verdict == "good" for s in tested):
            out += [
                "",
                f"Warning: the test failed at every commit it ran on, and it isn't run on the "
                f"good end ({good[:10]}) itself. Check that the test really passes there.",
            ]
        printed = printed_by_test(search.start_output, search.output).get(search.first_bad)
        if printed:
            text = "\n".join(printed).strip()
            if len(text) > MAX_TEST_OUTPUT:
                text = (
                    f"[... {len(text) - MAX_TEST_OUTPUT:,} earlier characters]\n"
                    + text[-MAX_TEST_OUTPUT:]
                )
            if text:
                out += ["", "What the test printed at that commit:", text]
    elif search.timed_out:
        out.append(
            f"The search was stopped after {timeout}s, before it found a single commit. "
            "Give it more time, a faster test, or a closer good commit."
        )
    else:
        out.append("git bisect couldn't name a single first bad commit.")
        output = search.output.strip()
        candidates = output.split("The first bad commit could be any of:", 1)
        if len(candidates) == 2:
            shas = SHA.findall(candidates[1].split("We cannot bisect more", 1)[0])
            out.append(
                f"The test was skipped (exit 125) on the commits that matter, so it's one of "
                f"these {len(shas)}: " + ", ".join(sha[:10] for sha in shas)
            )
        elif output:
            tail = output[-MAX_TAIL:]
            out += ["", "The end of what git bisect run printed:", tail]
    if search.steps:
        out += ["", "Steps (from git bisect log):"]
        number = 0
        for step in search.steps:
            if step.given:
                label = "given"
            else:
                number += 1
                label = str(number)
            out.append(f"  {label:<6} {step.verdict:<5} {step.sha[:10]}  {step.subject}")
    if notes:
        out += ["", *notes]
    return "\n".join(out)
