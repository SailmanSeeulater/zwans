"""The CI tool: why a GitHub Actions run failed, without opening a browser.

When a push goes red, the reason is a few lines near the end of one step's log, under
thousands of lines of setup. This asks the GitHub CLI for the branch's latest failed run
(or the run given), its failed jobs and steps, and the logs of those steps, and shows each
failed step's last lines (where the error usually is) with the timestamps, colour codes and
group markers taken out. In a long log the error and warning lines are also grouped by
kind, as the Logs tool does, so one that came earlier isn't missed.

gh needs the network and the user's GitHub login, which the sandbox would block, so it runs
outside it, in the workspace root. The policy judges a call as a request to github.com.
"""

import asyncio
import json
import re
import shutil
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.logs import group_lines

TIMEOUT = 60.0
LOG_TIMEOUT = 180.0
RECENT_RUNS = 20
TAIL = 25  # meaningful lines shown from the end of each failed step
LONG = 60  # a step log longer than this also gets its problem lines grouped
MAX_PROBLEMS = 12
MAX_LINE = 300
MAX_LOG_BYTES = 20_000_000
MAX_OUTPUT = 12_000

FAILED = {"failure", "timed_out", "startup_failure"}
RUN_URL = re.compile(r"github\.com/([^/\s]+)/([^/\s]+)/actions/runs/(\d+)(?:/jobs?/(\d+))?")
TIMESTAMP = re.compile(r"^﻿?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ?")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
COMMAND = re.compile(r"^##\[(error|warning|notice|debug|command)\]")
LIST_FIELDS = "databaseId,status,conclusion,workflowName,displayTitle,headSha,event,createdAt,url"
VIEW_FIELDS = "jobs,conclusion,status,url,workflowName,displayTitle,headSha,headBranch,event"


def available() -> bool:
    return shutil.which("gh") is not None


class CIInput(BaseModel):
    run: str | None = Field(
        default=None,
        description="A run id, or a run's URL (a job's URL picks that job). Leave it out for "
        "the latest failed run on the branch.",
    )
    branch: str | None = Field(
        default=None, description="The branch whose runs to look at. Defaults to the current one."
    )
    job: str | None = Field(
        default=None, description="Only failed jobs whose name contains this, such as 'windows'."
    )


@dataclass
class StepLog:
    job: str
    step: str
    lines: list[str]


class CITool:
    name = "CI"
    description = (
        "Explain why a GitHub Actions run failed: finds the branch's latest failed run (or "
        "the run given by id or URL), lists its failed jobs and steps, and shows the end of "
        "each failed step's log, where the error usually is, with the error lines of a long "
        "log grouped. Use it when CI is red after a push, instead of guessing or asking the "
        "user to paste the log."
    )
    input_model = CIInput
    read_only = True

    def host(self, args: dict[str, Any]) -> str:
        return "github.com"

    async def run(self, args: CIInput, ctx: ToolContext) -> ToolOutput:
        root = str(getattr(ctx.executor, "root"))  # noqa: B009 (not on the Executor protocol)
        gh = shutil.which("gh")
        if gh is None:
            raise ToolError(
                "The GitHub CLI (gh) isn't installed, so CI can't read GitHub Actions runs. "
                "Install it from https://cli.github.com and run `gh auth login`."
            )
        repo: list[str] = []
        job_id: int | None = None
        notes: list[str] = []
        if args.run and args.run.strip():
            run_id, repo, job_id = _parse_run(args.run.strip())
        else:
            branch = (args.branch or "").strip() or await _current_branch(ctx)
            where = ["--branch", branch] if branch else []
            listing = ["run", "list", *where, "--limit", str(RECENT_RUNS), "--json", LIST_FIELDS]
            runs = await _gh_json(gh, listing, root)
            if not isinstance(runs, list):
                raise ToolError("gh run list sent something unexpected.")
            picked = _pick(runs, branch, notes)
            if isinstance(picked, str):
                return ToolOutput(content=picked)
            run_id = str(picked.get("databaseId"))
        view = await _gh_json(gh, ["run", "view", run_id, *repo, "--json", VIEW_FIELDS], root)
        if not isinstance(view, dict):
            raise ToolError("gh run view sent something unexpected.")
        log_text, log_problem = await _failed_log(gh, run_id, repo, root)
        report = _report(run_id, view, _split_log(log_text), log_problem, args.job, job_id, notes)
        return ToolOutput(content=report)


def _parse_run(run: str) -> tuple[str, list[str], int | None]:
    if run.isdigit():
        return run, [], None
    match = RUN_URL.search(run)
    if not match:
        raise ToolError(
            "run should be a run id (digits) or a run's URL, such as "
            "https://github.com/owner/repo/actions/runs/123."
        )
    owner, name, run_id, job = match.groups()
    return run_id, ["--repo", f"{owner}/{name}"], int(job) if job else None


async def _current_branch(ctx: ToolContext) -> str:
    result = await ctx.executor.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout=15)
    if result.exit_code != 0:
        raise ToolError(
            "This folder isn't a git repository, so there's no branch to look up. Pass run "
            "as a run's URL instead."
        )
    branch = result.output.strip().splitlines()[-1] if result.output.strip() else ""
    return "" if branch == "HEAD" else branch  # a detached HEAD: runs on every branch


async def _gh(gh: str, argv: list[str], root: str, timeout: float = TIMEOUT) -> tuple[int, str]:
    """Runs gh in the workspace root; returns its exit code and output (stderr on failure)."""
    try:
        process = await asyncio.create_subprocess_exec(
            gh,
            *argv,
            cwd=root,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise ToolError(f"Couldn't run gh: {exc}") from exc
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ToolError(f"gh {' '.join(argv[:2])} took longer than {timeout:.0f}s.") from exc
    code = process.returncode or 0
    if code == 0:
        return 0, out[-MAX_LOG_BYTES:].decode("utf-8", "replace")
    message = (err or out).decode("utf-8", "replace").strip()
    return code, message


def _gh_problem(message: str) -> ToolError:
    lower = message.lower()
    if "not a git repository" in lower:
        return ToolError(
            "This folder isn't a git repository, so gh can't tell which GitHub repository to "
            "look at. Pass run as a run's URL instead."
        )
    if "gh auth login" in lower or "not logged in" in lower or "authentication" in lower:
        return ToolError(f"gh isn't logged in to GitHub: {message}")
    if (
        "no git remote" in lower
        or "none of the git remotes" in lower
        or "known github host" in (lower)
    ):
        return ToolError(f"This repository has no GitHub remote: {message}")
    return ToolError(f"gh failed: {message[:1000]}")


async def _gh_json(gh: str, argv: list[str], root: str) -> Any:
    code, output = await _gh(gh, argv, root)
    if code != 0:
        raise _gh_problem(output)
    try:
        return json.loads(output)
    except ValueError as exc:
        raise ToolError(f"gh {' '.join(argv[:2])} sent something that isn't JSON.") from exc


async def _failed_log(gh: str, run_id: str, repo: list[str], root: str) -> tuple[str, str]:
    """The failed steps' logs, or why gh couldn't give them."""
    code, output = await _gh(gh, ["run", "view", run_id, *repo, "--log-failed"], root, LOG_TIMEOUT)
    if code != 0:
        if "gh auth login" in output.lower():
            raise _gh_problem(output)
        return "", output.splitlines()[-1] if output else f"gh exited with code {code}"
    return output, ""


def _short(run: dict[str, Any]) -> str:
    sha = str(run.get("headSha") or "")[:7]
    return f'{run.get("workflowName", "?")} "{run.get("displayTitle", "")}" ({sha})'


def _pick(runs: list[dict[str, Any]], branch: str, notes: list[str]) -> dict[str, Any] | str:
    """The latest finished failed run, or, when there's none, a listing of the recent runs."""
    where = f"on branch {branch}" if branch else "on any branch"
    if not runs:
        return f"No GitHub Actions runs {where}."
    latest = runs[0]
    if latest.get("status") != "completed":
        notes.append(f"The latest run, {_short(latest)}, is still {latest.get('status')}.")
    for index, run in enumerate(runs):
        if run.get("status") == "completed" and run.get("conclusion") in FAILED:
            fixed = [
                r
                for r in runs[:index]
                if r.get("workflowName") == run.get("workflowName")
                and r.get("conclusion") == "success"
            ]
            if fixed:
                notes.append(
                    f"A newer {run.get('workflowName')} run passed, {_short(fixed[0])}, so this "
                    "failure may already be fixed."
                )
            return run
    lines = [f"No failed runs among the last {len(runs)} {where}:"]
    for run in runs:
        state = run.get("conclusion") or run.get("status") or "?"
        created = str(run.get("createdAt") or "")[:16].replace("T", " ")
        lines.append(f"  {state:<11} {created}  {_short(run)}")
    return "\n".join(lines)


def _split_log(text: str) -> list[StepLog]:
    """gh's log lines are "job<TAB>step<TAB>timestamp text"; one entry per job and step."""
    steps: list[StepLog] = []
    for raw in text.splitlines():
        parts = raw.split("\t", 2)
        if len(parts) < 3:
            if steps:
                steps[-1].lines.append(ANSI.sub("", raw))
            continue
        job, step, rest = parts
        if not steps or steps[-1].job != job or steps[-1].step != step:
            steps.append(StepLog(job, step, []))
        steps[-1].lines.append(ANSI.sub("", TIMESTAMP.sub("", rest)))
    return steps


def meaningful(lines: list[str]) -> list[str]:
    """The step's lines without the runner's noise: the script and environment it echoes
    before running a command, group markers and blank lines."""
    kept: list[str] = []
    echo = False
    for line in lines:
        if line.startswith("##[group]"):
            title = line.removeprefix("##[group]").strip()
            echo = title.startswith("Run ")
            kept.append(f"> {title}")
            continue
        if line.startswith("##[endgroup]"):
            echo = False
            continue
        if echo or not line.strip():
            continue
        match = COMMAND.match(line)
        if match:
            if match.group(1) == "debug":
                continue
            line = f"{match.group(1)}: {line[match.end() :].strip()}"
        kept.append(line.rstrip())
    return kept


def failed_section(lines: list[str], step: str) -> list[str]:
    """The failed step's part of a whole job's log: from the "Run" header of the step (the
    one named like it, or else the last one before the first error) to the next step's."""
    starts = [i for i, line in enumerate(lines) if line.startswith("##[group]Run ")]
    cleanup = next((i for i, line in enumerate(lines) if line.startswith("Post job cleanup")), None)
    named = [i for i in starts if lines[i].removeprefix("##[group]").strip() == step.strip()]
    if named:
        start = named[0]
    else:
        error = next((i for i, line in enumerate(lines) if line.startswith("##[error]")), None)
        if error is None:
            return lines[:cleanup]
        start = max((i for i in starts if i <= error), default=0)
    following = [i for i in starts if i > start]
    end = min([*following[:1], cleanup if cleanup is not None and cleanup > start else len(lines)])
    return lines[start:end]


def _clip(line: str) -> str:
    return line if len(line) <= MAX_LINE else line[:MAX_LINE] + "…"


def _step_text(lines: list[str]) -> list[str]:
    lines = meaningful(lines)
    if not lines:
        return ["    (no output)"]
    out = []
    if len(lines) > LONG:
        groups, _ = group_lines(lines, None)
        earlier = len(lines) - TAIL
        problems = sorted(
            (g for g in groups if g.level and g.first <= earlier), key=lambda g: (-g.level, g.first)
        )
        if problems:
            out.append(f"  Error and warning lines before the end ({len(problems)} kinds):")
            for group in problems[:MAX_PROBLEMS]:
                out.append(f"    {group.count:>4}x line {group.first:,}: {_clip(group.example)}")
            if len(problems) > MAX_PROBLEMS:
                out.append(f"    ... and {len(problems) - MAX_PROBLEMS} more kinds")
    tail = lines[-TAIL:]
    cut = f"last {len(tail)} of {len(lines):,}" if len(lines) > TAIL else f"all {len(lines)}"
    out.append(f"  Log ({cut} lines):")
    out += [f"    {_clip(line)}" for line in tail]
    return out


def _report(
    run_id: str,
    view: dict[str, Any],
    logs: list[StepLog],
    log_problem: str,
    job_filter: str | None,
    job_id: int | None,
    notes: list[str],
) -> str:
    status, conclusion = view.get("status"), view.get("conclusion")
    state = conclusion or status or "?"
    if status and status != "completed":
        state = f"still {status}"
    sha = str(view.get("headSha") or "")[:7]
    branch = f" on {view['headBranch']}" if view.get("headBranch") else ""
    event = f", {view['event']}" if view.get("event") else ""
    lines = [
        f'Run {run_id}: {view.get("workflowName", "?")} "{view.get("displayTitle", "")}": {state}',
        f"Commit {sha}{branch}{event}  {view.get('url', '')}",
    ]
    lines += notes
    jobs = [j for j in view.get("jobs") or [] if isinstance(j, dict)]
    failed = [j for j in jobs if j.get("conclusion") in FAILED]
    if job_id is not None:
        failed = [j for j in jobs if j.get("databaseId") == job_id]
    if job_filter and job_filter.strip():
        wanted = job_filter.strip().lower()
        matching = [j for j in failed if wanted in str(j.get("name", "")).lower()]
        if not matching:
            names = ", ".join(str(j.get("name")) for j in failed) or "none"
            raise ToolError(f"No failed job's name contains {job_filter!r}. Failed jobs: {names}.")
        failed = matching
    cancelled = [str(j.get("name")) for j in jobs if j.get("conclusion") == "cancelled"]
    lines.append(f"Failed jobs: {len(failed)} of {len(jobs)}.")
    if cancelled:
        lines.append(f"Cancelled: {', '.join(cancelled)}.")
    if not failed:
        lines.append("No job failed." if conclusion not in FAILED else "No job's log failed.")
        return "\n".join(lines)
    if log_problem:
        lines.append(f"The logs aren't available: {log_problem}")

    for job in failed:
        name = str(job.get("name", ""))
        lines += ["", f'Job "{name}": {job.get("conclusion") or job.get("status")}']
        steps = [s for s in job.get("steps") or [] if s.get("conclusion") in FAILED]
        if not steps:
            lines.append("  No step failed; the job itself did.")
        own = [log for log in logs if log.job == name]
        step_names = {str(s.get("name")) for s in steps}
        for step in steps:
            lines.append(f'  Failed step {step.get("number", "?")}: "{step.get("name")}"')
            matched = [log for log in own if log.step == step.get("name")]
            joined = [line for log in matched for line in log.lines]
            if not matched and len(steps) == 1:
                # gh can't always tell the steps apart ("UNKNOWN STEP") and gives the whole
                # job's log: the failed step's part of it is cut out.
                whole = [line for log in own if log.step not in step_names for line in log.lines]
                joined = failed_section(whole, str(step.get("name")))
            if joined:
                lines += _step_text(joined)
            elif not log_problem:
                lines.append("    (no log for this step)")
        if not steps:
            for log in own:
                lines.append(f'  Step "{log.step}":')
                lines += _step_text(log.lines)

    text = "\n".join(lines)
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT].rsplit("\n", 1)[0]
        text += "\n[... cut here; pass job to see one failed job at a time]"
    return text
