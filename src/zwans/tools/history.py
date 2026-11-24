"""The History tool: why a file, or a few lines of it, are the way they are.

Code that looks wrong often has a reason, and the reason is usually written down in the
commit that made it so. This asks git: for a range of lines, who last changed each run of
them and in which commit (blame), then how that range changed over its last commits
(`git log -L`); for a whole file, its last commits with what each changed. Every commit
comes with its full message, since that is where the "why" lives, and a link to the pull
request when the subject names one and the repository is on GitHub.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput

TIMEOUT = 60
MAX_BODY = 1_500  # characters of a commit message's body
MAX_OLD_BODY = 400  # for the older commits of a file's history
FULL_BODIES = 3  # newest commits of a file's history shown with the longer cap
MAX_HUNK_LINES = 40  # of each commit's change to the lines
MAX_RUN_LINES = 6  # lines of a blame run shown whole; longer runs are shortened
MAX_LINE = 120  # characters of each line of code shown
MAX_OUTPUT = 24_000
NOT_COMMITTED = "0" * 40
# Each commit starts with a record separator; its fields are split by unit separators, and
# whatever follows the last one is the diff or the stat.
FORMAT = "--format=%x1e%H%x1f%an%x1f%as%x1f%s%x1f%b%x1f"
PR_SUBJECT = re.compile(r"\(#(\d+)\)\s*$|^Merge pull request #(\d+)")
# Lines at the end of a message that say who helped, not why
TRAILER = re.compile(r"^(?:Co-authored-by|Signed-off-by):.*$\n?", re.I | re.M)
GITHUB_REMOTE = re.compile(
    r"^(?:[a-z+]+://)?(?:[^@/]+@)?github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$"
)


class HistoryInput(BaseModel):
    path: str = Field(description="The file (or folder), relative to the workspace root.")
    line: int | None = Field(
        default=None,
        ge=1,
        description="The first line to explain. Leave it out for the whole file's history.",
    )
    end_line: int | None = Field(
        default=None, ge=1, description="The last line to explain (default: just `line`)."
    )
    limit: int = Field(default=5, ge=1, le=20, description="How many commits to show.")


@dataclass
class Commit:
    sha: str
    author: str
    date: str
    subject: str
    body: str = ""
    rest: str = ""  # the diff or stat after the message


@dataclass
class BlameRun:
    sha: str
    first: int
    last: int
    lines: list[str] = field(default_factory=list)


class HistoryTool:
    name = "History"
    description = (
        "Find out why code is the way it is, from git. Give a file and a line range to see "
        "who last changed each run of those lines and in which commit, then how the range "
        "changed over its last commits, each with its full commit message and pull request "
        "link. Give just a file to see its last commits and what each changed. Use it "
        "before changing code that looks odd, to learn the reason first."
    )
    input_model = HistoryInput
    read_only = True

    async def run(self, args: HistoryInput, ctx: ToolContext) -> ToolOutput:
        path = ctx.executor.relative(args.path)
        if args.line is None and args.end_line is not None:
            raise ToolError("end_line needs line as well.")
        first = args.line
        last = args.end_line if args.end_line is not None else args.line
        if first is not None and last is not None and last < first:
            raise ToolError("end_line comes before line.")
        await _check_repository(ctx)
        files = await _tracked(ctx, path)
        if not files:
            if not (await _git(ctx, "log", "-n1", "--format=%H", "--", path)).strip():
                raise ToolError(
                    f"git doesn't track {path} and it has no history: it's new, ignored, "
                    "or misspelled."
                )
            if first is not None:
                raise ToolError(
                    f"{path} isn't in the working tree any more; leave out line to see the "
                    "history of the file."
                )
        folder = bool(files) and files != [path]
        if folder and first is not None:
            raise ToolError(f"{path} is a folder; line needs a file.")
        repo = await _github_repo(ctx)
        if first is not None and last is not None:
            text = await _lines_report(ctx, path, first, last, args.limit, repo)
        else:
            text = await _file_report(ctx, path, args.limit, repo, follow=not folder)
        if len(text) > MAX_OUTPUT:
            text = (
                text[:MAX_OUTPUT]
                + f"\n[... {len(text) - MAX_OUTPUT:,} more characters cut; ask for a smaller "
                "range or a lower limit]"
            )
        return ToolOutput(content=text)


async def _git(ctx: ToolContext, *args: str, check: bool = True) -> str:
    argv = ["git", "-c", "color.ui=never", "-c", "core.quotepath=false", *args]
    try:
        result = await ctx.executor.run(argv, timeout=TIMEOUT)
    except FileNotFoundError as exc:
        raise ToolError("git isn't installed, so there's no history to read.") from exc
    if result.timed_out:
        raise ToolError(f"git {args[0]} took longer than {TIMEOUT}s.")
    if check and result.exit_code != 0:
        message = result.output.strip() or f"exit code {result.exit_code}"
        raise ToolError(f"git {args[0]} failed: {message[-1_000:]}")
    return result.output if result.exit_code == 0 else ""


async def _check_repository(ctx: ToolContext) -> None:
    try:
        result = await ctx.executor.run(["git", "rev-parse", "--is-inside-work-tree"], TIMEOUT)
    except FileNotFoundError as exc:
        raise ToolError("git isn't installed, so there's no history to read.") from exc
    if result.exit_code != 0 or result.output.strip() != "true":
        raise ToolError("The workspace isn't a git repository, so there's no history to read.")


async def _tracked(ctx: ToolContext, path: str) -> list[str]:
    output = await _git(ctx, "ls-files", "-z", "--", path, check=False)
    return [name for name in output.split("\0") if name]


async def _github_repo(ctx: ToolContext) -> str | None:
    url = (await _git(ctx, "remote", "get-url", "origin", check=False)).strip()
    return github_repo(url)


def github_repo(url: str) -> str | None:
    """owner/repo for a GitHub remote in its https or ssh forms, else None."""
    match = GITHUB_REMOTE.match(url.strip())
    return f"{match[1]}/{match[2]}" if match else None


def pr_link(subject: str, repo: str | None) -> str | None:
    match = PR_SUBJECT.search(subject)
    if not match:
        return None
    number = match[1] or match[2]
    if repo is None:
        return f"#{number} (the remote isn't on GitHub, so there's no link)"
    return f"https://github.com/{repo}/pull/{number}"


async def _lines_report(
    ctx: ToolContext, path: str, first: int, last: int, limit: int, repo: str | None
) -> str:
    span = f"{first},{last}"
    blamed = await _git(ctx, "blame", "--porcelain", "-L", span, "--", path)
    runs, info = parse_blame(blamed)
    where = f"line {first}" if first == last else f"lines {first}-{last}"
    out = [f"{path} {where}", "", "Who last changed them (git blame):"]
    width = len(str(last)) * 2 + 1
    for run in runs:
        lines = f"{run.first}" if run.first == run.last else f"{run.first}-{run.last}"
        if run.sha == NOT_COMMITTED:
            out.append(f"  {lines:<{width}}  not committed yet")
        else:
            meta = info[run.sha]
            out.append(
                f"  {lines:<{width}}  {run.sha[:8]}  {meta['author']}  {meta['date']}  "
                f"{meta['summary']}"
            )
        out += [f"  {'':<{width}}  | {text}" for text in _abbreviate(run.lines)]
    shas = list(dict.fromkeys(run.sha for run in runs if run.sha != NOT_COMMITTED))
    shown: set[str] = set()
    if shas:
        out += ["", "The commits behind them:"]
        for sha in shas:
            commit = await _commit(ctx, sha)
            out += _commit_lines(commit, repo, MAX_BODY)
            shown.add(sha)
    dirty = await _has_changes(ctx, path)
    evolution = await _git(
        ctx,
        "log",
        "--no-color",
        f"-L{span}:{path}",
        FORMAT,
        f"-n{limit}",
        check=False,
    )
    commits = parse_log(evolution)
    count = f"{len(commits)} commit" + ("" if len(commits) == 1 else "s")
    out += ["", f"How the lines changed (git log -L, newest first, {count}):"]
    if dirty:
        out.append(
            "  (The file has uncommitted changes; these line numbers are matched against the "
            "committed version.)"
        )
    if not commits:
        out.append("  No commits touch these lines yet.")
    for commit in commits:
        if commit.sha in shown:
            out.append(f"{commit.sha[:8]}  {commit.author}  {commit.date}  {commit.subject}")
            out.append("  (message above)")
        else:
            out += _commit_lines(commit, repo, MAX_BODY)
        out += ["  " + line for line in _hunk(commit.rest)]
    if len(commits) == limit:
        out.append("(Older changes not shown; raise limit, up to 20, to see more.)")
    return "\n".join(out)


async def _file_report(
    ctx: ToolContext, path: str, limit: int, repo: str | None, follow: bool
) -> str:
    argv = ["log", "--no-color", f"-n{limit}", FORMAT, "--stat=100"]
    if follow:
        argv.append("--follow")
    output = await _git(ctx, *argv, "--", path)
    commits = parse_log(output)
    if not commits:
        return f"{path} has no commits yet."
    kind = "" if follow else " (a folder)"
    out = [f"{path}{kind}: the last {len(commits)} commits that changed it, newest first"]
    for number, commit in enumerate(commits):
        out.append("")
        out += _commit_lines(commit, repo, MAX_BODY if number < FULL_BODIES else MAX_OLD_BODY)
        stat = [line.rstrip() for line in commit.rest.strip("\n").splitlines() if line.strip()]
        if len(stat) > 12:
            stat = [*stat[:10], f" ... {len(stat) - 11} more files", stat[-1]]
        out += ["  " + line.strip() for line in stat]
    if len(commits) == limit:
        out += ["", "(Older commits not shown; raise limit, up to 20, to see more.)"]
    if await _has_changes(ctx, path):
        out += ["", f"{path} also has uncommitted changes."]
    return "\n".join(out)


async def _has_changes(ctx: ToolContext, path: str) -> bool:
    result = await ctx.executor.run(["git", "diff", "--quiet", "HEAD", "--", path], timeout=TIMEOUT)
    return result.exit_code == 1


async def _commit(ctx: ToolContext, sha: str) -> Commit:
    commits = parse_log(await _git(ctx, "show", "-s", "--no-color", FORMAT, sha))
    if not commits:
        raise ToolError(f"git couldn't show commit {sha[:8]}.")
    return commits[0]


def parse_blame(output: str) -> tuple[list[BlameRun], dict[str, dict[str, str]]]:
    """Runs of consecutive lines last changed by the same commit, and each commit's author,
    date and summary, from `git blame --porcelain`."""
    runs: list[BlameRun] = []
    info: dict[str, dict[str, str]] = {}
    sha = ""
    number = 0
    time = ""
    for line in output.splitlines():
        if line.startswith("\t"):
            text = line[1:]
            if runs and runs[-1].sha == sha and runs[-1].last == number - 1:
                runs[-1].last = number
                runs[-1].lines.append(text)
            else:
                runs.append(BlameRun(sha, number, number, [text]))
            continue
        header = re.match(r"^([0-9a-f]{40}) \d+ (\d+)", line)
        if header:
            sha, number = header[1], int(header[2])
            info.setdefault(sha, {"author": "", "date": "", "summary": ""})
            continue
        key, _, value = line.partition(" ")
        meta = info.get(sha)
        if meta is None:
            continue
        if key == "author":
            meta["author"] = value
        elif key == "summary":
            meta["summary"] = value
        elif key == "author-time":
            time = value
        elif key == "author-tz":
            meta["date"] = _date(time, value)
    return runs, info


def _date(epoch: str, tz: str) -> str:
    try:
        sign = -1 if tz.startswith("-") else 1
        offset = timedelta(hours=int(tz[1:3]), minutes=int(tz[3:5])) * sign
        return datetime.fromtimestamp(int(epoch), timezone(offset)).strftime("%Y-%m-%d")
    except (ValueError, IndexError):
        return datetime.fromtimestamp(int(epoch or 0), UTC).strftime("%Y-%m-%d")


def parse_log(output: str) -> list[Commit]:
    commits = []
    for chunk in output.split("\x1e")[1:]:
        fields = chunk.split("\x1f", 5)
        if len(fields) < 6:
            continue
        sha, author, date, subject, body, rest = fields
        commits.append(Commit(sha.strip(), author, date, subject, body.strip(), rest))
    return commits


def _commit_lines(commit: Commit, repo: str | None, cap: int) -> list[str]:
    out = [f"{commit.sha[:8]}  {commit.author}  {commit.date}  {commit.subject}"]
    link = pr_link(commit.subject, repo)
    if link:
        out.append(f"  Pull request: {link}")
    body = TRAILER.sub("", commit.body).strip()
    if len(body) > cap:
        body = body[:cap].rstrip() + f" [... {len(body) - cap:,} more characters]"
    out += ["  " + line if line else "" for line in body.splitlines()]
    return out


def _hunk(diff: str) -> list[str]:
    lines = diff.strip("\n").splitlines()
    start = next((n for n, line in enumerate(lines) if line.startswith("@@")), len(lines))
    lines = [_short(line) for line in lines[start:]]
    if len(lines) > MAX_HUNK_LINES:
        cut = len(lines) - MAX_HUNK_LINES
        lines = [*lines[:MAX_HUNK_LINES], f"[... {cut} more lines of this change]"]
    return lines


def _abbreviate(lines: list[str]) -> list[str]:
    shown = [_short(line) for line in lines]
    if len(shown) <= MAX_RUN_LINES:
        return shown
    return [*shown[:3], f"... {len(shown) - 5} more lines", *shown[-2:]]


def _short(line: str) -> str:
    return line if len(line) <= MAX_LINE else line[: MAX_LINE - 1] + "…"
